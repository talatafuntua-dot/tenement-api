```python
# -*- coding: utf-8 -*-

import os
import re
from pathlib import Path
from types import SimpleNamespace

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


# ============================================================
# DIRECTORIES
# ============================================================

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent

TEMPLATES_FOLDER = BASE_DIR / "templates"
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


# ============================================================
# GENERAL HELPERS
# ============================================================

def get_record_value(record, key, default=""):
    """
    Get a value from either:
        - dictionary
        - object / SimpleNamespace
    Supports case-insensitive dictionary keys.
    """

    if record is None:
        return default

    if isinstance(record, dict):
        if key in record:
            return record[key]

        key_upper = str(key).upper()

        for existing_key, value in record.items():
            if str(existing_key).upper() == key_upper:
                return value

        return default

    return getattr(record, key, default)


def normalize_column_name(name):
    """
    Convert Excel column headings into safe uppercase keys.

    Example:
        LG Code       -> LG_CODE
        Owner Name    -> OWNER_NAME
        Property No   -> PROPERTY_NO
    """

    text = str(name).strip()

    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text)

    return text.strip("_").upper()


def make_safe_filename(value, fallback="notice"):
    """
    Convert a value into a safe filename.
    """

    if value is None:
        value = ""

    value = str(value).strip()

    if not value:
        value = fallback

    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    value = re.sub(r"\s+", "_", value)

    return value[:180]


# ============================================================
# PROPERTY DATA PREPARATION
# ============================================================

def prepare_property_data(property_record):
    """
    Convert a property/database/Excel record into the
    fields expected by the Word template.
    """

    data = prepare_row(property_record)

    data["NAME_OF_OCCUPIER"] = get_record_value(
        data,
        "OWNER_NAME",
        ""
    )

    data["PROPERTY_ADDRESS"] = get_record_value(
        data,
        "ADDRESS",
        ""
    )

    data["ASSESSMENT_NO"] = get_record_value(
        data,
        "PROPERTY_NO",
        ""
    )

    data["RATING_AREA"] = get_record_value(
        data,
        "RATING_AREA",
        ""
    )

    data["ESTIMATED"] = get_record_value(
        data,
        "ANNUAL_VALUE",
        ""
    )

    data["RATE_1"] = get_record_value(
        data,
        "RATE_DUE",
        ""
    )

    # Optional fields used by some templates
    for field in [
        "RATE_2",
        "RATE_3",
        "ARREARS_1",
        "ARREARS_2",
        "ARREARS_3",
        "PER_1",
        "PER_2",
        "PER_3",
        "TOTAL_1",
        "TOTAL_2",
        "TOTAL_3",
    ]:
        if field not in data:
            data[field] = ""

    data["LG_CODE"] = get_record_value(
        data,
        "LG_CODE",
        ""
    )

    return data


# ============================================================
# SINGLE PDF GENERATION
# ============================================================

def generate_notice_pdf(
    property_record,
    template_path=None,
    template_name="template.docx",
    output_folder=None,
):
    """
    Generate ONE PDF from ONE property/Excel record.

    output_folder is optional.
    If supplied, the PDF is written there.
    """

    # --------------------------------------------------------
    # Output directory
    # --------------------------------------------------------

    if output_folder is None:
        output_folder = OUTPUT_FOLDER
    else:
        output_folder = Path(output_folder)

    output_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Resolve template
    # --------------------------------------------------------

    if template_path:
        template_file = Path(template_path)
    else:
        template_file = TEMPLATES_FOLDER / template_name

    if not template_file.exists():
        raise FileNotFoundError(
            f"Word template not found: {template_file}"
        )

    if template_file.suffix.lower() != ".docx":
        raise ValueError(
            "The Word template must be a .docx file."
        )

    # --------------------------------------------------------
    # Prepare data
    # --------------------------------------------------------

    data = prepare_property_data(property_record)

    # --------------------------------------------------------
    # Determine unique filename
    #
    # Priority:
    # 1. PROPERTY_NO
    # 2. LG_CODE
    # 3. notice
    # --------------------------------------------------------

    assessment_no = str(
        data.get("ASSESSMENT_NO", "")
    ).strip()

    lg_code = str(
        data.get("LG_CODE", "")
    ).strip()

    if assessment_no:
        output_identifier = assessment_no
    elif lg_code:
        output_identifier = lg_code
    else:
        output_identifier = "notice"

    safe_name = make_safe_filename(
        output_identifier
    )

    docx_file = output_folder / f"{safe_name}.docx"
    pdf_file = output_folder / f"{safe_name}.pdf"

    # --------------------------------------------------------
    # Render Word document
    # --------------------------------------------------------

    engine = TemplateEngine()

    engine.render(
        str(template_file),
        str(docx_file),
        data
    )

    # --------------------------------------------------------
    # Convert DOCX → PDF
    # --------------------------------------------------------

    converter = WordConverter()

    converter.convert(
        str(docx_file),
        str(pdf_file)
    )

    if not pdf_file.exists():
        raise RuntimeError(
            f"PDF conversion failed: {pdf_file}"
        )

    return str(pdf_file)


# ============================================================
# EXCEL READER
# ============================================================

def read_excel_records(
    excel_path,
    sheet_name=None
):
    """
    Read Excel rows into dictionaries.

    First row is treated as the header row.
    """

    if load_workbook is None:
        raise RuntimeError(
            "openpyxl is not installed."
        )

    excel_file = Path(excel_path)

    if not excel_file.exists():
        raise FileNotFoundError(
            f"Excel file not found: {excel_file}"
        )

    workbook = load_workbook(
        filename=str(excel_file),
        data_only=True
    )

    try:

        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet '{sheet_name}' not found."
                )

            worksheet = workbook[sheet_name]

        else:
            worksheet = workbook[workbook.sheetnames[0]]

        rows = worksheet.iter_rows(
            values_only=True
        )

        try:
            header_row = next(rows)
        except StopIteration:
            return []

        headers = [
            normalize_column_name(value)
            for value in header_row
        ]

        records = []

        excel_row_number = 2

        for row in rows:

            if not any(
                value is not None and str(value).strip() != ""
                for value in row
            ):
                excel_row_number += 1
                continue

            record = {}

            for index, value in enumerate(row):

                if index >= len(headers):
                    continue

                header = headers[index]

                if not header:
                    continue

                record[header] = value

            record["_EXCEL_ROW"] = excel_row_number

            records.append(record)

            excel_row_number += 1

        return records

    finally:
        workbook.close()


# ============================================================
# EXCEL → INDIVIDUAL PDFS
# ============================================================

def generate_notice_pdfs_from_excel(
    excel_path,
    template_path=None,
    template_name="template.docx",
    sheet_name=None,
    selected_rows=None,
    output_folder=None,
):
    """
    Generate one separate PDF for every valid Excel row.

    IMPORTANT:
        These are INDIVIDUAL PDFs.
        They are NOT merged.
    """

    records = read_excel_records(
        excel_path=excel_path,
        sheet_name=sheet_name
    )

    if output_folder is None:
        output_folder = OUTPUT_FOLDER
    else:
        output_folder = Path(output_folder)

    output_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    generated = []
    failed = []
    skipped = []

    for record in records:

        excel_row = record.get(
            "_EXCEL_ROW"
        )

        # ----------------------------------------------------
        # Optional row filtering
        # ----------------------------------------------------

        if selected_rows is not None:

            if excel_row not in selected_rows:
                continue

        # ----------------------------------------------------
        # Identify record
        # ----------------------------------------------------

        property_no = str(
            record.get(
                "PROPERTY_NO",
                ""
            ) or ""
        ).strip()

        lg_code = str(
            record.get(
                "LG_CODE",
                ""
            ) or ""
        ).strip()

        owner_name = str(
            record.get(
                "OWNER_NAME",
                ""
            ) or ""
        ).strip()

        # ----------------------------------------------------
        # A row must have PROPERTY_NO or LG_CODE
        # ----------------------------------------------------

        if not property_no and not lg_code:

            skipped.append({
                "excel_row": excel_row,
                "reason": (
                    "Missing PROPERTY_NO and LG_CODE"
                ),
            })

            continue

        # ----------------------------------------------------
        # Build object for existing generator
        # ----------------------------------------------------

        property_object = SimpleNamespace()

        for key, value in record.items():

            setattr(
                property_object,
                key,
                value
            )

            setattr(
                property_object,
                str(key).lower(),
                value
            )

        # ----------------------------------------------------
        # Generate individual PDF
        # ----------------------------------------------------

        try:

            pdf_path = generate_notice_pdf(
                property_record=property_object,
                template_path=template_path,
                template_name=template_name,
                output_folder=output_folder,
            )

            generated.append({
                "excel_row": excel_row,
                "lg_code": lg_code,
                "property_no": property_no,
                "owner_name": owner_name,
                "pdf": pdf_path,
            })

        except Exception as exc:

            failed.append({
                "excel_row": excel_row,
                "lg_code": lg_code,
                "property_no": property_no,
                "owner_name": owner_name,
                "error": str(exc),
            })

    return {
        "total_records": len(records),
        "generated": generated,
        "failed": failed,
        "skipped": skipped,
    }


# ============================================================
# WINDOWS DESKTOP HELPERS
# ============================================================

def select_excel_file():
    """
    Desktop helper.
    Not used by the web API.
    """

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename(
        title="Select Excel File",
        filetypes=[
            (
                "Excel Files",
                "*.xlsx *.xlsm"
            ),
            (
                "All Files",
                "*.*"
            ),
        ],
    )

    root.destroy()

    return file_path


def select_word_template():
    """
    Desktop helper.
    Not used by the web API.
    """

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename(
        title="Select Word Template",
        filetypes=[
            (
                "Word Documents",
                "*.docx"
            ),
            (
                "All Files",
                "*.*"
            ),
        ],
    )

    root.destroy()

    return file_path


def select_excel_and_generate():
    """
    Desktop helper for the standalone generator.
    """

    excel_path = select_excel_file()

    if not excel_path:
        return None

    template_path = select_word_template()

    if not template_path:
        return None

    return generate_notice_pdfs_from_excel(
        excel_path=excel_path,
        template_path=template_path,
    )
```
