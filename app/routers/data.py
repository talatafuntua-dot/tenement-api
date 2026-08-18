from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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

            if value is not None:
                record[column.name] = value
            else:
                record[column.name] = None

        records.append(record)

    return {
        "records": records
    }
