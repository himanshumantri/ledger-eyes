"""ffmpeg helpers. ffmpeg is a video tool, not a model."""
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
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


_PROGRESS_KEYS = {"frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms", "out_time", "dup_frames", "drop_frames", "speed", "progress"}
COPY_LIMIT_BYTES = 80 * 1024 * 1024  # a video this small that a browser can already play is used as it is


def playable_as_is(video: Path) -> bool:
    """True for an H.264 video in the usual pixel format with no rotation flag and a modest size: a browser plays it
    as it is, so the preview can be a copy made in seconds. A rotated video is re-encoded so the rotation is baked in."""
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt:stream_side_data=rotation:stream_tags=rotate", "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        stream = json.loads(done.stdout)["streams"][0]
        rotated = any(int(float(s.get("rotation", 0))) % 360 for s in stream.get("side_data_list", [])) or int(float(stream.get("tags", {}).get("rotate", 0))) % 360 != 0
        return stream.get("codec_name") == "h264" and stream.get("pix_fmt") == "yuv420p" and not rotated and video.stat().st_size <= COPY_LIMIT_BYTES
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, IndexError):
        return False


def make_preview(video: Path, out: Path, on_progress: Callable[[int], None] | None = None, duration: float | None = None) -> None:
    """A silent copy the reviewer can play and pause in the browser.

    A small H.264 video that needs no rotating is copied as it is (seconds). Anything else is re-encoded to 540 px wide,
    12 frames a second and about 700 kbps (plenty to pause on a moment). On the free host's sliver of a CPU a full-rate
    re-encode of an 8-minute video took longer than anyone would wait, so it runs at a low priority and at 12 frames a
    second. `on_progress` gets a percentage (0-99) as ffmpeg reports how much it has done; it needs `duration` for that.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if playable_as_is(video):
        encode = ["-c:v", "copy"]
    else:
        encode = ["-vf", "scale=540:-2,fps=12", "-c:v", "libx264", "-preset", "superfast", "-b:v", "700k", "-maxrate", "800k", "-bufsize", "1600k"]
    cmd = ["ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1", "-stats_period", "2", "-y", "-i", str(video), "-an", *encode, "-movflags", "+faststart", str(out)]
    if shutil.which("nice"):  # keep the server answering requests while this runs
        cmd = ["nice", "-n", "15", *cmd]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    complaints: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms"):  # both are microseconds, whatever the second one is called
            if on_progress and duration and value.isdigit():
                on_progress(min(99, int(int(value) / 1e6 / duration * 100)))
        elif key not in _PROGRESS_KEYS and not key.startswith("stream_"):
            complaints.append(line.strip())
    if proc.wait() != 0:
        raise RuntimeError(("ffmpeg could not make the preview: " + " ".join(complaints[-3:]))[:400])


def wav_bytes(video: Path) -> bytes:
    """Mono 16-bit 16 kHz WAV of the clip's audio, as the transcribe endpoint requires."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
        return wav.read_bytes()
