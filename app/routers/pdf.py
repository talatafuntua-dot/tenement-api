from pathlib import Path
import zipfile
import shutil

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.pdf_generator import generate_notice_pdfs_from_excel


router = APIRouter()

# ---------------------------------------------------------
# BASE DIRECTORIES
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]

OUTPUT_FOLDER = BASE_DIR / "output_pdfs"
UPLOAD_FOLDER = BASE_DIR / "excel_uploads"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# DOWNLOAD PDF
# ---------------------------------------------------------

@router.get("/download/{filename}")
def download_pdf(filename: str):
    print("=== PDF DOWNLOAD DEBUG ===")

    # Prevent path traversal
    safe_filename = Path(filename).name
    file_path = OUTPUT_FOLDER / safe_filename

    print("BASE_DIR:", BASE_DIR)
    print("OUTPUT_FOLDER:", OUTPUT_FOLDER)
    print("REQUESTED:", filename)
    print("SAFE FILENAME:", safe_filename)
    print("LOOKING FOR:", file_path)
    print("FILE EXISTS:", file_path.is_file())

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    # ZIP files need their own download handling
    if file_path.suffix.lower() == ".zip":
        return FileResponse(
            path=str(file_path),
            media_type="application/zip",
            filename=safe_filename
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=safe_filename
    )


# ---------------------------------------------------------
# PRINT PDF
# ---------------------------------------------------------

@router.get("/print/{filename}")
def print_pdf(filename: str):
    safe_filename = Path(filename).name
    file_path = OUTPUT_FOLDER / safe_filename

    print("=== PDF PRINT DEBUG ===")
    print("REQUESTED:", filename)
    print("SAFE FILENAME:", safe_filename)
    print("LOOKING FOR:", file_path)
    print("FILE EXISTS:", file_path.is_file())

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    # Printing is only for PDF files
    if file_path.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files can be printed."
        )

    file_handle = open(file_path, "rb")

    return StreamingResponse(
        file_handle,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"',
            "Cache-Control": "no-store"
        }
    )


# ---------------------------------------------------------
# DOWNLOAD BATCH ZIP
# ---------------------------------------------------------

@router.get("/download-batch/{filename}")
def download_batch(filename: str):
    safe_filename = Path(filename).name
    file_path = OUTPUT_FOLDER / safe_filename

    print("=== BATCH DOWNLOAD DEBUG ===")
    print("REQUESTED:", filename)
    print("LOOKING FOR:", file_path)
    print("FILE EXISTS:", file_path.is_file())

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Batch ZIP file not found"
        )

    if file_path.suffix.lower() != ".zip":
        raise HTTPException(
            status_code=400,
            detail="The requested file is not a ZIP file."
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/zip",
        filename=safe_filename
    )


# ---------------------------------------------------------
# EXCEL → PDF GENERATION
# ---------------------------------------------------------

@router.post("/generate-from-excel")
async def generate_from_excel(
    file: UploadFile = File(...),
    template_name: str = Form("template.docx")
):
    """
    Upload an Excel file and generate one PDF for each row.

    Excel does NOT need to be imported into Neon.

    The Excel columns are read directly and passed to the
    existing Word template/PDF generation system.
    """

    # -----------------------------------------------------
    # CHECK EXCEL FILE
    # -----------------------------------------------------

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No Excel file was supplied."
        )

    original_name = Path(file.filename).name
    extension = Path(original_name).suffix.lower()

    if extension not in (".xlsx", ".xlsm"):
        raise HTTPException(
            status_code=400,
            detail="Please upload an Excel .xlsx or .xlsm file."
        )

    # -----------------------------------------------------
    # CHECK TEMPLATE
    # -----------------------------------------------------

    safe_template_name = Path(template_name).name

    if not safe_template_name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="The template must be a .docx Word file."
        )

    template_path = BASE_DIR / "templates" / safe_template_name

    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Word template not found: {safe_template_name}"
        )

    # -----------------------------------------------------
    # SAVE UPLOADED EXCEL TEMPORARILY
    # -----------------------------------------------------

    excel_path = UPLOAD_FOLDER / original_name

    try:
        with open(excel_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print("=== EXCEL PDF GENERATION ===")
        print("Excel file:", excel_path)
        print("Template:", template_path)

        # -------------------------------------------------
        # GENERATE PDF FILES
        # -------------------------------------------------

        result = generate_notice_pdfs_from_excel(
            excel_path=str(excel_path),
            template_path=str(template_path)
        )

        generated_files = result.get("generated", [])
        failed_files = result.get("failed", [])
        skipped_files = result.get("skipped", [])

        # -------------------------------------------------
        # NOTHING GENERATED
        # -------------------------------------------------

        if not generated_files:
            return {
                "success": False,
                "message": "No PDF files were generated.",
                "generated": [],
                "failed": failed_files,
                "skipped": skipped_files
            }

        # -------------------------------------------------
        # ONE PDF
        # -------------------------------------------------

        if len(generated_files) == 1:

            pdf_path = Path(generated_files[0])

            if not pdf_path.is_file():
                raise HTTPException(
                    status_code=500,
                    detail="PDF was reported as generated but the file was not found."
                )

            filename = pdf_path.name

            return {
                "success": True,
                "mode": "single",
                "message": "PDF generated successfully.",
                "filename": filename,
                "generated_count": 1,
                "failed_count": len(failed_files),
                "skipped_count": len(skipped_files),
                "download_url": f"/pdf/download/{filename}",
                "print_url": f"/pdf/print/{filename}",
                "generated": [filename],
                "failed": failed_files,
                "skipped": skipped_files
            }

        # -------------------------------------------------
        # MULTIPLE PDFs → ZIP
        # -------------------------------------------------

        zip_name = "tenement_rate_batch.zip"
        zip_path = OUTPUT_FOLDER / zip_name

        # Remove an old ZIP if it exists
        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(
            zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED
        ) as zip_file:

            for pdf_file in generated_files:

                pdf_path = Path(pdf_file)

                if pdf_path.is_file():
                    zip_file.write(
                        pdf_path,
                        arcname=pdf_path.name
                    )

        if not zip_path.is_file():
            raise HTTPException(
                status_code=500,
                detail="PDF batch was generated but ZIP file could not be created."
            )

        return {
            "success": True,
            "mode": "batch",
            "message": f"{len(generated_files)} PDF files generated successfully.",
            "filename": zip_name,
            "generated_count": len(generated_files),
            "failed_count": len(failed_files),
            "skipped_count": len(skipped_files),
            "download_url": f"/pdf/download-batch/{zip_name}",
            "generated": [
                Path(item).name
                for item in generated_files
            ],
            "failed": failed_files,
            "skipped": skipped_files
        }

    except HTTPException:
        raise

    except Exception as ex:
        print("=== EXCEL PDF GENERATION ERROR ===")
        print(str(ex))

        raise HTTPException(
            status_code=500,
            detail=f"Excel PDF generation failed: {str(ex)}"
        )

    finally:
        # -------------------------------------------------
        # DELETE TEMPORARY EXCEL
        # -------------------------------------------------

        try:
            if excel_path.exists():
                excel_path.unlink()
                print("Temporary Excel deleted:", excel_path)
        except Exception as cleanup_error:
            print(
                "Could not delete temporary Excel:",
                cleanup_error
            )

        try:
            await file.close()
        except Exception:
            pass
