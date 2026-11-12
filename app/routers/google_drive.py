
import os
import secrets

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

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


def create_flow(state=None):
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
    )


def state_serializer():
    _, client_secret, _ = get_settings()
    return URLSafeTimedSerializer(
        client_secret,
        salt="tenement-google-drive-oauth"
    )


@router.get("/connect")
def connect_google_drive():
    flow = create_flow()

    state = secrets.token_urlsafe(32)

    authorization_url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    response = RedirectResponse(authorization_url)

    signed_state = state_serializer().dumps(state)

    response.set_cookie(
        key=STATE_COOKIE,
        value=signed_state,
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
    state: str = None
):
    if not code:
        raise HTTPException(
            status_code=400,
            detail="Google authorization code missing."
        )

    signed_state = request.cookies.get(STATE_COOKIE)

    if not signed_state or not state:
        raise HTTPException(
            status_code=400,
            detail="OAuth session missing. Start again from Connect Google Drive."
        )

    try:
        saved_state = state_serializer().loads(
            signed_state,
            max_age=600
        )
    except BadSignature:
        raise HTTPException(
            status_code=400,
            detail="OAuth state expired or invalid. Start again."
        )

    if not secrets.compare_digest(saved_state, state):
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state. Start again."
        )

    flow = create_flow(state=state)
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
        response = JSONResponse({
            "message": "More than one TENEMENT STORAGE folder was found.",
            "folders": matches,
            "instruction": "Folder selection is required."
        })
        response.delete_cookie(STATE_COOKIE, path="/google-drive")
        return response

    response = JSONResponse({
        "message": "Google Drive connected successfully.",
        "folder_name": matches[0]["name"],
        "folder_id": matches[0]["id"],
        "refresh_token": credentials.refresh_token,
        "instruction": "Copy the refresh token and folder ID into Render environment variables. Keep the refresh token private."
    })

    response.delete_cookie(STATE_COOKIE, path="/google-drive")

    return response
