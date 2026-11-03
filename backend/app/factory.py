import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import create_router
from app.config import DATABASE_URL, OUT, UPLOADS
from app.db import make_session_factory
from app.investigate import Segmenter, create_investigation_router
from app.jobs import Runner, fail_interrupted


def _default_runner() -> Runner:
    from app.pipeline import run_clip  # imported late: pulls in the model clients, which tests replace

    return run_clip


def _default_segmenter() -> Segmenter:
    from app.sam_still import segment_still

    return segment_still


def create_app(
    database_url: str = DATABASE_URL, uploads: Path = UPLOADS, runner: Runner | None = None,
    out: Path = OUT, segmenter: Segmenter | None = None,
) -> FastAPI:
    app = FastAPI(title="LedgerEyes API")

    # Comma-separated list of allowed frontend origins (the Vercel domain in production).
    origins = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    sessions = make_session_factory(database_url)
    fail_interrupted(sessions, out)
    app.include_router(create_router(sessions, uploads, runner or _default_runner(), out))
    app.include_router(create_investigation_router(sessions, uploads, out, segmenter or _default_segmenter()))
    return app

