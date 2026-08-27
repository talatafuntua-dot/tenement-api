from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from pathlib import Path
import shutil

from app.database import get_db
from app.models import NoticeTemplate


router = APIRouter(
    prefix="/templates",
    tags=["Templates"]
)


# ---------------------------------------------------------
# TEMPLATE STORAGE DIRECTORY
# ---------------------------------------------------------

TEMPLATE_DIR = Path("/app/templates")

TEMPLATE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ---------------------------------------------------------
# GET ALL TEMPLATES
# ---------------------------------------------------------

@router.get("/")
def get_templates(
    db: Session = Depends(get_db)
):
    templates = (
        db.query(NoticeTemplate)
        .order_by(NoticeTemplate.id.desc())
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


# ---------------------------------------------------------
# GET SINGLE TEMPLATE
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# UPLOAD TEMPLATE
# ---------------------------------------------------------

@router.post("/upload")
def upload_template(
    file: UploadFile = File(...),
    description: str = Form(""),
    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # CHECK FILE
    # -----------------------------------------------------

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file was provided."
        )


    # -----------------------------------------------------
    # ONLY ALLOW WORD DOCUMENTS
    # -----------------------------------------------------

    extension = Path(file.filename).suffix.lower()

    if extension != ".docx":
        raise HTTPException(
            status_code=400,
            detail="Only .docx Word templates are allowed."
        )


    # -----------------------------------------------------
    # CLEAN FILE NAME
    # -----------------------------------------------------

    original_filename = Path(file.filename).name

    template_name = Path(
        original_filename
    ).stem


    # -----------------------------------------------------
    # CHECK DUPLICATE TEMPLATE
    # -----------------------------------------------------

    existing = (
        db.query(NoticeTemplate)
        .filter(
            NoticeTemplate.name == template_name
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="A template with this name already exists."
        )


    # -----------------------------------------------------
    # CREATE FILE PATH
    # -----------------------------------------------------

    destination = TEMPLATE_DIR / original_filename

    file_path = str(destination)


    # -----------------------------------------------------
    # SAVE UPLOADED FILE
    # -----------------------------------------------------

    try:

        with destination.open("wb") as buffer:

            shutil.copyfileobj(
                file.file,
                buffer
            )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"Could not save template file: {exc}"
        )


    # -----------------------------------------------------
    # CREATE DATABASE RECORD
    # -----------------------------------------------------

    template = NoticeTemplate(
        name=template_name,
        filename=original_filename,
        file_path=file_path,
        description=description
    )


    db.add(template)

    try:

        db.commit()

        db.refresh(template)

    except Exception as exc:

        db.rollback()

        # Remove uploaded file if database insertion fails

        if destination.exists():

            destination.unlink()

        raise HTTPException(
            status_code=500,
            detail=f"Could not save template to database: {exc}"
        )


    # -----------------------------------------------------
    # RESPONSE
    # -----------------------------------------------------

    return {
        "message": "Template uploaded successfully.",
        "template": {
            "id": template.id,
            "name": template.name,
            "filename": template.filename,
            "description": template.description,
            "file_path": template.file_path,
            "created_at": template.created_at
        }
    }
