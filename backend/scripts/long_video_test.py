"""Do SAM and the voice model accept a long video, and how long do they take?

    python scripts/long_video_test.py [--repeat 7] [--only voice|sam|all] [--build-only] [--book testdata/fresh_book_stock.csv]

Joins Fresh 1-5 (about 81 seconds, five shelves, each narrated) `--repeat` times into testdata/Long test <N>x.mp4
(7 times is about 9.5 minutes, 3 times about 4 minutes), then runs the real services on it and prints, for each
stage, whether it was accepted, how long it took and, on a refusal, the server's own message. A failed stage does not
stop the others. Nothing is uploaded to the app. Needs MODEL_API_KEY unless the results are already cached in testdata/out.

It also shows how the narration turns would split the video by shelf: each turn with its start and end time and the plan
location it names (if any). That is what a one-clip-per-shelf split would be built on.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import narration  # noqa: E402
from app.config import TESTDATA  # noqa: E402
from app.media import duration_seconds, wav_bytes  # noqa: E402
from app.pipeline import SAM_PHRASE, run_clip  # noqa: E402
from app.reconcile import load_book  # noqa: E402
from app.sam_client import segment_video  # noqa: E402
from app.segmentation import parse_sam_output  # noqa: E402
from app.voice_client import transcribe  # noqa: E402

PARTS = [f"Fresh {n}.mp4" for n in range(1, 6)]


def build(repeat: int, target: Path) -> None:
    """Re-encode every part to the same size and frame rate so they can be joined; audio is kept (it holds the narration)."""
    inputs = [TESTDATA / p for p in PARTS] * repeat
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for p in inputs:
        cmd += ["-i", str(p)]
    chains = "".join(f"[{i}:v]scale=576:1024,setsar=1,fps=30[v{i}];[{i}:a]aresample=16000,aformat=channel_layouts=mono[a{i}];" for i in range(len(inputs)))
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(inputs)))
    cmd += ["-filter_complex", f"{chains}{joined}concat=n={len(inputs)}:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-c:a", "aac", "-b:a", "64k", str(target)]
    print(f"joining {len(inputs)} clips ...")
    subprocess.run(cmd, check=True)


def stage(label: str, fn):
    """Run one call; print whether it worked, how long it took and the server's message if it refused. Returns None on failure."""
    start = time.perf_counter()
    try:
        out = fn()
    except Exception as e:
        took = time.perf_counter() - start
        why = f"{type(e).__name__}: {str(e)[:200]}"
        if isinstance(e, httpx.HTTPStatusError):
            why += f"\n      server said: {e.response.text[:400]!r}"
        print(f"   {label}: FAILED after {took:.0f}s: {why}")
        return None
    print(f"   {label}: ok in {time.perf_counter() - start:.0f}s")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=7)
    ap.add_argument("--only", choices=["voice", "sam", "all"], default="all")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--book", default=str(TESTDATA / "fresh_book_stock.csv"))
    args = ap.parse_args()

    video = TESTDATA / f"Long test {args.repeat}x.mp4"
    if not video.exists():
        build(args.repeat, video)
    length = duration_seconds(video)
    print(f"{video.name}: {length:.0f} s ({length / 60:.1f} min), {video.stat().st_size / 1e6:.0f} MB, audio sent as {len(wav_bytes(video)) / 1e6:.0f} MB of WAV")
    if args.build_only:
        return

    book = load_book(Path(args.book))
    items = sorted({b.item for b in book})
    locations = sorted({b.location for b in book})
    voice_ok = sam_ok = args.only == "sam" and None

    if args.only in ("voice", "all"):
        voice = stage("voice transcription", lambda: transcribe(video, keywords=items))
        voice_ok = voice is not None
        if voice:
            print(f"   audio {voice.get('audioDurationMs', 0) / 1000:.0f} s, {len(voice.get('turns', []))} turns")
            for t in voice.get("turns", []):
                where = narration.resolve_location(t["transcript"], locations)
                print(f"     {t['startMs'] / 1000:6.1f}-{t['endMs'] / 1000:6.1f} s  {where or '-':8} {t['transcript'][:70]}")

    if args.only in ("sam", "all"):
        raw = stage("SAM on the whole video", lambda: segment_video(video, SAM_PHRASE))
        sam_ok = raw is not None
        if raw:
            print(f"   output {len(raw) / 1e6:.1f} MB of text, {len(parse_sam_output(raw))} frames")

    if args.only == "all" and voice_ok and sam_ok:
        result = stage("whole pipeline (uses the two results above, adds the verification)", lambda: run_clip(video, book))
        if result:
            print(f"   location={result.location} counted={result.counted} needs_review={result.needs_review}")
            print(f"   reasons: {'; '.join(result.reasons)}")
            print("\nExpected for a joined multi-shelf video today: location not recognised and a count for one frame only. That is why a split by shelf is needed.")


if __name__ == "__main__":
    main()
