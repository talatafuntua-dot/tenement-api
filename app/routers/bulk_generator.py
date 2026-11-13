import re
import shutil
import tempfile
import time
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.pdf_generator import render_notice_docx
from app.word_converter import WordConverter
from app.models import NoticeTemplate, BulkGenerationJob
from app.lg_code_allocator import allocate_bulk_lg_code
from app.google_drive_storage import archive_pdfs_to_drive


router = APIRouter(prefix="/bulk-bills", tags=["Bulk Bill Generation"])

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output_pdfs"
BATCH_DIR = OUTPUT_DIR / "bulk_batches"
CONVERSION_BATCH_SIZE = 25


def log_bulk_performance(metrics):
    """Write a consistent performance report to the Render application log."""
    total_seconds = time.perf_counter() - metrics["started_at"]
    submitted = metrics.get("submitted", 0)
    successful = metrics.get("successful", 0)
    failed = metrics.get("failed", 0)

    def duration(seconds):
        seconds = max(0, float(seconds))
        minutes, remaining = divmod(int(seconds), 60)
        return f"{minutes:02d}:{remaining:02d}" if minutes else f"{remaining:02d}s"

    print("========== BULK PERFORMANCE REPORT ==========")
    print(f"Properties submitted: {submitted}")
    print(f"LG Code allocation:   {duration(metrics.get('allocation_seconds', 0))}")
    print(f"DOCX rendering:       {duration(metrics.get('render_seconds', 0))}")
    print(f"PDF conversion:       {duration(metrics.get('conversion_seconds', 0))}")
    print(f"Conversion batches:   {metrics.get('conversion_batches', 0)}")
    print(f"PDF merging:          {duration(metrics.get('merge_seconds', 0))}")
    print(f"Excel updating:       {duration(metrics.get('excel_seconds', 0))}")
    print(f"ZIP packaging:        {duration(metrics.get('zip_seconds', 0))}")
    print("----------------------------------------------")
    print(f"TOTAL TIME:           {duration(total_seconds)}")
    print(f"DOCX documents:       {metrics.get('rendered', 0)}")
    print(f"PDF files created:    {successful}")
    print(f"Failed properties:    {failed}")
    print("==============================================")


def safe_name(value, fallback):
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value[:100] or fallback


def update_original_excel_with_lg_codes(source_bytes, output_path, lg_codes_by_row):
    """Preserve the uploaded XLSX and update only the LG CODE cells."""
    workbook = load_workbook(filename=BytesIO(source_bytes))
    worksheet = workbook[workbook.sheetnames[0]]
    lg_code_column = None

    for cell in worksheet[1]:
        heading = str(cell.value or "").strip().upper().replace(" ", "_")
        if heading in {"LG_CODE", "LGCODE"}:
            lg_code_column = cell.column
            break

    if lg_code_column is None:
        lg_code_column = worksheet.max_column + 1
        worksheet.cell(row=1, column=lg_code_column, value="LG CODE")

    for excel_row, lg_code in lg_codes_by_row.items():
        worksheet.cell(row=excel_row, column=lg_code_column, value=str(lg_code))

    workbook.save(output_path)


@router.post("/generate")
async def generate_bulk_bills(
    excel_file: UploadFile = File(...),
    template_id: int = Form(...),
    output_format: Literal["individual", "merged", "both"] = Form("individual"),
    db: Session = Depends(get_db),
):
    if not excel_file.filename or not excel_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Upload an Excel workbook (.xlsx or .xls).")

    template = db.query(NoticeTemplate).filter(NoticeTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    template_path = Path(template.file_path)
    print("========== BULK TEMPLATE CHECK ==========")
    print(f"Submitted template ID: {template_id}")
    print(f"Database template name: {getattr(template, 'name', 'N/A')}")
    print(f"Database file path: {template.file_path}")
    print(f"Resolved template path: {template_path.resolve()}")
    print(f"File exists: {template_path.is_file()}")
    print("=========================================")

    if not template_path.is_file():
        raise HTTPException(status_code=404, detail="The selected Word template file could not be found.")

    performance = {
        "started_at": time.perf_counter(),
        "submitted": 0,
        "rendered": 0,
        "successful": 0,
        "failed": 0,
        "conversion_batches": 0,
        "allocation_seconds": 0.0,
        "render_seconds": 0.0,
        "conversion_seconds": 0.0,
        "merge_seconds": 0.0,
        "excel_seconds": 0.0,
        "zip_seconds": 0.0,
    }

    try:
        contents = await excel_file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="The Excel file is empty.")

        # XLS can be read by pandas, but openpyxl cannot preserve/edit the old
        # binary XLS format. Require XLSX for the original-workbook write-back.
        if not excel_file.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=400,
                detail="Please save the workbook as .xlsx so its original layout can be preserved while writing LG Codes.",
            )

        with tempfile.TemporaryDirectory(prefix="bulk_upload_") as temporary:
            temp_dir = Path(temporary)
            workbook_path = temp_dir / Path(excel_file.filename).name
            workbook_path.write_bytes(contents)

            try:
                dataframe = pd.read_excel(workbook_path, dtype=object)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Unable to read Excel workbook: {exc}") from exc

            if dataframe.empty:
                raise HTTPException(status_code=400, detail="The Excel workbook contains no data rows.")
            performance["submitted"] = len(dataframe)

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
                        detail="The workbook needs a PROPERTY_NO or ASSESSMENT_NO column.",
                    )

            batch_name = next(tempfile._get_candidate_names())
            batch_dir = BATCH_DIR / batch_name
            docx_dir = batch_dir / "docx"
            pdf_dir = batch_dir / "individual"
            docx_dir.mkdir(parents=True, exist_ok=True)
            pdf_dir.mkdir(parents=True, exist_ok=True)

            errors = []
            jobs = []
            job_metadata = []
            lg_codes_by_row = {}
            seen_codes = set()

            if "LG_CODE" not in dataframe.columns:
                dataframe["LG_CODE"] = None
            dataframe["LG_CODE"] = dataframe["LG_CODE"].astype(object)

            # Phase 1: allocate codes and render DOCX documents. No PDF
            # conversion is started inside this property loop.
            for position, (index, row) in enumerate(dataframe.iterrows(), start=1):
                record = row.where(pd.notna(row), None).to_dict()
                property_number = str(
                    record.get("PROPERTY_NO")
                    or record.get("ASSESSMENT_NO")
                    or f"row_{index + 2}"
                ).strip()
                excel_row = int(index) + 2

                try:
                    prefix = record.get("PREFIX") or record.get("PRFIX") or "LG"
                    existing_code = str(record.get("LG_CODE") or "").strip()

                    allocation_started = time.perf_counter()
                    if existing_code:
                        lg_code = existing_code
                    else:
                        lg_code = allocate_bulk_lg_code(
                            db,
                            prefix=str(prefix).strip(),
                            property_identifier=property_number,
                        )
                        dataframe.at[index, "LG_CODE"] = lg_code
                    performance["allocation_seconds"] += time.perf_counter() - allocation_started

                    if lg_code in seen_codes:
                        raise ValueError(f"Duplicate LG Code in workbook: {lg_code}")
                    seen_codes.add(lg_code)
                    lg_codes_by_row[excel_row] = lg_code

                    record["LG_CODE"] = lg_code
                    record["PROPERTY_NO"] = property_number

                    docx_name = f"{position:07d}_{safe_name(property_number, 'bill')}.docx"
                    pdf_name = f"{position:07d}_{safe_name(property_number, 'bill')}.pdf"
                    docx_path = docx_dir / docx_name
                    pdf_path = pdf_dir / pdf_name

                    render_started = time.perf_counter()
                    render_notice_docx(
                        property_record=record,
                        docx_path=docx_path,
                        template_path=template_path,
                    )
                    performance["render_seconds"] += time.perf_counter() - render_started
                    performance["rendered"] += 1
                    jobs.append((str(docx_path), str(pdf_path)))
                    job_metadata.append({
                        "row": excel_row,
                        "property": property_number,
                        "pdf_path": pdf_path,
                    })

                except Exception as exc:
                    db.rollback()
                    errors.append({"row": excel_row, "property": property_number, "error": str(exc)})

            # Phase 2: genuine batch conversion. LibreOffice is launched once
            # for each group of up to CONVERSION_BATCH_SIZE DOCX documents.
            if jobs:
                performance["conversion_batches"] = (
                    len(jobs) + CONVERSION_BATCH_SIZE - 1
                ) // CONVERSION_BATCH_SIZE
                conversion_started = time.perf_counter()
                try:
                    with WordConverter(batch_size=CONVERSION_BATCH_SIZE, timeout=600) as word:
                        conversion_results = word.convert_many(jobs)
                except Exception as exc:
                    conversion_results = [(False, str(exc)) for _ in jobs]
                finally:
                    performance["conversion_seconds"] += time.perf_counter() - conversion_started

                for metadata, (ok, message) in zip(job_metadata, conversion_results):
                    if not ok:
                        errors.append({
                            "row": metadata["row"],
                            "property": metadata["property"],
                            "error": message,
                        })

            individual_files = [
                metadata["pdf_path"]
                for metadata in job_metadata
                if metadata["pdf_path"].is_file()
            ]
            performance["successful"] = len(individual_files)
            performance["failed"] = len(errors)

            excel_started = time.perf_counter()
            updated_workbook_path = batch_dir / "bulk_generation_with_lg_codes.xlsx"
            update_original_excel_with_lg_codes(
                source_bytes=contents,
                output_path=updated_workbook_path,
                lg_codes_by_row=lg_codes_by_row,
            )
            performance["excel_seconds"] += time.perf_counter() - excel_started

            merged_path = batch_dir / "merged_bills.pdf"
            if output_format in ("merged", "both") and individual_files:
                merge_started = time.perf_counter()
                writer = PdfWriter()
                try:
                    for pdf_path in individual_files:
                        writer.append(str(pdf_path))
                    with merged_path.open("wb") as output:
                        writer.write(output)
                finally:
                    writer.close()
                    performance["merge_seconds"] += time.perf_counter() - merge_started

            # Archive successfully generated PDFs in Google Drive. Upload failures
            # are logged but never interrupt the existing bulk download workflow.
            drive_files = list(individual_files)
            if merged_path.is_file():
                drive_files.append(merged_path)
            archive_pdfs_to_drive(drive_files, context=f"synchronous bulk batch {batch_name}")

            archive_path = BATCH_DIR / f"bulk_bills_{batch_name}.zip"
            zip_started = time.perf_counter()
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                if output_format in ("individual", "both"):
                    for pdf_path in individual_files:
                        archive.write(pdf_path, arcname=f"individual/{pdf_path.name}")

                if output_format in ("merged", "both") and merged_path.is_file():
                    archive.write(merged_path, arcname="merged_bills.pdf")

                archive.write(
                    updated_workbook_path,
                    arcname="bulk_generation_with_lg_codes.xlsx",
                )

                if errors:
                    error_text = "\n".join(
                        f"Excel row {item['row']} ({item['property']}): {item['error']}"
                        for item in errors
                    )
                    archive.writestr("generation_errors.txt", error_text)

            performance["zip_seconds"] += time.perf_counter() - zip_started
            return FileResponse(
                path=str(archive_path),
                media_type="application/zip",
                filename=archive_path.name,
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Bulk generation failed: {exc}") from exc
    finally:
        try:
            await excel_file.close()
        finally:
            log_bulk_performance(performance)

# =====================================================
# BACKGROUND BULK GENERATION
#
# New endpoints:
# POST /bulk-bills/start
# GET  /bulk-bills/jobs/{job_id}
# GET  /bulk-bills/jobs/{job_id}/download
#
# The original synchronous /generate endpoint remains
# available until the WordPress interface is switched.
# =====================================================

def _save_job(db, job_id, **changes):
    job = db.query(BulkGenerationJob).filter(
        BulkGenerationJob.id == job_id
    ).first()
    if job is None:
        return None

    for key, value in changes.items():
        setattr(job, key, value)

    db.commit()
    db.refresh(job)
    return job


def run_bulk_generation_job(job_id, source_path, original_filename, template_id, output_format):
    """Run a submitted bulk job after the API has returned its job ID."""
    db = SessionLocal()
    performance = {
        "started_at": time.perf_counter(),
        "submitted": 0,
        "rendered": 0,
        "successful": 0,
        "failed": 0,
        "conversion_batches": 0,
        "allocation_seconds": 0.0,
        "render_seconds": 0.0,
        "conversion_seconds": 0.0,
        "merge_seconds": 0.0,
        "excel_seconds": 0.0,
        "zip_seconds": 0.0,
    }

    try:
        job = db.query(BulkGenerationJob).filter(
            BulkGenerationJob.id == job_id
        ).first()
        if job is None:
            return

        _save_job(
            db, job_id,
            status="processing",
            stage="Preparing workbook",
            processed=0,
            stage_completed=0,
            stage_total=0,
            error=None,
        )

        template = db.query(NoticeTemplate).filter(
            NoticeTemplate.id == template_id
        ).first()
        if not template:
            raise RuntimeError("The selected notice template no longer exists.")

        template_path = Path(template.file_path)
        print("========== BACKGROUND BULK TEMPLATE CHECK ==========")
        print(f"Job ID: {job_id}")
        print(f"Submitted template ID: {template_id}")
        print(f"Database template name: {getattr(template, 'name', 'N/A')}")
        print(f"Database file path: {template.file_path}")
        print(f"Resolved template path: {template_path.resolve()}")
        print(f"File exists: {template_path.is_file()}")
        print("=====================================================")

        if not template_path.is_file():
            raise RuntimeError("The selected Word template file could not be found.")

        contents = Path(source_path).read_bytes()
        if not contents:
            raise RuntimeError("The uploaded Excel workbook is empty.")

        if not original_filename.lower().endswith(".xlsx"):
            raise RuntimeError(
                "Please save the workbook as .xlsx so its original layout can be preserved while writing LG Codes."
            )

        job_dir = BATCH_DIR / job_id
        docx_dir = job_dir / "docx"
        pdf_dir = job_dir / "individual"
        docx_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)

        workbook_path = job_dir / Path(original_filename).name
        workbook_path.write_bytes(contents)

        try:
            dataframe = pd.read_excel(workbook_path, dtype=object)
        except Exception as exc:
            raise RuntimeError(f"Unable to read Excel workbook: {exc}") from exc

        if dataframe.empty:
            raise RuntimeError("The Excel workbook contains no data rows.")

        performance["submitted"] = len(dataframe)
        dataframe.columns = [
            str(column).strip().replace(" ", "_").upper()
            for column in dataframe.columns
        ]

        if "PROPERTY_NO" not in dataframe.columns:
            if "ASSESSMENT_NO" in dataframe.columns:
                dataframe["PROPERTY_NO"] = dataframe["ASSESSMENT_NO"]
            else:
                raise RuntimeError(
                    "The workbook needs a PROPERTY_NO or ASSESSMENT_NO column."
                )

        _save_job(
            db, job_id,
            total=len(dataframe),
            processed=0,
            stage="Allocating LG Codes and rendering notices",
            stage_completed=0,
            stage_total=len(dataframe),
        )

        errors = []
        jobs = []
        job_metadata = []
        lg_codes_by_row = {}
        seen_codes = set()

        if "LG_CODE" not in dataframe.columns:
            dataframe["LG_CODE"] = None
        dataframe["LG_CODE"] = dataframe["LG_CODE"].astype(object)

        # Phase 1: preserve existing codes, allocate missing codes and render DOCX.
        for position, (index, row) in enumerate(dataframe.iterrows(), start=1):
            record = row.where(pd.notna(row), None).to_dict()
            property_number = str(
                record.get("PROPERTY_NO")
                or record.get("ASSESSMENT_NO")
                or f"row_{index + 2}"
            ).strip()
            excel_row = int(index) + 2

            try:
                prefix = record.get("PREFIX") or record.get("PRFIX") or "LG"
                existing_code = str(record.get("LG_CODE") or "").strip()

                allocation_started = time.perf_counter()
                if existing_code:
                    lg_code = existing_code
                else:
                    lg_code = allocate_bulk_lg_code(
                        db,
                        prefix=str(prefix).strip(),
                        property_identifier=property_number,
                    )
                    dataframe.at[index, "LG_CODE"] = lg_code
                performance["allocation_seconds"] += (
                    time.perf_counter() - allocation_started
                )

                if lg_code in seen_codes:
                    raise ValueError(f"Duplicate LG Code in workbook: {lg_code}")
                seen_codes.add(lg_code)
                lg_codes_by_row[excel_row] = lg_code

                record["LG_CODE"] = lg_code
                record["PROPERTY_NO"] = property_number

                docx_name = f"{position:07d}_{safe_name(property_number, 'bill')}.docx"
                pdf_name = f"{position:07d}_{safe_name(property_number, 'bill')}.pdf"
                docx_path = docx_dir / docx_name
                pdf_path = pdf_dir / pdf_name

                render_started = time.perf_counter()
                render_notice_docx(
                    property_record=record,
                    docx_path=docx_path,
                    template_path=template_path,
                )
                performance["render_seconds"] += time.perf_counter() - render_started
                performance["rendered"] += 1
                jobs.append((str(docx_path), str(pdf_path)))
                job_metadata.append({
                    "row": excel_row,
                    "property": property_number,
                    "pdf_path": pdf_path,
                })

            except Exception as exc:
                db.rollback()
                errors.append({
                    "row": excel_row,
                    "property": property_number,
                    "error": str(exc),
                })

            # Write genuine progress in small groups to avoid 500 DB commits.
            if position % 5 == 0 or position == len(dataframe):
                _save_job(
                    db, job_id,
                    processed=position,
                    stage_completed=position,
                    successful=sum(1 for item in job_metadata if item["pdf_path"].is_file()),
                    failed=len(errors),
                )

        # Phase 2: convert in groups of 25 and publish progress after each group.
        _save_job(
            db, job_id,
            stage="Converting PDFs",
            processed=0,
            stage_completed=0,
            stage_total=len(jobs),
            successful=0,
            failed=len(errors),
        )

        conversion_started = time.perf_counter()
        if jobs:
            performance["conversion_batches"] = (
                len(jobs) + CONVERSION_BATCH_SIZE - 1
            ) // CONVERSION_BATCH_SIZE

            with WordConverter(batch_size=CONVERSION_BATCH_SIZE, timeout=600) as word:
                for start in range(0, len(jobs), CONVERSION_BATCH_SIZE):
                    batch_jobs = jobs[start:start + CONVERSION_BATCH_SIZE]
                    batch_metadata = job_metadata[start:start + CONVERSION_BATCH_SIZE]

                    try:
                        batch_results = word.convert_many(batch_jobs)
                    except Exception as exc:
                        batch_results = [(False, str(exc)) for _ in batch_jobs]

                    for metadata, result in zip(batch_metadata, batch_results):
                        ok, message = result
                        if not ok:
                            errors.append({
                                "row": metadata["row"],
                                "property": metadata["property"],
                                "error": message,
                            })

                    completed = min(start + len(batch_jobs), len(jobs))
                    successful_now = sum(
                        1 for item in job_metadata if item["pdf_path"].is_file()
                    )
                    _save_job(
                        db, job_id,
                        processed=completed,
                        stage_completed=completed,
                        successful=successful_now,
                        failed=len(errors),
                    )

        performance["conversion_seconds"] += (
            time.perf_counter() - conversion_started
        )

        individual_files = [
            metadata["pdf_path"]
            for metadata in job_metadata
            if metadata["pdf_path"].is_file()
        ]
        performance["successful"] = len(individual_files)
        performance["failed"] = len(errors)

        # Phase 3: update the original workbook without rebuilding its layout.
        _save_job(
            db, job_id,
            stage="Updating Excel workbook",
            processed=0,
            stage_completed=0,
            stage_total=1,
            successful=performance["successful"],
            failed=performance["failed"],
        )

        excel_started = time.perf_counter()
        updated_workbook_path = job_dir / "bulk_generation_with_lg_codes.xlsx"
        update_original_excel_with_lg_codes(
            source_bytes=contents,
            output_path=updated_workbook_path,
            lg_codes_by_row=lg_codes_by_row,
        )
        performance["excel_seconds"] += time.perf_counter() - excel_started
        _save_job(db, job_id, processed=1, stage_completed=1)

        # Phase 4: merge, if requested.
        merged_path = job_dir / "merged_bills.pdf"
        if output_format in ("merged", "both") and individual_files:
            _save_job(
                db, job_id,
                stage="Merging PDFs",
                processed=0,
                stage_completed=0,
                stage_total=1,
            )
            merge_started = time.perf_counter()
            writer = PdfWriter()
            try:
                for pdf_path in individual_files:
                    writer.append(str(pdf_path))
                with merged_path.open("wb") as output:
                    writer.write(output)
            finally:
                writer.close()
                performance["merge_seconds"] += (
                    time.perf_counter() - merge_started
                )
            _save_job(db, job_id, processed=1, stage_completed=1)

        # Phase 5: package the same output files as the existing endpoint.
        _save_job(
            db, job_id,
            stage="Packaging ZIP download",
            processed=0,
            stage_completed=0,
            stage_total=1,
        )

        archive_path = job_dir / f"bulk_bills_{job_id}.zip"
        zip_started = time.perf_counter()
        with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            if output_format in ("individual", "both"):
                for pdf_path in individual_files:
                    archive.write(
                        pdf_path,
                        arcname=f"individual/{pdf_path.name}",
                    )

            if output_format in ("merged", "both") and merged_path.is_file():
                archive.write(merged_path, arcname="merged_bills.pdf")

            archive.write(
                updated_workbook_path,
                arcname="bulk_generation_with_lg_codes.xlsx",
            )

            if errors:
                error_text = "\n".join(
                    f"Excel row {item['row']} ({item['property']}): {item['error']}"
                    for item in errors
                )
                archive.writestr("generation_errors.txt", error_text)

        performance["zip_seconds"] += time.perf_counter() - zip_started

        _save_job(
            db, job_id,
            status="completed",
            stage="Completed",
            processed=1,
            stage_completed=1,
            stage_total=1,
            successful=performance["successful"],
            failed=performance["failed"],
            zip_path=str(archive_path),
            error=None,
        )

        # Archive after marking the job complete so the existing progress bar
        # and ZIP download become available without waiting for Drive uploads.
        drive_files = list(individual_files)
        if merged_path.is_file():
            drive_files.append(merged_path)
        archive_pdfs_to_drive(drive_files, context=f"background bulk job {job_id}")

    except Exception as exc:
        db.rollback()
        _save_job(
            db, job_id,
            status="failed",
            stage="Failed",
            error=str(exc)[:2000],
        )
        print(f"Bulk job {job_id} failed: {exc}")

    finally:
        try:
            log_bulk_performance(performance)
        except Exception as log_exc:
            print(f"Bulk job performance logging failed: {log_exc}")
        db.close()


@router.post("/start", status_code=202)
async def start_bulk_generation(
    background_tasks: BackgroundTasks,
    excel_file: UploadFile = File(...),
    template_id: int = Form(...),
    output_format: Literal["individual", "merged", "both"] = Form("individual"),
    db: Session = Depends(get_db),
):
    """Accept the workbook, create a tracked job and return immediately."""
    if not excel_file.filename or not excel_file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Please upload an .xlsx workbook.",
        )

    template = db.query(NoticeTemplate).filter(
        NoticeTemplate.id == template_id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    template_path = Path(template.file_path)
    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The selected Word template file could not be found.",
        )

    contents = await excel_file.read()
    await excel_file.close()

    if not contents:
        raise HTTPException(status_code=400, detail="The Excel file is empty.")

    job_id = str(uuid.uuid4())
    job_dir = BATCH_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    original_filename = Path(excel_file.filename).name
    source_path = job_dir / "uploaded_workbook.xlsx"
    source_path.write_bytes(contents)

    job = BulkGenerationJob(
        id=job_id,
        status="queued",
        stage="Waiting to start",
        total=0,
        processed=0,
        stage_completed=0,
        stage_total=0,
        successful=0,
        failed=0,
        zip_path=None,
        error=None,
    )
    db.add(job)
    db.commit()

    background_tasks.add_task(
        run_bulk_generation_job,
        job_id,
        str(source_path),
        original_filename,
        template_id,
        output_format,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Bulk generation has been accepted.",
    }


@router.get("/jobs/{job_id}")
def get_bulk_generation_status(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(BulkGenerationJob).filter(
        BulkGenerationJob.id == job_id
    ).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Bulk generation job not found.")

    percent = 0
    if job.stage_total:
        percent = int((job.stage_completed / job.stage_total) * 100)

    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "processed": job.processed,
        "total": job.total,
        "stage_completed": job.stage_completed,
        "stage_total": job.stage_total,
        "stage_percent": min(100, max(0, percent)),
        "successful": job.successful,
        "failed": job.failed,
        "error": job.error,
        "download_ready": (
            job.status == "completed"
            and bool(job.zip_path)
            and Path(job.zip_path).is_file()
        ),
    }


@router.get("/jobs/{job_id}/download")
def download_bulk_generation(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.query(BulkGenerationJob).filter(
        BulkGenerationJob.id == job_id
    ).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Bulk generation job not found.")

    if job.status != "completed" or not job.zip_path:
        raise HTTPException(
            status_code=409,
            detail="The ZIP file is not ready yet.",
        )

    archive_path = Path(job.zip_path)
    if not archive_path.is_file():
        raise HTTPException(
            status_code=410,
            detail="The generated ZIP file is no longer available. The server may have restarted.",
        )

    return FileResponse(
        path=str(archive_path),
        media_type="application/zip",
        filename=archive_path.name,
    )
