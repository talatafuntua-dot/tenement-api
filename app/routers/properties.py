from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from sqlalchemy.orm import Session

from pathlib import Path

from app.database import get_db
from app import crud
from app.models import NoticeTemplate
from app.pdf_generator import generate_notice_pdf


router = APIRouter(
    prefix="/properties",
    tags=["Properties"]
)


# =========================================================
# DIRECTORIES
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[2]

TEMPLATES_FOLDER = BASE_DIR / "templates"


# =========================================================
# GET PROPERTIES
# =========================================================

@router.get("/")
def get_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):

    return crud.get_all_properties(
        db,
        skip,
        limit
    )


# =========================================================
# UNIVERSAL PROPERTY SEARCH
# =========================================================

@router.get("/search")
def search_properties(
    query: str,
    db: Session = Depends(get_db)
):

    return crud.search_properties(
        db,
        query
    )


# =========================================================
# SEARCH BY OWNER
# =========================================================

@router.get("/search/owner")
def search_by_owner(
    owner_name: str,
    db: Session = Depends(get_db)
):

    return crud.search_owner(
        db,
        owner_name
    )


# =========================================================
# AVAILABLE TEMPLATES
# =========================================================

@router.get("/templates")
def get_templates(
    db: Session = Depends(get_db)
):

    templates = (
        db.query(NoticeTemplate)
        .order_by(NoticeTemplate.id.desc())
        .all()
    )

    result = []

    for template in templates:

        result.append(
            {
                "id": template.id,
                "name": template.name,
                "filename": template.filename,
                "description": template.description
            }
        )

    return {
        "templates": result
    }


# =========================================================
# GENERATE NOTICE
# =========================================================

@router.post("/generate-notice")
async def generate_notice(
    data: dict,
    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # Property number
    # -----------------------------------------------------

    property_no = data.get(
        "property_no"
    )

    if not property_no:

        raise HTTPException(
            status_code=400,
            detail="Property number is required"
        )

    # -----------------------------------------------------
    # Find property
    # -----------------------------------------------------

    property_record = (
        crud.get_property_by_number(
            db,
            property_no
        )
    )

    if not property_record:

        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    # -----------------------------------------------------
    # Template selection
    # -----------------------------------------------------

    template_id = data.get(
        "template_id"
    )

    template_record = None

    # -----------------------------------------------------
    # Use database template when template_id supplied
    # -----------------------------------------------------

    if template_id is not None:

        try:

            template_id = int(
                template_id
            )

        except (TypeError, ValueError):

            raise HTTPException(
                status_code=400,
                detail="template_id must be an integer"
            )

        template_record = (
            db.query(NoticeTemplate)
            .filter(
                NoticeTemplate.id == template_id
            )
            .first()
        )

        if not template_record:

            raise HTTPException(
                status_code=404,
                detail="Template not found"
            )

        # IMPORTANT:
        # Use the database file path.

        template_path = Path(
            template_record.file_path
        )

        template_name = (
            template_record.filename
        )

    # -----------------------------------------------------
    # Backward-compatible filename selection
    # -----------------------------------------------------

    else:

        template_name = data.get(
            "template",
            "template.docx"
        )

        template_name = Path(
            template_name
        ).name

        template_path = (
            TEMPLATES_FOLDER /
            template_name
        )

    # -----------------------------------------------------
    # Verify template exists
    # -----------------------------------------------------

    if not template_path.exists():

        raise HTTPException(
            status_code=404,
            detail=(
                f"Template file not found: "
                f"{template_path}"
            )
        )

    # -----------------------------------------------------
    # Generate PDF
    # -----------------------------------------------------

    try:

        pdf_file = generate_notice_pdf(
            property_record=property_record,
            template_path=template_path
        )

    except FileNotFoundError as error:

        raise HTTPException(
            status_code=404,
            detail=str(error)
        )

    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )

    # -----------------------------------------------------
    # Response
    # -----------------------------------------------------

    return {
        "message":
            "Notice generated successfully",

        "pdf":
            pdf_file,

        "template":
            template_name,

        "template_id":
            template_id
    }


# =========================================================
# GET PROPERTY
#
# IMPORTANT:
# This catch-all route is LAST.
# It accepts property numbers containing "/".
# =========================================================

@router.get("/{property_no:path}")
def get_property(
    property_no: str,
    db: Session = Depends(get_db)
):

    property_record = (
        crud.get_property_by_number(
            db,
            property_no
        )
    )

    if not property_record:

        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    return property_record
