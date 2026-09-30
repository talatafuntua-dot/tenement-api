# -*- coding: utf-8 -*-
"""
formatter.py
Handles all number and currency formatting.
"""

from app.config import CURRENCY_FIELDS, CURRENCY_SYMBOL


# =========================================================
# CLEAN KEY
# =========================================================

def clean_key(key):
    """
    Convert Excel/database column names into standard
    placeholder keys.

    Examples:

        Rate 1
        -> RATE_1

        rate_1
        -> RATE_1

        Owner Name
        -> OWNER_NAME
    """

    return (
        str(key)
        .strip()
        .replace(" ", "_")
        .upper()
    )


# =========================================================
# SAFE NUMBER
# =========================================================

def safe_number(value):
    """
    Safely convert values to float.

    Returns None if conversion fails.
    """

    if value is None:
        return None

    try:

        if isinstance(value, str):

            value = (
                value
                .replace(",", "")
                .replace(CURRENCY_SYMBOL, "")
                .strip()
            )

        if value == "":
            return None

        text = str(value).strip().lower()

        if text in (
            "nan",
            "none",
            "null",
            "nat",
        ):
            return None

        return float(value)

    except Exception:

        return None


# =========================================================
# FORMAT NUMBER
# =========================================================

def format_number(value, decimals=2):
    """
    Format ordinary numbers.

    Examples:

        1000
        -> 1,000

        1234.5
        -> 1,234.50
    """

    num = safe_number(value)

    if num is None:
        return ""

    if num.is_integer():
        return f"{int(num):,}"

    return f"{num:,.{decimals}f}"


# =========================================================
# FORMAT CURRENCY
# =========================================================

def format_currency(value, decimals=2):
    """
    Format currency.

    Example:

        2500
        -> ₦2,500.00
    """

    num = safe_number(value)

    if num is None:
        num = 0

    return (
        f"{CURRENCY_SYMBOL}"
        f"{num:,.{decimals}f}"
    )


# =========================================================
# FORMAT VALUE
# =========================================================

def format_value(key, value):
    """
    Automatically determine how a field should be formatted.
    """

    key = clean_key(key)

    if key in CURRENCY_FIELDS:

        return format_currency(
            value
        )

    if safe_number(value) is not None:

        return format_number(
            value
        )

    return (
        ""
        if value is None
        else str(value)
    )


# =========================================================
# PREPARE ROW
# =========================================================

def prepare_row(record):
    """
    Convert any supported record into a dictionary ready
    for the DOCX template.

    Supported:

        1. Python dictionary
        2. Pandas Series / row
        3. SQLAlchemy model
        4. SimpleNamespace
        5. Other normal Python objects
    """

    data = {}

    # =====================================================
    # DICTIONARY
    # =====================================================

    if isinstance(record, dict):

        items = record.items()

    # =====================================================
    # PANDAS ROW / SERIES
    # =====================================================

    elif hasattr(record, "to_dict"):

        items = record.to_dict().items()

    # =====================================================
    # NORMAL OBJECT / SQLALCHEMY
    # =====================================================

    else:

        items = vars(record).items()

    # =====================================================
    # FORMAT EACH FIELD
    # =====================================================

    for column, value in items:

        if str(column).startswith("_"):
            continue

        key = clean_key(
            column
        )

        data[key] = format_value(
            key,
            value
        )

    return data

