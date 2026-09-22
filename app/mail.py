"""Send email over SMTP, logging in with the sender's own OAuth 2.0 token (XOAUTH2).

The token belongs to whoever is signed in, so the mail really comes from their
mailbox: the worker sends the request, the manager sends the answer.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").strip().rstrip("/")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587      # submission port: plain, then upgraded by STARTTLS


class MailError(Exception):
    """Sending failed; main.py turns this into an answer instead of a crash."""


# autoescape turns a reason containing <script> into harmless text
templates = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def send(sender, token, to, subject, text, html):
    """Send one email FROM `sender`, using that person's access token."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    # Without Date and Message-ID the mail looks machine-made and lands in Spam.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.partition("@")[2] or None)

    # multipart/alternative: plain text first, HTML last (the richest goes last).
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    auth_string = f"user={sender}\x01auth=Bearer {token}\x01\x01"

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())   # encrypt BEFORE the login
            # On a bad token Google sends a challenge; the empty answer ends it with 535.
            smtp.auth("XOAUTH2", lambda challenge=None: auth_string if challenge is None else "")
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as error:
        raise MailError(f"Gmail refused the login for {sender} ({error.smtp_code}). "
                        "Sign in again at /login.")
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"Could not send the email: {error}")


def send_request_to_manager(req, token):
    """Worker's mailbox -> manager, with the two buttons."""
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

    send(req.employee_email, token, req.manager_email,
         f"[ABSENT #{req.id}] Absence request from {req.employee_email}", text, html)


def send_result_to_employee(req, token):
    """Manager's mailbox -> worker, with the decision."""
    text = (f"Your absence request #{req.id} ({req.from_date} to {req.to_date}) "
            f"was {req.status.lower()} by {req.manager_email}.")
    html = templates.get_template("absence_result.html").render(req=req)

    send(req.manager_email, token, req.employee_email,
         f"[ABSENT #{req.id}] Your absence request was {req.status.lower()}", text, html)
