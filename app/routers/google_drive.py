
import os
import secrets

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

router = APIRouter(prefix="/google-drive", tags=["Google Drive"])

SCOPES = ["https://www.googleapis.com/auth/drive"]


def create_flow(request: Request, state=None):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")

    if not all([client_id, client_secret, redirect_uri]):
        raise HTTPException(
            status_code=500,
            detail="Google OAuth environment variables are not configured."
        )

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
    )


@router.get("/connect")
def connect_google_drive(request: Request):
    flow = create_flow(request)

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    request.app.state.google_drive_oauth_state = state

    return RedirectResponse(authorization_url)


@router.get("/callback")
def google_drive_callback(request: Request, code: str = None, state: str = None):
    if not code:
        raise HTTPException(status_code=400, detail="Google authorization code missing.")

    saved_state = getattr(
        request.app.state, "google_drive_oauth_state", None
    )

    if not saved_state or not state or not secrets.compare_digest(saved_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state. Start again.")

    request.app.state.google_drive_oauth_state = None

    flow = create_flow(request, state=saved_state)
    flow.fetch_token(code=code)

    credentials = flow.credentials

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token received. Reconnect and approve access again."
        )

    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

    folders = drive.files().list(
        q="name = 'TENEMENT STORAGE' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id,name)",
        pageSize=20,
    ).execute()

    matches = folders.get("files", [])

    if not matches:
        raise HTTPException(
            status_code=404,
            detail="TENEMENT STORAGE folder was not found in this Google account."
        )

    if len(matches) > 1:
        return JSONResponse({
            "message": "More than one TENEMENT STORAGE folder was found. Folder selection is required.",
            "folders": matches,
        })

    return JSONResponse({
        "message": "Google Drive connected successfully.",
        "folder_name": matches[0]["name"],
        "folder_id": matches[0]["id"],
        "refresh_token": credentials.refresh_token,
        "instruction": "Copy the refresh token and folder ID into Render environment variables. Do not share the token."
    })
