
import os
import secrets

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.http import MediaFileUpload
from pathlib import Path

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

    # Generate and preserve the PKCE verifier for the callback.
    code_verifier = secrets.token_urlsafe(64)

    flow = create_flow(
        state=state,
        code_verifier=code_verifier
    )

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    # Sign both values so they cannot be altered by the browser.
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
        saved_data = state_serializer().loads(
            signed_data,
            max_age=600
        )
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

    # Recreate the flow with the SAME PKCE verifier used at connection.
    flow = create_flow(
        state=saved_state,
        code_verifier=code_verifier
    )

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
    response.delete_cookie(
        key=STATE_COOKIE,
        path="/google-drive"
    )

    return response
from pathlib import Path
