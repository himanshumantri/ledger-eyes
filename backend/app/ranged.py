"""Serve a file with HTTP range support, so a browser can seek in a video.

Starlette's FileResponse in the pinned version ignores the Range header, and without ranges a video cannot jump to a
time that has not been downloaded yet. Each answer carries at most CHUNK bytes, which keeps memory small on a free host.
"""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

CHUNK = 4 * 1024 * 1024


def ranged_file(path: Path, range_header: str | None, media_type: str) -> Response:
    size = path.stat().st_size
    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    unit, _, spec = range_header.partition("=")
    first, _, last = spec.split(",")[0].strip().partition("-")
    try:
        if unit.strip() != "bytes":
            raise ValueError
        if first == "":  # the final N bytes
            start, end = max(0, size - int(last)), size - 1
        else:
            start, end = int(first), int(last) if last else size - 1
    except ValueError:
        raise HTTPException(416, "Unreadable Range header", headers={"Content-Range": f"bytes */{size}"}) from None
    if start >= size or start > end:
        raise HTTPException(416, "Range is outside the file", headers={"Content-Range": f"bytes */{size}"})
    end = min(end, size - 1, start + CHUNK - 1)
    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(end - start + 1)
    return Response(
        data, status_code=206, media_type=media_type,
        headers={"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(len(data))},
    )
