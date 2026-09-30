import os
from pathlib import Path
from types import SimpleNamespace
import re

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row


# =========================================================
# OPTIONAL EXCEL SUPPORT
# =========================================================

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


# =========================================================
# DIRECTORIES
# =========================================================

APP_DIR = Path(__file__).resolve().parent

BASE_DIR = APP_DIR.parent

TEMPLATES_FOLDER = BASE_DIR / "templates"

OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


# =========================================================
# HELPER - GET VALUE FROM OBJECT OR DICT
# =========================================================

def get_record_value(record, key, default=""):
    """
    Get a value from either:

        - database/model object
        - dictionary
        - SimpleNamespace

    Also tries case-insensitive dictionary/attribute matching.
    """

    if record is None:
        return default

    # -----------------------------------------------------
    # Dictionary
    # -----------------------------------------------------

    if isinstance(record, dict):

        if key in record:
            value = record[key]

            return default if value is None else value

        key_upper = str(key).upper()

        for existing_key, value in record.items():

            if str(existing_key).upper() == key_upper:

                return default if value is None else value

        return default

    # -----------------------------------------------------
    # Normal object
    # -----------------------------------------------------

    value = getattr(
        record,
        key,
        default
    )

    if value is None:
        return default

    return value


# =========================================================
# NORMALIZE EXCEL COLUMN NAME
# =========================================================

def normalize_column_name(name):
    """
    Converts Excel headers such as:

        Owner Name
        owner_name
        OWNER NAME
        Owner-Name

    into:

        OWNER_NAME
    """

    if name is None:
        return ""

    value = str(name).strip()

    value = value.replace("-", "_")
    value = value.replace("/", "_")
    value = value.replace("\\", "_")

    value = re.sub(
        r"\s+",
        "_",
        value
    )

    value = re.sub(
        r"[^A-Za-z0-9_]",
        "",
        value
    )

    return value.upper()


# =========================================================
# PREPARE PROPERTY DATA
# =========================================================

def prepare_property_data(property_record):
    """
    Converts a database record or Excel record into the
    dictionary expected by TemplateEngine.
    """

    data = prepare_row(
        property_record
    )

    if data is None:
        data = {}

    # -----------------------------------------------------
    # Standard field mappings
    # -----------------------------------------------------

    data["NAME_OF_OCCUPIER"] = get_record_value(
        property_record,
        "OWNER_NAME",
        data.get("OWNER_NAME", "")
    )

    data["PROPERTY_ADDRESS"] = get_record_value(
        property_record,
        "ADDRESS",
        data.get("ADDRESS", "")
    )

    data["ASSESSMENT_NO"] = get_record_value(
        property_record,
        "PROPERTY_NO",
        data.get("PROPERTY_NO", "")
    )

    data["RATING_AREA"] = get_record_value(
        property_record,
        "RATING_AREA",
        data.get("RATING_AREA", "")
    )

    data["ESTIMATED"] = get_record_value(
        property_record,
        "ANNUAL_VALUE",
        data.get("ANNUAL_VALUE", "")
    )

    data["RATE_1"] = get_record_value(
        property_record,
        "RATE_DUE",
        data.get("RATE_DUE", "")
    )

    # -----------------------------------------------------
    # LG CODE
    # -----------------------------------------------------

    data["LG_CODE"] = get_record_value(
        property_record,
        "LG_CODE",
        data.get("LG_CODE", "")
    )

    # =====================================================
    # DEFAULT VALUES
    # =====================================================

    defaults = {

        "RATE_2": "",
        "RATE_3": "",

        "ARREARS_1": "",
        "ARREARS_2": "",
        "ARREARS_3": "",

        "PER_1": "",
        "PER_2": "",
        "PER_3": "",

        "TOTAL_1": "",
        "TOTAL_2": "",
        "TOTAL_3": "",
    }

    for key, value in defaults.items():

        data.setdefault(
            key,
            value
        )

    return data


# =========================================================
# GET SAFE OUTPUT NAME
# =========================================================

def make_safe_filename(value, fallback="notice"):

    if value is None:
        value = ""

    value = str(value).strip()

    if not value:
        value = fallback

    value = value.replace(
        "/",
        "_"
    )

    value = value.replace(
        "\\",
        "_"
    )

    value = re.sub(
        r'[<>:"|?*]',
        "_",
        value
    )

    value = value.strip(
        ". "
    )

    if not value:
        value = fallback

    return value


# =========================================================
# GENERATE NOTICE PDF
# =========================================================

def generate_notice_pdf(
    property_record,
    template_path=None,
    template_name="template.docx"
):

    # -----------------------------------------------------
    # Create output directory
    # -----------------------------------------------------

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    # =====================================================
    # DETERMINE TEMPLATE
    # =====================================================

    if template_path is not None:

        template_file = Path(
            template_path
        )

    else:

        if not template_name:
            template_name = "template.docx"

        template_name = Path(
            template_name
        ).name

        template_file = (
            TEMPLATES_FOLDER /
            template_name
        )

    # =====================================================
    # DEBUG
    # =====================================================

    print(
        "=========================================="
    )

    print(
        "TEMPLATE DEBUG"
    )

    print(
        f"Template path: {template_file}"
    )

    print(
        f"Template exists: {template_file.exists()}"
    )

    print(
        f"Template is file: {template_file.is_file()}"
    )

    print(
        "=========================================="
    )

    # =====================================================
    # VALIDATE TEMPLATE
    # =====================================================

    if not template_file.exists():

        raise FileNotFoundError(
            f"Template not found: {template_file}"
        )

    if not template_file.is_file():

        raise FileNotFoundError(
            f"Template is not a file: {template_file}"
        )

    if template_file.suffix.lower() != ".docx":

        raise ValueError(
            "Only DOCX templates are supported."
        )

    # =====================================================
    # PREPARE DATA
    # =====================================================

    data = prepare_property_data(
        property_record
    )

    # =====================================================
    # OUTPUT FILE NAME
    # =====================================================

    assessment_no = data.get(
        "ASSESSMENT_NO",
        "notice"
    )

    safe_name = make_safe_filename(
        assessment_no
    )

    docx_file = (
        OUTPUT_FOLDER /
        f"{safe_name}.docx"
    )

    pdf_file = (
        OUTPUT_FOLDER /
        f"{safe_name}.pdf"
    )

    # =====================================================
    # RENDER WORD TEMPLATE
    # =====================================================

    print(
        f"Rendering template: {template_file}"
    )

    engine = TemplateEngine()

    engine.render(
        str(template_file),
        str(docx_file),
        data
    )

    # =====================================================
    # CONVERT DOCX → PDF
    # =====================================================

    print(
        f"Converting DOCX to PDF: {docx_file}"
    )

    with WordConverter() as word:

        ok, msg = word.convert(
            str(docx_file),
            str(pdf_file)
        )

    if not ok:

        raise Exception(
            msg
        )

    # =====================================================
    # RESULT
    # =====================================================

    print(
        f"PDF generated successfully: {pdf_file}"
    )

    return str(pdf_file)


# =========================================================
# READ EXCEL FILE
# =========================================================

def read_excel_records(
    excel_path,
    sheet_name=None
):
    """
    Read an Excel workbook and return a list of property
    records.

    The first row is treated as the column header.

    Example:

        LG_CODE | PROPERTY_NO | OWNER_NAME | ADDRESS | RATE_DUE

    Each row becomes a property record.
    """

    if load_workbook is None:

        raise ImportError(
            "openpyxl is required for Excel processing. "
            "Install it with: pip install openpyxl"
        )

    excel_file = Path(
        excel_path
    )

    if not excel_file.exists():

        raise FileNotFoundError(
            f"Excel file not found: {excel_file}"
        )

    if not excel_file.is_file():

        raise FileNotFoundError(
            f"Excel path is not a file: {excel_file}"
        )

    if excel_file.suffix.lower() not in (
        ".xlsx",
        ".xlsm"
    ):

        raise ValueError(
            "Only .xlsx and .xlsm Excel files are supported."
        )

    # =====================================================
    # OPEN WORKBOOK
    # =====================================================

    workbook = load_workbook(
        filename=str(excel_file),
        read_only=True,
        data_only=True
    )

    try:

        # -------------------------------------------------
        # Select worksheet
        # -------------------------------------------------

        if sheet_name is None:

            worksheet = workbook[
                workbook.sheetnames[0]
            ]

        elif isinstance(sheet_name, int):

            worksheet = workbook[
                workbook.sheetnames[sheet_name]
            ]

        else:

            worksheet = workbook[
                str(sheet_name)
            ]

        # -------------------------------------------------
        # Read rows
        # -------------------------------------------------

        rows = worksheet.iter_rows(
            values_only=True
        )

        try:

            header_row = next(rows)

        except StopIteration:

            return []

        headers = [
            normalize_column_name(
                header
            )
            for header in header_row
        ]

        records = []

        for row_number, row in enumerate(
            rows,
            start=2
        ):

            # Skip completely empty rows
            if not any(
                value is not None and str(value).strip() != ""
                for value in row
            ):
                continue

            record = {}

            for index, header in enumerate(headers):

                if not header:
                    continue

                value = (
                    row[index]
                    if index < len(row)
                    else None
                )

                record[header] = (
                    ""
                    if value is None
                    else value
                )

            # Keep original Excel row number
            record["_EXCEL_ROW"] = row_number

            records.append(
                record
            )

        return records

    finally:

        workbook.close()


# =========================================================
# GENERATE PDFs FROM EXCEL
# =========================================================

def generate_notice_pdfs_from_excel(
    excel_path,
    template_path=None,
    template_name="template.docx",
    sheet_name=None,
    selected_rows=None
):
    """
    Generate one PDF for every selected Excel record.

    Parameters
    ----------
    excel_path:
        Path to Excel workbook.

    template_path:
        Full path to DOCX template.

    template_name:
        Template filename inside templates folder.

    sheet_name:
        Worksheet name or worksheet index.

    selected_rows:
        Optional list of Excel row numbers.

        Example:
            [2, 5, 8]

        If None, ALL non-empty records are processed.

    Returns
    -------
    dict
        Summary containing generated, failed and skipped files.
    """

    # =====================================================
    # READ EXCEL
    # =====================================================

    records = read_excel_records(
        excel_path,
        sheet_name=sheet_name
    )

    if not records:

        raise ValueError(
            "No property records were found in the Excel file."
        )

    # =====================================================
    # FILTER SELECTED ROWS
    # =====================================================

    if selected_rows is not None:

        selected_rows = {
            int(row)
            for row in selected_rows
        }

        records = [
            record
            for record in records
            if record.get("_EXCEL_ROW")
            in selected_rows
        ]

    if not records:

        raise ValueError(
            "None of the selected Excel rows contained data."
        )

    # =====================================================
    # RESULTS
    # =====================================================

    generated = []
    failed = []
    skipped = []

    # =====================================================
    # PROCESS EACH RECORD
    # =====================================================

    for index, excel_record in enumerate(
        records,
        start=1
    ):

        excel_row = excel_record.get(
            "_EXCEL_ROW",
            index
        )

        print(
            ""
        )

        print(
            "=========================================="
        )

        print(
            f"PROCESSING EXCEL ROW {excel_row}"
        )

        print(
            f"Batch item {index} of {len(records)}"
        )

        print(
            "=========================================="
        )

        # -------------------------------------------------
        # Check property number / LG code
        # -------------------------------------------------

        property_no = get_record_value(
            excel_record,
            "PROPERTY_NO",
            ""
        )

        lg_code = get_record_value(
            excel_record,
            "LG_CODE",
            ""
        )

        owner_name = get_record_value(
            excel_record,
            "OWNER_NAME",
            ""
        )

        # -------------------------------------------------
        # Need at least an identifier
        # -------------------------------------------------

        if not str(property_no).strip() and not str(lg_code).strip():

            skipped.append({
                "excel_row": excel_row,
                "reason": (
                    "No PROPERTY_NO or LG_CODE found"
                )
            })

            continue

        # -------------------------------------------------
        # Convert dictionary to object
        #
        # This allows prepare_row() to work with Excel
        # records in the same way as database records.
        # -------------------------------------------------

        object_data = {}

        for key, value in excel_record.items():

            if key.startswith("_"):
                continue

            object_data[key] = value

            object_data[key.lower()] = value

        property_object = SimpleNamespace(
            **object_data
        )

        # -------------------------------------------------
        # Generate PDF
        # -------------------------------------------------

        try:

            pdf_path = generate_notice_pdf(
                property_object,
                template_path=template_path,
                template_name=template_name
            )

            generated.append({
                "excel_row": excel_row,
                "lg_code": lg_code,
                "property_no": property_no,
                "owner_name": owner_name,
                "pdf": pdf_path
            })

        except Exception as exc:

            print(
                f"ERROR processing Excel row "
                f"{excel_row}: {exc}"
            )

            failed.append({
                "excel_row": excel_row,
                "lg_code": lg_code,
                "property_no": property_no,
                "owner_name": owner_name,
                "error": str(exc)
            })

    # =====================================================
    # SUMMARY
    # =====================================================

    result = {

        "excel_file": str(
            Path(excel_path).resolve()
        ),

        "total_records": len(records),

        "generated_count": len(
            generated
        ),

        "failed_count": len(
            failed
        ),

        "skipped_count": len(
            skipped
        ),

        "generated": generated,

        "failed": failed,

        "skipped": skipped,
    }

    print(
        ""
    )

    print(
        "=========================================="
    )

    print(
        "EXCEL BATCH GENERATION COMPLETE"
    )

    print(
        f"Total:     {len(records)}"
    )

    print(
        f"Generated: {len(generated)}"
    )

    print(
        f"Failed:    {len(failed)}"
    )

    print(
        f"Skipped:   {len(skipped)}"
    )

    print(
        "=========================================="
    )

    return result


# =========================================================
# SELECT EXCEL FILE FROM WINDOWS
# =========================================================

def select_excel_file():
    """
    Opens a Windows file-selection dialog.
    """

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()

    root.withdraw()

    root.attributes(
        "-topmost",
        True
    )

    file_path = filedialog.askopenfilename(
        title="Select Excel File",
        filetypes=[
            (
                "Excel Files",
                "*.xlsx *.xlsm"
            ),
            (
                "Excel Workbook",
                "*.xlsx"
            ),
            (
                "Excel Macro Workbook",
                "*.xlsm"
            ),
            (
                "All Files",
                "*.*"
            )
        ]
    )

    root.destroy()

    if not file_path:
        return None

    return file_path


# =========================================================
# SELECT WORD TEMPLATE
# =========================================================

def select_word_template():
    """
    Opens a Windows file-selection dialog for a DOCX
    template.
    """

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()

    root.withdraw()

    root.attributes(
        "-topmost",
        True
    )

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
            )
        ]
    )

    root.destroy()

    if not file_path:
        return None

    return file_path


# =========================================================
# GUI: SELECT EXCEL AND TEMPLATE
# =========================================================

def select_excel_and_generate():
    """
    Simple Windows GUI workflow:

        1. Select Excel
        2. Select Word template
        3. Generate PDFs
        4. Show result

    This is intended for the desktop EXE version.
    """

    import tkinter as tk
    from tkinter import messagebox

    # -----------------------------------------------------
    # Select Excel
    # -----------------------------------------------------

    excel_file = select_excel_file()

    if not excel_file:

        return None

    # -----------------------------------------------------
    # Select Word template
    # -----------------------------------------------------

    template_file = select_word_template()

    if not template_file:

        return None

    # -----------------------------------------------------
    # Confirm
    # -----------------------------------------------------

    root = tk.Tk()

    root.withdraw()

    root.attributes(
        "-topmost",
        True
    )

    confirm = messagebox.askyesno(
        "Batch PDF Generation",
        "Generate PDFs for all records in this Excel file?\n\n"
        f"Excel:\n{excel_file}\n\n"
        f"Template:\n{template_file}"
    )

    if not confirm:

        root.destroy()

        return None

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

    try:

        result = generate_notice_pdfs_from_excel(
            excel_path=excel_file,
            template_path=template_file
        )

        messagebox.showinfo(
            "Batch Generation Complete",
            "PDF generation completed.\n\n"
            f"Total records: "
            f"{result['total_records']}\n\n"
            f"Generated: "
            f"{result['generated_count']}\n\n"
            f"Failed: "
            f"{result['failed_count']}\n\n"
            f"Skipped: "
            f"{result['skipped_count']}\n\n"
            f"Output folder:\n"
            f"{OUTPUT_FOLDER}"
        )

        return result

    except Exception as exc:

        messagebox.showerror(
            "Batch Generation Error",
            str(exc)
        )

        return None

    finally:

        root.destroy()
