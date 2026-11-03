"""Settings shared by the model clients and the pipeline."""
import os
from pathlib import Path

BASE_URL = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1").rstrip("/")
SAM_MODEL = os.environ.get("SAM_MODEL_ID", "sam-3.1")
SPARK_MODEL = os.environ.get("SPARK_MODEL_ID", "muse-spark-1.3")
VOICE_MODEL = os.environ.get("VOICE_MODEL_ID", "muse-voice-transcribe-1.0")

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = Path(os.environ.get("LEDGER_DATA_DIR", ROOT / "testdata"))
OUT = TESTDATA / "out"  # cached raw model output, so reruns need no API call

# Service settings. Locally: SQLite and a folder. On Render: DATABASE_URL (Postgres) and, later, object storage.
UPLOADS = Path(os.environ.get("UPLOAD_DIR", TESTDATA / "uploads"))
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(TESTDATA / 'ledgereyes.db').as_posix()}")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
# SAM refuses a video of more than 15,000 frames ("found at least 17101" for 9.5 minutes at 30 fps) and took 14,658 frames (8.1 minutes)
# in 671 s. The limit is frames, so a phone filming at 60 fps reaches it in half the time; both are checked on upload.
MAX_VIDEO_FRAMES = int(os.environ.get("MAX_VIDEO_FRAMES", "14900"))
MAX_VIDEO_SECONDS = int(os.environ.get("MAX_VIDEO_SECONDS", "500"))  # 8:20, which is 15,000 frames at 30 fps


def auth_headers() -> dict:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set; only cached results can be used without it.")
    return {"Authorization": f"Bearer {key}"}
