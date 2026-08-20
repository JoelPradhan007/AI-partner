"""
oauth.py
~~~~~~~~
Google OAuth 2.0 via Authlib.
Authlib stores the state in the session automatically and validates it
on callback — this is why it solves the "missing OAuth state" problem.
"""
import json
import logging

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from google.oauth2.credentials import Credentials
import google.auth.transport.requests
from cryptography.fernet import Fernet

from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Authlib OAuth registry ────────────────────────────────────────
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.readonly "
            "https://www.googleapis.com/auth/drive.readonly "
            "https://www.googleapis.com/auth/calendar.readonly"
        ),
        "prompt": "consent",
        "access_type": "offline",
    },
)


async def get_google_auth_url(request: Request) -> str:
    """Generate the Google consent URL. Authlib saves state in session."""
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


async def handle_google_callback(request: Request) -> dict:
    """
    Exchange the auth code for tokens.
    Authlib validates the state automatically — no manual session check needed.
    Returns a dict with token + userinfo.
    """
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or await oauth.google.userinfo(token=token)
    return {"token": token, "userinfo": userinfo}


# ── Token encryption ──────────────────────────────────────────────

def _fernet() -> Fernet:
    key = settings.fernet_key
    if not key:
        raise RuntimeError("FERNET_KEY is not set in .env")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: dict) -> bytes:
    payload = {
        "token":         token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "token_uri":     "https://oauth2.googleapis.com/token",
        "client_id":     settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "scopes":        token.get("scope", "").split(),
    }
    return _fernet().encrypt(json.dumps(payload).encode())


def decrypt_token(encrypted: bytes) -> dict:
    return json.loads(_fernet().decrypt(bytes(encrypted)).decode())


def build_credentials(user) -> Credentials:
    """
    Decrypt stored credentials, refresh if expired, return Credentials object.
    """
    cred_dict = decrypt_token(user.encrypted_credentials)

    creds = Credentials(
        token         = cred_dict["token"],
        refresh_token = cred_dict["refresh_token"],
        token_uri     = cred_dict["token_uri"],
        client_id     = cred_dict["client_id"],
        client_secret = cred_dict["client_secret"],
        scopes        = cred_dict["scopes"],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        cred_dict["token"] = creds.token
        user.encrypted_credentials = _fernet().encrypt(json.dumps(cred_dict).encode())
        # Caller is responsible for committing the session

    return creds
