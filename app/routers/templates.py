from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
import re

from app.database import get_db
from app.models import NoticeTemplate


router = APIRouter(
    prefix="/templates",
    tags=["Templates"]
)


TEMPLATE_DIR = Path("/app/templates")
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
def upload_template(
    file: UploadFile = File(...),
    description: str = Form(""),
    db: Session = Depends(get_db)
):
    # --------------------------------------------------
    # Validate file
    # --------------------------------------------------

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file selected."
        )

    original_filename = Path(file.filename).name

    # Only DOCX templates
    if not original_filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .docx template files are allowed."
        )

    # --------------------------------------------------
    # Create clean template name from filename
    # --------------------------------------------------

    template_name = Path(original_filename).stem

    # Remove unwanted characters
    template_name = re.sub(
        r"[^A-Za-z0-9_\- ]+",
        "",
        template_name
    ).strip()

    if not template_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid template filename."
        )

    # --------------------------------------------------
    # Check duplicate template name
    # --------------------------------------------------

    existing = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.name == template_name)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="A template with this name already exists."
        )

    # --------------------------------------------------
    # Check duplicate filename
    # --------------------------------------------------

    existing_file = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.filename == original_filename)
        .first()
    )

    if existing_file:
        raise HTTPException(
            status_code=400,
            detail="A template with this filename already exists."
        )

    # --------------------------------------------------
    # Save physical DOCX file
    # --------------------------------------------------

    destination = TEMPLATE_DIR / original_filename

    try:
        with destination.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not save template: {exc}"
        )

    # --------------------------------------------------
    # Save database record
    # --------------------------------------------------

   template = NoticeTemplate(
    name=template_name,
    filename=original_filename,
    file_path=str(destination),
    description=description or ""
)
    db.add(template)
    db.commit()
    db.refresh(template)

    # --------------------------------------------------
    # Return result
    # --------------------------------------------------

    return {
        "message": "Template uploaded successfully",
        "template": {
            "id": template.id,
            "name": template.name,
            "filename": template.filename,
            "description": template.description,
            "created_at": template.created_at
        }
    }


@router.get("/")
def get_templates(
    db: Session = Depends(get_db)
):
    templates = (
        db.query(NoticeTemplate)
        .order_by(NoticeTemplate.id)
        .all()
    )

    return [
        {
            "id": template.id,
            "name": template.name,
            "filename": template.filename,
            "description": template.description,
            "created_at": template.created_at
        }
        for template in templates
    ]


@router.get("/{template_id}")
def get_template(
    template_id: int,
    db: Session = Depends(get_db)
):
    template = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.id == template_id)
        .first()
    )

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Template not found."
        )

    return {
        "id": template.id,
        "name": template.name,
        "filename": template.filename,
        "description": template.description,
        "created_at": template.created_at
    }
