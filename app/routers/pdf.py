```python
# -*- coding: utf-8 -*-

import shutil
import tempfile
import uuid
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse

from app.pdf_generator import (
    OUTPUT_FOLDER,
    TEMPLATES_FOLDER,
    generate_notice_pdfs_from_excel,
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/pdf",
    tags=["PDF"]
)


# ============================================================
# DIRECTORIES
# ============================================================

UPLOAD_FOLDER = OUTPUT_FOLDER / "_uploads"

OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# SAFE FILE NAME
# ============================================================

def safe_filename(filename):
    """
    Prevent path traversal and unsafe filenames.
    """

    if not filename:
        return "file"

    return Path(filename).name


# ============================================================
# DOWNLOAD SINGLE PDF / ZIP
# ============================================================

@router.get("/download/{filename}")
def download_file(filename: str):

    filename = safe_filename(filename)

    file_path = OUTPUT_FOLDER / filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="File not found."
        )

    return FileResponse(
        path=str(file_path),
        filename=filename,
    )


# ============================================================
# PRINT / VIEW PDF
# ============================================================

@router.get("/print/{filename}")
def print_pdf(filename: str):

    filename = safe_filename(filename)

    file_path = OUTPUT_FOLDER / filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDF file not found."
        )

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="{filename}"'
            )
        },
    )


# ============================================================
# DOWNLOAD ZIP
# ============================================================

@router.get("/download-batch/{filename}")
def download_batch(filename: str):

    filename = safe_filename(filename)

    file_path = OUTPUT_FOLDER / filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="ZIP file not found."
        )

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/zip",
    )


# ============================================================
# EXCEL → PDF
# ============================================================

@router.post("/generate-from-excel")
async def generate_from_excel(
    file: UploadFile = File(...),

    template_name: str = Form(
        "template.docx"
    ),

    output_mode: str = Form(
        "zip"
    ),
):
    """
    Generate PDFs directly from an uploaded Excel file.

    output_mode:

        individual
            Generate separate PDFs.

        zip
            Generate separate PDFs and place them
            into one ZIP file.

        merged
            Generate separate PDFs first, then merge
            them into one PDF.
    """

    # ========================================================
    # VALIDATE OUTPUT MODE
    # ========================================================

    output_mode = str(
        output_mode or "zip"
    ).strip().lower()

    allowed_modes = {
        "individual",
        "zip",
        "merged",
    }

    if output_mode not in allowed_modes:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid output_mode. "
                "Use: individual, zip, or merged."
            ),
        )

    # ========================================================
    # VALIDATE EXCEL FILE
    # ========================================================

    original_filename = (
        file.filename or ""
    )

    extension = Path(
        original_filename
    ).suffix.lower()

    if extension not in {
        ".xlsx",
        ".xlsm",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please upload an Excel "
                ".xlsx or .xlsm file."
            ),
        )

    # ========================================================
    # VALIDATE WORD TEMPLATE
    # ========================================================

    template_name = safe_filename(
        template_name
    )

    if not template_name.lower().endswith(
        ".docx"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The template must be a "
                ".docx file."
            ),
        )

    template_path = (
        TEMPLATES_FOLDER /
        template_name
    )

    if not template_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Word template not found: "
                f"{template_name}"
            ),
        )

    # ========================================================
    # CREATE UNIQUE BATCH FOLDER
    # ========================================================

    batch_id = uuid.uuid4().hex[:12]

    original_stem = Path(
        original_filename
    ).stem

    original_stem = (
        safe_filename(original_stem)
    )

    batch_folder_name = (
        f"{original_stem}_{batch_id}"
    )

    batch_folder = (
        OUTPUT_FOLDER /
        batch_folder_name
    )

    batch_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # TEMPORARY EXCEL FILE
    # ========================================================

    temporary_excel = None

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=extension,
            dir=str(UPLOAD_FOLDER),
        ) as temp_file:

            temporary_excel = Path(
                temp_file.name
            )

            while True:

                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                temp_file.write(chunk)

        # ====================================================
        # GENERATE INDIVIDUAL PDF FILES
        # ====================================================

        result = (
            generate_notice_pdfs_from_excel(
                excel_path=str(
                    temporary_excel
                ),
                template_path=str(
                    template_path
                ),
                output_folder=str(
                    batch_folder
                ),
            )
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

        generated_pdf_paths = []

        for item in generated:

            if isinstance(item, dict):

                pdf_value = item.get(
                    "pdf"
                )

            else:

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

        # ====================================================
        # NOTHING GENERATED
        # ====================================================

        if not generated_pdf_paths:

            return {
                "success": False,
                "mode": output_mode,
                "message": (
                    "No PDF files were generated."
                ),
                "total_records": result.get(
                    "total_records",
                    0
                ),
                "generated_count": 0,
                "failed_count": len(
                    failed
                ),
                "skipped_count": len(
                    skipped
                ),
                "generated": generated,
                "failed": failed,
                "skipped": skipped,
            }

        # ====================================================
        # MODE 1 — INDIVIDUAL
        # ====================================================

        if output_mode == "individual":

            files = []

            for pdf_path in (
                generated_pdf_paths
            ):

                files.append({
                    "filename": pdf_path.name,
                    "download_url": (
                        f"/pdf/download/"
                        f"{pdf_path.name}"
                    ),
                    "print_url": (
                        f"/pdf/print/"
                        f"{pdf_path.name}"
                    ),
                })

            # ------------------------------------------------
            # Individual files live i
```
