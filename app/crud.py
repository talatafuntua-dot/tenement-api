from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from app.models import Property


# =====================================================
# GET ALL PROPERTIES
# =====================================================

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
# CHECK IF LG CODE COLUMN EXISTS
#
# This checks the ACTUAL database table.
#
# If lg_code does not exist:
#     Nothing breaks.
#
# If lg_code is added later:
#     The API automatically detects it.
# =====================================================

def has_lg_code_column(
    db: Session
):

    inspector = inspect(db.bind)

    columns = inspector.get_columns(
        Property.__tablename__
    )

    return any(
        column["name"].lower() == "lg_code"
        for column in columns
    )


# =====================================================
# GET PROPERTY BY NUMBER
#
# CASE-INSENSITIVE
#
# This remains available regardless of LG Code.
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
#
# CASE-INSENSITIVE
#
# This remains available regardless of LG Code.
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


# =====================================================
# UNIVERSAL PROPERTY SEARCH
#
# Searches:
#
# 1. LG CODE
#    - Only if the database column exists
#    - Exact match
#    - Case-insensitive
#
# 2. OWNER NAME
#    - Partial match
#    - Case-insensitive
#
# 3. PROPERTY NUMBER
#    - Partial match
#    - Case-insensitive
#
# This makes the API flexible.
# =====================================================

def search_properties(
    db: Session,
    query: str
):

    query = query.strip()

    if not query:
        return []


    # =================================================
    # ALWAYS SEARCH EXISTING COLUMNS
    # =================================================

    results = (
        db.query(Property)
        .filter(
            (
                Property.property_no.ilike(
                    f"%{query}%"
                )
            )
            |
            (
                Property.owner_name.ilike(
                    f"%{query}%"
                )
            )
        )
        .all()
    )


    # =================================================
    # SEARCH LG CODE ONLY IF COLUMN EXISTS
    # =================================================

    if has_lg_code_column(db):

        lg_results = db.execute(
            text("""
                SELECT *
                FROM properties
                WHERE LOWER(lg_code) = LOWER(:lg_code)
                LIMIT 1
            """),
            {
                "lg_code": query
            }
        ).mappings().all()


        # ---------------------------------------------
        # Avoid duplicate records
        # ---------------------------------------------

        existing_ids = {
            property.id
            for property in results
        }


        for row in lg_results:

            if row["id"] not in existing_ids:

                results.append(
                    dict(row)
                )


    return results
