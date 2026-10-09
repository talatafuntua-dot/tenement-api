
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfWriter

from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NoticeTemplate
from app.pdf_generator import generate_notice_pdf


router = APIRouter(
    prefix="/bulk-bills",
    tags=["Bulk Bill Generation"]
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
    output_format: str = Form("individual"),
    db: Session = Depends(get_db),
):
    if not excel_file.filename or not excel_file.filename.lower().endswith(
        (".xlsx", ".xls")
    ):
        raise HTTPException(
            status_code=400,
            detail="Upload an Excel workbook (.xlsx or .xls)."
        )

    if output_format not in ("individual", "merged", "both"):
        raise HTTPException(
            status_code=400,
            detail="output_format must be individual, merged, or both."
        )

    template = (
        db.query(NoticeTemplate)
        .filter(NoticeTemplate.id == template_id)
        .first()
    )

    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    template_path = Path(template.file_path)

    if not template_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The selected Word template file could not be found."
        )

    try:
        contents = await excel_file.read()

        if not contents:
            raise HTTPException(status_code=400, detail="The Excel file is empty.")

        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            workbook_path = temp_dir / Path(excel_file.filename).name
            workbook_path.write_bytes(contents)

            try:
                dataframe = pd.read_excel(workbook_path)
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to read Excel workbook: {exc}"
                )

            if dataframe.empty:
                raise HTTPException(
                    status_code=400,
                    detail="The Excel workbook contains no data rows."
                )

            # Normalize column headings for the existing bill renderer.
            dataframe.columns = [
                str(column).strip().replace(" ", "_").upper()
                for column in dataframe.columns
            ]

            if "PROPERTY_NO" not in dataframe.columns:
                if "ASSESSMENT_NO" in dataframe.columns:
                    dataframe["PROPERTY_NO"] = dataframe["ASSESSMENT_NO"]
                elif "LG_CODE" in dataframe.columns:
                    dataframe["PROPERTY_NO"] = dataframe["LG_CODE"]
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "The workbook needs a PROPERTY_NO, "
                            "ASSESSMENT_NO, or LG_CODE column."
                        )
                    )

            batch_name = next(tempfile._get_candidate_names())
            batch_dir = BATCH_DIR / batch_name
            batch_dir.mkdir(parents=True, exist_ok=True)

            individual_files = []
            errors = []

            try:
                for index, row in dataframe.iterrows():
                    record = row.where(pd.notna(row), None).to_dict()

                    property_number = str(
                        record.get("PROPERTY_NO")
                        or record.get("LG_CODE")
                        or f"row_{index + 2}"
                    ).strip()

                    # The existing generator names its output using the
                    # assessment/property number. Copy each result immediately
                    # so duplicate names in the workbook cannot overwrite
                    # earlier bills in this batch.
                    try:
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
                        errors.append({
                            "row": int(index) + 2,
                            "property": property_number,
                            "error": str(exc),
                        })

                if not individual_files:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "message": "No bills could be generated.",
                            "errors": errors,
                        },
                    )

                merged_path = batch_dir / "merged_bills.pdf"

                if output_format in ("merged", "both"):
                    writer = PdfWriter()

                    for pdf_path in individual_files:
                        writer.append(str(pdf_path))

                    with merged_path.open("wb") as output:
                        writer.write(output)

                    writer.close()

                archive_path = BATCH_DIR / f"bulk_bills_{batch_name}.zip"

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

                    if output_format in ("merged", "both"):
                        archive.write(
                            merged_path,
                            arcname="merged_bills.pdf",
                        )

                    if errors:
                        archive.writestr(
                            "generation_errors.txt",
                            "\n".join(
                                f"Excel row {item['row']} "
                                f"({item['property']}): {item['error']}"
                                for item in errors
                            ),
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
                )

    finally:
        await excel_file.close()
