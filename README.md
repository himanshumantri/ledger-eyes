# LedgerEyes

Turns a phone video of a stockroom into an audit-ready count, reconciled to the books. The business runs it; the auditor or lender receives the evidence.

## Stack
- Frontend: React (Vite PWA), hosted on Vercel
- Backend: Python (FastAPI) with a background worker and Postgres, hosted on Render (US region)
- Video, frames and evidence packs: S3-compatible object storage, uploaded directly from the browser

## Models: Meta only
| Model | Job |
| --- | --- |
| Segment Anything Model 3.1 | Finds, masks and tracks every instance of an item (text phrase or boxed example) |
| Muse Spark 1.3 | Reads labels and serials, classifies items, spots damage, checks capture against the plan |
| Muse Voice Transcribe | Transcribes narration and ties video segments to locations |
| Muse Glimmer (later) | Open-weight option for customers whose data cannot leave their premises |

No other models are used. Allowed non-model utilities: ffmpeg (frame extraction), `hashlib`/`cryptography` (sealing), numpy pixel statistics (lighting and steadiness checks). No OCR, ASR, detection or embedding libraries.

## Setup
```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set MODEL_API_KEY=...
python scripts/smoke_models.py
```
`smoke_models.py` lists every model ID the key can see. Base URL defaults to `https://api.meta.ai/v1`; override with `META_API_BASE_URL`.

## How a clip is counted
1. **Muse Voice Transcribe** transcribes the narration; `app/narration.py` turns "aisle one bay area two" into a plan location and finds the item named.
2. **SAM 3.1** tracks every "cardboard box" through the clip (`app/sam_client.py`). Its output is parsed and filtered per frame (`app/segmentation.py`).
3. **Muse Spark 1.3** checks each SAM box on the clip's best frame, 3 times, majority vote (`app/verification.py`). The count is the number of boxes verified in at least 2 of 3 runs.
4. Anything disputed, split between runs, or seen by Spark with no box sends the clip to human review, with a colour-coded frame (green verified, orange disputed, blue ? uncovered).
5. A human decision is recorded in `reviews.csv` (clip, item, qty, reviewer, note). Cartons are visually identical, so a mixed clip's count is split between items by the reviewer; the machine count stays in the note.
6. `app/reconcile.py` compares counts with book stock, values variances at cost, and writes `reconciliation.csv` and `proposed_adjustments.csv`. One clip per plan location is counted ("canonical"); a re-film replaces it, so a shelf is never counted twice.

Model output is cached in `testdata/out/`, so everything after the model calls reruns offline.

## Who supplies what, and which number wins
| Input | Test | Rollout | Role |
| --- | --- | --- | --- |
| Book stock (`book_stock.csv`) | Hand-written | Exported from the customer's ERP | Comparison baseline only; never a source for the count |
| Truth (`clip_truth.csv`, `fresh_truth.csv`) | Hand counts written before a run | Does not exist; a blind recount of a sampled shelf by a second person plays this part | Measures accuracy; never sets a count |
| Reviews (`reviews.csv`) | The tester | The customer's reviewer, in the reviewer queue, with name and timestamp | Overrides the machine count for that clip |

Counting policy, highest priority first:
1. A reviewer's decision replaces the machine count for that clip; the machine count stays in the note for the audit trail.
2. A machine count with no review reasons (no disputed boxes, split votes or uncovered cartons) is accepted.
3. A flagged machine count with no review is not accepted: it stays `pending_review` and produces no adjustment.

Never taken as a count: book stock, Spark's uncovered cartons (they only trigger review), quantities said aloud in the narration (they name the location and items; a later cross-check at most), and the truth file.

Not built yet, recommended for audit use: the reviewer must not be the person who filmed the shelf, and a blind recount of a sample should produce the stated accuracy.

## Output files
`reconciliation.csv`: one row per book line (plus a location-total row for an unreviewed mixed clip). For the accountant to review.

| Column | Meaning |
| --- | --- |
| location, item | Plan location and item, as in the book |
| book_qty, counted_qty | Book quantity; counted (or reviewed) quantity, blank if not counted |
| variance_qty | counted - book |
| unit_cost, variance_value | Cost from the book; variance_qty x unit_cost |
| status | `match`, `variance`, `pending_review`, `not_counted` |
| count_source, reviewer | `machine` (auto-passed) or `reviewed`, and who reviewed it; blank if nothing was counted |
| flag | `possible transfer with <location>` when the same item is short in one place and over in another: check before posting as two adjustments |
| evidence_frame | Review frame for the clip |
| note | Reviewer and machine count, or the reasons a clip was flagged |

`proposed_adjustments.csv`: only `variance` rows, in a NetSuite-style Inventory Adjustment layout (unconfirmed; test-import first).

| Column | Meaning |
| --- | --- |
| Item, Adjustment Location | As in the book |
| Adjustment Account | Blank: the customer's accounting choice |
| Adjust Qty. By, New Quantity | counted - book; counted |
| Unit Cost, Memo | Book unit cost; memo with the counts, machine or reviewer, the evidence frame and any transfer flag |

Ledger effect: a negative variance reduces inventory and is expensed to the adjustment account; a positive variance does the opposite. Values use the book's unit cost; the ERP revalues on posting if it uses average or FIFO cost, so treat them as estimates. `pending_review` and `not_counted` rows never reach the adjustments file.

## What we learned (build log)
| Step | Finding | Decision |
| --- | --- | --- |
| API check | `sam-3.1`, `muse-spark-1.3` and `muse-voice-transcribe-1.0` are all visible to the key; base URL `https://api.meta.ai/v1` | Hosted API is the main path; Baseten or Spark Open only as a fallback |
| SAM on video | Text prompts work and give masks, confidence and ids. Box prompts mark one object; "find every look-alike from one example" is not documented for the hosted API | Use a text phrase; derive hard-to-name items from Spark |
| SAM ids | Every clip returned exactly 16 distinct ids (probably a cap), and the docs say ids are unreliable across exit, re-entry and occlusion | Never count unique ids; count filtered boxes per frame |
| Filters | Confidence 0.8+, area 4-70% of frame, overlap suppression, then the 80th percentile of per-frame counts. Box size and edge rules cannot tell "more than half visible" | Don't tune thresholds on four clips; add a second opinion |
| Spark check | Per-box verdicts matched the frames; majority of 3 runs was exact on A, B, C and, with its stable uncovered cartons, on D | Spark verifies SAM; uncovered cartons are review triggers, not counts |
| Units bug | Spark returned uncovered boxes in pixels, percent or per-mille | Prompt states pixel size; boxes outside the image are dropped |
| Voice | Transcript was accurate and item names were recognised; timestamps are per turn, not per word | Staff should say a standard location phrase |
| SAM on a still | The hosted API accepts a still image (`input_image`, base64 data URL) and box and point prompts, returning a box, mask and confidence per object (`scripts/sam_still_test.py`, Fresh 3 and 5, frame 0) | An investigate-a-variance screen with click-to-add is feasible |
| Dark cartons | On the Fresh 5 still, SAM did box all five black keyboard cartons, but at 0.61-0.78 confidence, under the 0.8 cutoff; Fresh 3's black keyboard cartons scored 0.77 and 0.69 | The earlier "never boxed" reading was too strong: they were found and filtered out. A lower cutoff plus Spark's check is a hypothesis to test on new clips, not a fix |
| 16-object cap | A text prompt on one still returned exactly 16 objects (one a thin sliver) | The cap is per request, not a video-tracking effect. A shelf with more cartons needs region crops |
| Guided prompts | A point on a Fresh 3 keyboard carton returned the same box as the text prompt (0.76 confidence). On Fresh 5, prompts built from Spark's approximate boxes missed: one point landed on the neighbouring white carton, and box prompts scored 0.17 and 0.0 | A human click works; Spark's coordinates cannot be used as automatic prompts |
| Marking with four corners (2 Nov 2026) | `scripts/sam_corners_test.py`, four cartons on Fresh 3 and 5, frame 0. A `polygon` token is refused (400, unknown token). Four points on one object id are refused (400, "object id 1 is used more than once"). Four points as four ids return four unrelated objects: corner points sit on edges and grab the wall or shelf (boxes like (0,0)-(571,380), overlap with the reference 0.05-0.27) | SAM takes one point or one box per object, so four corners cannot be a shape. The reviewer marks a carton with two corners (top-left, bottom-right) and SAM gets that box |
| Box or point (same test) | Overlap with the reference box, box vs middle point: Fresh 3 keyboard 0.64 vs 0.59, Fresh 3 red carton 0.54 vs 0.60, Fresh 5 top keyboard 0.56 vs 0.34, Fresh 5 second keyboard 0.74 vs 0.19. On Fresh 5 the point picked the same different, taller object both times. The reference boxes are Spark's rough boxes, so overlaps are indicative, not exact | A box is the only way to add a carton in Correct real footage; the click-the-middle mode was removed |
| Confidence on a box prompt | 0.50 and 0.00 on outlines that matched the reference at 0.56 and 0.74 | Confidence is not shown for boxes the reviewer marked ("you marked it"); it stays in the log |
| Partly hidden cartons | SAM outlines only the visible part (Fresh 3, lower carton: a strip) | The reviewer marks what is visible and counts it only if more than half is; the rule and the reason go in the log |
| Footage | Some clips are filmed sideways; cartons are visually identical, so item identity comes from narration or labels | Capture check for orientation (todo); mixed clips compare location totals |

### Held-out test: Fresh 1-5 (code frozen, truth written beforehand)
Five clips on five different shelves, scored against `fresh_truth.csv` using the visible count (cartons more than half visible).

| Clip | Truth | Counted | Routed | What happened |
| --- | --- | --- | --- | --- |
| Fresh 1 (clean) | 4 | 4 | auto-pass | Correct |
| Fresh 2 (mixed) | 5 | 3 | review | SAM alone found all 5; Spark disputed the 2 red boxes, which look like real cartons |
| Fresh 3 (occluded) | 3 | 1 | review | 2 further cartons flagged as uncovered: the dark keyboard boxes on a dark shelf |
| Fresh 4 (labels) | 3 | 3 | auto-pass | Correct |
| Fresh 5 (16 visible, 17 present) | 16 | 6 | review | 7 further cartons flagged as uncovered; SAM never boxed the black keyboard cartons at 0.8+ confidence, and the best frame was a motion-blurred pan |

- No wrong count was passed automatically: both auto-passes were right, and every miss went to review. That is the design working, not accuracy: 2 of 5 clips were counted correctly without help.
- Weak spots: dark cartons on a dark background, blurred best frames, and Spark sometimes disputing real cartons (Fresh 2).
- Fresh 5 has 16 visible cartons, so it sits on the 16-id limit and does not test it cleanly. Raw ids were 16 again.
- Narration: "shelf B1 with four monitors" was resolved to A1-B4, because the "four" was read as a location number. Fixed afterwards: only numbers after "aisle", "bay", "shelf" or a code like "B2" count, and a shelf said without an aisle is reported as ambiguous when two shelves share it (here A3-B1 and A4-B1), not guessed. Fresh 1-5 were seen before this fix, so it is not a held-out result.
- Any change to filters or prompts made after this point is tuning on seen clips and needs new clips to measure.

Known limits: five clips is a small sample. Accuracy claims need more footage of other shelves, scored against hand counts. Cartons are treated as units (no pack sizes). The NetSuite-style adjustment columns come from community docs and need a test import.

## Running it
```
cd backend
.\.venv\Scripts\python.exe -m pytest                                  # unit tests
.\.venv\Scripts\python.exe scripts\evaluate.py                        # score cached SAM output vs testdata\clip_truth.csv
.\.venv\Scripts\python.exe scripts\run_pipeline.py "Clip A.mp4" --canonical "A1-B2=Clip A.mp4"
```
`run_pipeline.py` also takes `--book <csv>` (default `testdata/book_stock.csv`) and `--reviews <csv>`, so a separate set such as Fresh 1-5 keeps its own book and review files.
Model calls need `MODEL_API_KEY`. `testdata/` (clips, book_stock.csv, clip_truth.csv, cached output) is git-ignored.

## Running the service
Backend (SQLite locally, Postgres when `DATABASE_URL` is set):
```
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
set MODEL_API_KEY=...
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
Frontend:
```
cd frontend
copy .env.example .env        # VITE_API_URL=http://localhost:8000
npm install
npm run dev                   # http://localhost:5173
```
There is no login yet. A "Viewing as" switch (Capturer, Reviewer, Auditor) changes the tabs. Name and Employee ID start blank and must be filled in before anything is recorded; both are stored with the upload, the review and every step of Correct real footage, and the same employee ID (or the same name) cannot capture and review a clip. A "Viewing as" role records the typed name on actions: the capturer uploads, the reviewer counts flagged clips and corrects real footage, the auditor loads the book stock and reads the reconciliation. The server refuses a review from the person who captured the clip. A video can be up to 6 minutes (`MAX_VIDEO_SECONDS`; longer is refused with a message). `scripts/long_video_test.py` joins the Fresh clips into a long video and tries the services on it. Result on 3 Nov 2026: the voice model transcribed 6.8 minutes (13 MB of audio) in 63 seconds, split into 31 narration turns, but answered 502 Bad Gateway after 51 seconds to 9.5 minutes (18 MB), cause unknown; SAM accepted the 9.5-minute video in 32 seconds. The cap is therefore 6 minutes. The whole pipeline on a long video has not been run yet. After counting, the server makes a silent preview copy (about 540 px wide, 700 kbps, so about 50 MB for 10 minutes) and keeps it in the database so it survives a restart; it is what the reviewer plays and pauses. One upload is still one clip and one location: a video that names several shelves comes back as "location not recognised" until the split-by-shelf step (cut at each narration turn that names a location) is built. Flow in the app: **Book stock** (upload the ERP CSV) -> **Capture** (a clip is fingerprinted on the device and re-hashed by the server; a mismatch is rejected) -> counting runs in the background -> **Clips** (flagged clips show the evidence frame; the reviewer enters per-item counts, and names the location if the narration did not) -> **Correct real footage** (the reviewer's tool, on any counted clip: the reviewer plays a small copy of the video, pauses on the moment to correct and presses Use this frame, or starts from the frame the pipeline picked; SAM proposes cartons on that frame, the reviewer includes or excludes each, redraws a box that is wrong, deletes one that is not a carton, adds one SAM missed by clicking its top-left and bottom-right corners, and says which item each is; the box between the two corners is sent to SAM as a box prompt and SAM outlines the carton inside it, and the two corners are kept in the log (see the build log for why not four corners); confirming writes the counts as the clip's review) -> **Reconciliation** (table and the two CSV downloads).

API: `PUT /plan`, `GET /plan`, `POST /clips`, `GET /clips`, `GET /clips/{id}`, `GET /clips/{id}/evidence`, `POST /clips/{id}/review`, `POST /clips/{id}/investigations`, `GET /clips/{id}/investigations`, `GET /investigations/{id}`, `GET /investigations/{id}/frame`, `POST /investigations/{id}/clicks`, `POST /investigations/{id}/boxes`, `POST /clips/{id}/investigations/from-frame`, `GET /clips/{id}/preview`, `DELETE /investigations/{id}/objects/{obj}`, `PATCH /investigations/{id}/objects/{obj}`, `POST /investigations/{id}/resolve`, `GET /reconciliation`, `GET /reconciliation.csv`, `GET /proposed_adjustments.csv`. The latest finished clip per location is the one reconciled, so a re-film replaces the earlier clip; every upload and every review submission is kept.

Status: tested with a fake pipeline (`tests/test_api.py`). Deployed as a trial on free tiers: the API on Render (Docker, free Postgres) and the frontend on Vercel, reached by setting `VITE_API_URL` on Vercel and `CORS_ORIGINS` on Render. Free-tier limits: the API sleeps when idle, the filesystem is wiped on restart (uploaded videos are lost; counts, reviews, evidence images and the unmarked frames used by Correct real footage are also kept in the database, so they survive), and the free database expires. The paid setup with a persistent disk is in `render.yaml`. Not yet run end to end with real clips through the UI; the Correct real footage screen is tested against a fake SAM only (including drawn and redrawn boxes) and the drag has not been tried in a browser. It shows what one picture holds: cartons hidden behind others are not counted, SAM stops at 16 objects per request (the screen warns), and "explained as a transfer" is not an outcome yet. Every action in an investigation is logged, and the machine count is kept beside the reviewer's. If the hosting becomes a problem, Google Cloud is the fallback. Known gaps: no login or per-customer separation, counting runs inside the API process (a worker comes later), uploads sit on a disk (object storage later), tables are created at start-up (migrations before the schema changes), and the capture screen does not check orientation or lighting yet.

## Next steps
1. Fix the weak spots from the Fresh run (dark cartons, blurred frames, Spark over-disputing) and measure the fix on new clips, including one with more than 16 visible cartons. Waiting on new footage.
2. Run the service end to end with real clips through the UI, then deploy: Render (blueprint in `render.yaml`) and Vercel (set `VITE_API_URL`, and `CORS_ORIGINS` on the API).
3. Capture screen: orientation, lighting and steadiness checks before upload; server countersigning and a sealed evidence pack.
4. Login, reviewer separate from capturer, and a blind-recount sample for the stated accuracy.
