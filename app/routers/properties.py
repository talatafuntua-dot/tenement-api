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
# AUTOMATIC TEMPLATE DISCOVERY AND SYNCHRONISATION
# =========================================================

def discover_and_register_templates(db: Session):
    """
    Synchronise the Neon template registry with the DOCX files
    currently present in the templates directory.

    - New files are registered.
    - Deleted files are deactivated.
    - Restored files are reactivated using their existing IDs.
    - Existing names and descriptions are preserved.
    """

    if not TEMPLATES_FOLDER.is_dir():
        raise HTTPException(
            status_code=500,
            detail=f"Templates directory not found: {TEMPLATES_FOLDER}"
        )

    # Discover the current DOCX files. Ignore Word temporary files.
    discovered_files = {
        path.name: path
        for path in sorted(
            TEMPLATES_FOLDER.iterdir(),
            key=lambda item: item.name.casefold()
        )
        if (
            path.is_file()
            and path.suffix.lower() == ".docx"
            and not path.name.startswith("~$")
        )
    }

    try:
        # Load the existing registry once.
        existing_templates = db.query(NoticeTemplate).all()

        existing_by_filename = {
            template.filename: template
            for template in existing_templates
        }

        existing_names = {
            template.name
            for template in existing_templates
        }

        registered = 0

        # Register new files and reactivate files that have returned.
        for filename, template_path in discovered_files.items():

            existing = existing_by_filename.get(filename)

            if existing is not None:
                existing.is_active = True
                existing.file_path = str(template_path.resolve())
                continue

            # Choose a unique display name without changing existing names.
            base_name = template_path.stem
            template_name = base_name
            counter = 2

            while template_name in existing_names:
                template_name = f"{base_name} ({counter})"
                counter += 1

            new_template = NoticeTemplate(
                name=template_name,
                filename=filename,
                file_path=str(template_path.resolve()),
                description="",
                is_active=True
            )

            db.add(new_template)
            existing_names.add(template_name)
            registered += 1

        # Deactivate records whose files are no longer in the directory.
        for template in existing_templates:
            if template.filename not in discovered_files:
                template.is_active = False

        # Flush checks database constraints before committing the changes.
        db.flush()
        db.commit()

        return registered

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Template synchronisation encountered a database conflict. "
                "Please retry the template list request."
            )
        )

    except Exception:
        db.rollback()
        raise


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
# AUTOMATICALLY DISCOVER AND SYNCHRONISE FILES
# =========================================================

@router.get("/templates")
def get_templates(
    db: Session = Depends(get_db)
):
    discover_and_register_templates(db)

    templates = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.is_active == True)
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
