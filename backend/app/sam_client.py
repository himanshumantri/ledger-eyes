"""Segment Anything Model 3.1 over the Meta Model API: text-prompted tracking on a video clip."""
import json
from pathlib import Path

import httpx

from app.config import BASE_URL, OUT, SAM_MODEL, auth_headers


def cache_path(video: Path, phrase: str) -> Path:
    return OUT / f"sam_{video.stem}_{phrase.replace(' ', '_')}.txt"


def segment_video(video: Path, phrase: str) -> str:
    """Raw SAM output (one line per frame). Cached by clip and phrase; parse with app.segmentation."""
    cache = cache_path(video, phrase)
    if cache.exists() and cache.stat().st_size > 0:  # an empty file is a failed call, never an answer
        return cache.read_text(encoding="utf-8")

    with video.open("rb") as fh:
        up = httpx.post(f"{BASE_URL}/files", headers=auth_headers(), files={"file": (video.name, fh, "video/mp4")}, data={"purpose": "user_data"}, timeout=300)
    up.raise_for_status()
    body = {
        "model": SAM_MODEL,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": phrase},
            {"type": "input_video", "file_id": up.json()["id"]},
        ]}],
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        "stream": True,
    }
    deltas: list[str] = []
    seen: set[str] = set()
    with httpx.stream("POST", f"{BASE_URL}/responses", headers=auth_headers(), json=body, timeout=600) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"SAM request failed: {resp.status_code} {resp.read().decode()[:300]}")
        for line in resp.iter_lines():
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                event = json.loads(line[5:])
                kind = str(event.get("type", ""))
                seen.add(kind)
                if kind == "response.output_text.delta":
                    deltas.append(event["delta"])
                elif event.get("error") or "fail" in kind or "error" in kind:
                    raise RuntimeError(f"SAM reported a problem: {json.dumps(event)[:500]}")
    raw = "".join(deltas)
    if not raw.strip():  # a 9.5-minute video once came back empty after 32 s, which looked like success and was cached
        raise RuntimeError(f"SAM returned no output (stream events seen: {sorted(seen)[:8]}). The video may be too long for it.")
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(raw, encoding="utf-8")
    return raw
