import os

from pathlib import Path

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row


# =========================================================
# DIRECTORIES
# =========================================================

APP_DIR = Path(
    __file__
).resolve().parent

BASE_DIR = APP_DIR.parent

TEMPLATES_FOLDER = (
    BASE_DIR /
    "templates"
)

OUTPUT_FOLDER = (
    BASE_DIR /
    "output_pdfs"
)


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

    # -----------------------------------------------------
    # Debug information
    # -----------------------------------------------------

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
            f"Template not found: "
            f"{template_file}"
        )

    if not template_file.is_file():

        raise FileNotFoundError(
            f"Template is not a file: "
            f"{template_file}"
        )

    if template_file.suffix.lower() != ".docx":

        raise ValueError(
            "Only DOCX templates are supported."
        )

    # =====================================================
    # PREPARE DATA
    # =====================================================

    data = prepare_row(
        property_record
    )

    # -----------------------------------------------------
    # Template placeholders
    # -----------------------------------------------------

    data["NAME_OF_OCCUPIER"] = (
        data.get(
            "OWNER_NAME",
            ""
        )
    )

    data["PROPERTY_ADDRESS"] = (
        data.get(
            "ADDRESS",
            ""
        )
    )

    data["ASSESSMENT_NO"] = (
        data.get(
            "PROPERTY_NO",
            ""
        )
    )

    data["RATING_AREA"] = (
        data.get(
            "RATING_AREA",
            ""
        )
    )

    data["ESTIMATED"] = (
        data.get(
            "ANNUAL_VALUE",
            ""
        )
    )

    data["RATE_1"] = (
        data.get(
            "RATE_DUE",
            ""
        )
    )

    # =====================================================
    # DEFAULT VALUES
    # =====================================================

    defaults = {

        "LG_CODE": "",

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

    # =====================================================
    # OUTPUT FILE NAMES
    # =====================================================

    assessment_no = str(
        data.get(
            "ASSESSMENT_NO",
            "notice"
        )
    )

    safe_name = (
        assessment_no
        .replace("/", "_")
        .replace("\\", "_")
        .strip()
    )

    if not safe_name:

        safe_name = "notice"

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

        raise Exception(msg)

    # =====================================================
    # DELETE TEMPORARY DOCX
    # =====================================================

    if docx_file.exists():

        try:

            docx_file.unlink()

        except Exception as exc:

            print(
                f"Warning: could not delete "
                f"temporary DOCX: {exc}"
            )

    # =====================================================
    # RETURN PDF
    # =====================================================

    print(
        f"PDF generated successfully: {pdf_file}"
    )

    return str(pdf_file)
