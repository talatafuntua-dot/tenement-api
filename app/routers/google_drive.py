import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.http import MediaFileUpload

router = APIRouter(prefix="/google-drive", tags=["Google Drive"])

SCOPES = ["https://www.googleapis.com/auth/drive"]
STATE_COOKIE = "google_drive_oauth_state"


def get_settings():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")

    if not all([client_id, client_secret, redirect_uri]):
        raise HTTPException(
            status_code=500,
            detail="Google OAuth environment variables are not configured."
        )

    return client_id, client_secret, redirect_uri


def state_serializer():
    _, client_secret, _ = get_settings()
    return URLSafeTimedSerializer(
        client_secret,
        salt="tenement-google-drive-oauth"
    )


def create_flow(state=None, code_verifier=None):
    client_id, client_secret, redirect_uri = get_settings()

    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )


@router.get("/connect")
def connect_google_drive(request: Request):
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)

    flow = create_flow(state=state, code_verifier=code_verifier)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    signed_data = state_serializer().dumps({
        "state": state,
        "code_verifier": code_verifier,
    })

    response = RedirectResponse(authorization_url)
    response.set_cookie(
        key=STATE_COOKIE,
        value=signed_data,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/google-drive",
    )
    return response


@router.get("/callback")
def google_drive_callback(
    request: Request,
    code: str = None,
    state: str = None,
):
    if not code:
        raise HTTPException(
            status_code=400,
            detail="Google authorization code missing."
        )

    signed_data = request.cookies.get(STATE_COOKIE)
    if not signed_data:
        raise HTTPException(
            status_code=400,
            detail="OAuth session expired. Start again."
        )

    try:
        saved_data = state_serializer().loads(signed_data, max_age=600)
    except BadSignature:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth session. Start again."
        )

    saved_state = saved_data.get("state")
    code_verifier = saved_data.get("code_verifier")

    if (
        not saved_state
        or not code_verifier
        or not state
        or not secrets.compare_digest(saved_state, state)
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state. Start again."
        )

    flow = create_flow(state=saved_state, code_verifier=code_verifier)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token received. Reconnect and approve access again."
        )

    drive = build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False
    )

    folders = drive.files().list(
        q="name = 'TENEMENT STORAGE WEB' and "
          "mimeType = 'application/vnd.google-apps.folder' and "
          "trashed = false",
        fields="files(id,name)",
        pageSize=20,
    ).execute()

    matches = folders.get("files", [])
    if not matches:
        raise HTTPException(
            status_code=404,
            detail="TENEMENT STORAGE WEB folder was not found in this Google account."
        )

    response_data = {
        "message": "Google Drive connected successfully.",
        "folder_name": matches[0]["name"],
        "folder_id": matches[0]["id"],
        "refresh_token": credentials.refresh_token,
        "instruction": (
            "Copy the refresh token and folder ID into Render "
            "environment variables. Keep the refresh token private."
        )
    }

    if len(matches) > 1:
        response_data["message"] = (
            "More than one TENEMENT STORAGE WEB folder was found. "
            "Folder selection is required."
        )
        response_data["folders"] = matches

    response = JSONResponse(response_data)
    response.delete_cookie(key=STATE_COOKIE, path="/google-drive")
    return response


def archive_pdfs_to_drive(pdf_paths, context="PDF archive"):
    """Upload generated PDF files to the configured Google Drive folder.

    Drive is a secondary archive. Upload errors are logged and do not interrupt
    individual or bulk bill generation.
    """
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

    if not all([refresh_token, client_id, client_secret, folder_id]):
        print(
            f"[Google Drive] Skipped {context}: required environment variables are missing."
        )
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
        credentials.refresh(GoogleAuthRequest())
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
            media = MediaFileUpload(
                str(pdf_path),
                mimetype="application/pdf",
                resumable=True,
            )
            result = drive.files().create(
                body={"name": pdf_path.name, "parents": [folder_id]},
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

    print(f"[Google Drive] {context}: uploaded={uploaded}, failed={failed}.")
    return {"uploaded": uploaded, "failed": failed, "skipped": False}
