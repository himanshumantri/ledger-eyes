"""Do SAM and the voice model accept a 10-minute video, and how long do they take?

    python scripts/long_video_test.py [--repeat 7] [--build-only] [--book testdata/fresh_book_stock.csv]

Joins Fresh 1-5 (about 81 seconds, five shelves, each narrated) `--repeat` times into testdata/Long test.mp4 (7 times is
about 9.5 minutes), then runs the real services on it and prints, for each stage, whether it was accepted and how long it
took. Nothing is uploaded to the app. Needs MODEL_API_KEY unless the results are already cached in testdata/out.

It also shows how the narration turns would split the video by shelf: each turn with its start and end time and the plan
location it names (if any). That is what a one-clip-per-shelf split would be built on.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import narration  # noqa: E402
from app.config import TESTDATA  # noqa: E402
from app.media import duration_seconds  # noqa: E402
from app.pipeline import SAM_PHRASE, run_clip  # noqa: E402
from app.reconcile import load_book  # noqa: E402
from app.sam_client import segment_video  # noqa: E402
from app.segmentation import parse_sam_output  # noqa: E402
from app.voice_client import transcribe  # noqa: E402

PARTS = [f"Fresh {n}.mp4" for n in range(1, 6)]
LONG = TESTDATA / "Long test.mp4"


def build(repeat: int) -> None:
    """Re-encode every part to the same size and frame rate so they can be joined; audio is kept (it holds the narration)."""
    inputs = [TESTDATA / p for p in PARTS] * repeat
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for p in inputs:
        cmd += ["-i", str(p)]
    chains = "".join(f"[{i}:v]scale=576:1024,setsar=1,fps=30[v{i}];[{i}:a]aresample=16000,aformat=channel_layouts=mono[a{i}];" for i in range(len(inputs)))
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(inputs)))
    cmd += ["-filter_complex", f"{chains}{joined}concat=n={len(inputs)}:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-c:a", "aac", "-b:a", "64k", str(LONG)]
    print(f"joining {len(inputs)} clips ...")
    subprocess.run(cmd, check=True)


def stage(label: str, fn):
    start = time.perf_counter()
    try:
        out = fn()
    except Exception as e:  # report and stop: later stages need this one
        print(f"   {label}: REFUSED or FAILED after {time.perf_counter() - start:.0f}s: {type(e).__name__}: {str(e)[:300]}")
        raise SystemExit(1) from e
    print(f"   {label}: ok in {time.perf_counter() - start:.0f}s")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=7)
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--book", default=str(TESTDATA / "fresh_book_stock.csv"))
    args = ap.parse_args()

    if not LONG.exists():
        build(args.repeat)
    length = duration_seconds(LONG)
    print(f"{LONG.name}: {length:.0f} s ({length / 60:.1f} min), {LONG.stat().st_size / 1e6:.0f} MB")
    if args.build_only:
        return

    book = load_book(Path(args.book))
    items = sorted({b.item for b in book})
    locations = sorted({b.location for b in book})

    voice = stage("voice transcription", lambda: transcribe(LONG, keywords=items))
    print(f"   audio {voice.get('audioDurationMs', 0) / 1000:.0f} s, {len(voice.get('turns', []))} turns")
    for t in voice.get("turns", []):
        where = narration.resolve_location(t["transcript"], locations)
        print(f"     {t['startMs'] / 1000:6.1f}-{t['endMs'] / 1000:6.1f} s  {where or '-':8} {t['transcript'][:70]}")

    raw = stage("SAM on the whole video", lambda: segment_video(LONG, SAM_PHRASE))
    frames = parse_sam_output(raw)
    print(f"   output {len(raw) / 1e6:.1f} MB of text, {len(frames)} frames")

    result = stage("whole pipeline (uses the two results above, adds the verification)", lambda: run_clip(LONG, book))
    print(f"   location={result.location} counted={result.counted} needs_review={result.needs_review}")
    print(f"   reasons: {'; '.join(result.reasons)}")
    print("\nExpected for a joined multi-shelf video today: location not recognised and a count for one frame only. That is why a split by shelf is needed.")


if __name__ == "__main__":
    main()
