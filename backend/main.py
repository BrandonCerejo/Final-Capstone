import pdf2image
import base64
import json
import os
import tempfile
import traceback
from io import BytesIO
from pathlib import Path
from datetime import datetime

from auth import router as auth_router
from database import reports_collection
import logging

logger = logging.getLogger(__name__)

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import Image
import uvicorn
from pydantic import BaseModel

import inference as inf
import report_generation as rg
from chatbot.report_chatbot import ask_report_chatbot
from chatbot.rag_chain import ask_knowledge_chatbot, _load_resources
from xray_validation import validate_chest_xray
from doctor_routes import router as doctor_router, seed_doctor

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY


class ReportChatRequest(BaseModel):
    question: str
    report:   dict
    history:  list[dict] = []


class KnowledgeChatRequest(BaseModel):
    question: str
    history:  list[dict] = []


class PDFRequest(BaseModel):
    report:        dict
    gradcam_image: str        
    xray_image:    str        
    patient_email: str = ""


app = FastAPI(
    title="Chest X-Ray Analyzer API",
    description="DenseNet121 + Grad-CAM + Gemini LLM radiology report generator",
    version="1.0.0",
)

app.include_router(auth_router)
app.include_router(doctor_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}
ALLOWED_EXTENSIONS    = {".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE_MB      = 20


def pil_to_base64(pil_img: Image.Image, fmt: str = "PNG") -> str:
    buf = BytesIO()
    pil_img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def file_to_base64(path: str | Path) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


def validate_upload(file: UploadFile) -> None:
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file extension '{ext}'.")
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported content type '{file.content_type}'.")


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "message": "Chest X-Ray Analyzer API is running."}


# ── PDF builder ───────────────────────────────────────────────────────────────
def build_pdf(report: dict, gradcam_b64: str, xray_b64: str) -> bytes:
    """Build a professional PDF report and return as bytes."""
    buf = BytesIO()

    # A4 usable width = 21cm - 2cm*2 margins = 17cm
    PAGE_W = 17 * cm

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=2*cm      # slightly less top margin
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── colour palette ────────────────────────────────────────────────────
    TEAL  = colors.HexColor("#00BCD4")
    GRAY  = colors.HexColor("#8b949e")
    HIGH  = colors.HexColor("#fc8181")
    MOD   = colors.HexColor("#f6ad55")
    LOW   = colors.HexColor("#68d391")

    title_style = ParagraphStyle(
        "Title", parent=styles["Normal"],
        fontSize=24, textColor=TEAL,
        spaceBefore=0, spaceAfter=6,             # gap BELOW title
        fontName="Helvetica-Bold", alignment=TA_CENTER
    )
    sub_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        fontSize=10, textColor=GRAY,
        alignment=TA_CENTER,
        spaceBefore=0, spaceAfter=14             # gap between subtitle and rule
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Normal"],
        fontSize=11, textColor=TEAL,
        spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold"
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=9, textColor=colors.black,
        leading=14, spaceAfter=4, alignment=TA_JUSTIFY
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=8, textColor=GRAY, leading=12
    )
    img_label_style = ParagraphStyle(
        "ImgLabel", parent=styles["Normal"],
        fontSize=9, textColor=GRAY,
        fontName="Helvetica-Bold", alignment=TA_CENTER,
        spaceBefore=10, spaceAfter=4
    )
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"],
        fontSize=8, textColor=colors.HexColor("#e53e3e"),
        leading=12, spaceAfter=4
    )

    # ── Header ────────────────────────────────────────────────────────────
    header_style = ParagraphStyle(
        "Header", parent=styles["Normal"],
        fontSize=24, textColor=TEAL,
        spaceBefore=0, spaceAfter=16,
        fontName="Helvetica-Bold", alignment=TA_CENTER,
        leading=36                           
    )
 
    story.append(Paragraph(
        '&#10010; PneumaVision<br/>'
        '<font name="Helvetica" size="10" color="#8b949e">AI Chest X-Ray Analysis Report</font>',
        header_style
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=12))

    # ── Patient Info ──────────────────────────────────────────────────────
    pi = report.get("patient_info", {})
    story.append(Paragraph("PATIENT INFORMATION", section_style))

    patient_data = [
        ["Patient Name", pi.get("patient_id") or "N/A",
         "Study ID",     pi.get("study") or "N/A"],
        ["Age",          str(pi.get("age") or "N/A"),
         "Sex",          str(pi.get("sex") or "N/A")],
        ["Report Date",  datetime.now().strftime("%d %b %Y, %H:%M"),
         "View",         str(pi.get("view") or "N/A")],
    ]
    pt = Table(patient_data, colWidths=[3.5*cm, 5*cm, 3.5*cm, 5*cm])
    pt.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,-1), colors.HexColor("#f7fafc")),
        ("TEXTCOLOR",   (0,0),(0,-1),  GRAY),
        ("TEXTCOLOR",   (2,0),(2,-1),  GRAY),
        ("FONTNAME",    (0,0),(0,-1),  "Helvetica-Bold"),
        ("FONTNAME",    (2,0),(2,-1),  "Helvetica-Bold"),
        ("FONTSIZE",    (0,0),(-1,-1), 9),
        ("GRID",        (0,0),(-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING",     (0,0),(-1,-1), 6),
    ]))
    story.append(pt)
    story.append(Spacer(1, 10))

    # ── Images — stacked vertically, full usable width ────────────────────
    story.append(Paragraph("IMAGES", section_style))

    def b64_to_rl_image(b64str: str, w: float, h: float):
        """Decode base64 and return a ReportLab Image at the given cm dimensions."""
        raw = base64.b64decode(b64str)
        bio = BytesIO(raw)
        return RLImage(bio, width=w, height=h)

    # Helper: compute height that preserves aspect ratio at a given width
    def aspect_height(b64str: str, target_w: float) -> float:
        try:
            raw = base64.b64decode(b64str)
            from PIL import Image as PILImage
            img = PILImage.open(BytesIO(raw))
            w_px, h_px = img.size
            return target_w * h_px / w_px
        except Exception:
            return target_w * 0.75   # fallback 4:3

    try:
        img_w = PAGE_W                          # full usable width

        # ── Original X-Ray ────────────────────────────────────────────────
        xray_h = aspect_height(xray_b64, img_w)
        xray_h = min(xray_h, 11*cm)            # cap so it doesn't take the whole page
        xray_img = b64_to_rl_image(xray_b64, img_w, xray_h)

        story.append(Paragraph("Original X-Ray", img_label_style))

        xray_wrap = Table([[xray_img]], colWidths=[img_w])
        xray_wrap.setStyle(TableStyle([
            ("ALIGN",      (0,0), (-1,-1), "CENTER"),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("PADDING",    (0,0), (-1,-1), 0),
            ("BOX",        (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ]))
        story.append(xray_wrap)
        story.append(Spacer(1, 10))

        # ── Grad-CAM ──────────────────────────────────────────────────────
        gcam_h = aspect_height(gradcam_b64, img_w)
        gcam_h = min(gcam_h, 11*cm)
        gcam_img = b64_to_rl_image(gradcam_b64, img_w, gcam_h)

        story.append(Paragraph("Grad-CAM Visualisation", img_label_style))

        gcam_wrap = Table([[gcam_img]], colWidths=[img_w])
        gcam_wrap.setStyle(TableStyle([
            ("ALIGN",      (0,0), (-1,-1), "CENTER"),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("PADDING",    (0,0), (-1,-1), 0),
            ("BOX",        (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ]))
        story.append(gcam_wrap)

    except Exception:
        story.append(Paragraph("(Images could not be embedded)", small_style))

    story.append(Spacer(1, 10))

    # ── Findings ──────────────────────────────────────────────────────────
    findings = report.get("findings", [])
    if findings:
        story.append(Paragraph("FINDINGS", section_style))
        priority_color = {"high": HIGH, "moderate": MOD, "low": LOW}

        f_data = [["Condition", "Confidence", "Priority", "Location"]]
        for f in findings:
            f_data.append([
                f.get("condition",""),
                f"{float(f.get('confidence',0))*100:.1f}%",
                f.get("clinical_priority","").capitalize(),
                Paragraph(f.get("anatomical_location",""), small_style),
            ])

        ft = Table(f_data, colWidths=[3.5*cm, 2.5*cm, 3*cm, 8*cm])
        ft.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,0),  colors.HexColor("#edf2f7")),
            ("FONTNAME",    (0,0),(-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0,0),(-1,-1), 8.5),
            ("GRID",        (0,0),(-1,-1), 0.4, colors.HexColor("#e2e8f0")),
            ("PADDING",     (0,0),(-1,-1), 5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#f7fafc")]),
        ]))
        story.append(ft)
        story.append(Spacer(1, 8))

    # ── Not Detected ──────────────────────────────────────────────────────
    not_detected = report.get("not_detected", [])
    if not_detected:
        story.append(Paragraph("NOT DETECTED (below threshold)", section_style))
        nd_text = "  |  ".join(
            f"{nd['condition']} ({float(nd.get('raw_score',0))*100:.1f}%)"
            for nd in not_detected
        )
        story.append(Paragraph(nd_text, small_style))
        story.append(Spacer(1, 8))

    # ── Impression ────────────────────────────────────────────────────────
    impression = report.get("impression","")
    if impression:
        story.append(Paragraph("RADIOLOGIST IMPRESSION", section_style))
        story.append(Paragraph(impression, body_style))
        story.append(Spacer(1, 8))

    # ── Disclaimer ────────────────────────────────────────────────────────
    disclaimer = report.get("disclaimer","")
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY, spaceAfter=6))
    story.append(Paragraph(
        "&#9888; " + (disclaimer or "This report was generated by an AI model and is intended for "
                 "informational purposes only. It does not constitute a medical diagnosis or "
                 "professional clinical advice. All findings must be reviewed and verified by "
                 "a qualified radiologist."),
        disclaimer_style
    ))

    doc.build(story)
    return buf.getvalue()


# ── Main analysis endpoint ────────────────────────────────────────────────────
@app.post("/analyze", tags=["Analysis"])
async def analyze(
    file:           UploadFile = File(...),
    patient_name:   str = Form(""),       # ← NEW
    patient_age:    str = Form(""),       # ← NEW
    patient_sex:    str = Form(""),       # ← NEW
    patient_email:  str = Form(""),       # ← NEW
):
    validate_upload(file)
    raw_bytes = await file.read()

    if len(raw_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_FILE_SIZE_MB} MB.")

    try:
        test_img = Image.open(BytesIO(raw_bytes))
        test_img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read as image. Upload JPEG or PNG.")

    validation = validate_chest_xray(raw_bytes)
    if not validation["is_valid"]:
        raise HTTPException(
            status_code=400,
            detail=f"Not a chest X-ray. Reason: {validation['reason']}."
        )

    suffix = Path(file.filename).suffix if file.filename else ".png"
    xray_b64 = base64.b64encode(raw_bytes).decode("utf-8")  # ← save original for PDF

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=tempfile.gettempdir()) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        tmp_path_obj = Path(tmp_path)

        inference_result = inf.run_inference(str(tmp_path_obj), save_visualization=True)

        gradcam_b64: str | None = None
        viz_path = inference_result.get("visualization_path")
        if viz_path and Path(viz_path).exists():
            gradcam_b64 = file_to_base64(viz_path)
        else:
            orig_pil = Image.open(BytesIO(raw_bytes)).convert("RGB")
            gradcam_b64 = pil_to_base64(orig_pil)

        # ── Patient info to inject ────────────────────────────────────────
        patient_info_override = {
            "patient_id": patient_name or "N/A",
            "age":        patient_age  or "N/A",
            "sex":        patient_sex  or "N/A",
        }

        report = rg.run_pipeline(
            image_path=str(tmp_path_obj),
            json_input=inference_result,
            output_path=str(tmp_path_obj.with_name(tmp_path_obj.stem + "_report.json")),
            patient_info_override=patient_info_override,   # ← NEW param
        )

        # ── Store in MongoDB ──────────────────────────────────────────────
        if patient_email:
            report_doc = {
                "email":       patient_email,
                "name":        patient_name,
                "age":         patient_age,
                "sex":         patient_sex,
                "report":      report,
                "xray_image":  xray_b64,
                "gradcam_image": gradcam_b64,
                "filename":    file.filename,
                "created_at":  datetime.utcnow(),
            }
            insert_result = reports_collection.insert_one(report_doc)

        return JSONResponse(content={
            "gradcam_image": gradcam_b64,
            "xray_image":    xray_b64,      # ← NEW: send back for PDF
            "report":        report,
            "num_findings":  inference_result["num_findings"],
            "predictions":   inference_result["predictions"],
            "report_id":     str(insert_result.inserted_id) if patient_email else None,
        })

    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(exc)}")
    finally:
        for candidate in [
            tmp_path_obj,
            tmp_path_obj.with_name(tmp_path_obj.stem + "_gradcam.png"),
            tmp_path_obj.with_name(tmp_path_obj.stem + "_report.json"),
        ]:
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception:
                pass


# ── PDF generation endpoint ───────────────────────────────────────────────────
@app.post("/generate-pdf", tags=["Report"])
async def generate_pdf(req: PDFRequest):
    """Generate and return a PDF report as a downloadable file."""
    try:
        pdf_bytes = build_pdf(req.report, req.gradcam_image, req.xray_image)
        patient_name = req.report.get("patient_info", {}).get("patient_id", "report")
        filename = f"PneumaVision_{patient_name.replace(' ','_')}.pdf"
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(exc)}")


@app.post("/preview-pdf", tags=["Report"])
async def preview_pdf(req: PDFRequest):
    try:
        import fitz  # PyMuPDF

        pdf_bytes = build_pdf(req.report, req.gradcam_image, req.xray_image)

        doc   = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []

        for page in doc:
            # Render at 2x zoom for sharp display (150 DPI equivalent)
            mat  = fitz.Matrix(2.0, 2.0)
            pix  = page.get_pixmap(matrix=mat, alpha=False)
            png  = pix.tobytes("png")
            pages.append(base64.b64encode(png).decode("utf-8"))

        doc.close()
        return JSONResponse(content={"pages": pages})

    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"PDF preview failed: {str(exc)}"
        )

@app.on_event("startup")
async def startup_event():
    print("[startup] Loading RAG knowledge base...")
    _load_resources()
    print("[startup] RAG knowledge base ready")
    seed_doctor()


@app.post("/report-chat", tags=["Chatbot"])
async def report_chat(req: ReportChatRequest):
    try:
        answer = ask_report_chatbot(report=req.report, question=req.question, history=req.history)
        return {"answer": answer}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chatbot error: {str(exc)}")


@app.post("/knowledge-chat", tags=["Chatbot"])
async def knowledge_chat(req: KnowledgeChatRequest):
    try:
        answer = ask_knowledge_chatbot(question=req.question, history=req.history)
        return {"answer": answer}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Knowledge chatbot error: {str(exc)}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)