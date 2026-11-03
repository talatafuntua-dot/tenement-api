
# -*- coding: utf-8 -*-

"""
Tenement Rate PDF Generator
Performance Instrumentation Version

Measures the time spent on:
1. Output directory preparation
2. Template validation
3. Data preparation
4. Filename preparation
5. DOCX rendering
6. LibreOffice converter setup
7. PDF conversion
8. Total generation time

This version preserves the existing generation process.
No template logic or conversion architecture is changed.
"""

import os
import time
from pathlib import Path

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row


# -------------------------------------------------------
# DIRECTORIES
# -------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent

TEMPLATES_FOLDER = BASE_DIR / "templates"
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


# -------------------------------------------------------
# PERFORMANCE HELPER
# -------------------------------------------------------

def elapsed_ms(start_time):
    return round((time.perf_counter() - start_time) * 1000, 2)


# -------------------------------------------------------
# GENERATE NOTICE PDF
# -------------------------------------------------------

def generate_notice_pdf(
    property_record,
    template_path=None,
    template_name="template.docx"
):

    total_start = time.perf_counter()

    timings = {}

    # ---------------------------------------------------
    # 1. PREPARE OUTPUT DIRECTORY
    # ---------------------------------------------------

    stage_start = time.perf_counter()

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    timings["output_directory_ms"] = elapsed_ms(stage_start)

    # ---------------------------------------------------
    # 2. RESOLVE AND VALIDATE TEMPLATE
    # ---------------------------------------------------

    stage_start = time.perf_counter()

    if template_path:
        template_file = Path(template_path)
    else:
        template_file = TEMPLATES_FOLDER / template_name

    if not template_file.exists():
        raise FileNotFoundError(
            f"Template not found: {template_file}"
        )

    if not template_file.is_file():
        raise ValueError(
            f"Template path is not a file: {template_file}"
        )

    if template_file.suffix.lower() != ".docx":
        raise ValueError(
            f"Invalid template format: {template_file}"
        )

    timings["template_validation_ms"] = elapsed_ms(stage_start)

    # ---------------------------------------------------
    # 3. PREPARE PROPERTY DATA
    # ---------------------------------------------------

    stage_start = time.perf_counter()

    data = prepare_row(property_record)

    data["NAME_OF_OCCUPIER"] = data.get("OWNER_NAME", "")
    data["PROPERTY_ADDRESS"] = data.get("ADDRESS", "")
    data["ASSESSMENT_NO"] = data.get("PROPERTY_NO", "")
    data["RATING_AREA"] = data.get("RATING_AREA", "")
    data["ESTIMATED"] = data.get("ANNUAL_VALUE", "")
    data["RATE_1"] = data.get("RATE_DUE", "")

    data.setdefault("LG_CODE", "")
    data.setdefault("RATE_2", "")
    data.setdefault("RATE_3", "")

    data.setdefault("ARREARS_1", "")
    data.setdefault("ARREARS_2", "")
    data.setdefault("ARREARS_3", "")

    data.setdefault("PER_1", "")
    data.setdefault("PER_2", "")
    data.setdefault("PER_3", "")

    data.setdefault("TOTAL_1", "")
    data.setdefault("TOTAL_2", "")
    data.setdefault("TOTAL_3", "")

    timings["data_preparation_ms"] = elapsed_ms(stage_start)

    # ---------------------------------------------------
    # 4. PREPARE OUTPUT FILENAMES
    # ---------------------------------------------------

    stage_start = time.perf_counter()

    property_number = str(
        data.get("ASSESSMENT_NO")
        or "unknown_property"
    )

    safe_name = (
        property_number
        .replace("/", "_")
        .replace("\\", "_")
    )

    docx_file = OUTPUT_FOLDER / f"{safe_name}.docx"
    pdf_file = OUTPUT_FOLDER / f"{safe_name}.pdf"

    timings["filename_preparation_ms"] = elapsed_ms(stage_start)

    # ---------------------------------------------------
    # 5. RENDER WORD DOCUMENT
    # ---------------------------------------------------

    stage_start = time.perf_counter()

    engine = TemplateEngine()

    engine.render(
        template_path=str(template_file),
        output_path=str(docx_file),
        data=data
    )

    timings["docx_rendering_ms"] = elapsed_ms(stage_start)

    # ---------------------------------------------------
    # 6. CONVERT DOCX TO PDF
    # ---------------------------------------------------

    converter_total_start = time.perf_counter()

    with WordConverter() as word:

        timings["converter_setup_ms"] = elapsed_ms(
            converter_total_start
        )

        conversion_start = time.perf_counter()

        ok, msg = word.convert(
            docx_path=docx_file,
            pdf_path=pdf_file
        )

        timings["pdf_conversion_ms"] = elapsed_ms(
            conversion_start
        )

    timings["converter_total_ms"] = elapsed_ms(
        converter_total_start
    )

    # ---------------------------------------------------
    # 7. CHECK CONVERSION RESULT
    # ---------------------------------------------------

    if not ok:
        raise RuntimeError(
            f"PDF conversion failed: {msg}"
        )

    if not pdf_file.exists():
        raise RuntimeError(
            f"PDF file was not created: {pdf_file}"
        )

    # ---------------------------------------------------
    # 8. PRINT PERFORMANCE REPORT
    # ---------------------------------------------------

    timings["total_ms"] = elapsed_ms(total_start)

    print("")
    print("========== BILL GENERATION PROFILE ==========")
    print(f"Template: {template_file.name}")
    print(f"Property: {property_number}")

    for stage, duration in timings.items():
        print(f"{stage}: {duration} ms")

    print("=============================================")
    print("")

    # ---------------------------------------------------
    # 9. RETURN PDF PATH
    # ---------------------------------------------------

    return str(pdf_file)
