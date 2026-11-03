import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import CreateTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import make_session_factory  # noqa: E402
from app.factory import create_app  # noqa: E402
from app.reconcile import ClipResult  # noqa: E402
from app.tables import Clip  # noqa: E402

BOOK_CSV = "item,location,book_qty,unit_cost\nmonitor,A1-B2,5,100\n"


def make_client(tmp_path):
    runner = lambda video, book: ClipResult(video.name, "A1-B2", "monitor", 4, False, [], "", "")  # noqa: E731
    client = TestClient(create_app("sqlite://", tmp_path / "uploads", runner, tmp_path / "out", lambda image, prompt: ""))
    client.put("/plan", files={"file": ("b.csv", BOOK_CSV, "text/csv")})
    return client


def test_the_capturer_cannot_review_their_own_clip(tmp_path):
    client = make_client(tmp_path)
    clip = client.post("/clips", files={"file": ("s.mp4", b"v", "video/mp4")}, data={"captured_by": "Ravi"}).json()
    assert clip["captured_by"] == "Ravi"
    line = {"item": "monitor", "qty": 4}
    own = client.post(f"/clips/{clip['id']}/review", json={"reviewer": " ravi ", "lines": [line]})
    assert own.status_code == 409 and "someone else" in own.json()["detail"]
    assert client.post(f"/clips/{clip['id']}/investigations", json={"reviewer": "RAVI"}).status_code == 409
    assert client.post(f"/clips/{clip['id']}/review", json={"reviewer": "Meera", "lines": [line]}).status_code == 200


def test_a_clip_with_no_named_capturer_can_be_reviewed_by_anyone(tmp_path):
    client = make_client(tmp_path)
    clip = client.post("/clips", files={"file": ("s.mp4", b"v", "video/mp4")}).json()
    assert client.post(f"/clips/{clip['id']}/review", json={"reviewer": "Meera", "lines": [{"item": "monitor", "qty": 4}]}).status_code == 200


def test_a_column_added_to_the_code_is_added_to_an_existing_table(tmp_path):
    db = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    old_ddl = re.sub(r",\s*captured_by(_id)? VARCHAR\(\d+\)", "", str(CreateTable(Clip.__table__).compile(engine)))
    assert "captured_by" not in old_ddl
    with engine.begin() as conn:
        conn.execute(text(old_ddl))
    make_session_factory(f"sqlite:///{db.as_posix()}")
    assert {"captured_by", "captured_by_id"} <= {c["name"] for c in inspect(engine).get_columns("clips")}


def test_the_same_employee_id_is_the_same_person_even_under_another_name(tmp_path):
    client = make_client(tmp_path)
    clip = client.post("/clips", files={"file": ("s.mp4", b"v", "video/mp4")}, data={"captured_by": "Ana", "captured_by_id": "E-17"}).json()
    assert clip["captured_by_id"] == "E-17"
    body = {"reviewer": "Ana K", "reviewer_id": "e-17", "lines": [{"item": "monitor", "qty": 4}]}
    assert client.post(f"/clips/{clip['id']}/review", json=body).status_code == 409
    body = {"reviewer": "Meera", "reviewer_id": "E-42", "lines": [{"item": "monitor", "qty": 4}]}
    done = client.post(f"/clips/{clip['id']}/review", json=body).json()
    assert done["review"]["reviewer"] == "Meera" and done["review"]["reviewer_id"] == "E-42"
    assert any("Meera (E-42)" in r["reviewer"] for r in client.get("/reconciliation").json() if r["count_source"] == "reviewed")


def test_a_clip_cut_off_by_a_restart_is_marked_failed_not_left_counting(tmp_path):
    url = f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
    sessions = make_session_factory(url)
    with sessions() as s:
        for name, status in (("a", "running"), ("b", "queued"), ("c", "done")):
            s.add(Clip(id=name, filename=f"{name}.mp4", original_name=f"{name}.mp4", sha256="0", size_bytes=1, status=status))
        s.commit()
    client = TestClient(create_app(url, tmp_path / "uploads", lambda video, book: None, tmp_path / "out", lambda image, prompt: ""))
    by_id = {c["id"]: c for c in client.get("/clips").json()}
    assert [by_id[k]["status"] for k in "abc"] == ["failed", "failed", "done"]
    assert "restarted" in by_id["a"]["error"]
