import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import jobs  # noqa: E402
from app.db import make_session_factory  # noqa: E402
from app.tables import Clip  # noqa: E402


def test_preview_progress_is_written_to_the_clip_at_most_every_two_seconds(tmp_path, monkeypatch):
    sessions = make_session_factory("sqlite://")
    with sessions() as s:
        s.add(Clip(id="c", filename="c.mp4", original_name="c.mp4", sha256="0", size_bytes=1, status="done", duration_seconds=42.0))
        s.commit()
    clock = iter([100.0, 100.0, 100.5, 103.0])  # start, then one reading per progress report
    monkeypatch.setattr(jobs.time, "monotonic", lambda: next(clock, 200.0))
    seen: list = []

    def make(video, out, progress, duration):
        seen.append(duration)  # the clip's own length is what turns the encoder's position into a percentage
        for percent in (10, 20, 60):
            progress(percent)
            with sessions() as other:
                seen.append(other.get(Clip, "c").preview_progress)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")

    jobs.build_preview(sessions, "c", tmp_path, tmp_path, make)
    assert seen == [42.0, 10, 10, 60]  # the 20 came 0.5 s after the 10, so it was not written
    with sessions() as s:
        clip = s.get(Clip, "c")
        assert (clip.preview, clip.preview_progress, clip.preview_error) == ("previews/c.mp4", 100, None)


def test_a_failed_preview_keeps_the_reason(tmp_path):
    sessions = make_session_factory("sqlite://")
    with sessions() as s:
        s.add(Clip(id="c", filename="c.mp4", original_name="c.mp4", sha256="0", size_bytes=1, status="done"))
        s.commit()

    def make(video, out, progress, duration):
        raise RuntimeError("ffmpeg could not make the preview: Invalid data")

    jobs.build_preview(sessions, "c", tmp_path, tmp_path, make)
    with sessions() as s:
        clip = s.get(Clip, "c")
        assert clip.preview == "" and clip.preview_progress is None and "Invalid data" in clip.preview_error
