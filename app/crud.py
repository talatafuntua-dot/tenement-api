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
# Checks the ACTUAL database.
#
# If lg_code does not exist:
#     Property Number and Owner Name still work.
#
# If lg_code is added later:
#     It is automatically detected.
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
# PARTIAL MATCH
# =====================================================

def search_owner(
    db: Session,
    owner_name: str
):

    owner_name = owner_name.strip()

    if not owner_name:
        return []

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
#    - If column exists in database
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
# LG CODE IS OPTIONAL.
# Its absence MUST NOT affect other searches.
# =====================================================

def search_properties(
    db: Session,
    query: str
):

    query = query.strip()

    if not query:
        return []


    # =================================================
    # ALWAYS SEARCH OWNER NAME + PROPERTY NUMBER
    # =================================================

    results = (
        db.query(Property)
        .filter(
            (
                Property.owner_name.ilike(
                    f"%{query}%"
                )
            )
            |
            (
                Property.property_no.ilike(
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

        lg_result = db.execute(
            text("""
                SELECT *
                FROM properties
                WHERE LOWER(lg_code) = LOWER(:lg_code)
                LIMIT 1
            """),
            {
                "lg_code": query
            }
        ).mappings().first()


        if lg_result:

            existing_ids = {
                item.id
                for item in results
            }


            # -----------------------------------------
            # Add LG Code result if not already found
            # -----------------------------------------

            if lg_result["id"] not in existing_ids:

                # Find the SQLAlchemy Property object
                # using the database ID.
                property_by_id = (
                    db.query(Property)
                    .filter(
                        Property.id == lg_result["id"]
                    )
                    .first()
                )


                if property_by_id:

                    results.append(
                        property_by_id
                    )


    return results
