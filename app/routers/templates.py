from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends
)

from sqlalchemy.orm import Session

from pathlib import Path
import shutil

from app.database import get_db
from app.models import NoticeTemplate


router = APIRouter(
    prefix="/templates",
    tags=["Templates"]
)


# =========================================================
# TEMPLATE STORAGE DIRECTORY
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[2]

TEMPLATE_DIR = BASE_DIR / "templates"

TEMPLATE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# =========================================================
# GET ALL TEMPLATES
# =========================================================

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


# =========================================================
# GET SINGLE TEMPLATE
# =========================================================

@router.get("/{template_id}")
def get_template(
    template_id: int,
    db: Session = Depends(get_db)
):

    template = (
        db.query(NoticeTemplate)
        .filter(
            NoticeTemplate.id == template_id
        )
        .first()
    )

    if not template:

        raise HTTPException(
            status_code=404,
            detail="Template not found."
        )

    # Check physical file
    file_exists = False

    if template.file_path:

        file_exists = Path(
            template.file_path
        ).exists()

    return {
        "id": template.id,
        "name": template.name,
        "filename": template.filename,
        "description": template.description,
        "file_path": template.file_path,
        "file_exists": file_exists,
        "created_at": template.created_at
    }


# =========================================================
# UPLOAD / RESTORE TEMPLATE
# =========================================================

@router.post("/upload")
def upload_template(
    file: UploadFile = File(...),
    description: str = Form(""),
    db: Session = Depends(get_db)
):

    # =====================================================
    # CHECK FILE
    # =====================================================

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="No file was provided."
        )


    # =====================================================
    # ONLY DOCX
    # =====================================================

    extension = Path(
        file.filename
    ).suffix.lower()

    if extension != ".docx":

        raise HTTPException(
            status_code=400,
            detail="Only .docx Word templates are allowed."
        )


    # =====================================================
    # CLEAN FILE NAME
    # =====================================================

    original_filename = Path(
        file.filename
    ).name

    template_name = Path(
        original_filename
    ).stem


    # =====================================================
    # DESTINATION
    # =====================================================

    destination = (
        TEMPLATE_DIR /
        original_filename
    )

    file_path = str(
        destination
    )


    # =====================================================
    # CHECK EXISTING DATABASE RECORD
    # =====================================================

    existing = (
        db.query(NoticeTemplate)
        .filter(
            NoticeTemplate.name == template_name
        )
        .first()
    )


    # =====================================================
    # EXISTING TEMPLATE
    # =====================================================

    if existing:

        # -------------------------------------------------
        # If the physical file already exists
        # -------------------------------------------------

        if destination.exists():

            raise HTTPException(
                status_code=400,
                detail=(
                    "A template with this name already exists "
                    "and its file is present."
                )
            )


        # -------------------------------------------------
        # DATABASE RECORD EXISTS BUT FILE IS MISSING
        #
        # Restore the physical file.
        # Keep the same database ID.
        # -------------------------------------------------

        try:

            with destination.open("wb") as buffer:

                shutil.copyfileobj(
                    file.file,
                    buffer
                )

        except Exception as exc:

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Could not restore template file: {exc}"
                )
            )


        # -------------------------------------------------
        # Verify restored file
        # -------------------------------------------------

        if not destination.exists():

            raise HTTPException(
                status_code=500,
                detail="Template file was not created."
            )


        # -------------------------------------------------
        # Update existing database record
        # -------------------------------------------------

        existing.filename = (
            original_filename
        )

        existing.file_path = (
            file_path
        )

        existing.description = (
            description
        )

        try:

            db.commit()

            db.refresh(existing)

        except Exception as exc:

            db.rollback()

            if destination.exists():

                destination.unlink()

            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not update existing template: "
                    f"{exc}"
                )
            )


        # -------------------------------------------------
        # RESTORED RESPONSE
        # -------------------------------------------------

        return {
            "message": (
                "Existing template restored successfully."
            ),
            "template": {
                "id": existing.id,
                "name": existing.name,
                "filename": existing.filename,
                "description": existing.description,
                "file_path": existing.file_path,
                "created_at": existing.created_at
            }
        }


    # =====================================================
    # NEW TEMPLATE
    # =====================================================

    try:

        with destination.open("wb") as buffer:

            shutil.copyfileobj(
                file.file,
                buffer
            )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not save template file: {exc}"
            )
        )


    # =====================================================
    # VERIFY FILE
    # =====================================================

    if not destination.exists():

        raise HTTPException(
            status_code=500,
            detail="Template file was not created."
        )


    # =====================================================
    # CREATE DATABASE RECORD
    # =====================================================

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

        if destination.exists():

            destination.unlink()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not save template to database: {exc}"
            )
        )


    # =====================================================
    # RESPONSE
    # =====================================================

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
