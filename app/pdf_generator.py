import os
from pathlib import Path

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row


BASE_DIR = Path(__file__).resolve().parent.parent

TEMPLATES_FOLDER = BASE_DIR / "templates"

OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


def generate_notice_pdf(
    property_record,
    template_name="template.docx"
):

    os.makedirs(
        OUTPUT_FOLDER,
        exist_ok=True
    )


    # =====================================================
    # VALIDATE TEMPLATE NAME
    # =====================================================

    if not template_name:
        template_name = "template.docx"


    # Prevent directory traversal
    template_name = Path(
        template_name
    ).name


    template_file = (
        TEMPLATES_FOLDER /
        template_name
    )


    if not template_file.exists():

        raise FileNotFoundError(
            f"Template not found: {template_name}"
        )


    if template_file.suffix.lower() != ".docx":

        raise ValueError(
            "Only DOCX templates are supported."
        )


    # =====================================================
    # PREPARE DATA
    # =====================================================

    data = prepare_row(property_record)


    # Map database fields to template placeholders

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

    pdf_name = (
        f"{data['ASSESSMENT_NO'].replace('/', '_')}.pdf"
    )


    docx_file = (
        OUTPUT_FOLDER /
        pdf_name.replace(
            ".pdf",
            ".docx"
        )
    )


    pdf_file = (
        OUTPUT_FOLDER /
        pdf_name
    )


    # =====================================================
    # RENDER WORD TEMPLATE
    # =====================================================

    engine = TemplateEngine()


    engine.render(
        str(template_file),
        str(docx_file),
        data
    )


    # =====================================================
    # CONVERT DOCX → PDF
    # =====================================================

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

    if os.path.exists(docx_file):

        os.remove(docx_file)


    return str(pdf_file)
