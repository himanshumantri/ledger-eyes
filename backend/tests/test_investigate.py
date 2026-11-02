import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.factory import create_app  # noqa: E402
from app.reconcile import ClipResult  # noqa: E402

BOOK_CSV = "item,location,book_qty,unit_cost\nmonitor,A1-B2,5,100\nkeyboard,A1-B2,2,50\nmonitor,A1-B4,2,100\n"


def box(i, x1, y1, x2, y2, c):
    return f"{i}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w=200;h=300;c={c}|><|mask;x=0;y=0;c={c};data=zz|>"


class FakeSam:
    """Auto proposal: two sure cartons and one weak one. A click returns a box around the clicked point."""

    def __init__(self):
        self.calls: list[str] = []
        self.nothing_at_click = False
        self.sixteen = False

    def __call__(self, image, prompt):
        self.calls.append(prompt)
        if prompt == "cardboard box" and self.sixteen:
            return "<0f>" + ",".join(box(i, 0, i, 5, i + 5, 0.9) for i in range(16))
        if prompt == "cardboard box":
            return "<0f>" + ",".join([box(0, 10, 10, 90, 60, 0.95), box(1, 10, 70, 90, 120, 0.9), box(2, 10, 130, 90, 180, 0.62)])
        if self.nothing_at_click:
            return ""
        if "<|box;" in prompt:  # a box the reviewer drew: SAM outlines the carton inside, a little tighter than the drawn box
            x1, y1, x2, y2 = (int(prompt.split(f"{k}=")[1].split(";")[0].split("|")[0]) for k in ("x1", "y1", "x2", "y2"))
            return "<0f>" + box(1, x1 + 2, y1 + 2, x2 - 2, y2 - 2, 0.93)
        x = int(prompt.split("x=")[1].split(";")[0])
        y = int(prompt.split("y=")[1].split(";")[0])
        return "<0f>" + box(1, x - 20, y - 15, x + 20, y + 15, 0.81)


@pytest.fixture
def sam():
    return FakeSam()


@pytest.fixture
def env(tmp_path, sam):
    out = tmp_path / "out"

    def runner(video, book):
        (out / "evidence").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 300), "white").save(out / "evidence" / f"{video.stem}_raw.png")
        return ClipResult(video.name, None, None, 3, True, ["location not recognised from narration"], "evidence/x_review.png", "shelf")

    client = TestClient(create_app("sqlite://", tmp_path / "uploads", runner, out, sam))
    client.put("/plan", files={"file": ("b.csv", BOOK_CSV, "text/csv")})
    clip = client.post("/clips", files={"file": ("s.mp4", b"video", "video/mp4")}).json()
    return client, clip["id"]


def start(client, clip_id, **extra):
    return client.post(f"/clips/{clip_id}/investigations", json={"reviewer": "ana", **extra})


def test_sam_proposals_start_included_only_when_confident(env, sam):
    client, clip_id = env
    inv = start(client, clip_id).json()
    assert [(o["id"], o["included"]) for o in inv["objects"]] == [(0, True), (1, True), (2, False)]
    assert inv["machine_count"] == 3 and (inv["frame_w"], inv["frame_h"]) == (200, 300)
    assert inv["capped"] is False and inv["events"][0]["action"] == "started"
    assert client.get(f"/investigations/{inv['id']}/frame").headers["content-type"] == "image/png"


def test_sam_reaching_its_object_limit_is_flagged(env, sam):
    client, clip_id = env
    sam.sixteen = True
    assert start(client, clip_id).json()["capped"] is True


def test_click_adds_the_object_under_the_point(env, sam):
    client, clip_id = env
    inv = start(client, clip_id).json()
    after = client.post(f"/investigations/{inv['id']}/clicks", json={"x": 100, "y": 200}).json()
    added = after["objects"][-1]
    assert (added["id"], added["source"], added["box"], added["included"]) == (100, "click", [80, 185, 120, 215], True)
    assert sam.calls[-1] == "<0f>1<|point;x=100;y=200;w=200;h=300|>"
    assert client.post(f"/investigations/{inv['id']}/clicks", json={"x": 500, "y": 5}).status_code == 422
    sam.nothing_at_click = True
    assert client.post(f"/investigations/{inv['id']}/clicks", json={"x": 5, "y": 5}).status_code == 422


def test_a_drawn_box_adds_a_carton_outlined_by_sam(env, sam):
    client, clip_id = env
    inv = start(client, clip_id).json()
    corners = [[20, 200], [120, 200], [120, 260], [20, 260]]
    after = client.post(f"/investigations/{inv['id']}/boxes", json={"box": [20, 200, 120, 260], "corners": corners}).json()
    added = after["objects"][-1]
    assert (added["id"], added["source"], added["box"], added["conf"], added["included"]) == (100, "drawn", [22, 202, 118, 258], 0.93, True)
    assert sam.calls[-1] == "<0f>1<|box;x1=20;y1=200;x2=120;y2=260;w=200;h=300|>"
    assert after["events"][-1]["action"] == "box_added" and after["events"][-1]["detail"]["drawn"] == [20, 200, 120, 260]
    assert after["events"][-1]["detail"]["corners"] == corners
    # a clicked carton after a drawn one still gets a fresh id
    assert client.post(f"/investigations/{inv['id']}/clicks", json={"x": 100, "y": 100}).json()["objects"][-1]["id"] == 101


def test_redrawing_a_box_replaces_it_and_keeps_the_decision(env):
    client, clip_id = env
    inv = start(client, clip_id).json()
    url = f"/investigations/{inv['id']}"
    client.patch(f"{url}/objects/1", json={"item": "keyboard"})
    after = client.post(f"{url}/boxes", json={"box": [30, 60, 100, 130], "object_id": 1}).json()
    redrawn = next(o for o in after["objects"] if o["id"] == 1)
    assert (redrawn["box"], redrawn["conf"], redrawn["included"], redrawn["item"], redrawn["adjusted"]) == ([32, 62, 98, 128], 0.93, True, "keyboard", True)
    assert len(after["objects"]) == 3
    last = after["events"][-1]
    assert last["action"] == "box_redrawn" and last["detail"]["was"] == [10, 70, 90, 120] and last["detail"]["object"] == 1


def test_drawn_boxes_are_validated(env, sam):
    client, clip_id = env
    inv = start(client, clip_id).json()
    url = f"/investigations/{inv['id']}/boxes"
    assert client.post(url, json={"box": [0, 0, 300, 100]}).status_code == 422  # outside the frame
    assert client.post(url, json={"box": [50, 50, 50, 90]}).status_code == 422  # no width
    assert client.post(url, json={"box": [50, 50, 54, 54]}).status_code == 422  # too small
    assert client.post(url, json={"box": [1, 2, 3]}).status_code == 422
    assert client.post(url, json={"box": [10, 10, 80, 80], "object_id": 99}).status_code == 404
    sam.nothing_at_click = True
    assert client.post(url, json={"box": [10, 10, 80, 80]}).status_code == 422  # SAM outlined nothing
    assert len(client.get(f"/investigations/{inv['id']}").json()["objects"]) == 3


def test_a_deleted_box_is_gone_but_stays_in_the_log(env, sam):
    client, clip_id = env
    sam.sixteen = False
    inv = start(client, clip_id).json()
    url = f"/investigations/{inv['id']}"
    after = client.delete(f"{url}/objects/2").json()
    assert [o["id"] for o in after["objects"]] == [0, 1]
    last = after["events"][-1]
    assert last["action"] == "object_deleted" and last["detail"]["box"] == [10, 130, 90, 180] and last["detail"]["conf"] == 0.62
    assert client.delete(f"{url}/objects/2").status_code == 404
    client.post(f"{url}/resolve", json={"outcome": "unresolved"})
    assert client.delete(f"{url}/objects/1").status_code == 409


def test_deleting_boxes_does_not_hide_that_sam_hit_its_limit(env, sam):
    client, clip_id = env
    sam.sixteen = True
    inv = start(client, clip_id).json()
    for i in range(3):
        inv = client.delete(f"/investigations/{inv['id']}/objects/{i}").json()
    assert inv["capped"] is True and len(inv["objects"]) == 13


def test_edits_are_logged_and_validated(env):
    client, clip_id = env
    inv = start(client, clip_id).json()
    url = f"/investigations/{inv['id']}/objects/2"
    assert client.patch(url, json={"included": True, "item": "keyboard"}).status_code == 200
    assert client.patch(url, json={"item": "toaster"}).status_code == 422
    assert client.patch(f"/investigations/{inv['id']}/objects/99", json={"included": False}).status_code == 404
    events = client.get(f"/investigations/{inv['id']}").json()["events"]
    assert [e["action"] for e in events] == ["started", "object_changed"]
    assert events[1]["detail"] == {"object": 2, "included": True, "item": "keyboard"}


def test_confirmed_investigation_becomes_the_clips_review(env):
    client, clip_id = env
    inv = start(client, clip_id, location="A1-B2").json()
    base = f"/investigations/{inv['id']}"
    body = {"outcome": "confirmed"}
    assert client.post(f"{base}/resolve", json=body).status_code == 422  # included cartons have no item yet
    for obj_id, item in ((0, "monitor"), (1, "monitor")):
        client.patch(f"{base}/objects/{obj_id}", json={"item": item})
    client.patch(f"{base}/objects/2", json={"included": True, "item": "keyboard"})
    done = client.post(f"{base}/resolve", json={**body, "note": "third carton was a keyboard"}).json()
    assert (done["status"], done["counts"]["per_item"]) == ("resolved", {"monitor": 2, "keyboard": 1})
    assert client.patch(f"{base}/objects/0", json={"included": False}).status_code == 409
    rows = {(r["location"], r["item"]): r for r in client.get("/reconciliation").json() if r["location"] == "A1-B2"}
    assert (rows[("A1-B2", "monitor")]["counted_qty"], rows[("A1-B2", "monitor")]["variance_qty"]) == (2, -3)
    assert (rows[("A1-B2", "keyboard")]["counted_qty"], rows[("A1-B2", "keyboard")]["reviewer"]) == (1, "ana")
    clip = client.get(f"/clips/{clip_id}").json()
    assert clip["review"]["lines"][0]["note"] == f"investigation {inv['id']}" and clip["location"] == "A1-B2"


def test_confirming_needs_a_location_and_at_least_one_carton(env):
    client, clip_id = env
    inv = start(client, clip_id).json()
    assert client.post(f"/investigations/{inv['id']}/resolve", json={"outcome": "confirmed"}).status_code == 422
    assert start(client, clip_id, location="Z9-Z9").status_code == 422
    resolved = client.post(f"/investigations/{inv['id']}/resolve", json={"outcome": "unresolved", "note": "shelf was blocked"}).json()
    assert resolved["outcome"] == "unresolved" and client.get(f"/clips/{clip_id}").json()["review"] is None


def test_unknown_ids(env):
    client, _ = env
    assert client.post("/clips/nope/investigations", json={"reviewer": "ana"}).status_code == 404
    assert client.get("/investigations/nope").status_code == 404
    assert client.get("/clips/nope/investigations").json() == []


def test_frames_survive_the_disk_being_wiped(env, tmp_path):
    client, clip_id = env
    first = start(client, clip_id).json()
    import shutil

    shutil.rmtree(tmp_path / "out")  # a restart on a host with an ephemeral disk
    assert client.get(f"/investigations/{first['id']}/frame").status_code == 200
    shutil.rmtree(tmp_path / "out")
    again = start(client, clip_id)  # starts from the database copy of the frame
    assert again.status_code == 201
    shutil.rmtree(tmp_path / "out")
    assert client.post(f"/investigations/{again.json()['id']}/clicks", json={"x": 50, "y": 50}).status_code == 200


def test_evidence_image_survives_the_disk_being_wiped(tmp_path):
    out = tmp_path / "out"

    def runner(video, book):
        (out / "evidence").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), "red").save(out / "evidence" / f"{video.stem}_review.png")
        return ClipResult(video.name, "A1-B2", "monitor", 1, False, [], f"evidence/{video.stem}_review.png", "")

    client = TestClient(create_app("sqlite://", tmp_path / "uploads", runner, out, FakeSam()))
    client.put("/plan", files={"file": ("b.csv", BOOK_CSV, "text/csv")})
    clip = client.post("/clips", files={"file": ("s.mp4", b"video", "video/mp4")}).json()
    import shutil

    shutil.rmtree(out)
    served = client.get(f"/clips/{clip['id']}/evidence")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"


def picture(w=200, h=300):
    import io

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def start_from_frame(client, clip_id, image=None, **form):
    data = {"at_ms": "17000", "reviewer": "ana", "reviewer_id": "E-1", **form}
    return client.post(f"/clips/{clip_id}/investigations/from-frame", data=data, files={"file": ("f.png", image or picture(), "image/png")})


def test_a_paused_frame_starts_an_investigation_on_that_exact_picture(env, sam):
    client, clip_id = env
    res = start_from_frame(client, clip_id, picture(240, 320))
    assert res.status_code == 201
    inv = res.json()
    assert (inv["frame_w"], inv["frame_h"]) == (240, 320)
    assert [o["id"] for o in inv["objects"]] == [0, 1, 2]  # SAM ran on the paused picture, as it does on the best frame
    started = inv["events"][0]
    assert started["action"] == "started" and started["detail"]["picked"] == "paused" and started["detail"]["at_ms"] == 17000
    assert started["actor"] == "ana (E-1)"
    assert client.get(f"/investigations/{inv['id']}/frame").headers["content-type"] == "image/png"


def test_a_paused_frame_survives_the_disk_being_wiped(env, tmp_path):
    import shutil

    client, clip_id = env
    inv = start_from_frame(client, clip_id).json()
    shutil.rmtree(tmp_path / "out" / "investigation_frames")
    assert client.get(f"/investigations/{inv['id']}/frame").status_code == 200
    assert client.post(f"/investigations/{inv['id']}/boxes", json={"box": [20, 200, 120, 260]}).status_code == 200


def test_a_paused_frame_is_checked(env):
    client, clip_id = env
    assert start_from_frame(client, clip_id, b"not a picture").status_code == 422
    assert start_from_frame(client, clip_id, picture(10, 10)).status_code == 422  # too small to be a frame
    assert start_from_frame(client, clip_id, picture(5000, 100)).status_code == 422  # too large a side
    assert start_from_frame(client, clip_id, reviewer="").status_code == 422
    assert start_from_frame(client, clip_id, at_ms="-1").status_code == 422
    assert start_from_frame(client, clip_id, location="Z9-Z9").status_code == 422
    assert start_from_frame(client, "nope").status_code == 404


def test_the_capturer_cannot_start_from_a_paused_frame_of_their_own_clip(tmp_path, sam):
    out = tmp_path / "out"

    def runner(video, book):
        (out / "evidence").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 300), "white").save(out / "evidence" / f"{video.stem}_raw.png")
        return ClipResult(video.name, None, None, 3, True, [], "", "shelf")

    client = TestClient(create_app("sqlite://", tmp_path / "uploads", runner, out, sam))
    client.put("/plan", files={"file": ("b.csv", BOOK_CSV, "text/csv")})
    clip = client.post("/clips", files={"file": ("s.mp4", b"video", "video/mp4")}, data={"captured_by_id": "E-1"}).json()
    assert start_from_frame(client, clip["id"]).status_code == 409
    assert start_from_frame(client, clip["id"], reviewer_id="E-2").status_code == 201
