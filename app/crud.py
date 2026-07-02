from sqlalchemy.orm import Session
from app.models import Property


def get_all_properties(db: Session, skip: int = 0, limit: int = 100):
    return (
        db.query(Property)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_property_by_number(db: Session, property_no: str):
    return (
        db.query(Property)
        .filter(Property.property_no == property_no)
        .first()
    )
def get_property_by_number(db: Session, property_no: str):
    return (
        db.query(Property)
        .filter(Property.property_no == property_no)
        .first()
    )

def search_owner(db: Session, owner_name: str):
    return (
        db.query(Property)
        .filter(Property.owner_name.ilike(f"%{owner_name}%"))
        .all()
    )