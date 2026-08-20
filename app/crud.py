from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

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
# CHECK WHETHER LG CODE COLUMN EXISTS
# =====================================================

def has_lg_code_column(db: Session):
    inspector = inspect(db.bind)

    columns = inspector.get_columns(
        Property.__tablename__
    )

    return any(
        column["name"].lower() == "lg_code"
        for column in columns
    )


# =====================================================
# GET PROPERTY BY LG CODE
# FLEXIBLE DATABASE LOOKUP
# =====================================================

def get_property_by_lg_code(
    db: Session,
    lg_code: str
):

    # LG Code column does not exist yet.
    # Do not break the existing application.
    if not has_lg_code_column(db):
        return None

    return db.execute(
        text("""
            SELECT *
            FROM properties
            WHERE LOWER(lg_code) = LOWER(:lg_code)
            LIMIT 1
        """),
        {
            "lg_code": lg_code.strip()
        }
    ).mappings().first()


# =====================================================
# GET PROPERTY BY NUMBER
# CASE-INSENSITIVE
# ALWAYS AVAILABLE
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
# ALWAYS AVAILABLE
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
