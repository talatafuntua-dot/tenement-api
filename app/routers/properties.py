from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from sqlalchemy.orm import Session

from pathlib import Path

from app.database import get_db
from app import crud
from app.pdf_generator import generate_notice_pdf


router = APIRouter(
    prefix="/properties",
    tags=["Properties"]
)


# =====================================================
# TEMPLATE LOCATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[2]

TEMPLATES_FOLDER = (
    BASE_DIR / "templates"
)


# =====================================================
# GET PROPERTIES
# =====================================================

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


# =====================================================
# UNIVERSAL PROPERTY SEARCH
#
# Searches:
#
#   LG Code       - if column exists
#   Owner Name
#   Property Number
#
# All searches are case-insensitive.
# =====================================================

@router.get("/search")
def search_properties(
    query: str,
    db: Session = Depends(get_db)
):

    return crud.search_properties(
        db,
        query
    )


# =====================================================
# SEARCH BY OWNER
#
# Existing endpoint retained for compatibility.
# =====================================================

@router.get("/search/owner")
def search_by_owner(
    owner_name: str,
    db: Session = Depends(get_db)
):

    return crud.search_owner(
        db,
        owner_name
    )


# =====================================================
# AVAILABLE TEMPLATES
# =====================================================

@router.get("/templates")
def get_templates():

    if not TEMPLATES_FOLDER.exists():

        return {
            "templates": []
        }


    templates = []


    for file in sorted(
        TEMPLATES_FOLDER.glob("*.docx")
    ):

        templates.append(
            {
                "name": file.name,
                "label": file.stem.replace(
                    "_",
                    " "
                ).title()
            }
        )


    return {
        "templates": templates
    }


# =====================================================
# GET PROPERTY
#
# This route accepts property numbers
# containing '/'
#
# Property Number lookup remains available.
# =====================================================

@router.get("/{property_no:path}")
def get_property(
    property_no: str,
    db: Session = Depends(get_db)
):

    property = (
        crud.get_property_by_number(
            db,
            property_no
        )
    )


    if not property:

        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )


    return property

```python
# =====================================================
# GENERATE NOTICE
# =====================================================

@router.post("/generate-notice")
async def generate_notice(
    data: dict,
    db: Session = Depends(get_db)
):

    property_no = data.get("property_no")

    if not property_no:
        raise HTTPException(
            status_code=400,
            detail="Property number is required"
        )

    # -------------------------------------------------
    # Find property
    # -------------------------------------------------

    property = crud.get_property_by_number(
        db,
        property_no
    )

    if not property:
        raise HTTPException(
            status_code=404,
            detail="Property not found"
        )

    # -------------------------------------------------
    # Select template
    #
    # If template_id is supplied:
    #     Load template from notice_templates
    #
    # Otherwise:
    #     Keep existing template behavior
    # -------------------------------------------------

    template_id = data.get("template_id")

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

        template_name = template_record.filename

    else:

        # -------------------------------------------------
        # Backward compatibility
        # -------------------------------------------------

        template_name = data.get(
            "template",
            "template.docx"
        )

    # -------------------------------------------------
    # Generate PDF
    # -------------------------------------------------

    try:

        pdf_file = generate_notice_pdf(
            property,
            template_name
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

    # -------------------------------------------------
    # Response
    # -------------------------------------------------

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
```
