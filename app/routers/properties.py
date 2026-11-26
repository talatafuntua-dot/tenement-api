
import secrets
import string
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app import crud
from app.models import (
    NoticeTemplate,
    Property,
    IndividualGenerationHistory
)
from app.pdf_generator import generate_notice_pdf
from app.lg_code_allocator import get_or_create_lg_code


router = APIRouter(
    prefix="/properties",
    tags=["Properties"]
)

BASE_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_FOLDER = BASE_DIR / "templates"


# =========================================================
# AUTOMATIC TEMPLATE DISCOVERY
# =========================================================

def discover_and_register_templates(db: Session):
    """
    Automatically discover DOCX templates and register
    previously unseen files in the database.

    Existing template IDs and descriptions are preserved.
    """

    if not TEMPLATES_FOLDER.is_dir():
        raise HTTPException(
            status_code=500,
            detail=f"Templates directory not found: {TEMPLATES_FOLDER}"
        )

    discovered_files = sorted(
        [
            path for path in TEMPLATES_FOLDER.iterdir()
            if (
                path.is_file()
                and path.suffix.lower() == ".docx"
                and not path.name.startswith("~$")
            )
        ],
        key=lambda path: path.name.casefold()
    )

    registered = 0

    for template_path in discovered_files:

        filename = template_path.name

        # -------------------------------------------------
        # Check whether this filename is already registered
        # -------------------------------------------------

        existing = (
            db.query(NoticeTemplate)
            .filter(NoticeTemplate.filename == filename)
            .first()
        )

        if existing:
            continue

        # -------------------------------------------------
        # Generate a unique template name
        # -------------------------------------------------

        base_name = template_path.stem
        template_name = base_name
        counter = 2

        while (
            db.query(NoticeTemplate)
            .filter(NoticeTemplate.name == template_name)
            .first()
        ):
            template_name = f"{base_name} ({counter})"
            counter += 1

        # -------------------------------------------------
        # Register the new template
        # -------------------------------------------------

        new_template = NoticeTemplate(
            name=template_name,
            filename=filename,
            file_path=str(template_path.resolve()),
            description=""
        )

        db.add(new_template)

        try:
            db.commit()
            registered += 1

        except IntegrityError:

            db.rollback()

            # Another request may have registered it
            # while this request was running.

            existing = (
                db.query(NoticeTemplate)
                .filter(NoticeTemplate.filename == filename)
                .first()
            )

            if not existing:
                raise

    return registered


# =========================================================
# GET PROPERTIES
# =========================================================

@router.get("/")
def get_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    return crud.get_all_properties(db, skip, limit)


# =========================================================
# UNIVERSAL PROPERTY SEARCH
# =========================================================

@router.get("/search")
def search_properties(
    query: str,
    db: Session = Depends(get_db)
):
    return crud.search_properties(db, query)


# =========================================================
# SEARCH BY OWNER
# =========================================================

@router.get("/search/owner")
def search_by_owner(
    owner_name: str,
    db: Session = Depends(get_db)
):
    return crud.search_owner(db, owner_name)


# =========================================================
# AVAILABLE TEMPLATES
# AUTOMATICALLY DISCOVER AND REGISTER NEW FILES
# =========================================================

@router.get("/templates")
def get_templates(
    db: Session = Depends(get_db)
):

    discover_and_register_templates(db)

    templates = (
        db.query(NoticeTemplate)
        .order_by(NoticeTemplate.id.asc())
        .all()
    )

    return {
        "templates": [
            {
                "id": template.id,
                "name": template.name,
                "filename": template.filename,
                "description": template.description or ""
            }
            for template in templates
        ]
    }


# =========================================================
# GET PROPERTY BY UNIQUE NEON ID
# =========================================================

@router.get("/by-id/{property_id}")
def get_property_by_id(
    property_id: int,
    db: Session = Depends(get_db)
):

    property_record = (
        db.query(Property)
        .filter(Property.id == property_id)
        .first()
    )

    if not property_record:
        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    return property_record


# =========================================================
# GENERATE NOTICE
# =========================================================

@router.post("/generate-notice")
async def generate_notice(
    data: dict,
    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # Find exact property by Neon ID.
    # Keep property-number fallback for older callers.
    # -----------------------------------------------------

    property_id = data.get("property_id")
    property_no = data.get("property_no")

    if property_id is not None:

        try:
            property_id = int(property_id)

        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="property_id must be an integer"
            )

        property_record = (
            db.query(Property)
            .filter(Property.id == property_id)
            .first()
        )

    elif property_no:

        property_record = crud.get_property_by_number(
            db,
            property_no
        )

    else:

        raise HTTPException(
            status_code=400,
            detail="Property ID or property number is required"
        )

    if not property_record:
        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    # -----------------------------------------------------
    # Generate or retrieve LG Code
    # -----------------------------------------------------

    property_record.lg_code = get_or_create_lg_code(
        db,
        property_record,
        prefix=property_record.lg_prefix
    )

    db.commit()
    db.refresh(property_record)

    # -----------------------------------------------------
    # TEMPLATE SELECTION
    # -----------------------------------------------------

    template_id = data.get("template_id")
    template_record = None

    if template_id is not None:

        try:
            template_id = int(template_id)

        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="template_id must be an integer"
            )

        template_record = (
            db.query(NoticeTemplate)
            .filter(NoticeTemplate.id == template_id)
            .first()
        )

        if not template_record:
            raise HTTPException(
                status_code=404,
                detail="Template not found"
            )

        template_path = Path(template_record.file_path)
        template_name = template_record.filename

    else:

        template_name = Path(
            data.get("template", "template.docx")
        ).name

        template_path = TEMPLATES_FOLDER / template_name

    # -----------------------------------------------------
    # VERIFY TEMPLATE EXISTS
    # -----------------------------------------------------

    if not template_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Template file not found: {template_path}"
        )

    # -----------------------------------------------------
    # GENERATE PDF
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
    # RECORD SUCCESSFUL INDIVIDUAL BILL GENERATION
    # -----------------------------------------------------

    history_record = IndividualGenerationHistory(
        property_id=property_record.id,
        property_no=property_record.property_no,
        lg_code=property_record.lg_code,
        template_id=template_id,
        pdf_filename=Path(pdf_file).name if pdf_file else None
    )

    db.add(history_record)
    db.commit()

    return {
        "message": "Notice generated successfully",
        "pdf": pdf_file,
        "template": template_name,
        "template_id": template_id
    }


# =========================================================
# GET PROPERTY BY PROPERTY NUMBER
# KEEP THIS CATCH-ALL ROUTE LAST
# =========================================================

@router.get("/{property_no:path}")
def get_property(
    property_no: str,
    db: Session = Depends(get_db)
):

    property_record = crud.get_property_by_number(
        db,
        property_no
    )

    if not property_record:
        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    return property_record
