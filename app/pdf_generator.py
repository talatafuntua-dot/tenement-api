import os
from pathlib import Path

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row

BASE_DIR = Path(__file__).resolve().parent.parent

TEMPLATE_FILE = BASE_DIR / "templates" / "template.docx"
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


def generate_notice_pdf(property_record):

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    data = prepare_row(property_record)

    # Map database fields to template placeholders
    data["NAME_OF_OCCUPIER"] = data.get("OWNER_NAME", "")
    data["PROPERTY_ADDRESS"] = data.get("ADDRESS", "")
    data["ASSESSMENT_NO"] = data.get("PROPERTY_NO", "")
    data["RATING_AREA"] = data.get("RATING_AREA", "")
    data["ESTIMATED"] = data.get("ANNUAL_VALUE", "")
    data["RATE_1"] = data.get("RATE_DUE", "")

    # Temporary values until database is expanded
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
        data.setdefault(key, value)

    pdf_name = f"{data['ASSESSMENT_NO'].replace('/', '_')}.pdf"

    docx_file = OUTPUT_FOLDER / pdf_name.replace(".pdf", ".docx")
    pdf_file = OUTPUT_FOLDER / pdf_name

    engine = TemplateEngine()

    engine.render(
        str(TEMPLATE_FILE),
        str(docx_file),
        data
    )

    with WordConverter() as word:
        ok, msg = word.convert(str(docx_file), str(pdf_file))

    if not ok:
        raise Exception(msg)

    if os.path.exists(docx_file):
        os.remove(docx_file)

    return str(pdf_file)