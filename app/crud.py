from sqlalchemy.orm import Session
from app.models import Property


def get_all_properties(
    db: Session,
    skip: int = 0,
    limit: int = 100
):
    return (
        db.query(Property)
        .offset(skip)
        .limit(limit)
        .all()
    )


# =====================================================
# GET PROPERTY BY NUMBER
# CASE-INSENSITIVE
# =====================================================

def get_property_by_number(
    db: Session,
    property_no: str
):
    return (
        db.query(Property)
        .filter(
            Property.property_no.ilike(
                property_no.strip()
            )
        )
        .first()
    )


# =====================================================
# SEARCH BY OWNER
# CASE-INSENSITIVE
# =====================================================

def search_owner(
    db: Session,
    owner_name: str
):
    return (
        db.query(Property)
        .filter(
            Property.owner_name.ilike(
                f"%{owner_name}%"
            )
        )
        .all()
    )
