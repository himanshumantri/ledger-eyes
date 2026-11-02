"""Muse Voice Transcribe over the Meta Model API: staff narration to turn-level text."""
import json
import time
from pathlib import Path

import httpx

from app.config import BASE_URL, OUT, VOICE_MODEL, auth_headers
from app.media import wav_bytes


ATTEMPTS, PAUSE = 3, 5  # tries, and seconds to wait (times the attempt number) between them


def transcribe(video: Path, keywords: list[str], language: str = "English") -> dict:
    """TranscribeResponse as a dict (`transcript`, `turns` with startMs/endMs). Cached by clip."""
    cache = OUT / f"voice_{video.stem}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    req = {"model": VOICE_MODEL, "audioEncoding": "WAV", "mode": "ENDPOINTING", "keywords": keywords, "languageBias": [language]}
    audio = wav_bytes(video)
    # A 9.5-minute recording was refused with a 502 once and accepted the next time, so a server error is tried again.
    for attempt in range(1, ATTEMPTS + 1):
        try:
            resp = httpx.post(
                f"{BASE_URL}/asr/transcribe",
                headers={**auth_headers(), "Accept": "application/json"},
                files={"request": (None, json.dumps(req), "application/json"), "audio": ("audio.wav", audio, "audio/wav")},
                timeout=300,
            )
            if resp.status_code >= 500 and attempt < ATTEMPTS:
                raise httpx.HTTPStatusError(f"server error {resp.status_code}", request=resp.request, response=resp)
            break
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == ATTEMPTS:
                raise
            time.sleep(PAUSE * attempt)
    resp.raise_for_status()
    data = resp.json()
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
