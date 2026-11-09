
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from fastapi.encoders import jsonable_encoder
from decimal import Decimal
import math

from app.database import get_db
from app.models import Property


router = APIRouter(
    prefix="/data",
    tags=["Data"]
)


# =====================================================
# EXISTING ENDPOINT 1: GET DATA FIELDS
# =====================================================

@router.get("/fields")
def get_data_fields():

    fields = [
        column.name
        for column in Property.__table__.columns
    ]

    return {
        "fields": fields
    }


# =====================================================
# EXISTING ENDPOINT 2: GET DATA RECORDS
# UNCHANGED
# =====================================================

@router.get("/records")
def get_data_records(
    db: Session = Depends(get_db)
):

    properties = db.query(Property).all()

    records = []

    for property in properties:

        record = {}

        for column in Property.__table__.columns:

            value = getattr(property, column.name)

            # Handle floating-point NaN / Infinity
            if isinstance(value, float):
                if not math.isfinite(value):
                    value = None

            # Handle Decimal NaN / Infinity
            elif isinstance(value, Decimal):
                if not value.is_finite():
                    value = None

            record[column.name] = value

        records.append(record)

    return jsonable_encoder({
        "records": records
    })


# =====================================================
# NEW ENDPOINT: SERVER-SIDE TENEMENT DASHBOARD
# =====================================================

@router.get("/dashboard-summary")
def get_dashboard_summary(
    year: int | None = None,
    db: Session = Depends(get_db)
):

    # Get all available assessment years
    years = (
        db.query(Property.year)
        .filter(Property.year.isnot(None))
        .distinct()
        .order_by(Property.year.desc())
        .all()
    )

    available_years = [
        row[0] for row in years
    ]

    # PAID is paid; every other status is unpaid
    normalized_status = func.upper(
        func.trim(
            func.coalesce(Property.status, "")
        )
    )

    paid_condition = (
        normalized_status == "PAID"
    )

    paid_count_expression = case(
        (paid_condition, 1),
        else_=0
    )

    outstanding_expression = case(
        (
            ~paid_condition,
            func.coalesce(Property.rate_due, 0)
        ),
        else_=0
    )

    # Perform calculations inside PostgreSQL
    query = db.query(
        func.count(Property.id),
        func.coalesce(
            func.sum(paid_count_expression), 0
        ),
        func.coalesce(
            func.sum(Property.rate_due), 0
        ),
        func.coalesce(
            func.sum(outstanding_expression), 0
        )
    )

    # Apply selected assessment year
    if year is not None:
        query = query.filter(
            Property.year == year
        )

    result = query.one()

    total = int(result[0] or 0)
    paid = int(result[1] or 0)
    total_rate_due = float(result[2] or 0)
    outstanding_rate = float(result[3] or 0)

    unpaid = total - paid

    collection_rate = (
        (paid / total) * 100
        if total else 0
    )

    paid_percentage = collection_rate

    unpaid_percentage = (
        (unpaid / total) * 100
        if total else 0
    )

    return {
        "selected_year": year,
        "years": available_years,
        "total_properties": total,
        "paid_properties": paid,
        "unpaid_properties": unpaid,
        "total_rate_due": total_rate_due,
        "outstanding_rate": outstanding_rate,
        "collection_rate": collection_rate,
        "paid_percentage": paid_percentage,
        "unpaid_percentage": unpaid_percentage
    }
