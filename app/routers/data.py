from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder
from decimal import Decimal
import math

from app.database import get_db
from app.models import Property


router = APIRouter(
    prefix="/data",
    tags=["Data"]
)


@router.get("/fields")
def get_data_fields():

    fields = [
        column.name
        for column in Property.__table__.columns
    ]

    return {
        "fields": fields
    }


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
