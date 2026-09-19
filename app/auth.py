"""Sign in with Google - only TDTU accounts are accepted.

This is OpenID Connect ("Sign in with Google"), built on OAuth 2.0. We ask for
the scopes "openid email", which only reveal WHO the person is. Nothing here
touches their mailbox.

    1. /login          -> we send the browser to Google's sign-in page
    2. Google          -> the person signs in with their TDTU account
    3. /auth/callback  -> Google sends back a one-time code; we swap it for an
                          ID token, check it, and remember the email in a
                          signed session cookie
"""
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

from .mail import BASE_URL

# The "Web application" OAuth client from Google Cloud (not the Desktop one used for SMTP).
LOGIN_CLIENT_FILE = os.getenv("LOGIN_CLIENT_FILE", "login_client.json")
ALLOWED_DOMAINS = [d.strip().lower() for d in
                   os.getenv("ALLOWED_DOMAINS", "tdtu.edu.vn,student.tdtu.edu.vn").split(",")]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = f"{BASE_URL}/auth/callback"

router = APIRouter(tags=["login"])


def _client():
    """client_id and client_secret of the Web application client."""
    path = Path(LOGIN_CLIENT_FILE)
    if not path.exists():
        raise HTTPException(500, f"{LOGIN_CLIENT_FILE} not found: download the Web client JSON "
                                 "from Google Cloud (see README).")
    web = json.loads(path.read_text())["web"]
    return web["client_id"], web["client_secret"]


def current_user(request: Request):
    """The signed-in email, or None."""
    return request.session.get("email")


def require_user(request: Request):
    """Use in an endpoint that needs a signed-in TDTU user. 401 if nobody is signed in."""
    email = current_user(request)
    if email is None:
        raise HTTPException(401, "Sign in first: open /login in this browser.")
    return email


@router.get("/login")
def login(request: Request, next: str = "/docs"):
    """Step 1: send the browser to Google's sign-in page."""
    client_id, _ = _client()
    # Only allow going back to a page of THIS site, never to another website.
    if not next.startswith("/") or next.startswith("//"):
        next = "/docs"
    # state = a random value we check when Google sends the browser back (stops CSRF).
    state = secrets.token_urlsafe(16)
    request.session["state"] = state
    request.session["next"] = next
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Step 3: Google sent the browser back with a one-time code."""
    if error:
        raise HTTPException(400, f"Google sign-in failed: {error}")
    if not state or state != request.session.pop("state", None):
        raise HTTPException(400, "Sign-in expired or invalid. Open /login again.")

    # Swap the one-time code for tokens - directly between our server and Google.
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

    # The ID token is signed by Google. verify_oauth2_token checks the signature,
    # that it was made for OUR app (audience) and that it has not expired.
    claims = id_token.verify_oauth2_token(answer.json()["id_token"], GoogleRequest(), client_id)

    email = claims.get("email", "").lower()
    domain = email.partition("@")[2]
    if not claims.get("email_verified") or domain not in ALLOWED_DOMAINS:
        raise HTTPException(403, f"Only TDTU accounts may sign in ({', '.join(ALLOWED_DOMAINS)}).")

    request.session["email"] = email
    return RedirectResponse(request.session.pop("next", "/docs"))


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "Signed out."}


@router.get("/me")
def me(request: Request):
    """Who is signed in in this browser (handy in /docs)."""
    return {"email": current_user(request)}
