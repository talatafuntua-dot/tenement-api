from pathlib import Path
import zipfile
import tempfile
import shutil

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
)

from fastapi.responses import (
    FileResponse,
    StreamingResponse,
)

from app.pdf_generator import (
    generate_notice_pdfs_from_excel,
)


router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]

OUTPUT_FOLDER = BASE_DIR / "output_pdfs"

UPLOAD_FOLDER = BASE_DIR / "excel_uploads"


# =====================================================
# DIRECTORIES
# =====================================================

OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


# =====================================================
# DOWNLOAD PDF
# =====================================================

@router.get("/download/{filename}")
def download_pdf(filename: str):

    print("=== PDF DOWNLOAD DEBUG ===")

    print(
        "BASE_DIR:",
        BASE_DIR
    )

    print(
        "OUTPUT_FOLDER:",
        OUTPUT_FOLDER
    )

    print(
        "FOLDER EXISTS:",
        OUTPUT_FOLDER.exists()
    )

    print(
        "FILES:",
        list(OUTPUT_FOLDER.iterdir())
        if OUTPUT_FOLDER.exists()
        else []
    )

    file_path = OUTPUT_FOLDER / filename

    print(
        "REQUESTED:",
        filename
    )

    print(
        "LOOKING FOR:",
        file_path
    )

    print(
        "FILE EXISTS:",
        file_path.is_file()
    )

    if not file_path.is_file():

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename
    )


# =====================================================
# PRINT / VIEW PDF INLINE
# =====================================================

@router.get("/print/{filename}")
def print_pdf(filename: str):

    file_path = OUTPUT_FOLDER / filename

    print("=== PDF PRINT DEBUG ===")

    print(
        "REQUESTED:",
        filename
    )

    print(
        "LOOKING FOR:",
        file_path
    )

    print(
        "FILE EXISTS:",
        file_path.is_file()
    )

    if not file_path.is_file():

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    file_handle = open(
        file_path,
        "rb"
    )

    return StreamingResponse(
        file_handle,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="{filename}"',

            "Cache-Control":
                "no-store"
        }
    )


# =====================================================
# EXCEL → PDF BATCH GENERATION
# =====================================================

@router.post("/generate-from-excel")
async def generate_from_excel(
    file: UploadFile = File(...),
    template_name: str = Form(
        "template.docx"
    )
):

    print(
        "=========================================="
    )

    print(
        "EXCEL PDF GENERATION REQUEST"
    )

    print(
        "Excel filename:",
        file.filename
    )

    print(
        "Template:",
        template_name
    )

    print(
        "=========================================="
    )

    # =================================================
    # VALIDATE EXCEL FILE
    # =================================================

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="No Excel file was supplied."
        )

    extension = (
        Path(file.filename)
        .suffix
        .lower()
    )

    if extension not in (
        ".xlsx",
        ".xlsm"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Only Excel .xlsx or .xlsm "
                "files are supported."
            )
        )

    # =================================================
    # VALIDATE TEMPLATE
    # =================================================

    template_file = (
        BASE_DIR /
        "templates" /
        Path(template_name).name
    )

    if not template_file.exists():

        raise HTTPException(
            status_code=404,
            detail=(
                f"Template not found: "
                f"{template_file.name}"
            )
        )

    # =================================================
    # SAVE UPLOADED EXCEL
    # =================================================

    temporary_excel = (
        UPLOAD_FOLDER /
        file.filename
    )

    try:

        with open(
            temporary_excel,
            "wb"
        ) as output_file:

            shutil.copyfileobj(
                file.file,
                output_file
            )

        print(
            "Excel saved:",
            temporary_excel
        )

        # =============================================
        # GENERATE PDFs
        # =============================================

        result = generate_notice_pdfs_from_excel(
            excel_path=str(
                temporary_excel
            ),
            template_path=str(
                template_file
            )
        )

        # =============================================
        # COLLECT GENERATED PDFs
        # =============================================

        generated_files = []

        for item in result.get(
            "generated",
            []
        ):

            pdf_path = item.get(
                "pdf"
            )

            if not pdf_path:
                continue

            pdf_file = Path(
                pdf_path
            )

            if pdf_file.is_file():

                generated_files.append(
                    pdf_file
                )

        # =============================================
        # NOTHING GENERATED
        # =============================================

        if not generated_files:

            return {
                "success": False,
                "message": (
                    "No PDFs were generated."
                ),
                "result": result
            }

        # =============================================
        # ONE PDF
        # =============================================

        if len(generated_files) == 1:

            pdf_file = generated_files[0]

            return {
                "success": True,
                "type": "single_pdf",
                "filename": pdf_file.name,
                "download_url":
                    f"/pdf/download/{pdf_file.name}",
                "print_url":
                    f"/pdf/print/{pdf_file.name}",
                "result": result
            }

        # =============================================
        # MULTIPLE PDFs
        # =============================================

        zip_name = (
            "tenement_rate_batch.zip"
        )

        zip_path = (
            OUTPUT_FOLDER /
            zip_name
        )

        if zip_path.exists():

            zip_path.unlink()

        # =============================================
        # CREATE ZIP
        # =============================================

        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as archive:

            for pdf_file in generated_files:

                archive.write(
                    pdf_file,
                    arcname=pdf_file.name
                )

        print(
            "ZIP created:",
            zip_path
        )

        # =============================================
        # RESPONSE
        # =============================================

        return {
            "success": True,

            "type": "batch",

            "total_records":
                result.get(
                    "total_records",
                    0
                ),

            "generated_count":
                result.get(
                    "generated_count",
                    0
                ),

            "failed_count":
                result.get(
                    "failed_count",
                    0
                ),

            "skipped_count":
                result.get(
                    "skipped_count",
                    0
                ),

            "zip_filename":
                zip_path.name,

            "download_url":
                f"/pdf/download/{zip_path.name}",

            "generated_files": [
                pdf.name
                for pdf in generated_files
            ],

            "result": result
        }

    except HTTPException:

        raise

    except Exception as exc:

        print(
            "EXCEL PDF GENERATION ERROR:",
            exc
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc)
        )

    finally:

        # =============================================
        # DELETE TEMPORARY EXCEL
        # =============================================

        try:

            if temporary_excel.exists():

                temporary_excel.unlink()

        except Exception as cleanup_error:

            print(
                "WARNING: Could not delete "
                "temporary Excel file:",
                cleanup_error
            )


# =====================================================
# DOWNLOAD BATCH ZIP
# =====================================================

@router.get("/download-batch/{filename}")
def download_batch(filename: str):

    file_path = (
        OUTPUT_FOLDER /
        filename
    )

    if not file_path.is_file():

        raise HTTPException(
            status_code=404,
            detail="Batch file not found"
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/zip",
        filename=filename
    )
