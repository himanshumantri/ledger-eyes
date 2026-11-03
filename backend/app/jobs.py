"""Run one uploaded clip through the pipeline and store the result. Runs in the background after the upload returns."""
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import OUT
from app.files import save_blob
from app.media import make_preview
from app.reconcile import BookLine, ClipResult
from app.tables import BookLineRow, Clip

Runner = Callable[[Path, list[BookLine]], ClipResult]
LOG = logging.getLogger("uvicorn.error")  # shows up in the host's log next to the server's own lines


def book_lines(session: Session) -> list[BookLine]:
    return [BookLine(r.item, r.location, r.book_qty, r.unit_cost) for r in session.scalars(select(BookLineRow).order_by(BookLineRow.id))]


def process_clip(sessions: sessionmaker[Session], clip_id: str, uploads: Path, runner: Runner, out: Path = OUT) -> None:
    with sessions() as s:
        clip = s.get(Clip, clip_id)
        clip.status = "running"
        s.commit()
        try:
            result = runner(uploads / clip.filename, book_lines(s))
        except Exception as e:  # a model or network failure must end as a visible failed job, not a stuck one
            clip.status, clip.error = "failed", f"{type(e).__name__}: {e}"[:2000]
        else:
            clip.status = "done"
            clip.location, clip.item, clip.counted = result.location, result.item, result.counted
            clip.needs_review, clip.reasons = result.needs_review, result.reasons
            clip.evidence, clip.transcript = result.evidence, result.transcript[:4000]
            stem = Path(clip.filename).stem
            for relative in (result.evidence, f"evidence/{stem}_raw.png"):
                if relative:
                    save_blob(s, out, relative)
        clip.finished_at = datetime.now(UTC)
        s.commit()


def build_preview(
    sessions: sessionmaker[Session], clip_id: str, uploads: Path, out: Path = OUT,
    make: Callable[[Path, Path, Callable[[int], None], float | None], None] = make_preview,
) -> None:
    """Make the playable copy once counting is done, so it can never delay or fail a count. Progress and any failure are
    written to the clip so the reviewer sees what is happening instead of waiting blind."""
    with sessions() as s:
        clip = s.get(Clip, clip_id)
        if clip is None or clip.status != "done":
            return
        relative = f"previews/{Path(clip.filename).stem}.mp4"
        started, last = time.monotonic(), [-1, 0.0]  # last percent written, and when

        def progress(percent: int) -> None:
            now = time.monotonic()
            if percent != last[0] and now - last[1] >= 2:  # at most one write every two seconds
                last[0], last[1] = percent, now
                clip.preview_progress = percent
                s.commit()

        clip.preview_progress, clip.preview_error = 0, None
        s.commit()
        try:
            make(uploads / clip.filename, out / relative, progress, clip.duration_seconds)
            made = save_blob(s, out, relative)
            error = None if made else "The preview file was not written"
        except Exception as e:  # ffmpeg missing, the video unreadable, or the database refusing the file
            made, error = False, f"{type(e).__name__}: {e}"[:500]
        clip.preview, clip.preview_error = (relative if made else ""), error
        clip.preview_progress = 100 if made else None
        s.commit()
        LOG.info("preview for %s: %s in %.0f s", clip_id, "ready" if made else f"failed ({error})", time.monotonic() - started)


def fail_interrupted(sessions: sessionmaker[Session]) -> int:
    """At start-up, any clip still queued or running was cut off by a restart (counting runs inside the server), so it
    can never finish. Mark it failed so the screen stops saying "Counting..." for ever. Returns how many were marked."""
    with sessions() as s:
        done = s.execute(
            update(Clip).where(Clip.status.in_(("queued", "running"))).values(
                status="failed", finished_at=datetime.now(UTC),
                error="The server restarted while this video was being counted. Upload it again.",
            )
        )
        # A preview that was being made when the server stopped will never finish either.
        s.execute(
            update(Clip).where(Clip.status == "done", Clip.preview.is_(None), Clip.finished_at > datetime.now(UTC) - timedelta(minutes=60)).values(
                preview="", preview_progress=None, preview_error="The server restarted while the video was being prepared.",
            )
        )
        s.commit()
        return done.rowcount
