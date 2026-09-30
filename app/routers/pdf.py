from pathlib import Path
import zipfile
import shutil

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.pdf_generator import generate_notice_pdfs_from_excel


router = APIRouter()


# =========================================================
# DIRECTORIES
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[2]

OUTPUT_FOLDER = BASE_DIR / "output_pdfs"
UPLOAD_FOLDER = BASE_DIR / "excel_uploads"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


# =========================================================
# DOWNLOAD PDF OR ZIP
# =========================================================

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

    # ZIP download
    if file_path.suffix.lower() == ".zip":

        return FileResponse(
            path=str(file_path),
            media_type="application/zip",
            filename=safe_filename
        )

    # PDF download
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=safe_filename
    )


# =========================================================
# PRINT PDF
# =========================================================

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
            "Content-Disposition": (
                f'inline; filename="{safe_filename}"'
            ),
            "Cache-Control": "no-store"
        }
    )


# =========================================================
# DOWNLOAD BATCH ZIP
# =========================================================

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


# =========================================================
# EXCEL → PDF GENERATION
# =========================================================

@router.post("/generate-from-excel")
async def generate_from_excel(
    file: UploadFile = File(...),
    template_name: str = Form("template.docx")
):
    """
    Upload an Excel workbook and generate one PDF
    for each valid Excel record.

    The Excel file is processed directly.

    It does NOT need to be imported into Neon.
    """

    # =====================================================
    # VALIDATE EXCEL FILE
    # =====================================================

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

    # =====================================================
    # VALIDATE WORD TEMPLATE
    # =====================================================

    safe_template_name = Path(template_name).name

    if not safe_template_name.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="The template must be a .docx Word file."
        )

    template_path = (
        BASE_DIR
        / "templates"
        / safe_template_name
    )

    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Word template not found: "
                f"{safe_template_name}"
            )
        )

    # =====================================================
    # SAVE TEMPORARY EXCEL
    # =====================================================

    excel_path = (
        UPLOAD_FOLDER
        / original_name
    )

    try:

        with open(excel_path, "wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

        print("")
        print("==========================================")
        print("EXCEL PDF GENERATION REQUEST")
        print("==========================================")
        print("Excel:", excel_path)
        print("Template:", template_path)
        print("==========================================")

        # =================================================
        # GENERATE PDFs
        # =================================================

        result = generate_notice_pdfs_from_excel(
            excel_path=str(excel_path),
            template_path=str(template_path)
        )

        generated = result.get(
            "generated",
            []
        )

        failed = result.get(
            "failed",
            []
        )

        skipped = result.get(
            "skipped",
            []
        )

        # =================================================
        # NOTHING GENERATED
        # =================================================

        if not generated:

            return {
                "success": False,
                "message": "No PDF files were generated.",
                "total_records": result.get(
                    "total_records",
                    0
                ),
                "generated_count": 0,
                "failed_count": len(failed),
                "skipped_count": len(skipped),
                "generated": [],
                "failed": failed,
                "skipped": skipped
            }

        # =================================================
        # EXTRACT PDF PATHS
        #
        # pdf_generator.py returns:
        #
        # {
        #     "excel_row": ...,
        #     "lg_code": ...,
        #     "property_no": ...,
        #     "owner_name": ...,
        #     "pdf": "/path/to/file.pdf"
        # }
        #
        # =================================================

        generated_pdf_paths = []

        for item in generated:

            if isinstance(item, dict):

                pdf_value = item.get(
                    "pdf"
                )

            else:
                # Safety fallback if an older version
                # returns plain paths
                pdf_value = item

            if not pdf_value:
                continue

            pdf_path = Path(
                str(pdf_value)
            )

            if pdf_path.is_file():
                generated_pdf_paths.append(
                    pdf_path
                )

        # =================================================
        # VERIFY PDF FILES
        # =================================================

        if not generated_pdf_paths:

            raise HTTPException(
                status_code=500,
                detail=(
                    "The generator reported successful "
                    "records, but no PDF files were found."
                )
            )

        # =================================================
        # ONE PDF
        # =================================================

        if len(generated_pdf_paths) == 1:

            pdf_path = generated_pdf_paths[0]

            filename = pdf_path.name

            return {
                "success": True,
                "mode": "single",
                "message": (
                    "PDF generated successfully."
                ),
                "filename": filename,
                "total_records": result.get(
                    "total_records",
                    1
                ),
                "generated_count": len(
                    generated_pdf_paths
                ),
                "failed_count": len(
                    failed
                ),
                "skipped_count": len(
                    skipped
                ),
                "download_url": (
                    f"/pdf/download/{filename}"
                ),
                "print_url": (
                    f"/pdf/print/{filename}"
                ),
                "generated": generated,
                "failed": failed,
                "skipped": skipped
            }

        # =================================================
        # MULTIPLE PDFs → ZIP
        # =================================================

        zip_name = "tenement_rate_batch.zip"

        zip_path = (
            OUTPUT_FOLDER
            / zip_name
        )

        # Remove previous ZIP
        if zip_path.exists():
            zip_path.unlink()

        # =================================================
        # CREATE ZIP
        # =================================================

        with zipfile.ZipFile(
            zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED
        ) as zip_file:

            for pdf_path in generated_pdf_paths:

                zip_file.write(
                    pdf_path,
                    arcname=pdf_path.name
                )

        # =================================================
        # VERIFY ZIP
        # =================================================

        if not zip_path.is_file():

            raise HTTPException(
                status_code=500,
                detail=(
                    "PDF files were generated, "
                    "but the ZIP file could not be created."
                )
            )

        # =================================================
        # SUCCESS
        # =================================================

        return {
            "success": True,
            "mode": "batch",
            "message": (
                f"{len(generated_pdf_paths)} "
                "PDF files generated successfully."
            ),
            "filename": zip_name,
            "total_records": result.get(
                "total_records",
                len(generated_pdf_paths)
            ),
            "generated_count": len(
                generated_pdf_paths
            ),
            "failed_count": len(
                failed
            ),
            "skipped_count": len(
                skipped
            ),
            "download_url": (
                f"/pdf/download-batch/{zip_name}"
            ),
            "generated": generated,
            "failed": failed,
            "skipped": skipped
        }

    except HTTPException:
        raise

    except Exception as ex:

        print("")
        print("==========================================")
        print("EXCEL PDF GENERATION ERROR")
        print("==========================================")
        print(str(ex))
        print("==========================================")

        raise HTTPException(
            status_code=500,
            detail=(
                f"Excel PDF generation failed: {str(ex)}"
            )
        )

    finally:

        # =================================================
        # DELETE TEMPORARY EXCEL
        # =================================================

        try:

            if excel_path.exists():

                excel_path.unlink()

                print(
                    "Temporary Excel deleted:",
                    excel_path
                )

        except Exception as cleanup_error:

            print(
                "Could not delete temporary Excel:",
                cleanup_error
            )

        try:

            await file.close()

        except Exception:

            pass
