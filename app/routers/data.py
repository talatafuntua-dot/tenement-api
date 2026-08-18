
from fastapi import APIRouter
from app.models import Property

router = APIRouter(
    prefix="/data",
    tags=["Data"]
)


@router.get("/fields")
def get_data_fields():
    """
    Return all available Property fields.
    """

    fields = [
        column.name
        for column in Property.__table__.columns
    ]

    return {
        "fields": fields
    }
