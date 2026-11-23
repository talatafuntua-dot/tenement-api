
"""
Google Drive Tenement Bill Retriever
------------------------------------
Searches the existing TENEMENT STORAGE WEB archive in:

YYYY / Month / DD Month YYYY /
    Individual Bills
    Bulk Bills
        Named Batch Folders
    Merged PDFs

Supports both the original archive structure and named batch folders.

It does not modify, move, rename, or delete archived files.
Scanned/image-only PDFs are reported as needing OCR; this module does not
pretend that text extraction can search their contents.
"""

import io
import os
import re
import secrets
import tempfile
import zipfile

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    HTTPException,
    Header,
    Depends,
    Query,
)

from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    IndividualGenerationHistory,
    BulkGenerationJob,
)

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from pypdf import PdfReader, PdfWriter


router = APIRouter(
    prefix="/storage-retriever",
    tags=["Storage Retriever"],
)

SCOPES = ["https://www.googleapis.com/auth/drive"]

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
PDF_MIME_TYPE = "application/pdf"

SEARCH_CATEGORIES = {
    "Individual Bills",
    "Bulk Bills",
    "Merged PDFs",
}


# =========================================================
# API KEY SECURITY
# =========================================================

def _check_retriever_key(
    x_storage_retriever_key: Optional[str] = Header(default=None)
):
    expected = os.getenv("STORAGE_RETRIEVER_API_KEY")

    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Storage retriever is not enabled. "
                "Set STORAGE_RETRIEVER_API_KEY in Render."
            ),
        )

    if (
        not x_storage_retriever_key
        or not secrets.compare_digest(
            x_storage_retriever_key,
            expected,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Not authorised to use the storage retriever.",
        )


# =========================================================
# REQUEST MODELS
# =========================================================

class SearchRequest(BaseModel):
    search_term: str = Field(
        ...,
        min_length=2,
        max_length=200,
    )


class ExtractRequest(BaseModel):
    file_id: str = Field(
        ...,
        min_length=5,
        max_length=200,
    )

    pages: list[int] = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    filename: Optional[str] = Field(
        default=None,
        max_length=180,
    )


# =========================================================
# BILL GENERATION COUNT
# =========================================================

def _model_timestamp_column(model, preferred_names=None):
    """Find a timestamp column without assuming a model version."""

    available = set(model.__table__.columns.keys())

    candidates = preferred_names or (
        "created_at",
        "generated_at",
        "generation_time",
        "timestamp",
        "created_on",
        "generation_date",
    )

    for name in candidates:
        if name in available:
            return getattr(model, name)

    raise RuntimeError(
        f"{model.__name__} has no recognised generation timestamp column. "
        f"Available columns: {', '.join(sorted(available))}"
    )


def _nigeria_day_utc_bounds(selected_day: date, column):
    """Convert a Nigeria calendar day to UTC bounds for database filtering."""

    nigeria = ZoneInfo("Africa/Lagos")

    local_start = datetime.combine(
        selected_day,
        time.min,
        tzinfo=nigeria,
    )

    local_end = local_start + timedelta(days=1)

    start_utc = local_start.astimezone(timezone.utc)
    end_utc = local_end.astimezone(timezone.utc)

    if not getattr(column.type, "timezone", False):
        start_utc = start_utc.replace(tzinfo=None)
        end_utc = end_utc.replace(tzinfo=None)

    return start_utc, end_utc


@router.get("/generation-count")
def get_generation_count(
    selected_date: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    _auth: None = Depends(_check_retriever_key),
):
    """Return successful individual and bulk bill counts for one Nigeria day."""

    try:
        individual_timestamp = _model_timestamp_column(
            IndividualGenerationHistory
        )

        individual_start, individual_end = _nigeria_day_utc_bounds(
            selected_date,
            individual_timestamp,
        )

        individual_count = (
            db.query(IndividualGenerationHistory)
            .filter(
                individual_timestamp >= individual_start,
                individual_timestamp < individual_end,
            )
            .count()
        )

        bulk_timestamp = _model_timestamp_column(
            BulkGenerationJob,
            preferred_names=(
                "updated_at",
                "completed_at",
                "created_at",
                "generated_at",
                "timestamp",
            ),
        )

        bulk_start, bulk_end = _nigeria_day_utc_bounds(
            selected_date,
            bulk_timestamp,
        )

        bulk_count = (
            db.query(
                func.coalesce(
                    func.sum(BulkGenerationJob.successful),
                    0,
                )
            )
            .filter(
                bulk_timestamp >= bulk_start,
                bulk_timestamp < bulk_end,
            )
            .scalar()
        )

        individual_count = int(individual_count or 0)
        bulk_count = int(bulk_count or 0)

        return {
            "date": selected_date.isoformat(),
            "individual_count": individual_count,
            "bulk_count": bulk_count,
            "total_generated": individual_count + bulk_count,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not retrieve daily generation count: {exc}",
        ) from exc


# =========================================================
# ZIP HELPERS
# =========================================================

def _safe_zip_member_name(value: str) -> str:
    """Keep archive entries inside their category directory."""

    name = os.path.basename(
        str(value or "ARCHIVED_BILL.pdf")
    )

    name = re.sub(
        r"[^A-Za-z0-9._ -]+",
        "_",
        name,
    ).strip(" .")

    return name or "ARCHIVED_BILL.pdf"


def _iter_temporary_file(file_obj, chunk_size=1024 * 1024):
    try:
        file_obj.seek(0)

        while True:
            chunk = file_obj.read(chunk_size)

            if not chunk:
                break

            yield chunk

    finally:
        file_obj.close()


# =========================================================
# DAILY PDF DOWNLOAD
# =========================================================

@router.get("/daily-download")
def download_all_daily_pdfs(
    selected_date: date = Query(..., alias="date"),
    _auth: None = Depends(_check_retriever_key),
):
    """
    Download original bill PDFs for the selected Nigeria calendar day.

    Includes:
    - Individual Bills
    - Bulk Bills
    - PDFs inside named bulk batch folders
    - Merged PDFs

    Does not modify the PDF contents.
    """

    drive = _drive_client()

    expected_day_folder = selected_date.strftime("%d %B %Y")
    expected_year_folder = selected_date.strftime("%Y")

    try:
        # Recursive archive discovery now includes named batch folders.
        daily_files = [
            item
            for item in _archive_pdf_files(drive)
            if (
                item.get("archive_year") == expected_year_folder
                and item.get("archive_date") == expected_day_folder
                and item.get("archive_category") in SEARCH_CATEGORIES
            )
        ]

        if not daily_files:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No archived bill PDFs were found "
                    f"for {selected_date.isoformat()}."
                ),
            )

        output = tempfile.SpooledTemporaryFile(
            max_size=50 * 1024 * 1024,
            mode="w+b",
        )

        used_names = set()
        downloaded_count = 0

        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:

            for item in daily_files:
                pdf_bytes = _download_pdf(
                    drive,
                    item["id"],
                )

                category = item.get(
                    "archive_category",
                    "Bills",
                )

                filename = _safe_zip_member_name(
                    item.get("name")
                )

                stem, extension = os.path.splitext(filename)

                member_name = f"{category}/{filename}"

                suffix = 2

                while member_name.casefold() in used_names:
                    member_name = (
                        f"{category}/{stem}_{suffix}{extension}"
                    )
                    suffix += 1

                used_names.add(member_name.casefold())

                archive.writestr(
                    member_name,
                    pdf_bytes,
                )

                downloaded_count += 1

        output.seek(0)

        zip_name = (
            f"TENEMENT_BILLS_{selected_date.isoformat()}.zip"
        )

        return StreamingResponse(
            _iter_temporary_file(output),
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{zip_name}"'
                ),
                "X-PDF-Count": str(downloaded_count),
                "Cache-Control": "no-store",
            },
        )

    except HTTPException:
        raise

    except HttpError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Google Drive daily PDF retrieval failed: {exc}",
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not create the daily PDF download: {exc}",
        ) from exc


# =========================================================
# GOOGLE DRIVE CONNECTION
# =========================================================

def _drive_client():

    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not all((
        refresh_token,
        client_id,
        client_secret,
        os.getenv("GOOGLE_DRIVE_FOLDER_ID"),
    )):
        raise HTTPException(
            status_code=503,
            detail=(
                "Google Drive is not configured. Check "
                "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "GOOGLE_REFRESH_TOKEN and GOOGLE_DRIVE_FOLDER_ID "
                "in Render."
            ),
        )

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )

    try:
        credentials.refresh(GoogleAuthRequest())

        return build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to Google Drive: {exc}",
        ) from exc


# =========================================================
# GOOGLE DRIVE HELPERS
# =========================================================

def _escape_query(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _list_children(
    drive,
    parent_id: str,
    mime_type: Optional[str] = None,
):
    """List every child item, following Drive pagination."""

    items = []
    page_token = None

    while True:

        clauses = [
            f"'{_escape_query(parent_id)}' in parents",
            "trashed = false",
        ]

        if mime_type:
            clauses.append(
                f"mimeType = '{mime_type}'"
            )

        response = drive.files().list(
            q=" and ".join(clauses),
            pageSize=1000,
            pageToken=page_token,
            orderBy="name",
            fields=(
                "nextPageToken,"
                "files(id,name,mimeType,webViewLink,size,modifiedTime)"
            ),
        ).execute()

        items.extend(
            response.get("files", [])
        )

        page_token = response.get("nextPageToken")

        if not page_token:
            return items


# =========================================================
# RECURSIVE ARCHIVE PDF DISCOVERY
# =========================================================

def _archive_pdf_files(drive):
    """
    Find PDFs inside supported bill categories.

    Supports both archive structures:

    OLD:
        YEAR / MONTH / DAY / CATEGORY / bill.pdf

    NEW:
        YEAR / MONTH / DAY / Bulk Bills / BATCH FOLDER / bill.pdf

    Also supports further subfolders inside named batch folders.
    """

    root_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    found = []

    def collect_pdfs(
        folder_id,
        category_name,
        day_name,
        year_name,
    ):
        """
        Recursively collect PDFs inside a category
        and all its subfolders.
        """

        children = _list_children(
            drive,
            folder_id,
        )

        for item in children:

            mime_type = item.get("mimeType")

            if mime_type == PDF_MIME_TYPE:

                item["archive_category"] = category_name
                item["archive_date"] = day_name
                item["archive_year"] = year_name

                found.append(item)

            elif mime_type == FOLDER_MIME_TYPE:

                collect_pdfs(
                    item["id"],
                    category_name,
                    day_name,
                    year_name,
                )

    # Find year folders.
    years = _list_children(
        drive,
        root_id,
        FOLDER_MIME_TYPE,
    )

    for year in years:

        # Find month folders.
        months = _list_children(
            drive,
            year["id"],
            FOLDER_MIME_TYPE,
        )

        for month in months:

            # Find day folders.
            days = _list_children(
                drive,
                month["id"],
                FOLDER_MIME_TYPE,
            )

            for day in days:

                # Find category folders.
                categories = _list_children(
                    drive,
                    day["id"],
                    FOLDER_MIME_TYPE,
                )

                for category in categories:

                    if category.get("name") not in SEARCH_CATEGORIES:
                        continue

                    # Search directly inside the category and
                    # recursively inside all named batch folders.
                    collect_pdfs(
                        category["id"],
                        category["name"],
                        day["name"],
                        year["name"],
                    )

    return found


def _normalise(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        (value or "").casefold(),
    ).strip()


# =========================================================
# GOOGLE DRIVE PDF DOWNLOAD
# =========================================================

def _download_pdf(
    drive,
    file_id: str,
) -> bytes:

    request = drive.files().get_media(
        fileId=file_id,
    )

    buffer = io.BytesIO()

    downloader = MediaIoBaseDownload(
        buffer,
        request,
    )

    done = False

    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue()


# =========================================================
# PDF TEXT SEARCH
# =========================================================

def _pdf_page_matches(
    pdf_bytes: bytes,
    term: str,
):
    """
    Return 1-based matching page numbers
    and whether pages contain searchable text.
    """

    try:
        reader = PdfReader(
            io.BytesIO(pdf_bytes),
            strict=False,
        )

        matches = []
        text_pages = 0

        needle = _normalise(term)

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):

            text = page.extract_text() or ""

            if text.strip():
                text_pages += 1

            if needle in _normalise(text):
                matches.append(page_number)

        return (
            len(reader.pages),
            matches,
            text_pages,
        )

    except Exception as exc:

        raise ValueError(
            f"PDF could not be read: {exc}"
        ) from exc


# =========================================================
# SEARCH ARCHIVED BILLS
# =========================================================

@router.post("/search")
def search_archived_bills(
    payload: SearchRequest,
    _auth: None = Depends(_check_retriever_key),
):
    """
    Search individual, bulk and merged bill PDFs
    by LG Code or occupier name.

    Includes PDFs inside named batch folders.

    Returns file IDs, matching page numbers and Drive view links.
    """

    term = payload.search_term.strip()

    drive = _drive_client()

    try:

        # This now discovers old PDFs and named batch PDFs.
        files = _archive_pdf_files(drive)

        results = []

        for item in files:

            try:

                pdf_bytes = _download_pdf(
                    drive,
                    item["id"],
                )

                page_count, pages, text_pages = _pdf_page_matches(
                    pdf_bytes,
                    term,
                )

                if pages:

                    results.append({
                        "file_id": item["id"],
                        "filename": item["name"],
                        "category": item["archive_category"],
                        "archive_date": item["archive_date"],
                        "archive_year": item["archive_year"],
                        "matching_pages": pages,
                        "page_count": page_count,
                        "view_url": item.get("webViewLink"),
                        "extraction_note": (
                            "Review the matching pages and select the "
                            "complete bill pages before extracting."
                        )
                        if item["archive_category"] == "Merged PDFs"
                        else "Individual PDF match.",
                    })

                elif text_pages == 0:

                    results.append({
                        "file_id": item["id"],
                        "filename": item["name"],
                        "category": item["archive_category"],
                        "archive_date": item["archive_date"],
                        "archive_year": item["archive_year"],
                        "matching_pages": [],
                        "page_count": page_count,
                        "view_url": item.get("webViewLink"),
                        "status": "OCR_REQUIRED",
                        "extraction_note": (
                            "This PDF appears image-only. "
                            "OCR is required to search its contents."
                        ),
                    })

            except ValueError as exc:

                results.append({
                    "file_id": item["id"],
                    "filename": item["name"],
                    "category": item["archive_category"],
                    "archive_date": item["archive_date"],
                    "archive_year": item["archive_year"],
                    "status": "READ_ERROR",
                    "detail": str(exc),
                })

        return {
            "search_term": term,
            "files_checked": len(files),
            "matches": len([
                result
                for result in results
                if result.get("matching_pages")
            ]),
            "ocr_required": len([
                result
                for result in results
                if result.get("status") == "OCR_REQUIRED"
            ]),
            "results": results,
        }

    except HTTPException:
        raise

    except HttpError as exc:

        raise HTTPException(
            status_code=502,
            detail=f"Google Drive search failed: {exc}",
        ) from exc


# =========================================================
# EXTRACT SELECTED BILL PAGES
# =========================================================

@router.post("/extract")
def extract_bill_pages(
    payload: ExtractRequest,
    _auth: None = Depends(_check_retriever_key),
):
    """
    Extract explicitly selected 1-based pages from
    a merged or individual PDF.

    Supports PDFs directly inside archive categories
    and PDFs inside named batch folders.

    The original Drive PDF is never changed.
    """

    drive = _drive_client()

    try:

        metadata = drive.files().get(
            fileId=payload.file_id,
            fields="id,name,mimeType,parents,trashed",
        ).execute()

        if (
            metadata.get("trashed")
            or metadata.get("mimeType") != PDF_MIME_TYPE
        ):

            raise HTTPException(
                status_code=404,
                detail="PDF file was not found.",
            )

        # -------------------------------------------------
        # VALIDATE PDF LOCATION
        # -------------------------------------------------

        # Walk upwards through the folder hierarchy.
        # This supports both direct category PDFs and
        # PDFs stored inside named batch subfolders.

        root_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

        pending_ids = list(
            metadata.get("parents", [])
        )

        visited_ids = set()

        found_category = False
        found_root = False

        while pending_ids and len(visited_ids) < 100:

            current_id = pending_ids.pop(0)

            if current_id in visited_ids:
                continue

            visited_ids.add(current_id)

            if current_id == root_id:
                found_root = True
                continue

            parent = drive.files().get(
                fileId=current_id,
                fields="id,name,mimeType,parents",
            ).execute()

            if parent.get("name") in SEARCH_CATEGORIES:
                found_category = True

            if parent.get("mimeType") == FOLDER_MIME_TYPE:
                pending_ids.extend(
                    parent.get("parents", [])
                )

        if not (found_category and found_root):

            raise HTTPException(
                status_code=403,
                detail=(
                    "This PDF is outside the bill archive categories."
                ),
            )

        # -------------------------------------------------
        # DOWNLOAD ORIGINAL PDF
        # -------------------------------------------------

        pdf_bytes = _download_pdf(
            drive,
            payload.file_id,
        )

        reader = PdfReader(
            io.BytesIO(pdf_bytes),
            strict=False,
        )

        page_numbers = sorted(
            set(payload.pages)
        )

        if any(
            number < 1 or number > len(reader.pages)
            for number in page_numbers
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Page numbers must be between "
                    f"1 and {len(reader.pages)}."
                ),
            )

        # -------------------------------------------------
        # EXTRACT SELECTED PAGES
        # -------------------------------------------------

        writer = PdfWriter()

        for number in page_numbers:

            writer.add_page(
                reader.pages[number - 1]
            )

        output = io.BytesIO()

        writer.write(output)

        output.seek(0)

        safe_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "_",
            payload.filename or (
                f"{os.path.splitext(metadata['name'])[0]}_EXTRACTED.pdf"
            ),
        )

        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        return StreamingResponse(
            output,
            media_type=PDF_MIME_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{safe_name}"'
                ),
                "Cache-Control": "no-store",
            },
        )

    except HTTPException:
        raise

    except HttpError as exc:

        raise HTTPException(
            status_code=502,
            detail=f"Google Drive download failed: {exc}",
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"Could not extract PDF pages: {exc}",
        ) from exc
