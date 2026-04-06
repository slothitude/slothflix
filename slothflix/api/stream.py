"""Stream API routes — start, status, stop, file listing."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from slothflix.services.torrent_engine import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


class StreamStartRequest(BaseModel):
    magnet: str
    file_id: int | None = None


class StreamStartResponse(BaseModel):
    session_id: str
    file_path: str


@router.post("/stream/start", response_model=StreamStartResponse)
async def stream_start(body: StreamStartRequest):
    """Start torrent stream. Blocks until 10% buffered."""
    magnet = body.magnet
    file_id = body.file_id

    # Session ID from magnet hash
    session_id = magnet.split(":")[3][:12] if ":" in magnet else "default"

    try:
        file_path = await engine.start_torrent(magnet, file_id=file_id)
        return StreamStartResponse(session_id=session_id, file_path=file_path)
    except Exception as e:
        logger.error(f"Stream start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream/status")
async def stream_status():
    """Get current torrent download status."""
    return engine.get_status()


@router.post("/stream/stop")
async def stream_stop():
    """Stop the current torrent stream."""
    await engine.stop()
    return {"status": "stopped"}


@router.post("/stream/files")
async def torrent_files(body: StreamStartRequest):
    """Get file list from a magnet URI (for episode picker)."""
    try:
        files = await engine.get_torrent_files(body.magnet)
        return files
    except Exception as e:
        logger.error(f"File listing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
