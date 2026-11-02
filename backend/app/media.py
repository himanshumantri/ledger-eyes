"""ffmpeg helpers. ffmpeg is a video tool, not a model."""
import json
import subprocess
import tempfile
from pathlib import Path


def extract_frame(video: Path, n: int, out: Path) -> None:
    """Write frame number `n` (0-based, display orientation) as an image."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select=eq(n\\,{n})", "-vframes", "1", str(out)], check=True)


def duration_seconds(video: Path) -> float | None:
    """Length of the video, or None when ffprobe cannot read one (the pipeline then fails the clip with its own message)."""
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True,
        )
        return float(done.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def frame_count(video: Path) -> int | None:
    """Number of video frames, from the container's own count or else length times frame rate; None when it cannot be read."""
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames,avg_frame_rate,duration", "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        stream = json.loads(done.stdout)["streams"][0]
        if str(stream.get("nb_frames", "")).isdigit():
            return int(stream["nb_frames"])
        top, _, bottom = str(stream["avg_frame_rate"]).partition("/")
        return round(float(stream["duration"]) * float(top) / float(bottom or 1))
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, IndexError, ZeroDivisionError):
        return None


def make_preview(video: Path, out: Path) -> None:
    """A small silent copy (about 540 px wide, 700 kbps) the reviewer can play and pause in the browser. About 50 MB for 10 minutes."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-an", "-vf", "scale=540:-2", "-c:v", "libx264", "-preset", "veryfast",
         "-b:v", "700k", "-maxrate", "800k", "-bufsize", "1600k", "-movflags", "+faststart", str(out)],
        check=True,
    )


def wav_bytes(video: Path) -> bytes:
    """Mono 16-bit 16 kHz WAV of the clip's audio, as the transcribe endpoint requires."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
        return wav.read_bytes()
