import os
import shutil

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NoticeTemplate


router = APIRouter(
    prefix="/templates",
    tags=["Templates"]
)


TEMPLATE_DIR = "/app/templates"

os.makedirs(TEMPLATE_DIR, exist_ok=True)


@router.post("/upload")
def upload_template(
    name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file selected."
        )

    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only Microsoft Word .docx files are allowed."
        )

    name = name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Template name is required."
        )

    existing = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.name == name)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="A template with this name already exists."
        )

    safe_filename = os.path.basename(file.filename)

    file_path = os.path.join(
        TEMPLATE_DIR,
        safe_filename
    )

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to save template: {str(e)}"
        )

    template = NoticeTemplate(
        name=name,
        filename=safe_filename,
        file_path=file_path,
        description=description.strip()
    )

    db.add(template)

    try:
        db.commit()
        db.refresh(template)

    except Exception as e:
        db.rollback()

        if os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(
            status_code=500,
            detail=f"Unable to save template information: {str(e)}"
        )

    return {
        "message": "Template uploaded successfully.",
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
        .order_by(NoticeTemplate.name)
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
