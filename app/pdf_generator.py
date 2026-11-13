
from pathlib import Path

from app.template_engine import TemplateEngine
from app.word_converter import WordConverter
from app.formatter import prepare_row
from app.routers.google_drive import archive_pdfs_to_drive


APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
TEMPLATES_FOLDER = BASE_DIR / "templates"
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


def render_notice_docx(
    property_record,
    docx_path,
    template_path=None,
    template_name="template.docx"
):
    """Render a notice DOCX without starting LibreOffice."""

    if template_path is not None:
        template_file = Path(template_path)
    else:
        template_name = Path(
            template_name or "template.docx"
        ).name
        template_file = TEMPLATES_FOLDER / template_name

    if not template_file.exists() or not template_file.is_file():
        raise FileNotFoundError(
            f"Template not found: {template_file}"
        )

    if template_file.suffix.lower() != ".docx":
        raise ValueError("Only DOCX templates are supported.")

    data = prepare_row(property_record)

    data["NAME_OF_OCCUPIER"] = data.get("OWNER_NAME", "")
    data["PROPERTY_ADDRESS"] = data.get("ADDRESS", "")
    data["ASSESSMENT_NO"] = data.get("PROPERTY_NO", "")
    data["RATING_AREA"] = data.get("RATING_AREA", "")
    data["ESTIMATED"] = data.get("ANNUAL_VALUE", "")
    data["RATE_1"] = data.get("RATE_DUE", "")

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

    docx_file = Path(docx_path).resolve()
    docx_file.parent.mkdir(parents=True, exist_ok=True)

    engine = TemplateEngine()
    engine.render(
        str(template_file),
        str(docx_file),
        data
    )

    if not docx_file.is_file():
        raise RuntimeError(
            f"Word document was not created: {docx_file}"
        )

    return str(docx_file)


def generate_notice_pdf(
    property_record,
    template_path=None,
    template_name="template.docx"
):
    """Generate one PDF and archive it in Google Drive."""

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    data = prepare_row(property_record)

    assessment_no = str(
        data.get("PROPERTY_NO")
        or data.get("ASSESSMENT_NO")
        or "notice"
    )

    safe_name = (
        assessment_no
        .replace("/", "_")
        .replace("\\", "_")
        .strip()
        or "notice"
    )

    docx_file = OUTPUT_FOLDER / f"{safe_name}.docx"
    pdf_file = OUTPUT_FOLDER / f"{safe_name}.pdf"

    render_notice_docx(
        property_record=property_record,
        docx_path=docx_file,
        template_path=template_path,
        template_name=template_name,
    )

    with WordConverter() as word:
        ok, msg = word.convert(
            str(docx_file),
            str(pdf_file)
        )

    if not ok:
        raise RuntimeError(msg)

    if not pdf_file.is_file():
        raise RuntimeError(
            f"PDF file was not created: {pdf_file}"
        )

    print(f"PDF generated successfully: {pdf_file}")

    # Archive the completed PDF.
    # Google Drive failure must not interrupt bill generation.
    try:
        archive_pdfs_to_drive(
            [pdf_file],
            context=f"individual bill {safe_name}"
        )
    except Exception as exc:
        print(
            f"[Google Drive] Archive error for "
            f"{safe_name}: {exc}"
        )

    return str(pdf_file)
