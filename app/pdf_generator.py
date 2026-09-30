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


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_FOLDER = BASE_DIR / "templates"
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"

TEMPLATES_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)


def get_record_value(record, *names):
    """Get a value from a dictionary or object using case-insensitive names."""

    if record is None:
        return ""

    if isinstance(record, dict):
        for name in names:
            wanted = str(name).strip().lower()

            for key, value in record.items():
                if str(key).strip().lower() == wanted:
                    return value

        return ""

    for name in names:
        if hasattr(record, name):
            return getattr(record, name)

    wanted_names = {
        str(name).strip().lower()
        for name in names
    }

    for attribute in dir(record):
        if attribute.lower() in wanted_names:
            try:
                return getattr(record, attribute)
            except Exception:
                pass

    return ""


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def safe_filename(value):
    """Make a Windows/Linux-safe filename."""

    value = clean_text(value)

    if not value:
        return "notice"

    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.rstrip(". ")

    return value[:180] or "notice"


def normalize_column_name(value):
    """Convert Excel column names to consistent keys."""

    value = clean_text(value)

    value = value.replace("\n", " ")
    value = value.replace("\r", " ")
    value = re.sub(r"\s+", "_", value)

    return value.strip("_").upper()


def prepare_property_data(record):
    """
    Convert a property record into the field names expected
    by the Word template.
    """

    prepared = prepare_row(record)

    data = dict(prepared)

    owner_name = get_record_value(
        record,
        "OWNER_NAME",
        "OWNER",
        "NAME_OF_OCCUPIER"
    )

    address = get_record_value(
        record,
        "ADDRESS",
        "PROPERTY_ADDRESS"
    )

    property_no = get_record_value(
        record,
        "PROPERTY_NO",
        "PROPERTY_NUMBER",
        "ASSESSMENT_NO"
    )

    rating_area = get_record_value(
        record,
        "RATING_AREA"
    )

    annual_value = get_record_value(
        record,
        "ANNUAL_VALUE",
        "ESTIMATED"
    )

    rate_due = get_record_value(
        record,
        "RATE_DUE",
        "RATE_1"
    )

    lg_code = get_record_value(
        record,
        "LG_CODE",
        "LGCODE"
    )

    data["NAME_OF_OCCUPIER"] = clean_text(owner_name)
    data["PROPERTY_ADDRESS"] = clean_text(address)
    data["ASSESSMENT_NO"] = clean_text(property_no)
    data["RATING_AREA"] = clean_text(rating_area)
    data["LG_CODE"] = clean_text(lg_code)

    if "ESTIMATED" not in data or not data["ESTIMATED"]:
        data["ESTIMATED"] = clean_text(annual_value)

    if "RATE_1" not in data or not data["RATE_1"]:
        data["RATE_1"] = clean_text(rate_due)

    for field in (
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
    ):
        if field not in data:
            data[field] = ""

    return data


def resolve_template(template_name):
    """Locate a Word template."""

    template_name = clean_text(template_name)

    if not template_name:
        template_name = "template.docx"

    template_path = Path(template_name)

    if template_path.is_absolute() and template_path.exists():
        return template_path

    candidate = TEMPLATES_FOLDER / template_name

    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"Template not found: {template_name}"
    )


def make_unique_pdf_path(folder, base_name):
    """
    Make sure two records never overwrite each other's PDF.
    """

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    base_name = safe_filename(base_name)

    pdf_path = folder / f"{base_name}.pdf"

    if not pdf_path.exists():
        return pdf_path

    counter = 2

    while True:
        pdf_path = folder / f"{base_name}_{counter}.pdf"

        if not pdf_path.exists():
            return pdf_path

        counter += 1


def generate_notice_pdf(
    property_record,
    template_name="template.docx",
    output_folder=None
):
    """
    Generate one DOCX and one PDF from one property record.

    Returns the PDF path.
    """

    template_path = resolve_template(template_name)

    if output_folder:
        output_path = Path(output_folder)
    else:
        output_path = OUTPUT_FOLDER

    output_path.mkdir(parents=True, exist_ok=True)

    data = prepare_property_data(property_record)

    property_no = clean_text(
        get_record_value(
            property_record,
            "PROPERTY_NO",
            "PROPERTY_NUMBER",
            "ASSESSMENT_NO"
        )
    )

    lg_code = clean_text(
        get_record_value(
            property_record,
            "LG_CODE",
            "LGCODE"
        )
    )

    owner_name = clean_text(
        get_record_value(
            property_record,
            "OWNER_NAME",
            "OWNER"
        )
    )

    if property_no:
        base_name = property_no
    elif lg_code:
        base_name = lg_code
    elif owner_name:
        base_name = owner_name
    else:
        base_name = "notice"

    pdf_path = make_unique_pdf_path(
        output_path,
        base_name
    )

    docx_path = pdf_path.with_suffix(".docx")

    engine = TemplateEngine(str(template_path))

    engine.render(
        data,
        str(docx_path)
    )

    converter = WordConverter()

    converter.convert(
        str(docx_path),
        str(output_path)
    )

    generated_pdf = docx_path.with_suffix(".pdf")

    if not generated_pdf.exists():
        possible_pdf = output_path / f"{docx_path.stem}.pdf"

        if possible_pdf.exists():
            generated_pdf = possible_pdf

    if not generated_pdf.exists():
        raise FileNotFoundError(
            f"PDF was not generated: {generated_pdf}"
        )

    if generated_pdf != pdf_path:
        if pdf_path.exists():
            pdf_path.unlink()

        generated_pdf.rename(pdf_path)

    return str(pdf_path)


def read_excel_records(excel_path, worksheet_name=None):
    """
    Read the first worksheet of an Excel file and return
    normalized dictionaries.
    """

    if load_workbook is None:
        raise RuntimeError(
            "openpyxl is not installed."
        )

    excel_path = Path(excel_path)

    if not excel_path.exists():
        raise FileNotFoundError(
            f"Excel file not found: {excel_path}"
        )

    workbook = load_workbook(
        filename=str(excel_path),
        data_only=True
    )

    if worksheet_name:
        if worksheet_name not in workbook.sheetnames:
            raise ValueError(
                f"Worksheet not found: {worksheet_name}"
            )

        worksheet = workbook[worksheet_name]
    else:
        worksheet = workbook[workbook.sheetnames[0]]

    rows = worksheet.iter_rows(values_only=True)

    try:
        header_row = next(rows)
    except StopIteration:
        return []

    headers = [
        normalize_column_name(value)
        for value in header_row
    ]

    records = []

    for excel_row_number, row in enumerate(rows, start=2):

        if not any(
            value is not None and str(value).strip()
            for value in row
        ):
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

    workbook.close()

    return records


def generate_notice_pdfs_from_excel(
    excel_path,
    template_name="template.docx",
    output_folder=None,
    selected_rows=None
):
    """
    Generate one PDF for every usable Excel row.

    Returns a summary dictionary.
    """

    records = read_excel_records(excel_path)

    if output_folder:
        output_path = Path(output_folder)
    else:
        output_path = OUTPUT_FOLDER

    output_path.mkdir(
        parents=True,
        exist_ok=True
    )

    selected_set = None

    if selected_rows:
        selected_set = {
            int(row)
            for row in selected_rows
        }

    generated = []
    failed = []
    skipped = []

    for record in records:

        excel_row = record.get("_EXCEL_ROW")

        if (
            selected_set is not None
            and excel_row not in selected_set
        ):
            skipped.append({
                "excel_row": excel_row,
                "reason": "Not selected"
            })
            continue

        property_no = clean_text(
            get_record_value(
                record,
                "PROPERTY_NO",
                "PROPERTY_NUMBER",
                "ASSESSMENT_NO"
            )
        )

        lg_code = clean_text(
            get_record_value(
                record,
                "LG_CODE",
                "LGCODE"
            )
        )

        owner_name = clean_text(
            get_record_value(
                record,
                "OWNER_NAME",
                "OWNER",
                "NAME_OF_OCCUPIER"
            )
        )

        if not property_no and not lg_code:
            skipped.append({
                "excel_row": excel_row,
                "reason": (
                    "No PROPERTY_NO or LG_CODE"
                ),
                "owner_name": owner_name
            })
            continue

        try:
            property_object = SimpleNamespace(
                **{
                    key: value
                    for key, value in record.items()
                    if key != "_EXCEL_ROW"
                }
            )

            pdf_file = generate_notice_pdf(
                property_object,
                template_name=template_name,
                output_folder=output_path
            )

            generated.append({
                "excel_row": excel_row,
                "lg_code": lg_code,
                "property_no": property_no,
                "owner_name": owner_name,
                "pdf": str(pdf_file)
            })

        except Exception as exc:

            failed.append({
                "excel_row": excel_row,
                "lg_code": lg_code,
                "property_no": property_no,
                "owner_name": owner_name,
                "error": str(exc)
            })

    return {
        "generated": generated,
        "failed": failed,
        "skipped": skipped,
        "generated_count": len(generated),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "total_records": len(records)
    }
