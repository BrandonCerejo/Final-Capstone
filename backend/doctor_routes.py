from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from bson import ObjectId
from database import reports_collection, db, label_corrections_collection
import bcrypt

router = APIRouter()

doctors_collection  = db["doctors"]
feedbacks_collection = db["feedbacks"]

class DoctorLoginRequest(BaseModel):
    email:    str
    password: str

class SendToDoctorRequest(BaseModel):
    report_id:      str
    patient_email:  str
    doctor_email:   str
    doctor_name:    str

class FeedbackRequest(BaseModel):
    report_id:    str
    doctor_email: str
    feedback:     str

class LabelCorrectionRequest(BaseModel):
    report_id:       str
    doctor_email:    str
    predicted_labels: list[str]
    is_correct:      bool
    correct_labels:  list[str]

def seed_doctor():
    default_doctors = [
        {
            "name":  "Dr. Sarah Mitchell",
            "email": "sarah@pneumavision.com",
            "password": b"doctor123",
        },
        {
            "name":  "Dr. James Anderson",
            "email": "james@pneumavision.com",
            "password": b"doctor123",
        },
        {
            "name":  "Dr. Priya Sharma",
            "email": "priya@pneumavision.com",
            "password": b"doctor123",
        },
        {
            "name":  "Dr. Michael Chen",
            "email": "michael@pneumavision.com",
            "password": b"doctor123",
        },
    ]

    for doc in default_doctors:
        existing = doctors_collection.find_one({"email": doc["email"]})
        if not existing:
            hashed = bcrypt.hashpw(doc["password"], bcrypt.gensalt())
            doctors_collection.insert_one({
                "name":       doc["name"],
                "email":      doc["email"],
                "password":   hashed,
                "created_at": datetime.utcnow(),
            })
            print(f"[startup] Doctor created → {doc['email']} / doctor123")


def clean_doc(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    # drop heavy base64 blobs from list views — frontend fetches full detail separately
    doc.pop("xray_image",    None)
    doc.pop("gradcam_image", None)
    return doc

@router.post("/doctor/login", tags=["Doctor"])
def doctor_login(req: DoctorLoginRequest):
    doctor = doctors_collection.find_one({"email": req.email})
    if not doctor:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not bcrypt.checkpw(req.password.encode(), doctor["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    return {
        "message": "Login successful",
        "doctor": {
            "name":  doctor["name"],
            "email": doctor["email"],
        }
    }

@router.get("/doctor/list", tags=["Doctor"])
def get_doctors_list():
    """Return all doctors for patient to choose from."""
    doctors = list(doctors_collection.find({}, {"password": 0}))
    return [
        {
            "id":    str(d["_id"]),
            "name":  d.get("name", ""),
            "email": d.get("email", ""),
        }
        for d in doctors
    ]

@router.post("/doctor/send-report", tags=["Doctor"])
def send_report_to_doctor(req: SendToDoctorRequest):
    """Mark a report as sent to the doctor."""
    try:
        oid = ObjectId(req.report_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid report ID.")

    result = reports_collection.update_one(
        {"_id": oid, "email": req.patient_email},
        {"$set": {
            "sent_to_doctor":  True,
            "sent_at":         datetime.utcnow(),
            "doctor_email":    req.doctor_email,
            "doctor_name":     req.doctor_name,
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"message": "Report sent to doctor successfully."}

@router.get("/doctor/reports", tags=["Doctor"])
def get_doctor_reports(doctor_email: str):
    """Return only reports sent to this specific doctor."""
    docs = list(reports_collection.find({
        "sent_to_doctor": True,
        "doctor_email": doctor_email
    }))
    result = []
    for doc in docs:
        rid = str(doc["_id"])
        # attach feedback if exists
        
        fb = feedbacks_collection.find_one({"report_id": rid})
        lc = label_corrections_collection.find_one({"report_id": rid})
        entry = {
            "id":                   rid,
            "name":                 doc.get("name", "N/A"),
            "email":                doc.get("email", ""),
            "age":                  doc.get("age", "N/A"),
            "sex":                  doc.get("sex", "N/A"),
            "filename":             doc.get("filename", ""),
            "created_at":           doc.get("created_at", "").isoformat() if doc.get("created_at") else "",
            "sent_at":              doc.get("sent_at", "").isoformat() if doc.get("sent_at") else "",
            "sent_to_doctor":       doc.get("sent_to_doctor", False),
            "doctor_name":          doc.get("doctor_name", ""),
            "doctor_email":         doc.get("doctor_email", ""),
            "has_feedback":         fb is not None,
            "has_label_correction": lc is not None,
            "feedback":             fb["feedback"] if fb else None,
            "feedback_at":          fb["created_at"].isoformat() if fb and fb.get("created_at") else None,
            "gradcam_image":        doc.get("gradcam_image", ""),
            "xray_image":           doc.get("xray_image", ""),
            "report":               doc.get("report", {}),
        }
        result.append(entry)
    # newest first
    result.sort(key=lambda x: x["sent_at"] or "", reverse=True)
    unused_count = label_corrections_collection.count_documents({"used_for_training": False})
    return {"reports": result, "export_ready": unused_count >= 2}

@router.post("/doctor/feedback", tags=["Doctor"])
def submit_feedback(req: FeedbackRequest):
    """Doctor submits or updates feedback for a report."""
    # upsert so re-submitting overwrites
    feedbacks_collection.update_one(
        {"report_id": req.report_id},
        {"$set": {
            "report_id":    req.report_id,
            "doctor_email": req.doctor_email,
            "feedback":     req.feedback.strip(),
            "created_at":   datetime.utcnow(),
        }},
        upsert=True
    )
    # flag on the report itself so patient can see a badge
    try:
        reports_collection.update_one(
            {"_id": ObjectId(req.report_id)},
            {"$set": {"has_feedback": True}}
        )
    except Exception:
        pass
    return {"message": "Feedback submitted successfully."}

@router.get("/patient/reports", tags=["Patient"])
def get_patient_reports(email: str):
    """Return all reports for a patient, with feedback attached if available."""
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    docs = list(reports_collection.find({"email": email}))
    result = []
    for doc in docs:
        rid = str(doc["_id"])
        fb  = feedbacks_collection.find_one({"report_id": rid})
        entry = {
            "id":            rid,
            "filename":      doc.get("filename", ""),
            "created_at":    doc.get("created_at", "").isoformat() if doc.get("created_at") else "",
            "sent_to_doctor": doc.get("sent_to_doctor", False),
            "doctor_name":   doc.get("doctor_name", ""),
            "doctor_email":  doc.get("doctor_email", ""),
            "has_feedback":  fb is not None,
            "feedback":      fb["feedback"]              if fb else None,
            "feedback_at":   fb["created_at"].isoformat() if fb and fb.get("created_at") else None,
            "report":        doc.get("report", {}),
            "gradcam_image": doc.get("gradcam_image", ""),
            "xray_image":    doc.get("xray_image", ""),
        }
        result.append(entry)
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result

@router.post("/doctor/label-correction", tags=["Doctor"])
def submit_label_correction(req: LabelCorrectionRequest):
    # Get xray image from report
    try:
        report = reports_collection.find_one({"_id": ObjectId(req.report_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid report ID.")
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    xray_b64 = report.get("xray_image", "")

    # Save correction
    label_corrections_collection.update_one(
        {"report_id": req.report_id},
        {"$set": {
            "report_id":        req.report_id,
            "doctor_email":     req.doctor_email,
            "predicted_labels": req.predicted_labels,
            "is_correct":       req.is_correct,
            "correct_labels":   req.correct_labels if not req.is_correct else req.predicted_labels,
            "xray_image_b64":   xray_b64,
            "used_for_training": False,
            "created_at":       datetime.utcnow(),
        }},
        upsert=True
    )

    # Check count for export readiness
    unused_count = label_corrections_collection.count_documents(
        {"used_for_training": False}
    )

    # return {
    #     "message": "Label correction saved.",
    #     "unused_corrections": unused_count,
    #     "export_ready": unused_count >= 2
    # }

    if unused_count >= 2:
        print("\n" + "=" * 60)
        print("=" + " " * 58 + "=")
        print("TRAINING ZIP READY — {} corrections ready!{}".format(unused_count, " " * (18 - len(str(unused_count)))))
        print("GET http://localhost:8000/doctor/export-training-data")
        print("=" + " " * 58 + "=")
        print("=" * 60 + "\n")

    return {
        "message": "Label correction saved.",
        "unused_corrections": unused_count,
        "export_ready": unused_count >= 2
    }

@router.get("/doctor/export-training-data", tags=["Doctor"])
def export_training_data():
    import zipfile, io, csv, base64

    corrections = list(label_corrections_collection.find(
        {"used_for_training": False}
    ))
    if not corrections:
        raise HTTPException(status_code=404, detail="No corrections available.")

    LABELS = [
        "Atelectasis", "Cardiomegaly", "Effusion", "Infiltration", "Mass",
        "Nodule", "Pneumonia", "Pneumothorax", "Consolidation", "Edema",
        "Emphysema", "Fibrosis", "Pleural_Thickening", "Hernia",
    ]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

        # CSV
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["image_name"] + LABELS)

        for doc in corrections:
            image_name = f"{doc['report_id']}.png"
            correct    = doc.get("correct_labels", [])
            row        = [image_name] + [1 if lbl in correct else 0 for lbl in LABELS]
            writer.writerow(row)

            # Write image
            if doc.get("xray_image_b64"):
                img_bytes = base64.b64decode(doc["xray_image_b64"])
                zf.writestr(f"images/{image_name}", img_bytes)

        zf.writestr("labels.csv", csv_buffer.getvalue())

    # Mark all as used
    ids = [doc["_id"] for doc in corrections]
    label_corrections_collection.update_many(
        {"_id": {"$in": ids}},
        {"$set": {"used_for_training": True}}
    )

    zip_buffer.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=training_data.zip"}
    )


@router.get("/admin/check-training", tags=["Admin"])
def check_training_status():
    unused_count = label_corrections_collection.count_documents({"used_for_training": False})
    print("\n" + "█" * 60)
    print(f"CORRECTIONS IN DB: {unused_count}  {'READY!' if unused_count >= 2 else 'NOT READY YET'}")
    print(f"http://localhost:8000/doctor/export-training-data")
    print("█" * 60 + "\n")
    return {"unused_count": unused_count, "export_ready": unused_count >= 2}