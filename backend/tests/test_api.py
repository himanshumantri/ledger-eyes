import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.factory import create_app  # noqa: E402
from app.reconcile import ClipResult  # noqa: E402

BOOK_CSV = "item,location,book_qty,unit_cost\nmonitor,A1-B2,5,100\nmonitor,A1-B4,2,100\nkeyboard,A1-B4,2,50\n"
VIDEO = b"not a real video, the fake pipeline never decodes it"


class FakeRunner:
    """Stands in for the model pipeline: returns whatever result the test queued, or raises."""

    def __init__(self):
        self.results: list = []

    def __call__(self, video, book):
        nxt = self.results.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return ClipResult(video.name, *nxt)


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def client(tmp_path, runner):
    return TestClient(create_app("sqlite://", tmp_path / "uploads", runner))


def put_plan(client, text=BOOK_CSV):
    return client.put("/plan", files={"file": ("book.csv", text, "text/csv")})


def upload(client, data=VIDEO, **form):
    return client.post("/clips", files={"file": ("shelf.mp4", data, "video/mp4")}, data=form)


def auto_pass(location="A1-B2", item="monitor", counted=4):
    return (location, item, counted, False, [], "", "narration")


def test_plan_upload_replaces_book_and_validates(client):
    assert put_plan(client).json() == {"lines": 3, "locations": 2}
    assert client.get("/plan").json()["locations"] == ["A1-B2", "A1-B4"]
    assert put_plan(client, "item,location\nx,y\n").status_code == 422
    assert put_plan(client, "item,location,book_qty,unit_cost\nx,y,many,1\n").status_code == 422
    assert len(client.get("/plan").json()["lines"]) == 3  # a bad upload leaves the book as it was


def test_clip_needs_a_plan_and_a_video(client):
    assert upload(client).status_code == 409
    put_plan(client)
    assert client.post("/clips", files={"file": ("notes.txt", b"hi", "text/plain")}).status_code == 415


def test_upload_is_hashed_by_the_server_and_counted_in_the_background(client, runner):
    put_plan(client)
    runner.results.append(auto_pass())
    r = upload(client, client_sha256=hashlib.sha256(VIDEO).hexdigest())
    assert r.status_code == 201
    clip = client.get(f"/clips/{r.json()['id']}").json()
    assert clip["sha256"] == hashlib.sha256(VIDEO).hexdigest()
    assert (clip["status"], clip["machine_count"], clip["location"], clip["needs_review"]) == ("done", 4, "A1-B2", False)


def test_a_hash_that_differs_from_the_devices_is_rejected(client):
    put_plan(client)
    r = upload(client, client_sha256="0" * 64)
    assert r.status_code == 422 and client.get("/clips").json() == []


def test_a_pipeline_failure_ends_as_a_failed_clip(client, runner):
    put_plan(client)
    runner.results.append(RuntimeError("MODEL_API_KEY is not set"))
    clip = client.get(f"/clips/{upload(client).json()['id']}").json()
    assert clip["status"] == "failed" and "MODEL_API_KEY" in clip["error"]
    assert client.post(f"/clips/{clip['id']}/review", json={"reviewer": "kim", "lines": [{"item": "monitor", "qty": 1}]}).status_code == 409


def test_auto_passed_clip_reconciles_and_exports(client, runner):
    put_plan(client)
    runner.results.append(auto_pass())
    upload(client)
    rows = {(r["location"], r["item"]): r for r in client.get("/reconciliation").json()}
    assert rows[("A1-B2", "monitor")]["variance_qty"] == -1 and rows[("A1-B2", "monitor")]["count_source"] == "machine"
    assert rows[("A1-B4", "monitor")]["status"] == "not_counted"
    csv_text = client.get("/proposed_adjustments.csv")
    assert csv_text.headers["content-type"].startswith("text/csv")
    assert "monitor,A1-B2,,-1,4" in csv_text.text
    assert client.get("/reconciliation.csv").text.startswith("location,item,book_qty")


def test_review_names_the_location_and_replaces_the_machine_count(client, runner):
    put_plan(client)
    runner.results.append((None, None, 3, True, ["location not recognised from narration"], "", "shelf B4"))
    clip = upload(client).json()
    assert client.get("/reconciliation").json()[0]["status"] == "not_counted"  # no location yet, nothing to reconcile
    bad = client.post(f"/clips/{clip['id']}/review", json={"reviewer": "kim", "location": "Z9-Z9", "lines": [{"item": "monitor", "qty": 3}]})
    assert bad.status_code == 422
    ok = client.post(f"/clips/{clip['id']}/review", json={
        "reviewer": "kim", "location": "A1-B4",
        "lines": [{"item": "monitor", "qty": 3, "note": "third one behind"}, {"item": "keyboard", "qty": 2}],
    })
    assert ok.json()["location"] == "A1-B4" and len(ok.json()["review"]["lines"]) == 2
    rows = {(r["location"], r["item"]): r for r in client.get("/reconciliation").json()}
    assert (rows[("A1-B4", "monitor")]["counted_qty"], rows[("A1-B4", "monitor")]["reviewer"]) == (3, "kim")
    assert rows[("A1-B4", "keyboard")]["status"] == "match"


def test_second_review_supersedes_the_first_and_a_refilm_replaces_the_clip(client, runner):
    put_plan(client)
    runner.results += [(*auto_pass(counted=3)[:2], 3, True, ["x"], "", ""), auto_pass(counted=5)]
    first = upload(client).json()
    client.post(f"/clips/{first['id']}/review", json={"reviewer": "kim", "lines": [{"item": "monitor", "qty": 2}]})
    client.post(f"/clips/{first['id']}/review", json={"reviewer": "kim", "lines": [{"item": "monitor", "qty": 4}]})
    row = next(r for r in client.get("/reconciliation").json() if r["item"] == "monitor" and r["location"] == "A1-B2")
    assert row["counted_qty"] == 4
    upload(client)  # a re-film of the same shelf replaces the earlier clip, review included
    row = next(r for r in client.get("/reconciliation").json() if r["item"] == "monitor" and r["location"] == "A1-B2")
    assert (row["counted_qty"], row["count_source"]) == (5, "machine")
    assert len(client.get("/clips").json()) == 2  # both uploads are kept


def test_unknown_clip_is_404(client):
    assert client.get("/clips/nope").status_code == 404
    assert client.get("/clips/nope/evidence").status_code == 404


def test_a_video_over_the_length_cap_is_refused_and_not_kept(client, tmp_path, monkeypatch):
    put_plan(client)
    monkeypatch.setattr("app.api.duration_seconds", lambda path: 501.0)
    res = upload(client)
    assert res.status_code == 422 and "at most 8:20 minutes" in res.json()["detail"]
    assert list((tmp_path / "uploads").glob("*")) == []
    monkeypatch.setattr("app.api.duration_seconds", lambda path: 500.0)
    assert upload(client).status_code == 201
    monkeypatch.setattr("app.api.duration_seconds", lambda path: None)  # unreadable length: the pipeline decides
    assert upload(client).status_code == 201


def test_the_playable_copy_is_made_after_counting_and_can_be_seeked(client, runner, tmp_path, monkeypatch):
    put_plan(client)
    runner.results.append(auto_pass())
    monkeypatch.setattr("app.api.make_preview", lambda video, out, progress, duration: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"0123456789"))[1])
    clip = upload(client).json()
    assert client.get(f"/clips/{clip['id']}").json()["preview"] == "ready"
    whole = client.get(f"/clips/{clip['id']}/preview")
    assert whole.status_code == 200 and whole.content == b"0123456789" and whole.headers["accept-ranges"] == "bytes"
    part = client.get(f"/clips/{clip['id']}/preview", headers={"Range": "bytes=2-5", "Origin": "http://localhost:5173"})
    assert part.status_code == 206 and part.content == b"2345" and part.headers["content-range"] == "bytes 2-5/10"
    assert part.headers["access-control-allow-origin"] == "http://localhost:5173"  # the page reads the paused frame, so the video must be CORS-readable
    assert client.get(f"/clips/{clip['id']}/preview", headers={"Range": "bytes=7-"}).content == b"789"
    assert client.get(f"/clips/{clip['id']}/preview", headers={"Range": "bytes=-3"}).content == b"789"
    assert client.get(f"/clips/{clip['id']}/preview", headers={"Range": "bytes=99-"}).status_code == 416
    assert client.get(f"/clips/{clip['id']}/preview", headers={"Range": "lines=1-2"}).status_code == 416
    # the disk is wiped: the copy comes back from the database
    import shutil

    shutil.rmtree(tmp_path / "out", ignore_errors=True)
    assert client.get(f"/clips/{clip['id']}/preview").content == b"0123456789"


def test_a_playable_copy_that_cannot_be_made_does_not_touch_the_count(client, runner, monkeypatch):
    put_plan(client)
    runner.results.append(auto_pass())

    def broken(video, out, progress, duration):
        raise RuntimeError("ffmpeg is not installed")

    monkeypatch.setattr("app.api.make_preview", broken)
    clip = client.get(f"/clips/{upload(client).json()['id']}").json()
    assert clip["status"] == "done" and clip["machine_count"] == 4 and clip["preview"] == "failed"
    assert "ffmpeg is not installed" in clip["preview_error"] and clip["preview_progress"] is None
    assert client.get(f"/clips/{clip['id']}/preview").status_code == 404


def test_a_video_with_too_many_frames_for_the_counting_model_is_refused(client, tmp_path, monkeypatch):
    put_plan(client)
    monkeypatch.setattr("app.api.duration_seconds", lambda path: 300.0)  # a 5-minute video, but filmed at 60 frames per second
    monkeypatch.setattr("app.api.frame_count", lambda path: 18000)
    res = upload(client)
    assert res.status_code == 422 and "18,000 frames" in res.json()["detail"] and "at most 14,900" in res.json()["detail"]
    assert list((tmp_path / "uploads").glob("*")) == []
    monkeypatch.setattr("app.api.frame_count", lambda path: 14900)
    created = upload(client)
    assert created.status_code == 201 and created.json()["duration_seconds"] == 300.0


def test_frames_and_length_are_read_from_a_real_video(tmp_path):
    import shutil
    import subprocess

    from app.media import duration_seconds, frame_count

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    video = tmp_path / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=30", str(video)], check=True)
    assert frame_count(video) == 60 and round(duration_seconds(video)) == 2
    assert frame_count(tmp_path / "missing.mp4") is None
