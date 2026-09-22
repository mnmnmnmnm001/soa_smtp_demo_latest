"""The data: one dictionary in memory. A restart forgets everything."""
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Uvicorn uses several threads, so two clicks can arrive at the same moment.
_lock = threading.Lock()

APPROVED_FILE = Path(__file__).resolve().parent.parent / "approved.json"

_requests = {}   # id -> AbsenceRequest
_next_id = 1


def _now():
    return datetime.now(timezone.utc)


def _new_token():
    return secrets.token_urlsafe(32)


@dataclass
class AbsenceRequest:
    id: int
    employee_email: str
    manager_email: str
    reason: str
    from_date: str
    to_date: str
    status: str = "PENDING"                         # -> APPROVED or REJECTED
    token: str = field(default_factory=_new_token)  # secret inside the Yes/No links
    created_at: datetime = field(default_factory=_now)


def is_approved(email, role):
    """role is "employees" or "managers". No approved.json = everyone allowed."""
    if not APPROVED_FILE.exists():
        return True
    lists = json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
    allowed = [e.strip().lower() for e in lists.get(role, [])]
    return email.lower() in allowed


def add(employee_email, manager_email, reason, from_date, to_date):
    global _next_id
    with _lock:
        req = AbsenceRequest(_next_id, employee_email, manager_email,
                             reason, from_date, to_date)
        _requests[req.id] = req
        _next_id += 1
        return req


def remove(request_id):
    with _lock:
        _requests.pop(request_id, None)


def get(request_id):
    return _requests.get(request_id)


def all_requests():
    return list(_requests.values())


def decide(request_id, approved):
    """Write the answer once. Returns None if it was already answered.

    The lock makes "check PENDING, then write" one step, so two clicks
    arriving together cannot both succeed.
    """
    with _lock:
        req = _requests.get(request_id)
        if req is None or req.status != "PENDING":
            return None
        req.status = "APPROVED" if approved else "REJECTED"
        return req
