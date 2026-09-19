"""The API.  Run:  uvicorn app.main:app --reload

Sign in first: open /login and use a TDTU account (see auth.py).

The whole flow:
  1. employee  POST /nghiphep            -> saved as PENDING, manager gets an email
  2. manager   clicks Yes or No          -> GET /nghiphep/{id}/decision
  3. system    saves the answer          -> APPROVED or REJECTED
  4. system    emails the employee       -> and shows the manager a small page
     anyone   GET /nghiphep/{id}         -> read the status
"""
import hmac
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.sessions import SessionMiddleware

from . import auth, mail, store

app = FastAPI(title="Absence request demo (SMTP + OAuth 2.0)")

# The login is kept in a cookie signed with this secret, so nobody can forge it.
# Without SESSION_SECRET in .env a random one is used: everyone is signed out on restart.
app.add_middleware(SessionMiddleware,
                   secret_key=os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32))
app.include_router(auth.router)

# How long the Yes / No buttons keep working.
DECISION_VALID_HOURS = 48


class AbsenceIn(BaseModel):
    """FastAPI checks the body against this BEFORE our code runs.

    A bad email address or an empty reason is answered with 422 automatically.
    """
    manager_email: EmailStr   # the employee is whoever is signed in
    reason: str = Field(min_length=1, max_length=500)
    from_date: date
    to_date: date


def as_json(req):
    """What the API shows. Note the token is NOT here - it lives only in the email."""
    return {
        "id": req.id,
        "status": req.status,
        "employee_email": req.employee_email,
        "manager_email": req.manager_email,
        "from_date": req.from_date,
        "to_date": req.to_date,
        "reason": req.reason,
    }


def page(title, message, color, status=200):
    """The small web page the manager sees after clicking a button."""
    html = mail.templates.get_template("decision_page.html").render(
        title=title, message=message, color=color)
    return HTMLResponse(html, status_code=status)


# --- 1. the employee asks -----------------------------------------------------
@app.post("/nghiphep", status_code=201)
def create_absence(body: AbsenceIn, request: Request):
    employee = auth.require_user(request)   # 401 if nobody is signed in
    manager = body.manager_email.lower()

    # Only listed people may take part. Checked BEFORE saving or emailing,
    # so a refused request leaves no trace.
    if not store.is_approved(employee, "employees"):
        raise HTTPException(403, f"{employee} is not on the approved employee list")
    if not store.is_approved(manager, "managers"):
        raise HTTPException(403, f"{manager} is not on the approved manager list")

    req = store.add(employee, manager, body.reason, str(body.from_date), str(body.to_date))
    mail.send_request_to_manager(req)
    return {"id": req.id, "status": req.status,
            "message": f"Email with Yes / No buttons sent to {req.manager_email}."}


# --- 2 & 3. the manager answers ----------------------------------------------
@app.get("/nghiphep/{request_id}/decision", response_class=HTMLResponse)
def decide(request_id: int, answer: str, token: str, request: Request):
    req = store.get(request_id)

    # Unknown request, silly answer and wrong token all give the SAME page:
    # telling them apart would help somebody guessing links.
    # compare_digest takes the same time whatever the input, so the token
    # cannot be found one letter at a time by measuring the delay.
    if (req is None or answer not in ("yes", "no")
            or not hmac.compare_digest(token, req.token)):
        return page("Invalid link", "This link is not valid.", "#d93025", 400)

    # The link alone is not enough: you must also be signed in as THIS request's
    # manager. A forwarded email is useless to anyone else.
    email = auth.current_user(request)
    if email is None:
        here = f"/nghiphep/{request_id}/decision?answer={answer}&token={token}"
        return RedirectResponse(f"/login?next={quote(here)}")
    if email != req.manager_email:
        return page("Wrong account",
                    f"You are signed in as {email}. Sign in with the manager's TDTU account "
                    "(open /logout first).", "#d93025", 403)

    if req.status != "PENDING":
        return page("Already answered",
                    f"This request was already {req.status.lower()}. Nothing was changed.",
                    "#5f6368")

    if datetime.now(timezone.utc) - req.created_at > timedelta(hours=DECISION_VALID_HOURS):
        return page("Link expired", "This request is too old to be answered.", "#f29900", 410)

    updated = store.decide(request_id, answer == "yes")
    if updated is None:  # someone clicked at the very same moment
        return page("Already answered", "This request was already answered.", "#5f6368")

    # --- 4. tell the employee ---
    mail.send_result_to_employee(updated)

    approved = updated.status == "APPROVED"
    return page("Request approved" if approved else "Request rejected",
                f"Thank you. {updated.employee_email} has been notified by email.",
                "#188038" if approved else "#d93025")


# --- reading the status -------------------------------------------------------
@app.get("/nghiphep")
def list_absences():
    return [as_json(req) for req in store.all_requests()]


@app.get("/nghiphep/{request_id}")
def get_absence(request_id: int):
    req = store.get(request_id)
    if req is None:
        raise HTTPException(404, "Absence request not found")
    return as_json(req)
