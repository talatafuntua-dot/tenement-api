import os
from pathlib import Path

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row


# =====================================================
# DIRECTORIES
# =====================================================

APP_DIR = Path(__file__).resolve().parent

BASE_DIR = APP_DIR.parent

TEMPLATES_FOLDER = BASE_DIR / "templates"

OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


# =====================================================
# GENERATE NOTICE PDF
# =====================================================

def generate_notice_pdf(
    property_record,
    template_name="template.docx"
):

    # -------------------------------------------------
    # Create output directory
    # -------------------------------------------------

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    # -------------------------------------------------
    # Validate template name
    # -------------------------------------------------

    if not template_name:

        template_name = "template.docx"

    # Only allow filename, not paths
    template_name = Path(
        template_name
    ).name

    # -------------------------------------------------
    # Template path
    # -------------------------------------------------

    template_file = (
        TEMPLATES_FOLDER /
        template_name
    )

    # -------------------------------------------------
    # Debug information
    # -------------------------------------------------

    print(
        f"Looking for template: {template_file}"
    )

    print(
        f"Template exists: {template_file.exists()}"
    )

    # -------------------------------------------------
    # Validate template
    # -------------------------------------------------

    if not template_file.exists():

        raise FileNotFoundError(
            f"Template not found: "
            f"{template_name} "
            f"at {template_file}"
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

    # =================================================
    # PREPARE DATA
    # =================================================

    data = prepare_row(
        property_record
    )

    # -------------------------------------------------
    # Template placeholders
    # -------------------------------------------------

    data["NAME_OF_OCCUPIER"] = \
        data.get("OWNER_NAME", "")

    data["PROPERTY_ADDRESS"] = \
        data.get("ADDRESS", "")

    data["ASSESSMENT_NO"] = \
        data.get("PROPERTY_NO", "")

    data["RATING_AREA"] = \
        data.get("RATING_AREA", "")

    data["ESTIMATED"] = \
        data.get("ANNUAL_VALUE", "")

    data["RATE_1"] = \
        data.get("RATE_DUE", "")

    # =================================================
    # DEFAULT VALUES
    # =================================================

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

    # =================================================
    # OUTPUT NAMES
    # =================================================

    assessment_no = str(
        data.get(
            "ASSESSMENT_NO",
            "notice"
        )
    )

    safe_name = assessment_no.replace(
        "/",
        "_"
    )

    pdf_file = (
        OUTPUT_FOLDER /
        f"{safe_name}.pdf"
    )

    docx_file = (
        OUTPUT_FOLDER /
        f"{safe_name}.docx"
    )

    # =================================================
    # RENDER TEMPLATE
    # =================================================

    engine = TemplateEngine()

    engine.render(
        str(template_file),
        str(docx_file),
        data
    )

    # =================================================
    # CONVERT DOCX → PDF
    # =================================================

    with WordConverter() as word:

        ok, msg = word.convert(
            str(docx_file),
            str(pdf_file)
        )

    if not ok:

        raise Exception(msg)

    # =================================================
    # REMOVE TEMP DOCX
    # =================================================

    if docx_file.exists():

        docx_file.unlink()

    # =================================================
    # RETURN PDF
    # =================================================

    return str(pdf_file)
