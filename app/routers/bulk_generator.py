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


def update_original_excel_with_lg_codes(
    source_bytes: bytes,
    output_path: Path,
    lg_codes_by_row: dict[int, str],
):
    """
    Preserve the original Excel workbook exactly as supplied.

    Only the LG CODE cells are changed.
    No Pandas reconstruction is used for the exported workbook.
    This prevents blank columns from becoming UNNAMED:_2,
    UNNAMED:_3, etc.
    """

    workbook = load_workbook(
        filename=BytesIO(source_bytes)
    )

    worksheet = workbook[workbook.sheetnames[0]]

    lg_code_column = None

    # Locate the original LG CODE heading.
    for cell in worksheet[1]:
        heading = str(cell.value or "").strip().upper()
        normalized = heading.replace(" ", "_")

        if normalized in {
            "LG_CODE",
            "LGCODE",
        }:
            lg_code_column = cell.column
            break

    # If the workbook does not already contain LG CODE,
    # add it at the end without disturbing existing columns.
    if lg_code_column is None:
        lg_code_column = worksheet.max_column + 1
        worksheet.cell(
            row=1,
            column=lg_code_column,
            value="LG CODE",
        )

    # Write only the generated LG Codes.
    for excel_row, lg_code in lg_codes_by_row.items():
        worksheet.cell(
            row=excel_row,
            column=lg_code_column,
            value=str(lg_code),
        )

    workbook.save(output_path)


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

                # LG Codes are text, not numbers.
                # This prevents Pandas float64 assignment errors.
                dataframe["LG_CODE"] = dataframe["LG_CODE"].astype(
                    "object"
                )

                seen_codes = set()

                # Keep generated LG Codes separately by original
                # Excel row number so the original workbook can be
                # updated without reconstructing its layout.
                lg_codes_by_row = {}

                # Generate each property's bill separately.
                for index, row in dataframe.iterrows():
                    record = row.where(
                        pd.notna(row),
                        None,
                    ).to_dict()

                    property_number = str(
                        record.get("PROPERTY_NO")
                        or record.get("ASSESSMENT_NO")
                        or f"row_{index + 2}"
                    ).strip()

                    try:
                        # Accept both the correct PREFIX heading
                        # and the earlier PRFIX heading.
                        prefix = (
                            record.get("PREFIX")
                            or record.get("PRFIX")
                            or "LG"
                        )

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
                                prefix=str(prefix).strip(),
                                property_identifier=property_number,
                            )

                            # Save the new code into the Pandas
                            # dataframe used for PDF generation.
                            dataframe.at[
                                index,
                                "LG_CODE",
                            ] = lg_code

                        if lg_code in seen_codes:
                            raise ValueError(
                                f"Duplicate LG Code in workbook: {lg_code}"
                            )

                        seen_codes.add(lg_code)

                        # Excel row 1 is the heading.
                        # Pandas row 0 therefore corresponds to
                        # Excel row 2.
                        excel_row = int(index) + 2
                        lg_codes_by_row[excel_row] = lg_code

                        record["LG_CODE"] = lg_code
                        record["PROPERTY_NO"] = property_number

                        generated_path = Path(
                            generate_notice_pdf(
                                property_record=record,
                                template_path=template_path,
                            )
                        )

                        if not generated_path.is_file():
                            raise RuntimeError(
                                "The PDF was not created."
                            )

                        filename = (
                            f"{index + 1:04d}_"
                            f"{safe_name(property_number, 'bill')}.pdf"
                        )

                        saved_path = batch_dir / filename

                        shutil.copy2(
                            generated_path,
                            saved_path,
                        )

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

                # ------------------------------------------------
                # CREATE EXCEL OUTPUT
                # ------------------------------------------------
                #
                # IMPORTANT:
                # Do NOT use dataframe.to_excel().
                #
                # The original workbook is preserved and only
                # LG CODE cells are updated.
                #
                updated_workbook_path = (
                    batch_dir
                    / "bulk_generation_with_lg_codes.xlsx"
                )

                update_original_excel_with_lg_codes(
                    source_bytes=contents,
                    output_path=updated_workbook_path,
                    lg_codes_by_row=lg_codes_by_row,
                )

                # Merge all successfully generated PDFs when requested.
                merged_path = batch_dir / "merged_bills.pdf"

                if (
                    output_format in ("merged", "both")
                    and individual_files
                ):
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
                    BATCH_DIR
                    / f"bulk_bills_{batch_name}.zip"
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

                    # Include the original-format Excel workbook
                    # containing the generated LG Codes.
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
