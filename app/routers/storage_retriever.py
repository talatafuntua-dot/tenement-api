"""
Google Drive Tenement Bill Retriever
------------------------------------
Searches the existing TENEMENT STORAGE WEB archive in:
YYYY / Month / DD Month YYYY / Individual Bills or Merged PDFs

It does not modify, move, rename, or delete archived files.
Scanned/image-only PDFs are reported as needing OCR; this module does not
pretend that text extraction can search their contents.
"""

import io
import os
import re
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from pypdf import PdfReader, PdfWriter

router = APIRouter(prefix="/storage-retriever", tags=["Storage Retriever"])

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
PDF_MIME_TYPE = "application/pdf"
SEARCH_CATEGORIES = {"Individual Bills", "Merged PDFs"}


def _check_retriever_key(x_storage_retriever_key: Optional[str] = Header(default=None)):
    expected = os.getenv("STORAGE_RETRIEVER_API_KEY")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Storage retriever is not enabled. Set STORAGE_RETRIEVER_API_KEY in Render."
        )
    if not x_storage_retriever_key or not secrets.compare_digest(x_storage_retriever_key, expected):
        raise HTTPException(status_code=401, detail="Not authorised to use the storage retriever.")


class SearchRequest(BaseModel):
    search_term: str = Field(..., min_length=2, max_length=200)


class ExtractRequest(BaseModel):
    file_id: str = Field(..., min_length=5, max_length=200)
    pages: list[int] = Field(..., min_length=1, max_length=100)
    filename: Optional[str] = Field(default=None, max_length=180)


def _drive_client():
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not all((refresh_token, client_id, client_secret,
                os.getenv("GOOGLE_DRIVE_FOLDER_ID"))):
        raise HTTPException(
            status_code=503,
            detail="Google Drive is not configured. Check GOOGLE_CLIENT_ID, "
                   "GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN and "
                   "GOOGLE_DRIVE_FOLDER_ID in Render."
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
        return build("drive", "v3", credentials=credentials,
                     cache_discovery=False)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to Google Drive: {exc}"
        ) from exc


def _escape_query(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _list_children(drive, parent_id: str, mime_type: Optional[str] = None):
    """List every child item, following Drive pagination."""
    items = []
    page_token = None
    while True:
        clauses = [
            f"'{_escape_query(parent_id)}' in parents",
            "trashed = false",
        ]
        if mime_type:
            clauses.append(f"mimeType = '{mime_type}'")
        response = drive.files().list(
            q=" and ".join(clauses),
            pageSize=1000,
            pageToken=page_token,
            orderBy="name",
            fields="nextPageToken,files(id,name,mimeType,webViewLink,size,modifiedTime)",
        ).execute()
        items.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return items


def _archive_pdf_files(drive):
    """Find PDFs only inside the two bill categories, at any archive date."""
    root_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    found = []
    years = _list_children(drive, root_id, FOLDER_MIME_TYPE)
    for year in years:
        months = _list_children(drive, year["id"], FOLDER_MIME_TYPE)
        for month in months:
            days = _list_children(drive, month["id"], FOLDER_MIME_TYPE)
            for day in days:
                categories = _list_children(drive, day["id"], FOLDER_MIME_TYPE)
                for category in categories:
                    if category.get("name") not in SEARCH_CATEGORIES:
                        continue
                    for item in _list_children(drive, category["id"]):
                        if item.get("mimeType") == PDF_MIME_TYPE:
                            item["archive_category"] = category["name"]
                            item["archive_date"] = day["name"]
                            item["archive_year"] = year["name"]
                            found.append(item)
    return found


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def _download_pdf(drive, file_id: str) -> bytes:
    request = drive.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def _pdf_page_matches(pdf_bytes: bytes, term: str):
    """Return 1-based matching page numbers and whether pages contain text."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        matches = []
        text_pages = 0
        needle = _normalise(term)
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                text_pages += 1
            if needle in _normalise(text):
                matches.append(page_number)
        return len(reader.pages), matches, text_pages
    except Exception as exc:
        raise ValueError(f"PDF could not be read: {exc}") from exc


@router.post("/search")
def search_archived_bills(
    payload: SearchRequest,
    _auth: None = Depends(_check_retriever_key),
):
    """
    Search bill PDFs by LG Code or occupier name.
    Returns file IDs, matching page numbers and Drive view links.
    """
    term = payload.search_term.strip()
    drive = _drive_client()
    try:
        files = _archive_pdf_files(drive)
        results = []
        for item in files:
            try:
                pdf_bytes = _download_pdf(drive, item["id"])
                page_count, pages, text_pages = _pdf_page_matches(pdf_bytes, term)
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
                            "Review the matching pages and select the complete "
                            "bill pages before extracting."
                        ) if item["archive_category"] == "Merged PDFs" else
                        "Individual PDF match.",
                    })
                elif text_pages == 0:
                    # Do not silently claim that a scanned PDF has no match.
                    item["_ocr_required"] = True
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
                        "extraction_note": "This PDF appears image-only. OCR is required to search its contents.",
                    })
            except ValueError as exc:
                results.append({
                    "file_id": item["id"],
                    "filename": item["name"],
                    "category": item["archive_category"],
                    "archive_date": item["archive_date"],
                    "status": "READ_ERROR",
                    "detail": str(exc),
                })
        return {
            "search_term": term,
            "files_checked": len(files),
            "matches": len([r for r in results if r.get("matching_pages")]),
            "ocr_required": len([r for r in results if r.get("status") == "OCR_REQUIRED"]),
            "results": results,
        }
    except HTTPException:
        raise
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Drive search failed: {exc}") from exc


@router.post("/extract")
def extract_bill_pages(
    payload: ExtractRequest,
    _auth: None = Depends(_check_retriever_key),
):
    """
    Extract explicitly selected 1-based pages from a merged/individual PDF.
    The original Drive PDF is never changed.
    """
    drive = _drive_client()
    try:
        metadata = drive.files().get(
            fileId=payload.file_id,
            fields="id,name,mimeType,parents,trashed",
        ).execute()
        if metadata.get("trashed") or metadata.get("mimeType") != PDF_MIME_TYPE:
            raise HTTPException(status_code=404, detail="PDF file was not found.")
        parents = metadata.get("parents", [])
        allowed_parent = False
        for parent_id in parents:
            parent = drive.files().get(fileId=parent_id, fields="id,name,parents").execute()
            if parent.get("name") in SEARCH_CATEGORIES:
                allowed_parent = True
                break
        if not allowed_parent:
            raise HTTPException(status_code=403, detail="This PDF is outside the bill archive categories.")
        pdf_bytes = _download_pdf(drive, payload.file_id)
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        page_numbers = sorted(set(payload.pages))
        if any(number < 1 or number > len(reader.pages) for number in page_numbers):
            raise HTTPException(
                status_code=400,
                detail=f"Page numbers must be between 1 and {len(reader.pages)}."
            )

        writer = PdfWriter()
        for number in page_numbers:
            writer.add_page(reader.pages[number - 1])
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)

        safe_name = re.sub(
            r"[^A-Za-z0-9._-]+", "_",
            payload.filename or f"{os.path.splitext(metadata['name'])[0]}_EXTRACTED.pdf"
        )
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        return StreamingResponse(
            output,
            media_type=PDF_MIME_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except HTTPException:
        raise
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Drive download failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not extract PDF pages: {exc}") from exc
