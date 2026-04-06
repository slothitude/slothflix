"""Games API routes -- ROM scanning, serving, and game torrent catalog."""

import asyncio
import logging
from pathlib import Path

import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from slothflix.config import settings
from slothflix.services.rom_scanner import (
    ROM_EXTENSIONS,
    SYSTEM_CORE_MAP,
    scan_roms,
)
from slothflix.services.search_provider import fetch_top_games

logger = logging.getLogger(__name__)

router = APIRouter(tags=["games"])


@router.get("/games")
async def games():
    """Scan ROM directories and return available games grouped by system."""
    return await scan_roms()


@router.get("/games/rom/{system}/{filename:path}")
async def serve_rom(system: str, filename: str):
    """Serve a ROM file with path traversal protection.

    The ``filename`` parameter uses Starlette's ``:path`` converter so it may
    contain slashes (e.g. sub-directories inside a system folder).  We resolve
    the full path and verify it stays within ROM_DIR before serving.
    """
    # Validate system name -- reject anything that tries to escape
    if "/" in system or "\\" in system or ".." in system:
        raise HTTPException(status_code=400, detail="Invalid system")

    rom_dir = Path(settings.rom_dir).resolve()
    full_path = (rom_dir / system / filename).resolve()

    # Path traversal check
    if not str(full_path).startswith(str(rom_dir)):
        raise HTTPException(status_code=400, detail="Invalid path")

    # Extension whitelist
    if full_path.suffix.lower() not in ROM_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        str(full_path),
        filename=full_path.name,
        media_type="application/octet-stream",
    )


@router.get("/catalog/games")
async def catalog_games():
    """Top 100 game torrents (cached, background refresh).

    Delegates to the catalog module's cache layer.
    """
    from slothflix.api.catalog import _background_refresh, _load_catalog, _save_catalog

    cached = await _load_catalog("games")
    if cached:
        from slothflix.services.search_provider import fetch_top_games

        asyncio.create_task(_background_refresh("games", fetch_top_games, "games"))
        return cached

    try:
        from slothflix.services.search_provider import fetch_top_games

        async with httpx.AsyncClient() as client:
            results = await fetch_top_games(client)
        await _save_catalog("games", results)
        return results
    except Exception as e:
        logger.error(f"Failed to fetch game catalog: {e}")
        raise HTTPException(status_code=500, detail=str(e))
