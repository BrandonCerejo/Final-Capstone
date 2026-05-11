import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as T
from torchvision.models import densenet121
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path
import json

WEIGHTS = Path(r"NIH model\best_model.pt")
IMG_SIZE = 320
SCORE_THRESHOLD = 0.5
CAM_THRESHOLD = 0.5

LABELS = [
    "Atelectasis", "Cardiomegaly", "Effusion", "Infiltration", "Mass",
    "Nodule", "Pneumonia", "Pneumothorax", "Consolidation", "Edema",
    "Emphysema", "Fibrosis", "Pleural_Thickening", "Hernia",
]

# Distinct colors per class for bounding boxes
COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#800000", "#aaffc3",
]

NUM_CLASSES = len(LABELS)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# --- Model ---
def build_model():
    m = densenet121(weights=None)
    m.classifier = nn.Linear(m.classifier.in_features, NUM_CLASSES)
    return m

model = build_model().to(DEVICE)
model.load_state_dict(torch.load(WEIGHTS, map_location=DEVICE))
model.eval()

preprocess = T.Compose([
    T.Resize((IMG_SIZE, IMG_SIZE)),
    T.ToTensor(),
    T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

# --- Grad-CAM ---
def grad_cam(image_tensor, class_idx):
    image_tensor = image_tensor.unsqueeze(0).to(DEVICE)
    feat_out = model.features(image_tensor)
    feat_out.requires_grad_(True)
    pooled = F.adaptive_avg_pool2d(F.relu(feat_out, inplace=False), 1).flatten(1)
    logits = model.classifier(pooled)
    score = logits[0, class_idx]
    grads = torch.autograd.grad(score, feat_out)[0]
    weights = grads.mean(dim=(2, 3), keepdim=True)
    cam = F.relu((weights * feat_out).sum(dim=1, keepdim=True))
    cam = F.interpolate(cam, size=(IMG_SIZE, IMG_SIZE), mode="bilinear", align_corners=False)
    cam = cam.squeeze().detach().cpu().numpy()
    if cam.max() > 0:
        cam = cam / cam.max()
    return cam

# --- BBox helpers ---
def cam_to_bbox(cam, threshold=CAM_THRESHOLD):
    mask = cam >= threshold
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]

def scale_bbox(bbox, src_size, dst_w, dst_h):
    sx, sy = dst_w / src_size, dst_h / src_size
    return [round(bbox[0]*sx, 2), round(bbox[1]*sy, 2),
            round(bbox[2]*sx, 2), round(bbox[3]*sy, 2)]

# --- Visualization ---
def save_gradcam_overlay(pil_img, cams, predictions, output_path):
    n = len(predictions)
    if n == 0:
        print("  [info] No predictions above threshold — skipping visualization.")
        return

    # Figure: 1 col for original + n cols for CAMs
    ncols = 1 + n
    fig, axes = plt.subplots(1, ncols, figsize=(4 * ncols, 5))
    if ncols == 1:
        axes = [axes]

    orig_arr = np.array(pil_img.convert("L"))  # grayscale for display

    # --- Left panel: original + all bounding boxes ---
    ax0 = axes[0]
    ax0.imshow(orig_arr, cmap="gray")
    ax0.set_title("Predictions", fontsize=10, fontweight="bold")
    ax0.axis("off")

    for pred in predictions:
        ci   = pred["category_id"] - 1
        bbox = pred["bbox"]          # xyxy in original pixel space
        color = COLORS[ci % len(COLORS)]
        x1, y1, x2, y2 = bbox
        rect = patches.Rectangle(
            (x1, y1), x2 - x1, y2 - y1,
            linewidth=1.5, edgecolor=color, facecolor="none"
        )
        ax0.add_patch(rect)
        ax0.text(
            x1, max(y1 - 4, 0),
            f"{pred['class_name']} {pred['score']:.2f}",
            color=color, fontsize=7, fontweight="bold",
            bbox=dict(facecolor="black", alpha=0.4, pad=1, linewidth=0)
        )

    # --- Right panels: one Grad-CAM per prediction ---
    img_resized = np.array(pil_img.convert("RGB").resize((IMG_SIZE, IMG_SIZE)))

    for col_idx, pred in enumerate(predictions):
        ax = axes[col_idx + 1]
        cam = cams[pred["class_name"]]

        # Blend heatmap over resized grayscale image
        ax.imshow(img_resized, alpha=0.45)
        ax.imshow(cam, cmap="jet", alpha=0.55, vmin=0, vmax=1)

        color = COLORS[(pred["category_id"] - 1) % len(COLORS)]
        ax.set_title(
            f"{pred['class_name']}\n{pred['score']:.4f}",
            fontsize=8, fontweight="bold", color=color
        )
        ax.axis("off")

    plt.tight_layout(pad=0.5)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  [info] Grad-CAM visualization saved → {output_path}")


# --- Main inference function ---
def run_inference(image_path: str, save_visualization: bool = True) -> dict:
    image_path = Path(image_path)
    pil = Image.open(image_path).convert("RGB")
    orig_w, orig_h = pil.size
    x = preprocess(pil)

    with torch.no_grad():
        logits = model(x.unsqueeze(0).to(DEVICE))
        scores = torch.sigmoid(logits)[0].cpu().numpy()

    predictions = []
    cams = {}  # store CAMs for visualization

    for ci, lbl in enumerate(LABELS):
        s = float(scores[ci])
        if s < SCORE_THRESHOLD:
            continue
        cam = grad_cam(x, ci)
        cams[lbl] = cam                          # save for plotting
        bbox_cam  = cam_to_bbox(cam)
        bbox_orig = scale_bbox(bbox_cam, IMG_SIZE, orig_w, orig_h) if bbox_cam else None

        predictions.append({
            "category_id": ci + 1,
            "class_name":  lbl,
            "score":       round(s, 4),
            "bbox":        bbox_orig,
            "bbox_format": "xyxy_pixels",
        })

    # Sort by score descending
    predictions.sort(key=lambda p: p["score"], reverse=True)

    result = {
        "image_path":   str(image_path),
        "image_size":   {"width": orig_w, "height": orig_h},
        "raw_scores":   {lbl: round(float(scores[i]), 4) for i, lbl in enumerate(LABELS)},
        "predictions":  predictions,
        "num_findings": len(predictions),
    }

    # Save visualization
    if save_visualization and predictions:
        viz_path = image_path.with_name(image_path.stem + "_gradcam.png")
        save_gradcam_overlay(pil, cams, predictions, viz_path)
        result["visualization_path"] = str(viz_path)

    return result


# --- Run ---
if __name__ == "__main__":
    import json
    result = run_inference(r"NIH model\00000001_002.png")
    print(json.dumps(result, indent=2))