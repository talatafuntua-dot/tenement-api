
# -*- coding: utf-8 -*-
"""
formatter.py

Central field-binding and formatting engine for Tenement Rate.

Responsibilities:
1. Normalize incoming field names.
2. Recognize aliases from Excel, database records and other sources.
3. Resolve equivalent names to standard internal fields.
4. Preserve original fields for Word-template compatibility.
5. Format currency and numeric values consistently.
6. Keep individual and bulk generation on the same binding rules.
"""

import re

from app.config import CURRENCY_FIELDS, CURRENCY_SYMBOL


# =========================================================
# STANDARD FIELD REGISTRY
# =========================================================
#
# Each dictionary key is a canonical internal field.
# Its aliases are alternative headings that may appear in
# Excel files, database records or other incoming sources.
#
# Add new aliases here instead of scattering special cases
# throughout the application.
#
# Existing renderer compatibility is preserved by using
# OWNER_NAME, ADDRESS and PROPERTY_NO as canonical fields.
# =========================================================

FIELD_REGISTRY = {
    "OWNER_NAME": [
        "OWNER NAME",
        "NAME OF OWNER",
        "NAME OF OCCUPIER",
        "OCCUPIER NAME",
        "OCCUPIER",
        "PROPERTY OWNER",
        "OWNER",
        "TENANT NAME",
    ],
    "ADDRESS": [
        "PROPERTY ADDRESS",
        "PROPERTY LOCATION",
        "LOCATION ADDRESS",
        "ADDRESS OF PROPERTY",
        "PROPERTY LOCATION ADDRESS",
        "LOCATION",
    ],
    "PROPERTY_NO": [
        "PROPERTY NO",
        "PROPERTY NUMBER",
        "ASSESSMENT NO",
        "ASSESSMENT NUMBER",
        "ASSESSMENT NO.",
        "ASSESSMENT NUMBER.",
        "PROPERTY IDENTIFICATION NUMBER",
    ],
    "LG_CODE": [
        "LOCAL GOVERNMENT CODE",
        "LOCAL GOVERNMENT AREA CODE",
        "LOCAL GOVERNMENT",
        "LGA CODE",
    ],
    "RATING_AREA": [
        "RATING AREA NAME",
        "RATING DISTRICT",
        "RATING ZONE",
    ],
    "ANNUAL_VALUE": [
        "ANNUAL VALUE",
        "ANNUAL RENTAL VALUE",
        "RATEABLE VALUE",
        "RATEABLE ANNUAL VALUE",
        "ASSESSED VALUE",
    ],
    "RATE_DUE": [
        "TENEMENT RATE",
        "TENEMENT RATE DUE",
        "ANNUAL RATE",
        "ANNUAL RATE DUE",
        "CURRENT RATE",
        "CURRENT RATE DUE",
        "RATE AMOUNT",
    ],
    "YEAR": [
        "ASSESSMENT YEAR",
        "BILL YEAR",
        "RATE YEAR",
        "TAX YEAR",
    ],
    "USE_OF_PROPERTY": [
        "PROPERTY USE",
        "PROPERTY TYPE",
        "TYPE OF PROPERTY",
        "USE",
    ],
    "STATUS": [
        "PAYMENT STATUS",
        "BILL STATUS",
    ],
}


# =========================================================
# NORMALIZE FIELD NAMES
# =========================================================

def clean_key(key):
    """
    Normalize field names consistently.

    Examples:
        'NAME OF OCCUPIER'  -> 'NAME_OF_OCCUPIER'
        'PROPERTY ADDRESS'  -> 'PROPERTY_ADDRESS'
        'Assessment No.'    -> 'ASSESSMENT_NO'
        'owner_name'        -> 'OWNER_NAME'
        ' Rate   Due '      -> 'RATE_DUE'
    """

    text = str(key or "").strip().upper()

    # Replace any run of non-alphanumeric characters with
    # one underscore. This handles spaces, punctuation,
    # hyphens and repeated separators consistently.
    text = re.sub(r"[^A-Z0-9]+", "_", text)

    return text.strip("_")


# =========================================================
# BUILD ALIAS LOOKUP
# =========================================================

def _build_alias_lookup():
    """
    Build the reverse lookup from alias -> canonical field.
    """

    lookup = {}

    for canonical, aliases in FIELD_REGISTRY.items():
        canonical_key = clean_key(canonical)
        lookup[canonical_key] = canonical_key

        for alias in aliases:
            lookup[clean_key(alias)] = canonical_key

    return lookup


FIELD_ALIASES = _build_alias_lookup()


# =========================================================
# EMPTY VALUE CHECK
# =========================================================

def _is_empty(value):
    """
    Identify missing values without treating valid zero
    values as missing.
    """

    if value is None:
        return True

    try:
        # Handles pandas NaN, NaT and similar missing values.
        if value != value:
            return True
    except Exception:
        pass

    if isinstance(value, str):
        return value.strip().lower() in {
            "",
            "nan",
            "none",
            "null",
            "nat",
        }

    return False


# =========================================================
# SAFE NUMBER
# =========================================================

def safe_number(value):
    """
    Convert a numeric value to float safely.

    Returns None when the value is empty or non-numeric.
    """

    if _is_empty(value):
        return None

    try:
        if isinstance(value, str):
            value = (
                value
                .replace(",", "")
                .replace(CURRENCY_SYMBOL, "")
                .strip()
            )

        if _is_empty(value):
            return None

        return float(value)

    except (TypeError, ValueError, OverflowError):
        return None


# =========================================================
# FORMAT NUMBER
# =========================================================

def format_number(value, decimals=2):
    """
    Format ordinary numeric values.

    Examples:
        1000     -> 1,000
        1234.5   -> 1,234.50
    """

    number = safe_number(value)

    if number is None:
        return ""

    if number.is_integer():
        return f"{int(number):,}"

    return f"{number:,.{decimals}f}"


# =========================================================
# FORMAT CURRENCY
# =========================================================

def format_currency(value, decimals=2):
    """
    Format currency values consistently.
    """

    number = safe_number(value)

    if number is None:
        return ""

    return (
        f"{CURRENCY_SYMBOL}"
        f"{number:,.{decimals}f}"
    )


# =========================================================
# FORMAT VALUE
# =========================================================

def format_value(key, value):
    """
    Format a value using the application's currency rules.
    """

    normalized_key = clean_key(key)

    # Check both the incoming key and its canonical name.
    canonical_key = FIELD_ALIASES.get(
        normalized_key,
        normalized_key,
    )

    currency_fields = {
        clean_key(field)
        for field in CURRENCY_FIELDS
    }

    canonical_currency_fields = {
        FIELD_ALIASES.get(field, field)
        for field in currency_fields
    }

    if (
        normalized_key in currency_fields
        or canonical_key in canonical_currency_fields
    ):
        return format_currency(value)

    number = safe_number(value)

    if number is not None:
        return format_number(value)

    if _is_empty(value):
        return ""

    return str(value).strip()


# =========================================================
# RESOLVE FIELD ALIASES
# =========================================================

def resolve_fields(data):
    """
    Add canonical fields from recognized aliases.

    Original normalized fields are retained, so existing
    Word templates can continue using their placeholders.

    A non-empty canonical value takes precedence. If it is
    missing or empty, the first non-empty alias is used.

    Unknown fields are preserved and are not discarded.
    """

    resolved = dict(data)

    for canonical, aliases in FIELD_REGISTRY.items():
        canonical_key = clean_key(canonical)

        # Keep a useful canonical value if already supplied.
        if (
            canonical_key in resolved
            and not _is_empty(resolved[canonical_key])
        ):
            continue

        candidates = [
            canonical_key,
            *[clean_key(alias) for alias in aliases],
        ]

        for candidate in candidates:
            if candidate not in resolved:
                continue

            value = resolved[candidate]

            if not _is_empty(value):
                resolved[canonical_key] = value
                break

        # Ensure recognized canonical fields exist even when
        # their source column was absent.
        resolved.setdefault(canonical_key, "")

    return resolved


# =========================================================
# PREPARE ROW
# =========================================================

def prepare_row(record):
    """
    Convert supported input records into a consistently
    formatted dictionary ready for Word-template rendering.

    Supported:
        1. Python dictionaries
        2. Pandas Series / rows
        3. SQLAlchemy model instances
        4. SimpleNamespace
        5. Other objects exposing normal instance fields

    Both individual and bulk PDF generation should use this
    same function through generate_notice_pdf().
    """

    data = {}

    # -----------------------------------------------------
    # Extract input fields
    # -----------------------------------------------------

    if isinstance(record, dict):
        items = record.items()

    elif hasattr(record, "to_dict"):
        items = record.to_dict().items()

    else:
        items = vars(record).items()

    # -----------------------------------------------------
    # Normalize and format incoming fields
    # -----------------------------------------------------

    for column, value in items:
        if str(column).startswith("_"):
            continue

        key = clean_key(column)

        if not key:
            continue

        data[key] = format_value(key, value)

    # -----------------------------------------------------
    # Resolve aliases into canonical internal fields
    # -----------------------------------------------------

    data = resolve_fields(data)

    return data
