"""Sign in with Google (TDTU accounts only) and keep each person's send permission.

At sign-in each person approves two things: who they are (openid email) and
permission to send from their mailbox (https://mail.google.com/).

  /login          -> Google's sign-in page
  /auth/callback  -> Google returns a one-time code; we swap it for tokens
"""
import datetime
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials

from .mail import BASE_URL

LOGIN_CLIENT_FILE = os.getenv("LOGIN_CLIENT_FILE", "login_client.json")
ALLOWED_DOMAINS = [d.strip().lower() for d in
                   os.getenv("ALLOWED_DOMAINS", "tdtu.edu.vn,student.tdtu.edu.vn").split(",")]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
REDIRECT_URI = f"{BASE_URL}/auth/callback"   # must be registered in Google Cloud

SCOPES = ["openid", "email", "https://mail.google.com/"]

_tokens = {}   # email -> Credentials, in memory only

router = APIRouter(tags=["login"])


def _client():
    path = Path(LOGIN_CLIENT_FILE)
    if not path.exists():
        raise HTTPException(500, f"{LOGIN_CLIENT_FILE} not found: download the Web client JSON "
                                 "from Google Cloud (see README).")
    web = json.loads(path.read_text())["web"]
    return web["client_id"], web["client_secret"]


def current_user(request: Request):
    return request.session.get("email")


def require_user(request: Request):
    email = current_user(request)
    if email is None:
        raise HTTPException(401, "Sign in first: open /login in this browser.")
    return email


def has_send_permission(email):
    """False after a restart: the cookie survives, the token does not."""
    return email in _tokens


def token_for(email):
    """That person's access token, refreshed if it has expired."""
    creds = _tokens.get(email)
    if creds is None:
        raise HTTPException(401, f"No send permission for {email}. Open /login again.")
    if not creds.valid and creds.refresh_token:
        creds.refresh(GoogleRequest())
    return creds.token


@router.get("/login")
def login(request: Request, next: str = "/docs", force: bool = False, hint: str = ""):
    """hint = which account we expect, so Google does not ask when it is signed in.

    force=1 always shows the account chooser and consent (handy when demoing).
    """
    client_id, _ = _client()
    if not next.startswith("/") or next.startswith("//"):
        next = "/docs"   # never send people to another website
    state = secrets.token_urlsafe(16)   # checked on the way back: stops CSRF
    request.session["state"] = state
    request.session["next"] = next
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",
    }
    if hint:
        params["login_hint"] = hint
    # Without "prompt" Google asks only the first time; later sign-ins are silent
    # if that browser is already signed in and has approved the app.
    if force:
        params["prompt"] = "consent select_account"
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        raise HTTPException(400, f"Google sign-in failed: {error}")
    if not state or state != request.session.pop("state", None):
        raise HTTPException(400, "Sign-in expired or invalid. Open /login again.")

    # Swap the one-time code for tokens, server to server.
    client_id, client_secret = _client()
    answer = requests.post(GOOGLE_TOKEN_URL, timeout=15, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    if answer.status_code != 200:
        raise HTTPException(400, "Google did not accept the sign-in code. Open /login again.")
    tokens = answer.json()

    # Checks Google's signature, that it is for OUR app, and that it is not expired.
    claims = id_token.verify_oauth2_token(tokens["id_token"], GoogleRequest(), client_id)

    email = claims.get("email", "").lower()
    domain = email.partition("@")[2]
    if not claims.get("email_verified") or domain not in ALLOWED_DOMAINS:
        raise HTTPException(403, f"Only TDTU accounts may sign in ({', '.join(ALLOWED_DOMAINS)}).")

    # The permissions are separate checkboxes and are NOT ticked by default.
    if "https://mail.google.com/" not in tokens.get("scope", ""):
        raise HTTPException(403,
            "You did not allow sending email. Open /login?force=1 and TICK the box "
            "that lets the app send email on your behalf - without it nothing can be sent.")

    previous = _tokens.get(email)
    _tokens[email] = Credentials(
        token=tokens["access_token"],
        # Google sends a refresh token only on the first approval.
        refresh_token=tokens.get("refresh_token") or getattr(previous, "refresh_token", None),
        token_uri=GOOGLE_TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
        expiry=(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                + datetime.timedelta(seconds=tokens["expires_in"] - 60)),
    )
    request.session["email"] = email
    return RedirectResponse(request.session.pop("next", "/docs"))


@router.get("/logout")
def logout(request: Request):
    """Sign out, and ask Google to cancel the permission for good.

    Forgetting our copy is not enough: Google would hand us a new token at the
    next sign-in without asking again.
    """
    creds = _tokens.pop(request.session.get("email", ""), None)
    request.session.clear()
    revoked = False
    if creds is not None:
        try:
            answer = requests.post(GOOGLE_REVOKE_URL, timeout=10,
                                   data={"token": creds.refresh_token or creds.token})
            revoked = answer.status_code == 200
        except requests.RequestException:
            revoked = False
    return {"message": "Signed out.", "permission_revoked_at_google": revoked}


@router.get("/me")
def me(request: Request):
    email = current_user(request)
    return {"email": email, "can_send": email in _tokens}
