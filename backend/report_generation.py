import google.generativeai as genai
import base64
import json
import os
import sys
from pathlib import Path
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()
API_KEY    = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite-preview"

SYSTEM_PROMPT = """You are a clinical AI radiology report generator. Your role is to produce 
structured, professional chest X-ray analysis reports based strictly on the output of a 
DenseNet121 multi-label classification model with Grad-CAM localisation, and the accompanying 
X-ray image.

Rules you must follow without exception:
- Base every statement ONLY on the provided JSON prediction data and the X-ray image supplied.
- Use the X-ray image to visually confirm and refine anatomical location descriptions. Be as 
  specific as possible — specify laterality and zone (e.g., left upper zone, right lower zone, 
  central mediastinum).
- Do NOT infer, assume, or add any clinical information not present in the JSON or visible 
  in the image.
- Do NOT mention treatment recommendations, differential diagnoses, or clinical history.
- Do NOT speculate about cause or severity beyond what the detection data supports.
- For the impression: write a genuine radiological narrative — not a list reformatted as 
  sentences. Note relationships between co-occurring findings where they are visually evident. 
  The impression must read like a senior radiologist wrote it.
- For anatomical_location: be specific. Use the bounding box coordinates and the image. 
  Do not write generic phrases like "bilateral thoracic regions".
- For clinical_priority: assign "high", "moderate", or "low" based solely on the detected 
  condition type and confidence score.
- Conditions the model did not predict (score below threshold) should be listed in not_detected
  along with their raw score.
- Since no ground truth labels are available, do NOT reference or compare against ground truth.
- Maintain a professional, formal tone consistent with a radiology report.
- Output must be valid, clean JSON matching the schema provided.
- Do NOT include markdown formatting, code fences, preamble, or any text outside the JSON."""


def build_user_prompt(data: dict) -> str:
    image_w = data["image_size"]["width"]
    image_h = data["image_size"]["height"]

    all_labels = [
        "Atelectasis", "Cardiomegaly", "Effusion", "Infiltration", "Mass",
        "Nodule", "Pneumonia", "Pneumothorax", "Consolidation", "Edema",
        "Emphysema", "Fibrosis", "Pleural_Thickening", "Hernia",
    ]

    predicted_names = {p["class_name"] for p in data["predictions"]}
    not_predicted = [
        {"condition": lbl, "raw_score": data["raw_scores"].get(lbl, 0.0)}
        for lbl in all_labels if lbl not in predicted_names
    ]

    # Derive anatomical zone from bbox centre
    def bbox_to_zone(bbox, w, h):
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        h_zone = "left" if cx < w/3 else ("central" if cx < 2*w/3 else "right")
        v_zone = "upper" if cy < h/3 else ("mid" if cy < 2*h/3 else "lower")
        return f"{h_zone} {v_zone} zone"

    annotated_predictions = []
    for p in data["predictions"]:
        annotated_predictions.append({
            **p,
            "derived_zone": bbox_to_zone(p["bbox"], image_w, image_h)
                            if p["bbox"] else "undetermined"
        })

    # Extract image filename to use as study ID
    study_id = Path(data["image_path"]).stem

    return f"""You have been provided with TWO images and the corresponding AI model 
prediction JSON.:
  Image 1: The original chest X-ray — use this for anatomical interpretation
  Image 2: The Grad-CAM visualization — use this to understand which regions 
            the model attended to for each predicted condition. The left panel 
            shows bounding boxes, the right panels show per-class heatmaps 
            (red = highest activation, blue = lowest). 
    No patient metadata or ground truth labels are available — base the report 
solely on the image and predictions.

STUDY ID: {study_id}
IMAGE DIMENSIONS: {image_w} x {image_h} pixels

ZONE MAPPING REFERENCE:
- x-axis : 0 to {image_w//3}px = left zone | {image_w//3} to {2*image_w//3}px = central | {2*image_w//3} to {image_w}px = right zone
- y-axis : 0 to {image_h//3}px = upper zone | {image_h//3} to {2*image_h//3}px = mid zone | {2*image_h//3} to {image_h}px = lower zone

RAW MODEL SCORES (sigmoid, threshold = 0.5):
{json.dumps(data["raw_scores"], indent=2)}

MODEL PREDICTIONS (above threshold, Grad-CAM bounding boxes [x1,y1,x2,y2] in pixels):
{json.dumps(annotated_predictions, indent=2)}

CONDITIONS BELOW THRESHOLD (not predicted):
{json.dumps(not_predicted, indent=2)}

TOTAL FINDINGS: {data["num_findings"]}

---

Instructions:
1. Use the X-ray image AND bounding box coordinates to describe anatomical locations accurately.
   The derived_zone field is a starting point — refine using the image.
2. Order findings by confidence score, highest first.
3. Write the impression as a single coherent paragraph synthesising all detected findings.
   Note spatial relationships between co-occurring conditions where relevant.
4. Since no ground truth is available, set ground_truth_confirmed to null for all findings.
5. For patient_info: populate study from the study ID, leave age/sex/view as null or "N/A"
   since no metadata is available.
6. Include a standard AI disclaimer.

Return ONLY a JSON object matching this exact schema — no other text:

{{
  "patient_info": {{
    "patient_id": "",
    "age": null,
    "sex": null,
    "study": "",
    "view": null,
    "projection": null
  }},
  "study_summary": {{
    "total_conditions_detected": 0,
    "total_instances": 0,
    "ground_truth_positives": null
  }},
  "findings": [
    {{
      "condition": "",
      "instances": 1,
      "anatomical_location": "",
      "confidence": 0.0,
      "ground_truth_confirmed": null,
      "status": "detected",
      "clinical_priority": "high | moderate | low"
    }}
  ],
  "not_detected": [
    {{
      "condition": "",
      "raw_score": 0.0,
      "reason": "score below threshold"
    }}
  ],
  "impression": "",
  "disclaimer": ""
}}"""

def load_image_as_base64(image_path: str):
    path = Path(image_path)
    suffix = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
    }
    mime_type = mime_map.get(suffix)
    if not mime_type:
        raise ValueError(f"Unsupported image format: {suffix}")

    img = Image.open(path)
    if max(img.size) > 1600:
        img.thumbnail((1600, 1600), Image.LANCZOS)
        print(f"  [info] Image resized to {img.size}")

    buf = BytesIO()
    img.save(buf, format="JPEG" if suffix in (".jpg", ".jpeg") else "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return b64, mime_type


def call_gemini(image_b64: str, mime_type: str,
                gradcam_b64: str = None, gradcam_mime: str = None,
                user_prompt: str = "") -> str:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=0.1,
            top_p=0.95,
        ),
    )

    content = [
        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
    ]
    if gradcam_b64:
        content.append(
            {"inline_data": {"mime_type": gradcam_mime, "data": gradcam_b64}}
        )
    content.append({"text": user_prompt})

    print("  [info] Sending request to Gemini API...")
    response = model.generate_content(content)
    return response.text


def parse_json_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned invalid JSON.\nError: {e}\n\nRaw:\n{raw[:500]}")


def print_report(report: dict):
    sep = "=" * 70
    pi  = report.get("patient_info", {})
    ss  = report.get("study_summary", {})

    print(f"\n{sep}")
    print("  CHEST X-RAY AI ANALYSIS REPORT")
    print(sep)
    print(f"  Study      : {pi.get('study', 'N/A')}")
    print(f"  Patient ID : {pi.get('patient_id', 'N/A')}")
    print(f"  Age / Sex  : {pi.get('age', 'N/A')} / {pi.get('sex', 'N/A')}")
    print(f"  View       : {pi.get('view', 'N/A')}")
    print(f"  Detected   : {ss.get('total_conditions_detected')} conditions, "
          f"{ss.get('total_instances')} instances")

    print(f"\n{'─'*70}")
    print("  FINDINGS  (ordered by confidence)")
    print(f"{'─'*70}")
    for f in report.get("findings", []):
        print(f"  [{f['condition']}]")
        print(f"    Confidence : {f['confidence']:.4f}  |  Priority: {f['clinical_priority']}")
        print(f"    Location   : {f['anatomical_location']}")
        print()

    nd = report.get("not_detected", [])
    if nd:
        print(f"{'─'*70}")
        print("  NOT DETECTED (below threshold)")
        print(f"{'─'*70}")
        for item in nd:
            print(f"  {item['condition']:25s}  score: {item.get('raw_score', 'N/A'):.4f}")

    print(f"\n{'─'*70}")
    print("  IMPRESSION")
    print(f"{'─'*70}")
    print(f"  {report.get('impression', '')}")

    print(f"\n{'─'*70}")
    print("  DISCLAIMER")
    print(f"{'─'*70}")
    print(f"  {report.get('disclaimer', '')}")
    print(f"{sep}\n")


def run_pipeline(image_path: str, json_input, output_path: str = "report.json", patient_info_override: dict = None) -> dict:
    if not API_KEY:
        print("ERROR: GEMINI_API_KEY not found in environment / .env file.")
        sys.exit(1)

    # Step 1 — Load JSON
    print("[1/5] Loading prediction JSON...")
    if isinstance(json_input, dict):
        data = json_input
    else:
        with open(json_input, "r") as f:
            data = json.load(f)
    print(f"  Study: {Path(data['image_path']).stem}  |  "
          f"Predictions: {data['num_findings']}")

    # Step 2 — Load original X-ray
    print("[2/5] Loading images...")
    image_b64, mime_type = load_image_as_base64(image_path)
    print(f"  Original : {Path(image_path).name}")

    # Grad-CAM path comes directly from the inference JSON
    gradcam_b64, gradcam_mime = None, None
    gradcam_path = data.get("visualization_path")
    if gradcam_path and Path(gradcam_path).exists():
        gradcam_b64, gradcam_mime = load_image_as_base64(gradcam_path)
        print(f"  Grad-CAM : {Path(gradcam_path).name}")
    else:
        print("  [warn] visualization_path not found in JSON or file missing "
              "— sending original image only")

    # Step 3 — Build prompt
    print("[3/5] Building prompt...")
    user_prompt = build_user_prompt(data)

    # Step 4 — Call Gemini
    print("[4/5] Calling Gemini API...")
    raw_response = call_gemini(
        image_b64, mime_type,
        gradcam_b64, gradcam_mime,
        user_prompt
    )

    # Step 5 — Parse and save
    print("[5/5] Parsing and saving report...")
    report = parse_json_response(raw_response)

    # Inject real patient info if provided
    if patient_info_override:
        report.setdefault("patient_info", {})
        report["patient_info"].update({k: v for k, v in patient_info_override.items() if v and v != "N/A"})

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Saved to: {output_path}")

    print_report(report)
    return report


if __name__ == "__main__":
    IMAGE_PATH  = r"NIH model\00000001_002.png"        # original X-ray
    JSON_PATH   = r"NIH model\1.json"        # inference output JSON
    OUTPUT_PATH = "report.json"

    run_pipeline(IMAGE_PATH, JSON_PATH, OUTPUT_PATH)