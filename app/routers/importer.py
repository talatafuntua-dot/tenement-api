import re
import secrets
import string
from decimal import Decimal
from io import BytesIO

import pandas as pd

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException
)

from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Property, LocalGovernment


router = APIRouter(
    prefix="/import",
    tags=["Excel Import"]
)


# =========================================================
# NORMALIZE EXCEL COLUMN HEADINGS
# =========================================================

def normalize_heading(value):
    if value is None:
        return ""

    value = str(value).strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "_",
        value
    )

    return value.strip("_")


# =========================================================
# ACCEPTED COLUMN NAMES
# =========================================================

COLUMN_ALIASES = {

    "property_no": {
        "property_no",
        "property_number",
        "property_num",
        "property",
        "property_id",
        "property_code",
        "lg_code"
    },

    "owner_name": {
        "owner_name",
        "owner",
        "owner_name_",
        "property_owner",
        "name_of_owner",
        "ratepayer",
        "rate_payer"
    },

    "address": {
        "address",
        "property_address",
        "property_location",
        "location",
        "property_location_address"
    },

    "annual_value": {
        "annual_value",
        "annualvalue",
        "annual_value_",
        "rateable_value",
        "assessment_value",
        "assessed_value",
        "value"
    },

    "rate_due": {
        "rate_due",
        "ratedue",
        "rate",
        "rate_amount",
        "amount_due",
        "tenement_rate",
        "tenement_rate_due"
    },

    "year": {
        "year",
        "rating_year",
        "rate_year",
        "assessment_year"
    },

    "rating_area": {
        "rating_area",
        "ratingarea",
        "area",
        "rating_zone",
        "zone"
    },

    "status": {
        "status",
        "payment_status",
        "property_status"
    }
}


# =========================================================
# FIND DATABASE FIELD FROM EXCEL HEADING
# =========================================================

def map_columns(dataframe):

    normalized = {}

    for column in dataframe.columns:

        normalized_name = normalize_heading(column)

        if normalized_name:
            normalized[normalized_name] = column

    mapped = {}

    for database_field, aliases in COLUMN_ALIASES.items():

        for normalized_name, original_name in normalized.items():

            if normalized_name in aliases:

                mapped[database_field] = original_name
                break

    return mapped


# =========================================================
# CLEAN NUMERIC VALUES
# =========================================================

def clean_number(value):

    if pd.isna(value):
        return Decimal("0")

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):

        if pd.isna(value):
            return Decimal("0")

        return Decimal(
            str(value)
        )

    value = str(value).strip()

    if not value:
        return Decimal("0")

    value = value.replace(",", "")
    value = value.replace("₦", "")
    value = value.strip()

    try:

        return Decimal(value)

    except Exception:

        raise ValueError(
            f"Invalid numeric value: {value}"
        )


# =========================================================
# GENERATE UNIQUE LG CODE
# =========================================================

def generate_lg_code(
    db,
    prefix
):

    alphabet = (
        string.ascii_uppercase +
        string.digits
    )

    prefix = prefix.upper().strip()

    for _ in range(20):

        random_part = "".join(
            secrets.choice(alphabet)
            for _ in range(8)
        )

        lg_code = (
            f"{prefix}-{random_part}"
        )

        exists = (
            db.query(Property)
            .filter(
                Property.lg_code == lg_code
            )
            .first()
        )

        if not exists:

            return lg_code

    raise HTTPException(
        status_code=500,
        detail="Unable to generate a unique LG Code."
    )


# =========================================================
# EXCEL IMPORT
# =========================================================

@router.post("/excel")
async def import_excel(
    file: UploadFile = File(...),

    local_government: str = Form(...),

    prefix: str = Form(...),

    code: str = Form(""),

    db: Session = Depends(get_db)
):

    # -----------------------------------------------------
    # VALIDATE FILE
    # -----------------------------------------------------

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="No Excel file selected."
        )

    filename = file.filename.lower()

    if not (
        filename.endswith(".xlsx")
        or filename.endswith(".xls")
    ):

        raise HTTPException(
            status_code=400,
            detail="Only Excel files (.xlsx or .xls) are allowed."
        )


    # -----------------------------------------------------
    # VALIDATE LG NAME
    # -----------------------------------------------------

    local_government = (
        local_government.strip()
    )

    if not local_government:

        raise HTTPException(
            status_code=400,
            detail="Local Government name is required."
        )


    # -----------------------------------------------------
    # VALIDATE PREFIX
    # -----------------------------------------------------

    prefix = prefix.strip().upper()

    if not prefix:

        raise HTTPException(
            status_code=400,
            detail="LG prefix is required."
        )

    if not re.fullmatch(
        r"[A-Z0-9]{2,10}",
        prefix
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "LG prefix must contain only "
                "letters/numbers and be 2-10 characters."
            )
        )


    # -----------------------------------------------------
    # READ EXCEL
    # -----------------------------------------------------

    try:

        contents = await file.read()

        dataframe = pd.read_excel(
            BytesIO(contents)
        )

    except Exception as error:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Unable to read Excel file: {error}"
            )
        )


    # -----------------------------------------------------
    # CHECK EMPTY FILE
    # -----------------------------------------------------

    if dataframe.empty:

        raise HTTPException(
            status_code=400,
            detail="The Excel file contains no records."
        )


    # -----------------------------------------------------
    # MAP COLUMNS
    # -----------------------------------------------------

    mapped = map_columns(
        dataframe
    )


    required_fields = [
        "property_no",
        "owner_name",
        "address",
        "annual_value",
        "rate_due",
        "year"
    ]


    missing_fields = [
        field
        for field in required_fields
        if field not in mapped
    ]


    if missing_fields:

        raise HTTPException(
            status_code=400,
            detail={
                "message": "Required Excel columns are missing.",
                "missing_fields": missing_fields,
                "detected_columns": [
                    str(column)
                    for column in dataframe.columns
                ]
            }
        )


    # -----------------------------------------------------
    # FIND OR CREATE LOCAL GOVERNMENT
    # -----------------------------------------------------

    lg = (
        db.query(LocalGovernment)
        .filter(
            LocalGovernment.name ==
            local_government
        )
        .first()
    )


    if lg:

        # Update prefix if the supplied
        # prefix is different.

        lg.prefix = prefix

        if code.strip():

            lg.code = code.strip()

    else:

        lg = LocalGovernment(

            name=local_government,

            code=(
                code.strip()
                if code
                else None
            ),

            prefix=prefix
        )

        db.add(lg)

        db.flush()


    # -----------------------------------------------------
    # IMPORT RECORDS
    # -----------------------------------------------------

    imported = 0
    skipped = 0
    errors = []

    for row_number, row in dataframe.iterrows():

        excel_row = row_number + 2

        try:

            property_no = str(
                row[mapped["property_no"]]
            ).strip()

            owner_name = str(
                row[mapped["owner_name"]]
            ).strip()

            address = str(
                row[mapped["address"]]
            ).strip()


            if not property_no:

                skipped += 1

                continue


            if not owner_name:

                raise ValueError(
                    "Owner name is empty."
                )


            if not address:

                raise ValueError(
                    "Address is empty."
                )


            annual_value = clean_number(
                row[mapped["annual_value"]]
            )

            rate_due = clean_number(
                row[mapped["rate_due"]]
            )


            year_value = row[
                mapped["year"]
            ]


            if pd.isna(year_value):

                raise ValueError(
                    "Year is empty."
                )


            year = int(
                float(year_value)
            )


            # -------------------------------------------------
            # EXISTING PROPERTY
            # -------------------------------------------------

            property_record = (
                db.query(Property)
                .filter(
                    Property.property_no ==
                    property_no
                )
                .first()
            )


            if property_record:

                property_record.owner_name = (
                    owner_name
                )

                property_record.address = (
                    address
                )

                property_record.annual_value = (
                    annual_value
                )

                property_record.rate_due = (
                    rate_due
                )

                property_record.year = (
                    year
                )

            else:

                property_record = Property(

                    property_no=property_no,

                    owner_name=owner_name,

                    address=address,

                    annual_value=annual_value,

                    rate_due=rate_due,

                    year=year,

                    status="UNPAID"
                )

                db.add(
                    property_record
                )

                db.flush()


            # -------------------------------------------------
            # LG INFORMATION
            # -------------------------------------------------

            property_record.lg_id = lg.id

            property_record.lg_prefix = (
                prefix
            )


            # -------------------------------------------------
            # RATING AREA
            # -------------------------------------------------

            if "rating_area" in mapped:

                rating_area = row[
                    mapped["rating_area"]
                ]

                if not pd.isna(rating_area):

                    property_record.rating_area = (
                        str(rating_area).strip()
                    )


            # -------------------------------------------------
            # STATUS
            # -------------------------------------------------

            if "status" in mapped:

                status = row[
                    mapped["status"]
                ]

                if not pd.isna(status):

                    property_record.status = (
                        str(status).strip().upper()
                    )


            # -------------------------------------------------
            # LG CODE
            #
            # Preserve existing code.
            # Generate only when missing.
            # -------------------------------------------------

            if not property_record.lg_code:

                property_record.lg_code = (
                    generate_lg_code(
                        db,
                        prefix
                    )
                )


            imported += 1


        except Exception as error:

            errors.append({

                "excel_row": excel_row,

                "property_no": (
                    str(
                        row.get(
                            mapped.get(
                                "property_no",
                                ""
                            ),
                            ""
                        )
                    )
                ),

                "error": str(error)
            })


    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    try:

        db.commit()

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Database import failed: {error}"
            )
        )


    # -----------------------------------------------------
    # RESPONSE
    # -----------------------------------------------------

    return {

        "message":
            "Excel import completed.",

        "local_government": {

            "id": lg.id,

            "name": lg.name,

            "code": lg.code,

            "prefix": lg.prefix
        },

        "file":
            file.filename,

        "total_rows":
            len(dataframe),

        "imported":
            imported,

        "skipped":
            skipped,

        "errors":
            errors
    }
