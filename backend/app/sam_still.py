"""Segment Anything Model 3.1 on a single still image: a text phrase, or a box/point prompt for objects already located.

Prompt grammar is from the SAM segmenting docs: `<0f>` then one `<id><|point;x=..;y=..;w=..;h=..|>` per object, where
w and h are the image's pixel size. At most 16 objects per request, and a request cannot mix a phrase with points.
"""
import base64
import hashlib
import json
from pathlib import Path

import httpx

from app.config import BASE_URL, OUT, SAM_MODEL, auth_headers


def point_prompt(x: int, y: int, w: int, h: int) -> str:
    return f"<0f>1<|point;x={x};y={y};w={w};h={h}|>"


def box_prompt(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> str:
    return f"<0f>1<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h}|>"


def segment_still(image: Path, prompt: str) -> str:
    """Raw SAM output for one image and prompt (parse with app.segmentation.parse_sam_output, frame 0). Cached."""
    data = image.read_bytes()
    cache = OUT / "sam_still" / f"{hashlib.sha256(data + prompt.encode()).hexdigest()[:24]}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    body = {
        "model": SAM_MODEL,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(data).decode()},
        ]}],
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        "stream": True,
    }
    deltas: list[str] = []
    with httpx.stream("POST", f"{BASE_URL}/responses", headers=auth_headers(), json=body, timeout=300) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"SAM request failed: {resp.status_code} {resp.read().decode()[:300]}")
        for line in resp.iter_lines():
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                event = json.loads(line[5:])
                if event.get("type") == "response.output_text.delta":
                    deltas.append(event["delta"])
    raw = "".join(deltas)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(raw, encoding="utf-8")
    return raw
