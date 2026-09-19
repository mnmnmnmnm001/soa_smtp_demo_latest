"""Sending email with SMTP, logging in with an OAuth 2.0 token from Google Cloud.

SMTP is the standard protocol for sending email. We connect to Gmail's SMTP
server, encrypt the connection (STARTTLS), and log in with XOAUTH2: instead of
a password we send an OAuth 2.0 access token.

Where the token comes from:
    credentials.json   who this app is       (downloaded from Google Cloud)
    consent screen     the owner says "yes"  (once, in the browser)
    token.json         proof of that "yes"   (created by check_gmail.py)
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from jinja2 import Environment, FileSystemLoader, select_autoescape

load_dotenv()  # read the .env file, so no secret is written in the code

MAIL_ADDRESS = os.getenv("MAIL_ADDRESS", "").strip()
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").strip().rstrip("/")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

# Gmail's SMTP server. Port 587 = start in plain text, then upgrade with STARTTLS.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# Google only accepts OAuth logins over SMTP with this scope (full mail access).
SCOPES = ["https://mail.google.com/"]

# autoescape turns a reason containing <script> into harmless text
templates = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def get_credentials(interactive=False):
    """Return a usable token. interactive=True may open the browser."""
    creds = None
    if Path(TOKEN_FILE).exists():
        saved = json.loads(Path(TOKEN_FILE).read_text())
        # A token made for another scope is useless here: ignore it and ask again.
        if set(SCOPES) <= set(saved.get("scopes", [])):
            creds = Credentials.from_authorized_user_info(saved, SCOPES)

    if creds and creds.valid:                  # 1. still good
        return creds

    if creds and creds.refresh_token:          # 2. expired, but renewable
        creds.refresh(Request())
        Path(TOKEN_FILE).write_text(creds.to_json())
        return creds

    if not interactive:                        # 3. we need a human
        raise RuntimeError("Gmail is not authorized. Run:  python check_gmail.py")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    Path(TOKEN_FILE).write_text(creds.to_json())
    return creds


def send(to, subject, text, html):
    """Build one email (plain text + HTML) and send it over SMTP."""
    msg = EmailMessage()
    msg["From"] = MAIL_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    # Real mail programs always set these two. Without them the message looks
    # machine-generated and is more likely to land in Spam.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=MAIL_ADDRESS.partition("@")[2] or None)

    msg.set_content(text)                      # shown when HTML is not available
    msg.add_alternative(html, subtype="html")  # what people normally see

    # XOAUTH2 login string: the access token takes the place of a password.
    token = get_credentials().token
    auth_string = f"user={MAIL_ADDRESS}\x01auth=Bearer {token}\x01\x01"

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())  # 1. encrypt first
        # 2. log in with the token. If Google refuses it, it sends a challenge
        #    and we answer with an empty line, which ends with a clear error.
        smtp.auth("XOAUTH2", lambda challenge=None: auth_string if challenge is None else "")
        smtp.send_message(msg)                               # 3. send


def send_request_to_manager(req):
    """Step 2 of the flow: email the manager, with a Yes and a No button.

    Both links carry the same secret token. Holding that token is the proof
    that you received the email - there is no login.
    """
    link = f"{BASE_URL}/nghiphep/{req.id}/decision"
    yes_url = f"{link}?answer=yes&token={req.token}"
    no_url = f"{link}?answer=no&token={req.token}"

    text = (f"{req.employee_email} asks for an absence.\n\n"
            f"From:   {req.from_date}\n"
            f"To:     {req.to_date}\n"
            f"Reason: {req.reason}\n\n"
            f"Yes, approve: {yes_url}\n"
            f"No, reject:   {no_url}\n")
    html = templates.get_template("absence_request.html").render(
        req=req, yes_url=yes_url, no_url=no_url)

    send(req.manager_email,
         f"[ABSENT #{req.id}] Absence request from {req.employee_email}", text, html)


def send_result_to_employee(req):
    """Step 4 of the flow: tell the employee what the manager decided."""
    text = (f"Your absence request #{req.id} ({req.from_date} to {req.to_date}) "
            f"was {req.status.lower()} by {req.manager_email}.")
    html = templates.get_template("absence_result.html").render(req=req)

    send(req.employee_email,
         f"[ABSENT #{req.id}] Your absence request was {req.status.lower()}", text, html)
