from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

OUTPUT_FOLDER = Path(__file__).resolve().parent.parent / "output_pdfs"


@router.get("/download/{filename}")
def download_pdf(filename: str):

    file_path = OUTPUT_FOLDER / filename

    if not file_path.exists():
        return {"error": "File not found"}

    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        filename=filename
    )
