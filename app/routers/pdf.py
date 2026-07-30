from fastapi.responses import FileResponse
from fastapi import APIRouter
import os

router = APIRouter()

OUTPUT_FOLDER = r"C:\Users\USER\Downloads\ALL\tenement\tenement\output_pdfs"

@router.get("/download/{filename}")
def download_pdf(filename: str):
    file_path = os.path.join(OUTPUT_FOLDER, filename)

    if not os.path.exists(file_path):
        return {"error": "File not found"}

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename
    )