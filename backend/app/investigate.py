"""Investigate a variance: a reviewer works on one clip's frame with SAM's help and records a count.

SAM proposes cartons from a text phrase; the reviewer includes or excludes each one, clicks a carton SAM missed
(a point prompt) or draws a box round it (a box prompt), redraws a box SAM got wrong, and says which item each carton is. Resolving as "confirmed" writes the per-item counts as a
review, so they flow into the reconciliation like any other reviewer decision. Every action is appended to an
event log, and the clip's machine count is kept, so the final number can be traced back to what the models said.
"""
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.files import restore_blob
from app.jobs import book_lines
from app.media import extract_frame
from app.roles import require_not_capturer
from app.sam_still import box_prompt, point_prompt
from app.segmentation import parse_sam_output
from app.tables import Clip, Investigation, InvestigationEvent, Review

Segmenter = Callable[[Path, str], str]
AUTO_PHRASE = "cardboard box"
MIN_CONF = 0.8  # the cutoff the counting pipeline uses; weaker proposals are shown but start excluded
SAM_LIMIT = 16  # SAM returns at most this many objects per request
CLICK_ID_START = 100  # ids from here up belong to cartons the reviewer added (clicked or drawn); lower ids are SAM's own
MIN_BOX = 8  # pixels; a smaller drawn box is a stray click


class StartIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    location: str | None = None


class ClickIn(BaseModel):
    x: int
    y: int


class BoxIn(BaseModel):
    box: list[int] = Field(min_length=4, max_length=4)  # x1, y1, x2, y2 in frame pixels, as the reviewer drew it
    object_id: int | None = None  # redraw this object's box; without it, add a new carton


class ObjectPatch(BaseModel):
    included: bool | None = None
    item: str | None = Field(default=None, max_length=200)


class ResolveIn(BaseModel):
    outcome: Literal["confirmed", "unresolved"]
    note: str = Field(default="", max_length=2000)


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def frame_path(s: Session, clip: Clip, uploads: Path, out: Path) -> Path:
    """The clip's unmarked frame: on disk, else restored from the database, else cut again from the video if that survives."""
    stem = Path(clip.filename).stem
    raw = out / "evidence" / f"{stem}_raw.png"
    if restore_blob(s, out, f"evidence/{stem}_raw.png"):
        return raw
    video, verify = uploads / clip.filename, out / f"verify_{stem}.json"
    if video.exists() and verify.exists():
        extract_frame(video, json.loads(verify.read_text(encoding="utf-8"))["frame"], raw)
        return raw
    raise HTTPException(404, "The frame for this clip is no longer available")


def counts(inv: Investigation) -> dict:
    per_item: dict[str, int] = {}
    unassigned = 0
    for o in inv.objects:
        if o["included"]:
            if o["item"]:
                per_item[o["item"]] = per_item.get(o["item"], 0) + 1
            else:
                unassigned += 1
    return {"per_item": per_item, "unassigned": unassigned}


def next_added_id(inv: Investigation) -> int:
    return max([o["id"] for o in inv.objects if o["id"] >= CLICK_ID_START], default=CLICK_ID_START - 1) + 1


def inv_json(s: Session, inv: Investigation) -> dict:
    events = s.scalars(select(InvestigationEvent).where(InvestigationEvent.investigation_id == inv.id).order_by(InvestigationEvent.id))
    return {
        "id": inv.id, "clip_id": inv.clip_id, "reviewer": inv.reviewer, "location": inv.location, "status": inv.status,
        "outcome": inv.outcome, "note": inv.note, "created_at": _iso(inv.created_at), "resolved_at": _iso(inv.resolved_at),
        "frame_w": inv.frame_w, "frame_h": inv.frame_h, "machine_count": inv.machine_count, "objects": inv.objects,
        "capped": sum(o["source"] == "auto" for o in inv.objects) >= SAM_LIMIT,  # SAM may have stopped before listing every carton
        "counts": counts(inv),
        "events": [{"at": _iso(e.at), "actor": e.actor, "action": e.action, "detail": e.detail} for e in events],
    }


def create_investigation_router(sessions: sessionmaker[Session], uploads: Path, out: Path, segment: Segmenter) -> APIRouter:
    router = APIRouter()

    def db():
        with sessions() as s:
            yield s

    def log(s: Session, inv: Investigation, action: str, **detail) -> None:
        s.add(InvestigationEvent(investigation_id=inv.id, actor=inv.reviewer, action=action, detail=detail))

    def get_open(s: Session, inv_id: str) -> Investigation:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "No such investigation")
        if inv.status != "open":
            raise HTTPException(409, "This investigation is resolved; start a new one to change the count")
        return inv

    @router.post("/clips/{clip_id}/investigations", status_code=201)
    def start(clip_id: str, body: StartIn, s: Session = Depends(db)) -> dict:
        clip = s.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(404, "No such clip")
        if clip.status != "done":
            raise HTTPException(409, f"Clip is {clip.status}; investigate it once counting has finished")
        require_not_capturer(clip, body.reviewer)
        if body.location is not None and body.location not in {b.location for b in book_lines(s)}:
            raise HTTPException(422, f"{body.location} is not a location in the book stock")
        frame = frame_path(s, clip, uploads, out)
        with Image.open(frame) as im:
            w, h = im.size
        proposals = parse_sam_output(segment(frame, AUTO_PHRASE)).get(0, [])
        objects = [
            {"id": d.obj_id, "source": "auto", "box": [d.x1, d.y1, d.x2, d.y2], "conf": round(d.conf, 3), "included": d.conf >= MIN_CONF, "item": clip.item, "click": None}
            for d in proposals
        ]
        inv = Investigation(
            id=uuid.uuid4().hex, clip_id=clip_id, reviewer=body.reviewer.strip(), location=body.location or clip.review_location or clip.location,
            frame=frame.relative_to(out).as_posix(), frame_w=w, frame_h=h, machine_count=clip.counted, objects=objects,
        )
        s.add(inv)
        log(s, inv, "started", machine_count=clip.counted, proposed=len(objects), included=sum(o["included"] for o in objects))
        s.commit()
        return inv_json(s, inv)

    @router.get("/clips/{clip_id}/investigations")
    def list_for_clip(clip_id: str, s: Session = Depends(db)) -> list[dict]:
        rows = s.scalars(select(Investigation).where(Investigation.clip_id == clip_id).order_by(Investigation.created_at.desc()))
        return [inv_json(s, i) for i in rows]

    @router.get("/investigations/{inv_id}")
    def get(inv_id: str, s: Session = Depends(db)) -> dict:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            raise HTTPException(404, "No such investigation")
        return inv_json(s, inv)

    @router.get("/investigations/{inv_id}/frame")
    def get_frame(inv_id: str, s: Session = Depends(db)) -> FileResponse:
        inv = s.get(Investigation, inv_id)
        path = restore_blob(s, out, inv.frame) if inv else None
        path = path.resolve() if path else None
        if path is None or out.resolve() not in path.parents:
            raise HTTPException(404, "No such frame")
        return FileResponse(path, media_type="image/png")

    @router.post("/investigations/{inv_id}/clicks")
    def click(inv_id: str, body: ClickIn, s: Session = Depends(db)) -> dict:
        """The reviewer points at a carton SAM missed; SAM outlines the object under that point."""
        inv = get_open(s, inv_id)
        if not (0 <= body.x < inv.frame_w and 0 <= body.y < inv.frame_h):
            raise HTTPException(422, "That point is outside the frame")
        frame = restore_blob(s, out, inv.frame)
        if frame is None:
            raise HTTPException(404, "The frame for this investigation is no longer available")
        found = parse_sam_output(segment(frame, point_prompt(body.x, body.y, inv.frame_w, inv.frame_h))).get(0, [])
        if not found:
            raise HTTPException(422, "No carton was found at that point")
        d = found[0]
        new_id = next_added_id(inv)
        clip = s.get(Clip, inv.clip_id)
        obj = {"id": new_id, "source": "click", "box": [d.x1, d.y1, d.x2, d.y2], "conf": round(d.conf, 3), "included": True, "item": clip.item, "click": [body.x, body.y]}
        inv.objects = [*inv.objects, obj]
        log(s, inv, "click_added", object=new_id, x=body.x, y=body.y, box=obj["box"], conf=obj["conf"])
        s.commit()
        return inv_json(s, inv)

    @router.post("/investigations/{inv_id}/boxes")
    def draw_box(inv_id: str, body: BoxIn, s: Session = Depends(db)) -> dict:
        """The reviewer draws a box round a carton and SAM outlines the carton inside it. That replaces the box of an
        existing object (its item and whether it is counted stay as they were), or adds a new carton."""
        inv = get_open(s, inv_id)
        x1, y1, x2, y2 = body.box
        if not (0 <= x1 < x2 <= inv.frame_w and 0 <= y1 < y2 <= inv.frame_h):
            raise HTTPException(422, "That box is outside the frame")
        if x2 - x1 < MIN_BOX or y2 - y1 < MIN_BOX:
            raise HTTPException(422, "That box is too small; drag it around the whole carton")
        if body.object_id is not None and not any(o["id"] == body.object_id for o in inv.objects):
            raise HTTPException(404, "No such object")
        frame = restore_blob(s, out, inv.frame)
        if frame is None:
            raise HTTPException(404, "The frame for this investigation is no longer available")
        found = parse_sam_output(segment(frame, box_prompt(x1, y1, x2, y2, inv.frame_w, inv.frame_h))).get(0, [])
        if not found:
            raise HTTPException(422, "No carton was found in that box; draw it a little larger, or click the carton instead")
        d = max(found, key=lambda f: f.conf)
        new_box, conf = [d.x1, d.y1, d.x2, d.y2], round(d.conf, 3)
        if body.object_id is None:
            clip = s.get(Clip, inv.clip_id)
            obj = {"id": next_added_id(inv), "source": "drawn", "box": new_box, "conf": conf, "included": True, "item": clip.item, "click": None}
            inv.objects = [*inv.objects, obj]
            log(s, inv, "box_added", object=obj["id"], drawn=body.box, box=new_box, conf=conf)
        else:
            before = next(o for o in inv.objects if o["id"] == body.object_id)["box"]
            inv.objects = [{**o, "box": new_box, "conf": conf, "adjusted": True} if o["id"] == body.object_id else o for o in inv.objects]
            log(s, inv, "box_redrawn", object=body.object_id, was=before, drawn=body.box, box=new_box, conf=conf)
        s.commit()
        return inv_json(s, inv)

    @router.patch("/investigations/{inv_id}/objects/{obj_id}")
    def patch_object(inv_id: str, obj_id: int, body: ObjectPatch, s: Session = Depends(db)) -> dict:
        inv = get_open(s, inv_id)
        if body.item is not None and body.item not in {b.item for b in book_lines(s)}:
            raise HTTPException(422, f"{body.item} is not an item in the book stock")
        if not any(o["id"] == obj_id for o in inv.objects):
            raise HTTPException(404, "No such object")
        changed = {}
        updated = []
        for o in inv.objects:
            if o["id"] == obj_id:
                o = dict(o)
                if body.included is not None and body.included != o["included"]:
                    o["included"] = changed["included"] = body.included
                if body.item is not None and body.item != o["item"]:
                    o["item"] = changed["item"] = body.item
            updated.append(o)
        inv.objects = updated
        if changed:
            log(s, inv, "object_changed", object=obj_id, **changed)
        s.commit()
        return inv_json(s, inv)

    @router.post("/investigations/{inv_id}/resolve")
    def resolve(inv_id: str, body: ResolveIn, s: Session = Depends(db)) -> dict:
        """"confirmed" records the per-item counts as the clip's review; "unresolved" only keeps the note."""
        inv = get_open(s, inv_id)
        if body.outcome == "confirmed":
            c = counts(inv)
            if c["unassigned"]:
                raise HTTPException(422, f"{c['unassigned']} included carton(s) have no item; say which item each one is")
            if not c["per_item"]:
                raise HTTPException(422, "No cartons are included; include at least one, or resolve as unresolved")
            if inv.location is None:
                raise HTTPException(422, "Choose the location this shelf belongs to")
            clip = s.get(Clip, inv.clip_id)
            clip.review_location = inv.location
            batch = uuid.uuid4().hex
            s.add_all(Review(clip_id=inv.clip_id, batch=batch, item=item, qty=qty, reviewer=inv.reviewer, note=f"investigation {inv.id}") for item, qty in c["per_item"].items())
        inv.status, inv.outcome, inv.note, inv.resolved_at = "resolved", body.outcome, body.note, datetime.now(UTC)
        log(s, inv, "resolved", outcome=body.outcome, counts=counts(inv)["per_item"], note=body.note)
        s.commit()
        return inv_json(s, inv)

    return router
