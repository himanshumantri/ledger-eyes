"""Can a reviewer mark a carton by clicking its four corners, and can SAM 3.1 use all four?

    python scripts/sam_corners_test.py [--dry-run]

For a few cartons on frame 0 of Fresh 3 and Fresh 5, takes the four corners (top-left, top-right, bottom-right,
bottom-left) and sends them to SAM in every shape that might work:

  centre point        one point in the middle (what "Click a carton" sends today)
  box from corners    the rectangle that contains the four corners (what "Draw a carton" sends today)
  4 points, one id    four points all labelled object 1 -- would mean "one object marked by four points"
  4 points, 4 ids     four points labelled 1 to 4 -- would mean four separate objects
  polygon             a `polygon` token; it is not in the SAM docs, so this is expected to be refused

Each answer is compared with the reference box (Spark's rough box for that carton, so a score near 0.6-0.8 is a good
match, not a perfect one). Raw output is saved as testdata/out/sam_corners_*.txt. --dry-run extracts the frames and
prints the requests without calling the API (no key needed).
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import OUT, TESTDATA  # noqa: E402
from app.media import extract_frame  # noqa: E402
from app.segmentation import parse_sam_output  # noqa: E402
from sam_still_test import ask  # noqa: E402

# Rough reference boxes in pixels of the 576x1024 frame (Spark's approx boxes from the cached verification).
CARTONS = {
    "Fresh 3": {"black keyboard carton": [119, 168, 519, 280], "small red carton": [78, 209, 282, 360]},
    "Fresh 5": {"top black keyboard carton": [330, 435, 525, 540], "second black keyboard carton": [330, 542, 517, 587]},
}
INSET = 0.08  # the reviewer clicks the corners a little inside the carton, not exactly on its edge


def corners(box: list[int]) -> list[tuple[int, int]]:
    x1, y1, x2, y2 = box
    dx, dy = int((x2 - x1) * INSET), int((y2 - y1) * INSET)
    return [(x1 + dx, y1 + dy), (x2 - dx, y1 + dy), (x2 - dx, y2 - dy), (x1 + dx, y2 - dy)]


def point(i: int, x: int, y: int, w: int, h: int) -> str:
    return f"{i}<|point;x={x};y={y};w={w};h={h}|>"


def requests(box: list[int], w: int, h: int) -> dict[str, str]:
    pts = corners(box)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    poly = ";".join(f"x{i}={x};y{i}={y}" for i, (x, y) in enumerate(pts, 1))
    return {
        "centre point": "<0f>" + point(1, cx, cy, w, h),
        "box from corners": f"<0f>1<|box;x1={min(xs)};y1={min(ys)};x2={max(xs)};y2={max(ys)};w={w};h={h}|>",
        "4 points, one id": "<0f>" + ",".join(point(1, x, y, w, h) for x, y in pts),
        "4 points, 4 ids": "<0f>" + ",".join(point(i, x, y, w, h) for i, (x, y) in enumerate(pts, 1)),
        "polygon": f"<0f>1<|polygon;{poly};w={w};h={h}|>",
    }


def overlap(a: list[int], b: list[int]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for clip, cartons in CARTONS.items():
        still = OUT / "stills" / f"{clip}_f0.png"
        extract_frame(TESTDATA / f"{clip}.mp4", 0, still)
        w, h = Image.open(still).size
        print(f"\n== {clip}: still is {w}x{h}")
        for name, ref in cartons.items():
            print(f"\n-- {name}: reference box {ref}, corners {corners(ref)}")
            for label, text in requests(ref, w, h).items():
                print(f"   [{label}] {text[:100]}{'...' if len(text) > 100 else ''}")
                if args.dry_run:
                    continue
                status, raw = ask(text, still)
                (OUT / f"sam_corners_{clip}_{name}_{label}.txt".replace(" ", "_").replace(",", "")).write_text(raw, encoding="utf-8")
                if status != 200:
                    print(f"      REFUSED {status}: {raw[:300]}")
                    continue
                found = parse_sam_output(raw).get(0, [])
                if not found:
                    print(f"      nothing returned; raw head {raw[:120]!r}")
                for d in found:
                    print(f"      id {d.obj_id}: conf {d.conf:.2f} box ({d.x1},{d.y1})-({d.x2},{d.y2}) overlap with reference {overlap([d.x1, d.y1, d.x2, d.y2], ref):.2f}")


if __name__ == "__main__":
    main()
