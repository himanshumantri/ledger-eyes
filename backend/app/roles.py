"""Separation of duties: whoever filmed a shelf cannot also decide its count."""
from fastapi import HTTPException

from app.tables import Clip


def label(name: str, employee_id: str | None) -> str:
    """How a person is shown in reports: the name, and the employee ID when one was given."""
    return f"{name.strip()} ({employee_id.strip()})" if employee_id and employee_id.strip() else name.strip()


def require_not_capturer(clip: Clip, reviewer: str, reviewer_id: str | None = None) -> None:
    """Same employee ID, or (when an ID is missing on either side) the same name, means the same person."""
    same_id = bool(clip.captured_by_id and reviewer_id and clip.captured_by_id.strip().casefold() == reviewer_id.strip().casefold())
    same_name = bool(clip.captured_by and clip.captured_by.strip().casefold() == reviewer.strip().casefold())
    if same_id or same_name:
        raise HTTPException(409, f"{reviewer.strip()} captured this clip, so someone else must review it")
