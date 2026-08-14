from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_FOLDER = BASE_DIR / "output_pdfs"


@router.get("/download/{filename}")
def download_pdf(filename: str):

    print("=== PDF DOWNLOAD DEBUG ===")
    print("BASE_DIR:", BASE_DIR)
    print("OUTPUT_FOLDER:", OUTPUT_FOLDER)
    print("FOLDER EXISTS:", OUTPUT_FOLDER.exists())
    print("FILES:", list(OUTPUT_FOLDER.iterdir()) if OUTPUT_FOLDER.exists() else [])

    file_path = OUTPUT_FOLDER / filename

    print("REQUESTED:", filename)
    print("LOOKING FOR:", file_path)
    print("FILE EXISTS:", file_path.is_file())

    if not file_path.is_file():
        return {"error": "File not found"}

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename
    )
