"""Database tables. One organisation for now: auth and per-customer separation come later."""
from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class BookLineRow(Base):
    """One line of the customer's book stock: the plan of locations and the quantities to count against."""
    __tablename__ = "book_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    item: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(100), index=True)
    book_qty: Mapped[int]
    unit_cost: Mapped[float]


class Clip(Base):
    """An uploaded video and what the pipeline made of it. sha256 is computed by the server on receipt."""
    __tablename__ = "clips"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))  # stored name "<id>.<ext>"; also the cache key for model output
    original_name: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    duration_seconds: Mapped[float | None] = mapped_column(default=None)  # length of the video, when ffprobe could read it
    uploaded_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed
    error: Mapped[str] = mapped_column(String(2000), default="")
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    # Pipeline result
    location: Mapped[str | None] = mapped_column(String(100), default=None)
    item: Mapped[str | None] = mapped_column(String(200), default=None)
    counted: Mapped[int | None] = mapped_column(default=None)
    needs_review: Mapped[bool] = mapped_column(default=False)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[str] = mapped_column(String(500), default="")
    transcript: Mapped[str] = mapped_column(String(4000), default="")
    # Set by a reviewer when the narration did not name a recognisable location
    review_location: Mapped[str | None] = mapped_column(String(100), default=None)
    captured_by: Mapped[str | None] = mapped_column(String(200), default=None)  # the capturer, who may not review this clip
    captured_by_id: Mapped[str | None] = mapped_column(String(100), default=None)  # their employee ID
    # The playable preview copy, made after counting: None = not made yet, "" = could not be made, else its path under the data folder
    preview: Mapped[str | None] = mapped_column(String(500), default=None)
    preview_progress: Mapped[int | None] = mapped_column(default=None)  # percent done while it is being made
    preview_error: Mapped[str | None] = mapped_column(String(500), default=None)  # why it could not be made


class Blob(Base):
    """A small file kept in the database so it survives a restart of the host's disk. Key is the path under the data folder."""
    __tablename__ = "blobs"
    key: Mapped[str] = mapped_column(String(500), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Investigation(Base):
    """A reviewer's session on one clip's frame: SAM proposes cartons, the reviewer includes, excludes, adds and labels them.

    `objects` is the current working set; every change is also appended to InvestigationEvent, which is never edited.
    """
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(200))
    reviewer_id: Mapped[str | None] = mapped_column(String(100), default=None)  # employee ID
    location: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    outcome: Mapped[str] = mapped_column(String(20), default="")  # confirmed | unresolved
    note: Mapped[str] = mapped_column(String(2000), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)
    frame: Mapped[str] = mapped_column(String(500))  # path under the data folder
    frame_w: Mapped[int]
    frame_h: Mapped[int]
    machine_count: Mapped[int | None] = mapped_column(default=None)  # the clip's count before anyone edited anything
    objects: Mapped[list] = mapped_column(JSON, default=list)


class InvestigationEvent(Base):
    """Append-only log of what the reviewer did, so a final count can be traced from the machine proposal."""
    __tablename__ = "investigation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    at: Mapped[datetime] = mapped_column(default=_now)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Review(Base):
    """One line of a reviewer's decision. A submission is a batch; the latest batch for a clip wins and older ones stay as history."""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"), index=True)
    batch: Mapped[str] = mapped_column(String(32))
    item: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int]
    reviewer: Mapped[str] = mapped_column(String(200))
    reviewer_id: Mapped[str | None] = mapped_column(String(100), default=None)  # employee ID
    note: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
