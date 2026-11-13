import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/drive"]


def archive_pdfs_to_drive(pdf_paths, context="PDF archive"):
    """Upload generated PDFs to the configured Drive folder.

    This helper deliberately treats Drive as a secondary archive: missing
    configuration or upload errors are logged and never interrupt bill
    generation or the user's ZIP download.
    """
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    if not all([refresh_token, client_id, client_secret, folder_id]):
        print(f"[Google Drive] Skipped {context}: required environment variables are missing.")
        return {"uploaded": 0, "failed": 0, "skipped": True}

    files_to_upload = [Path(item) for item in pdf_paths if item]
    files_to_upload = [item for item in files_to_upload if item.is_file()]
    if not files_to_upload:
        return {"uploaded": 0, "failed": 0, "skipped": False}

    try:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        credentials.refresh(Request())
        drive = build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
    except Exception as exc:
        print(f"[Google Drive] Could not establish connection for {context}: {exc}")
        return {"uploaded": 0, "failed": len(files_to_upload), "skipped": False}

    uploaded = 0
    failed = 0

    for pdf_path in files_to_upload:
        try:
            metadata = {
                "name": pdf_path.name,
                "parents": [folder_id],
            }
            media = MediaFileUpload(
                str(pdf_path),
                mimetype="application/pdf",
                resumable=True,
            )
            result = drive.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,webViewLink",
            ).execute()
            uploaded += 1
            print(
                f"[Google Drive] Uploaded {result.get('name')} "
                f"(file ID: {result.get('id')})"
            )
        except Exception as exc:
            failed += 1
            print(f"[Google Drive] Failed to upload {pdf_path.name}: {exc}")

    print(
        f"[Google Drive] {context}: uploaded={uploaded}, failed={failed}."
    )
    return {"uploaded": uploaded, "failed": failed, "skipped": False}
