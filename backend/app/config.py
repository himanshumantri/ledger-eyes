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
MAX_VIDEO_SECONDS = int(os.environ.get("MAX_VIDEO_SECONDS", "120"))  # only 12-29 second clips are proven; raise this when long_video_test.py passes at a longer length


def auth_headers() -> dict:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set; only cached results can be used without it.")
    return {"Authorization": f"Bearer {key}"}
