# -*- coding: utf-8 -*-
"""
formatter.py
Handles all number and currency formatting.
"""
from app.config import CURRENCY_FIELDS, CURRENCY_SYMBOL


def clean_key(key):
    """
    Convert Excel column names into standard placeholder keys.

    Example:
        Rate 1  -> RATE_1
        rate_1  -> RATE_1
    """
    return str(key).strip().replace(" ", "_").upper()


def safe_number(value):
    """
    Safely convert values to float.

    Returns None if conversion fails.
    """

    if value is None:
        return None

    try:

        if isinstance(value, str):
            value = value.replace(",", "").replace(CURRENCY_SYMBOL, "").strip()

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


def format_number(value, decimals=2):
    """
    Format ordinary numbers.

    Examples

        1000
        ->

        1,000

        1234.5
        ->

        1,234.50
    """

    num = safe_number(value)

    if num is None:
        return ""

    if num.is_integer():
        return f"{int(num):,}"

    return f"{num:,.{decimals}f}"


def format_currency(value, decimals=2):
    """
    Format currency.

    Example

        2500

        becomes

        ₦2,500.00
    """

    num = safe_number(value)

    if num is None:
        num = 0

    return f"{CURRENCY_SYMBOL}{num:,.{decimals}f}"


def format_value(key, value):
    """
    Automatically determine how a field should be formatted.
    """

    key = clean_key(key)

    if key in CURRENCY_FIELDS:
        return format_currency(value)

    return format_number(value) if safe_number(value) is not None else (
        "" if value is None else str(value)
    )


def prepare_row(record):
    """
    Convert either a Pandas row or a SQLAlchemy object
    into a dictionary ready for the template.
    """

    data = {}

    # Pandas row
    if hasattr(record, "to_dict"):
        items = record.to_dict().items()

    # SQLAlchemy model
    else:
        items = vars(record).items()

    for column, value in items:

        if column.startswith("_"):
            continue

        key = clean_key(column)

        data[key] = format_value(key, value)

    return data