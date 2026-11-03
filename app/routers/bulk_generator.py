
import re
import shutil
import tempfile
import time
import zipfileimport re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.database import get_db
from app.pdf_generator import generate_notice_pdf
from app.models import NoticeTemplate
from app.lg_code_allocator import allocate_bulk_lg_code


router = APIRouter(
    prefix="/bulk-bills",
    tags=["Bulk Bill Generation"],
)

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output_pdfs"
BATCH_DIR = OUTPUT_DIR / "bulk_batches"


def safe_name(value, fallback):
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value[:100] or fallback


@router.post("/generate")
async def generate_bulk_bills(
    excel_file: UploadFile = File(...),
    template_id: int = Form(...),
    output_format: Literal["individual", "merged", "both"] = Form(
        "individual"
    ),
    db: Session = Depends(get_db),
):
    if not excel_file.filename or not excel_file.filename.lower().endswith(
        (".xlsx", ".xls")
    ):
        raise HTTPException(
            status_code=400,
            detail="Upload an Excel workbook (.xlsx or .xls).",
        )

    # Retrieve the selected template from the database.
    template = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.id == template_id)
        .first()
    )

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Template not found.",
        )

    # Use the original template path handling.
    template_path = Path(template.file_path)

    # Diagnostic information for Render logs.
    print("========== BULK TEMPLATE CHECK ==========")
    print(f"Submitted template ID: {template_id}")
    print(f"Database template ID: {template.id}")
    print(
        f"Database template name: "
        f"{getattr(template, 'name', 'N/A')}"
    )
    print(f"Database file path: {template.file_path}")
    print(f"Resolved template path: {template_path.resolve()}")
    print(f"File exists: {template_path.is_file()}")
    print("=========================================")

    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The selected Word template file could not be found.",
        )

    try:
        contents = await excel_file.read()

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="The Excel file is empty.",
            )

        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            workbook_path = temp_dir / Path(excel_file.filename).name
            workbook_path.write_bytes(contents)

            try:
                dataframe = pd.read_excel(workbook_path)
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to read Excel workbook: {exc}",
                ) from exc

            if dataframe.empty:
                raise HTTPException(
                    status_code=400,
                    detail="The Excel workbook contains no data rows.",
                )

            # Normalize headings for the existing bill renderer.
            dataframe.columns = [
                str(column).strip().replace(" ", "_").upper()
                for column in dataframe.columns
            ]

            if "PROPERTY_NO" not in dataframe.columns:
                if "ASSESSMENT_NO" in dataframe.columns:
                    dataframe["PROPERTY_NO"] = dataframe["ASSESSMENT_NO"]
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "The workbook needs a PROPERTY_NO "
                            "or ASSESSMENT_NO column."
                        ),
                    )

            batch_name = next(tempfile._get_candidate_names())
            batch_dir = BATCH_DIR / batch_name
            batch_dir.mkdir(parents=True, exist_ok=True)

            individual_files = []
            errors = []

            try:
                # Ensure the workbook has an LG_CODE column.
                if "LG_CODE" not in dataframe.columns:
                    dataframe["LG_CODE"] = None

                seen_codes = set()

                # Generate each property's bill separately.
                for index, row in dataframe.iterrows():
                    record = row.where(pd.notna(row), None).to_dict()

                    property_number = str(
                        record.get("PROPERTY_NO")
                        or record.get("ASSESSMENT_NO")
                        or f"row_{index + 2}"
                    ).strip()

                    try:
                        prefix = record.get("PREFIX") or "LG"

                        existing_code = str(
                            record.get("LG_CODE") or ""
                        ).strip()

                        if existing_code:
                            lg_code = existing_code
                        else:
                            # Allocate directly from Excel.
                            # No Property lookup in Neon.
                            lg_code = allocate_bulk_lg_code(
                                db,
                                prefix=prefix,
                                property_identifier=property_number,
                            )

                            # Save the new code into the workbook.
                            dataframe.at[index, "LG_CODE"] = lg_code

                        if lg_code in seen_codes:
                            raise ValueError(
                                f"Duplicate LG Code in workbook: {lg_code}"
                            )

                        seen_codes.add(lg_code)

                        record["LG_CODE"] = lg_code
                        record["PROPERTY_NO"] = property_number

                        generated_path = Path(
                            generate_notice_pdf(
                                property_record=record,
                                template_path=template_path,
                            )
                        )

                        if not generated_path.is_file():
                            raise RuntimeError("The PDF was not created.")

                        filename = (
                            f"{index + 1:04d}_"
                            f"{safe_name(property_number, 'bill')}.pdf"
                        )

                        saved_path = batch_dir / filename
                        shutil.copy2(generated_path, saved_path)
                        individual_files.append(saved_path)

                    except Exception as exc:
                        db.rollback()

                        errors.append(
                            {
                                "row": int(index) + 2,
                                "property": property_number,
                                "error": str(exc),
                            }
                        )

                # Save the updated Excel workbook.
                updated_workbook_path = (
                    batch_dir / "bulk_generation_with_lg_codes.xlsx"
                )

                dataframe.to_excel(
                    updated_workbook_path,
                    index=False,
                )

                # Merge all successfully generated PDFs when requested.
                merged_path = batch_dir / "merged_bills.pdf"

                if output_format in ("merged", "both") and individual_files:
                    writer = PdfWriter()

                    try:
                        for pdf_path in individual_files:
                            writer.append(str(pdf_path))

                        with merged_path.open("wb") as output:
                            writer.write(output)
                    finally:
                        writer.close()

                # Package the requested output into a ZIP file.
                archive_path = (
                    BATCH_DIR / f"bulk_bills_{batch_name}.zip"
                )

                with zipfile.ZipFile(
                    archive_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:

                    if output_format in ("individual", "both"):
                        for pdf_path in individual_files:
                            archive.write(
                                pdf_path,
                                arcname=f"individual/{pdf_path.name}",
                            )

                    if (
                        output_format in ("merged", "both")
                        and merged_path.is_file()
                    ):
                        archive.write(
                            merged_path,
                            arcname="merged_bills.pdf",
                        )

                    # Include the Excel workbook containing LG Codes.
                    if updated_workbook_path.exists():
                        archive.write(
                            updated_workbook_path,
                            arcname="bulk_generation_with_lg_codes.xlsx",
                        )

                    if errors:
                        error_text = "\n".join(
                            f"Excel row {item['row']} "
                            f"({item['property']}): {item['error']}"
                            for item in errors
                        )

                        archive.writestr(
                            "generation_errors.txt",
                            error_text,
                        )

                return FileResponse(
                    path=str(archive_path),
                    media_type="application/zip",
                    filename=archive_path.name,
                )

            except HTTPException:
                raise

            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Bulk generation failed: {exc}",
                ) from exc

    finally:
        await excel_file.close()
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.database import get_db
from app.pdf_generator import generate_notice_pdf
from app.models import NoticeTemplate
from app.lg_code_allocator import allocate_bulk_lg_code


router = APIRouter(
    prefix="/bulk-bills",
    tags=["Bulk Bill Generation"],
)


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output_pdfs"
BATCH_DIR = OUTPUT_DIR / "bulk_batches"


def safe_name(value, fallback):
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value[:100] or fallback


def elapsed_ms(start_time):
    return round((time.perf_counter() - start_time) * 1000, 2)


@router.post("/generate")
async def generate_bulk_bills(
    excel_file: UploadFile = File(...),
    template_id: int = Form(...),
    output_format: Literal["individual", "merged", "both"] = Form(
        "individual"
    ),
    db: Session = Depends(get_db),
):

    bulk_start = time.perf_counter()

    timings = {
        "excel_upload_read_ms": 0,
        "template_lookup_ms": 0,
        "excel_read_ms": 0,
        "column_normalization_ms": 0,
        "row_preparation_ms": 0,
        "lg_code_allocation_ms": 0,
        "pdf_generation_ms": 0,
        "pdf_copy_ms": 0,
        "excel_export_ms": 0,
        "pdf_merge_ms": 0,
        "zip_creation_ms": 0,
    }

    rows_attempted = 0
    successful_bills = 0
    failed_bills = 0

    if not excel_file.filename or not excel_file.filename.lower().endswith(
        (".xlsx", ".xls")
    ):
        raise HTTPException(
            status_code=400,
            detail="Upload an Excel workbook (.xlsx or .xls).",
        )

    # ---------------------------------------------------
    # 1. RETRIEVE SELECTED TEMPLATE
    # ---------------------------------------------------

    stage_start = time.perf_counter()

    template = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.id == template_id)
        .first()
    )

    timings["template_lookup_ms"] = elapsed_ms(stage_start)

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Template not found.",
        )

    template_path = Path(template.file_path)

    print("========== BULK TEMPLATE CHECK ==========")
    print(f"Submitted template ID: {template_id}")
    print(f"Database template ID: {template.id}")
    print(
        f"Database template name: "
        f"{getattr(template, 'name', 'N/A')}"
    )
    print(f"Database file path: {template.file_path}")
    print(f"Resolved template path: {template_path.resolve()}")
    print(f"File exists: {template_path.is_file()}")
    print("=========================================")

    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The selected Word template file could not be found.",
        )

    try:

        # ---------------------------------------------------
        # 2. READ UPLOADED EXCEL FILE
        # ---------------------------------------------------

        stage_start = time.perf_counter()

        contents = await excel_file.read()

        timings["excel_upload_read_ms"] = elapsed_ms(stage_start)

        if not contents:
            raise HTTPException(
                status_code=400,
                detail="The Excel file is empty.",
            )

        with tempfile.TemporaryDirectory() as temporary:

            temp_dir = Path(temporary)
            workbook_path = temp_dir / Path(excel_file.filename).name
            workbook_path.write_bytes(contents)

            # ---------------------------------------------------
            # 3. READ EXCEL WORKBOOK
            # ---------------------------------------------------

            stage_start = time.perf_counter()

            try:
                dataframe = pd.read_excel(workbook_path)

            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to read Excel workbook: {exc}",
                ) from exc

            timings["excel_read_ms"] = elapsed_ms(stage_start)

            if dataframe.empty:
                raise HTTPException(
                    status_code=400,
                    detail="The Excel workbook contains no data rows.",
                )

            total_rows = len(dataframe)

            print(f"Bulk rows found: {total_rows}")

            # ---------------------------------------------------
            # 4. NORMALIZE EXCEL COLUMN HEADINGS
            # ---------------------------------------------------

            stage_start = time.perf_counter()

            dataframe.columns = [
                str(column).strip().replace(" ", "_").upper()
                for column in dataframe.columns
            ]

            if "PROPERTY_NO" not in dataframe.columns:

                if "ASSESSMENT_NO" in dataframe.columns:
                    dataframe["PROPERTY_NO"] = dataframe["ASSESSMENT_NO"]

                else:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "The workbook needs a PROPERTY_NO "
                            "or ASSESSMENT_NO column."
                        ),
                    )

            timings["column_normalization_ms"] = elapsed_ms(stage_start)

            # ---------------------------------------------------
            # 5. CREATE BATCH DIRECTORY
            # ---------------------------------------------------

            batch_name = next(tempfile._get_candidate_names())

            batch_dir = BATCH_DIR / batch_name
            batch_dir.mkdir(parents=True, exist_ok=True)

            individual_files = []
            errors = []

            try:

                # ---------------------------------------------------
                # 6. PREPARE LG CODE COLUMN
                # ---------------------------------------------------

                if "LG_CODE" not in dataframe.columns:
                    dataframe["LG_CODE"] = None

                # LG Codes are text, not numbers.
                # Prevent Pandas float64 assignment errors.
                dataframe["LG_CODE"] = dataframe["LG_CODE"].astype("object")

                seen_codes = set()

                # ---------------------------------------------------
                # 7. GENERATE EACH PROPERTY BILL
                # ---------------------------------------------------

                for index, row in dataframe.iterrows():

                    rows_attempted += 1

                    stage_start = time.perf_counter()

                    record = row.where(pd.notna(row), None).to_dict()

                    property_number = str(
                        record.get("PROPERTY_NO")
                        or record.get("ASSESSMENT_NO")
                        or f"row_{index + 2}"
                    ).strip()

                    timings["row_preparation_ms"] += elapsed_ms(stage_start)

                    try:

                        prefix = record.get("PREFIX") or "LG"

                        existing_code = str(
                            record.get("LG_CODE") or ""
                        ).strip()

                        if existing_code:

                            lg_code = existing_code

                        else:

                            # Allocate directly from Excel.
                            # No Property lookup in Neon.

                            stage_start = time.perf_counter()

                            lg_code = allocate_bulk_lg_code(
                                db,
                                prefix=prefix,
                                property_identifier=property_number,
                            )

                            timings["lg_code_allocation_ms"] += elapsed_ms(
                                stage_start
                            )

                            dataframe.at[index, "LG_CODE"] = lg_code

                        if lg_code in seen_codes:
                            raise ValueError(
                                f"Duplicate LG Code in workbook: {lg_code}"
                            )

                        seen_codes.add(lg_code)

                        record["LG_CODE"] = lg_code
                        record["PROPERTY_NO"] = property_number

                        # Generate PDF.

                        stage_start = time.perf_counter()

                        generated_path = Path(
                            generate_notice_pdf(
                                property_record=record,
                                template_path=template_path,
                            )
                        )

                        timings["pdf_generation_ms"] += elapsed_ms(
                            stage_start
                        )

                        if not generated_path.is_file():
                            raise RuntimeError("The PDF was not created.")

                        # Copy PDF into batch directory.

                        filename = (
                            f"{index + 1:04d}_"
                            f"{safe_name(property_number, 'bill')}.pdf"
                        )

                        saved_path = batch_dir / filename

                        stage_start = time.perf_counter()

                        shutil.copy2(generated_path, saved_path)

                        timings["pdf_copy_ms"] += elapsed_ms(stage_start)

                        individual_files.append(saved_path)

                        successful_bills += 1

                    except Exception as exc:

                        db.rollback()

                        failed_bills += 1

                        errors.append(
                            {
                                "row": int(index) + 2,
                                "property": property_number,
                                "error": str(exc),
                            }
                        )

                # ---------------------------------------------------
                # 8. EXPORT UPDATED EXCEL WORKBOOK
                # ---------------------------------------------------

                updated_workbook_path = (
                    batch_dir / "bulk_generation_with_lg_codes.xlsx"
                )

                stage_start = time.perf_counter()

                dataframe.to_excel(
                    updated_workbook_path,
                    index=False,
                )

                timings["excel_export_ms"] = elapsed_ms(stage_start)

                # ---------------------------------------------------
                # 9. MERGE PDF FILES IF REQUESTED
                # ---------------------------------------------------

                merged_path = batch_dir / "merged_bills.pdf"

                if output_format in ("merged", "both") and individual_files:

                    stage_start = time.perf_counter()

                    writer = PdfWriter()

                    try:

                        for pdf_path in individual_files:
                            writer.append(str(pdf_path))

                        with merged_path.open("wb") as output:
                            writer.write(output)

                    finally:
                        writer.close()

                    timings["pdf_merge_ms"] = elapsed_ms(stage_start)

                # ---------------------------------------------------
                # 10. CREATE ZIP ARCHIVE
                # ---------------------------------------------------

                archive_path = (
                    BATCH_DIR / f"bulk_bills_{batch_name}.zip"
                )

                stage_start = time.perf_counter()

                with zipfile.ZipFile(
                    archive_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:

                    if output_format in ("individual", "both"):

                        for pdf_path in individual_files:

                            archive.write(
                                pdf_path,
                                arcname=f"individual/{pdf_path.name}",
                            )

                    if (
                        output_format in ("merged", "both")
                        and merged_path.is_file()
                    ):

                        archive.write(
                            merged_path,
                            arcname="merged_bills.pdf",
                        )

                    # Include Excel workbook containing LG Codes.

                    if updated_workbook_path.exists():

                        archive.write(
                            updated_workbook_path,
                            arcname="bulk_generation_with_lg_codes.xlsx",
                        )

                    if errors:

                        error_text = "\n".join(
                            f"Excel row {item['row']} "
                            f"({item['property']}): {item['error']}"
                            for item in errors
                        )

                        archive.writestr(
                            "generation_errors.txt",
                            error_text,
                        )

                timings["zip_creation_ms"] = elapsed_ms(stage_start)

                # ---------------------------------------------------
                # 11. PRINT COMPLETE PERFORMANCE REPORT
                # ---------------------------------------------------

                timings["total_bulk_request_ms"] = elapsed_ms(bulk_start)

                print("")
                print("========== COMPLETE BULK PERFORMANCE PROFILE ==========")
                print(f"Output format: {output_format}")
                print(f"Total Excel rows: {total_rows}")
                print(f"Rows attempted: {rows_attempted}")
                print(f"Successful bills: {successful_bills}")
                print(f"Failed bills: {failed_bills}")

                for stage, duration in timings.items():
                    print(f"{stage}: {duration} ms")

                if successful_bills:

                    average_pdf_time = (
                        timings["pdf_generation_ms"] / successful_bills
                    )

                    print(
                        f"average_pdf_generation_per_bill_ms: "
                        f"{round(average_pdf_time, 2)} ms"
                    )

                print("=========================================================")
                print("")

                # ---------------------------------------------------
                # 12. RETURN ZIP DOWNLOAD
                # ---------------------------------------------------

                return FileResponse(
                    path=str(archive_path),
                    media_type="application/zip",
                    filename=archive_path.name,
                )

            except HTTPException:
                raise

            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Bulk generation failed: {exc}",
                ) from exc

    finally:
        await excel_file.close()
