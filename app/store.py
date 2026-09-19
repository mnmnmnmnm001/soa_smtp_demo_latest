"""The data: one dictionary in memory. Restarting the server forgets everything."""
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Uvicorn handles requests in several threads, so two clicks can arrive together.
_lock = threading.Lock()

# Who may ask and who may approve. No file = everyone is allowed.
APPROVED_FILE = Path(__file__).resolve().parent.parent / "approved.json"

_requests = {}   # id -> AbsenceRequest
_next_id = 1


def _now():
    return datetime.now(timezone.utc)


def _new_token():
    # Unguessable and safe to put in a URL.
    return secrets.token_urlsafe(32)


@dataclass
class AbsenceRequest:
    id: int
    employee_email: str
    manager_email: str
    reason: str
    from_date: str
    to_date: str
    status: str = "PENDING"                        # PENDING -> APPROVED or REJECTED
    token: str = field(default_factory=_new_token)  # secret inside the Yes/No links
    created_at: datetime = field(default_factory=_now)


def is_approved(email, role):
    """True if the email is on the list for that role ("employees" or "managers").

    The file is read on every call, so you can edit it while the server runs.
    """
    if not APPROVED_FILE.exists():
        return True
    lists = json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
    allowed = [e.strip().lower() for e in lists.get(role, [])]
    return email.lower() in allowed


def add(employee_email, manager_email, reason, from_date, to_date):
    """Save a new request with status PENDING."""
    global _next_id
    with _lock:
        req = AbsenceRequest(_next_id, employee_email, manager_email,
                             reason, from_date, to_date)
        _requests[req.id] = req
        _next_id += 1
        return req


def get(request_id):
    """One request, or None."""
    return _requests.get(request_id)


def all_requests():
    return list(_requests.values())


def decide(request_id, approved):
    """Write the answer, but only the first time.

    Returns None if the request does not exist or was already answered.
    The lock matters: without it two clicks could both pass the PENDING
    test and the button would work twice.
    """
    with _lock:
        req = _requests.get(request_id)
        if req is None or req.status != "PENDING":
            return None
        req.status = "APPROVED" if approved else "REJECTED"
        return req

