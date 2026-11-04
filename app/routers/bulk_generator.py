import re
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from app.database import get_db
from app.pdf_generator import render_notice_docx
from app.word_converter import WordConverter
from app.models import NoticeTemplate
from app.lg_code_allocator import allocate_bulk_lg_code


router = APIRouter(prefix="/bulk-bills", tags=["Bulk Bill Generation"])

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output_pdfs"
BATCH_DIR = OUTPUT_DIR / "bulk_batches"
CONVERSION_BATCH_SIZE = 25


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

                    if existing_code:
                        lg_code = existing_code
                    else:
                        lg_code = allocate_bulk_lg_code(
                            db,
                            prefix=str(prefix).strip(),
                            property_identifier=property_number,
                        )
                        dataframe.at[index, "LG_CODE"] = lg_code

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

                    render_notice_docx(
                        property_record=record,
                        docx_path=docx_path,
                        template_path=template_path,
                    )
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
                try:
                    with WordConverter(batch_size=CONVERSION_BATCH_SIZE, timeout=600) as word:
                        conversion_results = word.convert_many(jobs)
                except Exception as exc:
                    conversion_results = [(False, str(exc)) for _ in jobs]

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

            updated_workbook_path = batch_dir / "bulk_generation_with_lg_codes.xlsx"
            update_original_excel_with_lg_codes(
                source_bytes=contents,
                output_path=updated_workbook_path,
                lg_codes_by_row=lg_codes_by_row,
            )

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

            archive_path = BATCH_DIR / f"bulk_bills_{batch_name}.zip"
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
        await excel_file.close()
