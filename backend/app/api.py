"""HTTP API: plan (book stock), clip upload and status, reviewer decisions, reconciliation downloads.

Models and the database are injected so tests run with a fake pipeline and an in-memory database.
"""
import hashlib
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import MAX_UPLOAD_MB, MAX_VIDEO_FRAMES, MAX_VIDEO_SECONDS, OUT
from app.files import restore_blob
from app.jobs import Runner, book_lines, build_preview, process_clip
from app.media import duration_seconds, frame_count, make_preview
from app.ranged import ranged_file
from app.reconcile import ClipResult, ReviewLine, Row, parse_book, reconcile, write_reports
from app.roles import label, require_not_capturer
from app.tables import BookLineRow, Clip, Review


class ReviewLineIn(BaseModel):
    item: str = Field(min_length=1, max_length=200)
    qty: int = Field(ge=0)
    note: str = Field(default="", max_length=1000)


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    reviewer_id: str | None = Field(default=None, max_length=100)
    lines: list[ReviewLineIn] = Field(min_length=1)
    location: str | None = None  # only needed when the narration did not resolve one


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def latest_review(s: Session, clip_id: str) -> list[Review]:
    newest = s.scalars(select(Review).where(Review.clip_id == clip_id).order_by(Review.id.desc()).limit(1)).first()
    if newest is None:
        return []
    return list(s.scalars(select(Review).where(Review.clip_id == clip_id, Review.batch == newest.batch).order_by(Review.id)))


def preview_state(c: Clip) -> str:
    """ready: playable; pending: still being made; none: there is none (older clip, or it could not be made)."""
    if c.preview:
        return "ready"
    if c.preview == "":
        return "failed" if c.preview_error else "none"
    if c.status in ("queued", "running"):
        return "pending"
    finished = c.finished_at.replace(tzinfo=UTC) if c.finished_at and c.finished_at.tzinfo is None else c.finished_at
    return "pending" if c.status == "done" and finished and datetime.now(UTC) - finished < timedelta(minutes=60) else "none"


def clip_json(s: Session, c: Clip) -> dict:
    review = latest_review(s, c.id)
    return {
        "id": c.id, "captured_by": c.captured_by, "captured_by_id": c.captured_by_id, "original_name": c.original_name, "sha256": c.sha256, "size_bytes": c.size_bytes, "duration_seconds": c.duration_seconds,
        "uploaded_at": _iso(c.uploaded_at), "finished_at": _iso(c.finished_at), "status": c.status, "error": c.error,
        "location": c.review_location or c.location, "narrated_location": c.location, "item": c.item,
        "machine_count": c.counted, "needs_review": c.needs_review, "reasons": c.reasons,
        "has_evidence": bool(c.evidence), "preview": preview_state(c), "preview_progress": c.preview_progress, "preview_error": c.preview_error, "transcript": c.transcript,
        "review": {
            "reviewer": review[0].reviewer, "reviewer_id": review[0].reviewer_id, "created_at": _iso(review[0].created_at),
            "lines": [{"item": r.item, "qty": r.qty, "note": r.note} for r in review],
        } if review else None,
    }


def reconciliation_rows(s: Session) -> list[Row]:
    """Latest finished clip per location is the one counted, so a re-film replaces the earlier clip."""
    canonical: dict[str, ClipResult] = {}
    reviews: dict[str, list[ReviewLine]] = {}
    for c in s.scalars(select(Clip).where(Clip.status == "done").order_by(Clip.uploaded_at, Clip.id)):
        location = c.review_location or c.location
        if location is None:
            continue  # nothing to reconcile it against until a reviewer names the location
        canonical[location] = ClipResult(c.filename, location, c.item, c.counted or 0, c.needs_review, list(c.reasons), c.evidence, c.transcript)
        reviews[c.filename] = [ReviewLine(c.filename, r.item, r.qty, label(r.reviewer, r.reviewer_id), r.note) for r in latest_review(s, c.id)]
    return reconcile(book_lines(s), canonical, {k: v for k, v in reviews.items() if v})


def row_json(r: Row) -> dict:
    return {
        "location": r.location, "item": r.item, "book_qty": r.book_qty, "counted_qty": r.counted_qty,
        "variance_qty": r.variance_qty, "unit_cost": r.unit_cost, "variance_value": r.variance_value, "status": r.status,
        "count_source": r.count_source, "reviewer": r.reviewer, "flag": r.flag, "note": r.note,
    }


def create_router(sessions: sessionmaker[Session], uploads: Path, runner: Runner, out: Path = OUT) -> APIRouter:
    router = APIRouter()

    def db():
        with sessions() as s:
            yield s

    # --- plan ---------------------------------------------------------------
    @router.put("/plan")
    async def put_plan(file: UploadFile = File(...), s: Session = Depends(db)) -> dict:
        """Replace the book stock with an ERP export: item, location, book_qty, unit_cost."""
        try:
            lines = parse_book((await file.read()).decode("utf-8-sig").splitlines())
        except (ValueError, UnicodeDecodeError) as e:
            raise HTTPException(422, f"Could not read book stock CSV: {e}") from e
        if not lines:
            raise HTTPException(422, "Book stock CSV has no rows")
        s.execute(delete(BookLineRow))
        s.add_all(BookLineRow(item=b.item, location=b.location, book_qty=b.book_qty, unit_cost=b.unit_cost) for b in lines)
        s.commit()
        return {"lines": len(lines), "locations": len({b.location for b in lines})}

    @router.get("/plan")
    def get_plan(s: Session = Depends(db)) -> dict:
        lines = book_lines(s)
        return {
            "locations": sorted({b.location for b in lines}),
            "lines": [{"item": b.item, "location": b.location, "book_qty": b.book_qty, "unit_cost": b.unit_cost} for b in lines],
        }

    # --- clips --------------------------------------------------------------
    @router.post("/clips", status_code=201)
    async def upload_clip(
        background: BackgroundTasks,
        file: UploadFile = File(...),
        client_sha256: str | None = Form(default=None),
        captured_by: str | None = Form(default=None),
        captured_by_id: str | None = Form(default=None),
        s: Session = Depends(db),
    ) -> dict:
        """Store a video, hash it on arrival and queue it for counting. If the client sent its own hash and it differs, reject."""
        if not (file.content_type or "").startswith("video/"):
            raise HTTPException(415, "Upload a video file")
        if not book_lines(s):
            raise HTTPException(409, "Upload the book stock (PUT /plan) before clips")
        clip_id = uuid.uuid4().hex
        name = f"{clip_id}{Path(file.filename or '').suffix.lower()[:10]}"
        uploads.mkdir(parents=True, exist_ok=True)
        path, digest, size = uploads / name, hashlib.sha256(), 0
        with path.open("wb") as video_file:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    video_file.close()
                    path.unlink(missing_ok=True)
                    raise HTTPException(413, f"Video is larger than {MAX_UPLOAD_MB} MB. Film at 720p to keep long videos small.")
                digest.update(chunk)
                video_file.write(chunk)
        if client_sha256 and client_sha256.lower() != digest.hexdigest():
            path.unlink(missing_ok=True)
            raise HTTPException(422, "The video changed in transit: its hash does not match the one the device sent")
        length, frames = duration_seconds(path), frame_count(path)
        if length is not None and length > MAX_VIDEO_SECONDS:
            path.unlink(missing_ok=True)
            raise HTTPException(422, f"Videos can be at most {MAX_VIDEO_SECONDS // 60}:{MAX_VIDEO_SECONDS % 60:02d} minutes; this one is {length // 60:.0f}:{length % 60:02.0f}. Film one aisle at a time, at 720p.")
        if frames is not None and frames > MAX_VIDEO_FRAMES:
            path.unlink(missing_ok=True)
            raise HTTPException(
                422,
                f"This video has {frames:,} frames and the counting model takes at most {MAX_VIDEO_FRAMES:,}. "
                f"At 30 frames per second that is about {MAX_VIDEO_FRAMES / 30 / 60:.1f} minutes; a phone filming at 60 frames per second reaches it in half the time. "
                "Set the camera to 30 fps and 720p, or film a shorter stretch.",
            )
        clip = Clip(id=clip_id, filename=name, original_name=file.filename or name, sha256=digest.hexdigest(), size_bytes=size, duration_seconds=length, captured_by=(captured_by or "").strip() or None, captured_by_id=(captured_by_id or "").strip()[:100] or None)
        s.add(clip)
        s.commit()
        background.add_task(process_clip, sessions, clip_id, uploads, runner, out)
        background.add_task(build_preview, sessions, clip_id, uploads, out, make_preview)
        return clip_json(s, clip)

    @router.get("/clips")
    def list_clips(s: Session = Depends(db)) -> list[dict]:
        return [clip_json(s, c) for c in s.scalars(select(Clip).order_by(Clip.uploaded_at.desc(), Clip.id))]

    def _clip(s: Session, clip_id: str) -> Clip:
        clip = s.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(404, "No such clip")
        return clip

    @router.get("/clips/{clip_id}")
    def get_clip(clip_id: str, s: Session = Depends(db)) -> dict:
        return clip_json(s, _clip(s, clip_id))

    @router.get("/clips/{clip_id}/evidence")
    def get_evidence(clip_id: str, s: Session = Depends(db)) -> FileResponse:
        clip = _clip(s, clip_id)
        path = restore_blob(s, out, clip.evidence) if clip.evidence else None
        path = path.resolve() if path else None
        if path is None or out.resolve() not in path.parents:
            raise HTTPException(404, "No evidence frame for this clip")
        return FileResponse(path, media_type="image/png")

    @router.get("/clips/{clip_id}/preview")
    def get_preview(clip_id: str, request: Request, s: Session = Depends(db)) -> Response:
        clip = _clip(s, clip_id)
        path = restore_blob(s, out, clip.preview) if clip.preview else None
        if path is None:
            raise HTTPException(404, "No playable copy of this video")
        return ranged_file(path, request.headers.get("range"), "video/mp4")

    @router.post("/clips/{clip_id}/review")
    def post_review(clip_id: str, body: ReviewIn, s: Session = Depends(db)) -> dict:
        """Record a reviewer's per-item counts for a clip. The latest submission replaces the machine count; earlier ones are kept."""
        clip = _clip(s, clip_id)
        if clip.status != "done":
            raise HTTPException(409, f"Clip is {clip.status}; review it once counting has finished")
        require_not_capturer(clip, body.reviewer, body.reviewer_id)
        if body.location is not None:
            if body.location not in {b.location for b in book_lines(s)}:
                raise HTTPException(422, f"{body.location} is not a location in the book stock")
            clip.review_location = body.location
        batch = uuid.uuid4().hex
        s.add_all(Review(clip_id=clip_id, batch=batch, item=line.item.strip(), qty=line.qty, reviewer=body.reviewer.strip(), reviewer_id=(body.reviewer_id or "").strip() or None, note=line.note) for line in body.lines)
        s.commit()
        return clip_json(s, clip)

    # --- reconciliation -----------------------------------------------------
    @router.get("/reconciliation")
    def get_reconciliation(s: Session = Depends(db)) -> list[dict]:
        return [row_json(r) for r in reconciliation_rows(s)]

    def _csv(s: Session, filename: str) -> Response:
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(reconciliation_rows(s), Path(tmp))
            body = (Path(tmp) / filename).read_bytes()
        return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.get("/reconciliation.csv")
    def reconciliation_csv(s: Session = Depends(db)) -> Response:
        return _csv(s, "reconciliation.csv")

    @router.get("/proposed_adjustments.csv")
    def adjustments_csv(s: Session = Depends(db)) -> Response:
        return _csv(s, "proposed_adjustments.csv")

    return router
