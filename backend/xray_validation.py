import base64
import os
from io import BytesIO
from pathlib import Path
import google.generativeai as genai
from PIL import Image
from dotenv import load_dotenv
import logging
import json

logger = logging.getLogger(__name__)

load_dotenv()

API_KEY    = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite-preview"

SYSTEM_PROMPT = """You are a medical imaging classifier. Your only job is to 
determine whether an image is a chest X-ray (also called a chest radiograph).

A chest X-ray is a grayscale medical image showing the internal structures of 
the thorax — including the lungs, heart, ribs, spine, and diaphragm — produced 
by X-ray radiation. It may be a PA (posteroanterior), AP (anteroposterior), or 
lateral view.

You must reject:
- Photos of people, animals, or objects
- CT scans, MRI scans, ultrasounds, or other imaging modalities
- X-rays of body parts other than the chest (hand, knee, spine only, etc.)
- Screenshots, documents, drawings, or non-medical images
- Images that are too blurry, dark, or low quality to assess

Respond with ONLY a JSON object in this exact format, no other text:
{
  "is_chest_xray": true or false,
  "confidence": "high" or "medium" or "low",
  "reason": "one sentence explanation"
}"""

USER_PROMPT = """Is this image a chest X-ray? Examine it carefully and respond 
with only the JSON object as instructed."""


def validate_chest_xray(image_bytes: bytes) -> dict:
    if not API_KEY:
        print("[validator] No GEMINI_API_KEY found — skipping X-ray validation")
        return {"is_valid": True, "confidence": "low", "reason": "Validation skipped — no API key"}

    try:
        # Resize image if too large before sending to Gemini
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        if max(img.size) > 1600:
            img.thumbnail((1600, 1600), Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="JPEG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        genai.configure(api_key=API_KEY)
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=200,
            ),
        )

        response = model.generate_content([
            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
            {"text": USER_PROMPT},
        ])

        raw = response.text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        parsed = json.loads(raw)

        is_xray     = bool(parsed.get("is_chest_xray", False))
        confidence  = parsed.get("confidence", "low")
        reason      = parsed.get("reason", "No reason provided")

        print(f"[validator] is_chest_xray={is_xray} | confidence={confidence} | reason={reason}")

        return {
            "is_valid":   is_xray,
            "confidence": confidence,
            "reason":     reason,
        }

    except Exception as e:
        logger.error(f"[validator] Validation error: {e}")
        return {
            "is_valid": False,
            "confidence": "low",
            "reason": "Validation service encountered an error. Please try again.",
            "error": str(e),
        }