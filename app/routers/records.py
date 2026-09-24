from io import BytesIO
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query
)

from fastapi.responses import StreamingResponse

from sqlalchemy import or_, asc, desc
from sqlalchemy.orm import Session

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

from app.database import get_db
from app.models import Property


# =========================================================
# ROUTER
# =========================================================

router = APIRouter(
    prefix="/records",
    tags=["Records"]
)


# =========================================================
# ALLOWED SORT FIELDS
# =========================================================

SORT_FIELDS = {
    "id": Property.id,
    "property_no": Property.property_no,
    "owner_name": Property.owner_name,
    "address": Property.address,
    "rating_area": Property.rating_area,
    "annual_value": Property.annual_value,
    "rate_due": Property.rate_due,
    "year": Property.year,
    "status": Property.status,
    "lg_code": Property.lg_code,
    "lg_id": Property.lg_id,
    "lg_prefix": Property.lg_prefix,
    "created_at": Property.created_at,
    "updated_at": Property.updated_at,
}


# =========================================================
# SHARED FILTER LOGIC
#
# Used by BOTH:
#
# /records/
# /records/export
#
# This keeps display and export consistent.
# =========================================================

def build_records_query(
    db: Session,
    search: str | None = None,
    year: int | None = None,
    status: str | None = None,
    rating_area: str | None = None,
    lg_id: int | None = None,
    lg_prefix: str | None = None
):

    query = db.query(Property)

    # -----------------------------------------------------
    # Universal search
    # -----------------------------------------------------

    if search:

        search = search.strip()

        if search:

            pattern = f"%{search}%"

            query = query.filter(
                or_(
                    Property.property_no.ilike(pattern),
                    Property.owner_name.ilike(pattern),
                    Property.address.ilike(pattern),
                    Property.rating_area.ilike(pattern),
                    Property.lg_code.ilike(pattern),
                    Property.lg_prefix.ilike(pattern)
                )
            )

    # -----------------------------------------------------
    # Year
    # -----------------------------------------------------

    if year is not None:

        query = query.filter(
            Property.year == year
        )

    # -----------------------------------------------------
    # Status
    # -----------------------------------------------------

    if status:

        status = status.strip()

        if status:

            query = query.filter(
                Property.status.ilike(status)
            )

    # -----------------------------------------------------
    # Rating Area
    # -----------------------------------------------------

    if rating_area:

        rating_area = rating_area.strip()

        if rating_area:

            query = query.filter(
                Property.rating_area.ilike(
                    f"%{rating_area}%"
                )
            )

    # -----------------------------------------------------
    # Local Government ID
    # -----------------------------------------------------

    if lg_id is not None:

        query = query.filter(
            Property.lg_id == lg_id
        )

    # -----------------------------------------------------
    # LG Prefix
    # -----------------------------------------------------

    if lg_prefix:

        lg_prefix = lg_prefix.strip()

        if lg_prefix:

            query = query.filter(
                Property.lg_prefix.ilike(
                    lg_prefix
                )
            )

    return query


# =========================================================
# SERIALIZE PROPERTY
# =========================================================

def serialize_property(record: Property):

    return {
        "id": record.id,
        "property_no": record.property_no,
        "owner_name": record.owner_name,
        "address": record.address,
        "rating_area": record.rating_area,

        "annual_value": (
            float(record.annual_value)
            if record.annual_value is not None
            else 0
        ),

        "rate_due": (
            float(record.rate_due)
            if record.rate_due is not None
            else 0
        ),

        "year": record.year,
        "status": record.status,
        "lg_code": record.lg_code,
        "lg_id": record.lg_id,
        "lg_prefix": record.lg_prefix,

        "created_at": (
            record.created_at.isoformat()
            if record.created_at
            else None
        ),

        "updated_at": (
            record.updated_at.isoformat()
            if record.updated_at
            else None
        )
    }


# =========================================================
# GET RECORDS
#
# Examples:
#
# /records/?limit=10
# /records/?limit=50
# /records/?limit=50&offset=50
# /records/?search=ABU
# /records/?year=2026
# /records/?status=UNPAID
# /records/?rating_area=GUSAU
#
# =========================================================

@router.get("/")
def get_records(

    limit: int = Query(
        default=50,
        ge=1,
        le=500
    ),

    offset: int = Query(
        default=0,
        ge=0
    ),

    search: str | None = None,

    year: int | None = None,

    status: str | None = None,

    rating_area: str | None = None,

    lg_id: int | None = None,

    lg_prefix: str | None = None,

    sort_by: str = Query(
        default="id"
    ),

    sort_order: str = Query(
        default="asc"
    ),

    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # Validate sort field
    # -----------------------------------------------------

    if sort_by not in SORT_FIELDS:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid sort field. "
                f"Allowed fields: "
                f"{', '.join(SORT_FIELDS.keys())}"
            )
        )

    # -----------------------------------------------------
    # Validate sort order
    # -----------------------------------------------------

    sort_order = sort_order.lower()

    if sort_order not in (
        "asc",
        "desc"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "sort_order must be "
                "'asc' or 'desc'"
            )
        )

    # -----------------------------------------------------
    # Build filtered query
    # -----------------------------------------------------

    query = build_records_query(
        db=db,
        search=search,
        year=year,
        status=status,
        rating_area=rating_area,
        lg_id=lg_id,
        lg_prefix=lg_prefix
    )

    # -----------------------------------------------------
    # Total BEFORE pagination
    # -----------------------------------------------------

    total = query.count()

    # -----------------------------------------------------
    # Sorting
    # -----------------------------------------------------

    sort_column = SORT_FIELDS[
        sort_by
    ]

    if sort_order == "desc":

        query = query.order_by(
            desc(sort_column)
        )

    else:

        query = query.order_by(
            asc(sort_column)
        )

    # -----------------------------------------------------
    # Pagination
    # -----------------------------------------------------

    records = (
        query
        .offset(offset)
        .limit(limit)
        .all()
    )

    # -----------------------------------------------------
    # Calculate page information
    # -----------------------------------------------------

    current_page = (
        offset // limit
    ) + 1

    total_pages = (
        (total + limit - 1)
        // limit
        if total > 0
        else 0
    )

    # -----------------------------------------------------
    # Response
    # -----------------------------------------------------

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "current_page": current_page,
        "total_pages": total_pages,
        "returned": len(records),

        "has_previous": (
            offset > 0
        ),

        "has_next": (
            offset + limit < total
        ),

        "records": [
            serialize_property(record)
            for record in records
        ]
    }


# =========================================================
# EXPORT RECORDS TO EXCEL
#
# IMPORTANT:
#
# limit and offset are intentionally NOT used here.
#
# If the screen is showing 50 records but the current
# filter contains 8,000 records, Excel exports all
# 8,000 matching records.
#
# =========================================================

@router.get("/export")
def export_records(

    search: str | None = None,

    year: int | None = None,

    status: str | None = None,

    rating_area: str | None = None,

    lg_id: int | None = None,

    lg_prefix: str | None = None,

    sort_by: str = Query(
        default="id"
    ),

    sort_order: str = Query(
        default="asc"
    ),

    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # Validate sorting
    # -----------------------------------------------------

    if sort_by not in SORT_FIELDS:

        raise HTTPException(
            status_code=400,
            detail="Invalid sort field"
        )

    sort_order = sort_order.lower()

    if sort_order not in (
        "asc",
        "desc"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "sort_order must be "
                "'asc' or 'desc'"
            )
        )

    # -----------------------------------------------------
    # Build SAME filtered query used by display
    # -----------------------------------------------------

    query = build_records_query(
        db=db,
        search=search,
        year=year,
        status=status,
        rating_area=rating_area,
        lg_id=lg_id,
        lg_prefix=lg_prefix
    )

    # -----------------------------------------------------
    # Sorting
    # -----------------------------------------------------

    sort_column = SORT_FIELDS[
        sort_by
    ]

    if sort_order == "desc":

        query = query.order_by(
            desc(sort_column)
        )

    else:

        query = query.order_by(
            asc(sort_column)
        )

    # -----------------------------------------------------
    # Create Excel workbook
    #
    # write_only=True reduces memory use for larger exports.
    # -----------------------------------------------------

    workbook = Workbook(
        write_only=True
    )

    worksheet = workbook.create_sheet(
        title="Property Records"
    )

    # -----------------------------------------------------
    # Excel headings
    # -----------------------------------------------------

    headings = [
        "ID",
        "PROPERTY NO",
        "OWNER NAME",
        "ADDRESS",
        "RATING AREA",
        "ANNUAL VALUE",
        "RATE DUE",
        "YEAR",
        "STATUS",
        "LG CODE",
        "LG ID",
        "LG PREFIX",
        "CREATED AT",
        "UPDATED AT"
    ]

    worksheet.append(
        headings
    )

    # -----------------------------------------------------
    # Stream database records in batches
    #
    # yield_per prevents SQLAlchemy from unnecessarily
    # materializing a very large result set at once.
    # -----------------------------------------------------

    records = query.all()

for record in records:

    worksheet.append(
            [
                record.id,
                record.property_no,
                record.owner_name,
                record.address,
                record.rating_area,

                (
                    float(record.annual_value)
                    if record.annual_value is not None
                    else 0
                ),

                (
                    float(record.rate_due)
                    if record.rate_due is not None
                    else 0
                ),

                record.year,
                record.status,
                record.lg_code,
                record.lg_id,
                record.lg_prefix,

                (
                    record.created_at.replace(
                        tzinfo=None
                    )
                    if record.created_at
                    else None
                ),

                (
                    record.updated_at.replace(
                        tzinfo=None
                    )
                    if record.updated_at
                    else None
                )
            ]
        )

    # -----------------------------------------------------
    # Save workbook to memory
    # -----------------------------------------------------

    output = BytesIO()

    workbook.save(
        output
    )

    output.seek(0)

    # -----------------------------------------------------
    # Filename
    # -----------------------------------------------------

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    filename = (
        f"tenement_records_"
        f"{timestamp}.xlsx"
    )

    # -----------------------------------------------------
    # Return Excel download
    # -----------------------------------------------------

    headers = {
        "Content-Disposition":
            f'attachment; filename="{filename}"'
    }

    return StreamingResponse(
        output,
        media_type=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        headers=headers
    )
