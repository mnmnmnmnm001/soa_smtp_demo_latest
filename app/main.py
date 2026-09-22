"""The API.  Run:  uvicorn app.main:app --reload

  1. worker   POST /nghiphep           -> PENDING, emails the manager (from the worker)
  2. manager  clicks Yes / No          -> GET /nghiphep/{id}/decision
  3.          the answer is saved      -> APPROVED or REJECTED
  4.          emails the worker (from the manager) and shows a small page
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

# Signs the login cookie. A random one means everybody is signed out on restart.
app.add_middleware(SessionMiddleware,
                   secret_key=os.getenv("SESSION_SECRET") or secrets.token_urlsafe(32))
app.include_router(auth.router)

DECISION_VALID_HOURS = 48


class AbsenceIn(BaseModel):
    """Checked by FastAPI before our code runs; bad input answers 422."""
    manager_email: EmailStr   # the worker is whoever is signed in
    reason: str = Field(min_length=1, max_length=500)
    from_date: date
    to_date: date


def as_json(req):
    """Listed field by field so the secret token can never leak."""
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
    html = mail.templates.get_template("decision_page.html").render(
        title=title, message=message, color=color)
    return HTMLResponse(html, status_code=status)


@app.post("/nghiphep", status_code=201)
def create_absence(body: AbsenceIn, request: Request):
    employee = auth.require_user(request)
    manager = body.manager_email.lower()

    # Checked before saving or emailing, so a refused request leaves no trace.
    if employee == manager:
        raise HTTPException(400, "You cannot be your own manager.")
    if not store.is_approved(employee, "employees"):
        raise HTTPException(403, f"{employee} is not on the approved employee list")
    if not store.is_approved(manager, "managers"):
        raise HTTPException(403, f"{manager} is not on the approved manager list")

    req = store.add(employee, manager, body.reason, str(body.from_date), str(body.to_date))
    try:
        mail.send_request_to_manager(req, auth.token_for(employee))
    except mail.MailError as error:
        store.remove(req.id)   # without the email nobody could answer it
        raise HTTPException(502, str(error))
    return {"id": req.id, "status": req.status,
            "message": f"Email with Yes / No buttons sent to {req.manager_email}."}


@app.get("/nghiphep/{request_id}/decision", response_class=HTMLResponse)
def decide(request_id: int, answer: str, token: str, request: Request):
    req = store.get(request_id)

    # One answer for all three: telling them apart would help somebody guessing.
    # compare_digest takes constant time, so the token cannot be found letter by letter.
    if (req is None or answer not in ("yes", "no")
            or not hmac.compare_digest(token, req.token)):
        return page("Invalid link", "This link is not valid.", "#d93025", 400)

    # The link alone is not enough, so a forwarded email is useless.
    email = auth.current_user(request)
    if email is None:
        # We know which account is needed, so Google can sign them in without asking.
        here = f"/nghiphep/{request_id}/decision?answer={answer}&token={token}"
        return RedirectResponse(f"/login?next={quote(here)}&hint={quote(req.manager_email)}")
    if email != req.manager_email:
        return page("Wrong account",
                    f"You are signed in as {email}. Sign in with the manager's TDTU account "
                    "(open /logout first).", "#d93025", 403)

    # Right person, but the server was restarted since they signed in: send them
    # through Google again (silent) instead of failing after saving the answer.
    if not auth.has_send_permission(email):
        here = f"/nghiphep/{request_id}/decision?answer={answer}&token={token}"
        return RedirectResponse(f"/login?next={quote(here)}&hint={quote(req.manager_email)}")

    if req.status != "PENDING":
        return page("Already answered",
                    f"This request was already {req.status.lower()}. Nothing was changed.",
                    "#5f6368")

    if datetime.now(timezone.utc) - req.created_at > timedelta(hours=DECISION_VALID_HOURS):
        return page("Link expired", "This request is too old to be answered.", "#f29900", 410)

    updated = store.decide(request_id, answer == "yes")
    if updated is None:   # two clicks in the same instant
        return page("Already answered", "This request was already answered.", "#5f6368")

    try:
        mail.send_result_to_employee(updated, auth.token_for(email))
    except (mail.MailError, HTTPException) as error:
        # The answer is saved: say so, instead of inviting another click.
        return page("Answer saved, email failed",
                    f"Your answer was saved, but the email to {updated.employee_email} "
                    f"could not be sent: {getattr(error, 'detail', error)}", "#f29900", 502)

    approved = updated.status == "APPROVED"
    return page("Request approved" if approved else "Request rejected",
                f"Thank you. {updated.employee_email} has been notified by email.",
                "#188038" if approved else "#d93025")


@app.get("/nghiphep")
def list_absences(request: Request):
    """Only your own requests: a reason is private."""
    email = auth.require_user(request)
    return [as_json(req) for req in store.all_requests()
            if email in (req.employee_email, req.manager_email)]


@app.get("/nghiphep/{request_id}")
def get_absence(request_id: int, request: Request):
    email = auth.require_user(request)
    req = store.get(request_id)
    if req is None or email not in (req.employee_email, req.manager_email):
        raise HTTPException(404, "Absence request not found")   # 404, not 403: reveals nothing
    return as_json(req)
