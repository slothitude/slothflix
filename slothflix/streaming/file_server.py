"""File serving with HTTP Range request support + ffmpeg remux."""

import asyncio
import glob as globmod
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from slothflix.config import settings
from slothflix.services.torrent_engine import CHUNK_SIZE, MIME_TYPES, engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])


async def _resolve_file(file_path: str) -> str | None:
    """Wait for file to appear on disk, checking partial downloads."""
    expected_name = os.path.basename(file_path)
    dl_dir = settings.download_dir

    for i in range(120):  # up to 60s
        # Check exact path
        if os.path.exists(file_path):
            logger.info(f"File found after {i * 0.5:.1f}s")
            return file_path

        # Check partial download suffixes
        for suffix in (".!qB", ".part"):
            part_path = file_path + suffix
            if os.path.exists(part_path):
                logger.info(f"Found partial {suffix} after {i * 0.5:.1f}s")
                return part_path

        # Fallback glob search every 2s
        if i % 4 == 0 and expected_name:
            base_name = os.path.splitext(expected_name)[0]
            matches = globmod.glob(
                os.path.join(dl_dir, "**", base_name + "*"), recursive=True
            )
            if matches:
                logger.info(f"Found via glob: {matches[0]}")
                return matches[0]

        await asyncio.sleep(0.5)

    # Last-resort search
    if expected_name:
        base_name = os.path.splitext(expected_name)[0]
        matches = globmod.glob(
            os.path.join(dl_dir, "**", base_name + "*"), recursive=True
        )
        if matches:
            return matches[0]

    return None


@router.get("/stream/{session_id}")
async def stream_file(session_id: str, request: Request):
    """Stream the current torrent file with Range request support."""
    status = engine.get_status()
    if not status.get("active"):
        return JSONResponse({"error": "No active stream"}, status_code=404)

    file_path = status.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)

    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    mime_type = MIME_TYPES.get(ext, "video/mp4")

    range_header = request.headers.get("range")

    if range_header:
        range_spec = range_header.replace("bytes=", "")
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        async def generate_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            generate_range(),
            status_code=206,
            media_type=mime_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
            },
        )

    # Full file stream
    async def generate_full():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        generate_full(),
        status_code=200,
        media_type=mime_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


@router.get("/play/{session_id}")
async def play_file(session_id: str, request: Request):
    """Serve video for browser playback. MP4 direct, MKV remuxed via ffmpeg."""
    status = engine.get_status()
    if not status.get("active"):
        return JSONResponse({"error": "No active stream"}, status_code=404)

    file_path = status.get("file_path")
    if not file_path:
        return JSONResponse({"error": "File not found"}, status_code=404)

    # Wait for file to appear
    resolved = await _resolve_file(file_path)
    if not resolved:
        logger.error(f"File not found after 60s: {file_path}")
        return JSONResponse(
            {"error": "File not found on disk — torrent may have no seeders"},
            status_code=404,
        )

    ext = os.path.splitext(resolved)[1].lower()

    # MP4/M4V: serve directly with Range support
    if ext in (".mp4", ".m4v"):
        file_size = os.path.getsize(resolved)
        range_header = request.headers.get("range")

        if range_header:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            async def generate_range():
                with open(resolved, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                generate_range(),
                status_code=206,
                media_type="video/mp4",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(length),
                    "Accept-Ranges": "bytes",
                },
            )

        async def generate_full():
            with open(resolved, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            generate_full(),
            status_code=200,
            media_type="video/mp4",
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )

    # MKV/other: remux to fragmented MP4 via ffmpeg
    cmd = [
        "ffmpeg",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        "-i", resolved,
        "-c", "copy",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov",
        "-loglevel", "error",
        "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def generate_remux():
        try:
            while True:
                chunk = await proc.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            stderr = await proc.stderr.read()
            stderr_text = stderr.decode(errors="replace").strip()
            if stderr_text:
                logger.warning(f"ffmpeg stderr: {stderr_text}")
            proc.terminate()
            await proc.wait()

    return StreamingResponse(
        generate_remux(),
        status_code=200,
        media_type="video/mp4",
        headers={"Transfer-Encoding": "chunked"},
    )
