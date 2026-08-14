from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter()

# Project root
BASE_DIR = Path(__file__).resolve().parents[2]

# Same folder used by pdf_generator.py
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


@router.get("/download/{filename}")
def download_pdf(filename: str):

    file_path = OUTPUT_FOLDER / filename

    if not file_path.is_file():
        return {"error": "File not found"}

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename
    )
