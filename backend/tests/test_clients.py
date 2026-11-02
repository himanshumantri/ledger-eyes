import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import sam_client, voice_client  # noqa: E402


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}
        self.request = httpx.Request("POST", "https://x")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=self.request, response=self)

    def json(self):
        return self._body


def voice_with(monkeypatch, tmp_path, replies):
    monkeypatch.setattr(voice_client.httpx, "post", lambda *a, **k: replies.pop(0) if len(replies) > 1 else replies[0])
    monkeypatch.setattr(voice_client, "wav_bytes", lambda video: b"wav")
    monkeypatch.setattr(voice_client, "auth_headers", lambda: {})
    monkeypatch.setattr(voice_client, "OUT", tmp_path)
    monkeypatch.setattr(voice_client.time, "sleep", lambda s: None)


def test_a_server_error_from_the_voice_model_is_tried_again(tmp_path, monkeypatch):
    replies = [Reply(502), Reply(502), Reply(200, {"transcript": "ok", "turns": []})]
    voice_with(monkeypatch, tmp_path, replies)
    assert voice_client.transcribe(tmp_path / "v.mp4", keywords=[])["transcript"] == "ok"
    assert len(replies) == 1  # the third reply was the one used


def test_the_voice_model_giving_up_raises_and_caches_nothing(tmp_path, monkeypatch):
    voice_with(monkeypatch, tmp_path, [Reply(502)])
    with pytest.raises(httpx.HTTPStatusError):
        voice_client.transcribe(tmp_path / "v.mp4", keywords=[])
    assert not list(tmp_path.glob("voice_*"))


class Stream:
    """Stands in for httpx.stream: yields server-sent-event lines."""

    def __init__(self, events):
        self.status_code, self._events = 200, events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        return [f"data: {json.dumps(e)}" for e in self._events]


def sam_with(monkeypatch, tmp_path, events):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(sam_client, "OUT", tmp_path)
    monkeypatch.setattr(sam_client, "auth_headers", lambda: {})
    monkeypatch.setattr(sam_client.httpx, "post", lambda *a, **k: Reply(200, {"id": "file1"}))
    monkeypatch.setattr(sam_client.httpx, "stream", lambda *a, **k: Stream(events))
    return video


def test_an_empty_answer_from_sam_is_an_error_and_is_not_cached(monkeypatch, tmp_path):
    video = sam_with(monkeypatch, tmp_path, [{"type": "response.created"}, {"type": "response.completed"}])
    with pytest.raises(RuntimeError, match="no output"):
        sam_client.segment_video(video, "cardboard box")
    assert not list(tmp_path.glob("sam_*"))


def test_a_failure_event_from_sam_is_an_error(monkeypatch, tmp_path):
    video = sam_with(monkeypatch, tmp_path, [{"type": "response.failed", "error": {"message": "video too long"}}])
    with pytest.raises(RuntimeError, match="video too long"):
        sam_client.segment_video(video, "cardboard box")


def test_an_answer_is_cached_and_an_empty_cache_file_is_ignored(monkeypatch, tmp_path):
    video = sam_with(monkeypatch, tmp_path, [{"type": "response.output_text.delta", "delta": "<0f>1"}])
    (tmp_path / "sam_v_cardboard_box.txt").write_text("", encoding="utf-8")  # left behind by the old behaviour
    assert sam_client.segment_video(video, "cardboard box") == "<0f>1"
    assert (tmp_path / "sam_v_cardboard_box.txt").read_text(encoding="utf-8") == "<0f>1"
