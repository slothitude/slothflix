"""Vimm.net API routes for browsing, info, downloading ROMs, and cover art."""

import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from slothflix.config import settings
from slothflix.services.vimm_client import (
    browse,
    download_rom,
    fetch_cover_bytes,
    get_extension_for_system,
    get_game_info,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["vimm"])


# --- Request / Response models ---


class DownloadRequest(BaseModel):
    game_id: int
    media_id: int | None = None
    filename: str | None = None
    system: str = "nes"


class DownloadResponse(BaseModel):
    status: str
    path: str
    filename: str
    system: str


# --- Routes ---


@router.get("/vimm/browse")
async def vimm_browse(
    system: str = Query("NES", description="Vimm system name (e.g. NES, SNES, GBA)"),
    letter: str = Query("A", description="Letter to browse (A-Z)"),
):
    """Browse vimm.net game catalog by system and letter."""
    letter = letter.upper()
    if len(letter) != 1 or not letter.isalpha():
        letter = "A"
    games = await browse(system, letter)
    return {"games": games, "system": system, "letter": letter}


@router.get("/vimm/info")
async def vimm_info(
    game_id: int = Query(..., description="Vimm vault game ID"),
):
    """Get detailed info for a vimm.net game."""
    info = await get_game_info(game_id)
    if not info:
        raise HTTPException(status_code=404, detail="Game not found")
    return info


@router.post("/vimm/download", response_model=DownloadResponse)
async def vimm_download(body: DownloadRequest):
    """Download a ROM from vimm.net and save to the ROM directory.

    Tries docker exec into the emulatorjs container first (bypasses VPN block),
    then falls back to direct download through VPN.
    """
    game_id = body.game_id
    media_id = body.media_id
    system = body.system

    # Get game info if media_id not provided
    if not media_id:
        info = await get_game_info(game_id)
        if not info or not info.get("media_id"):
            raise HTTPException(
                status_code=400, detail="Could not determine media ID"
            )
        media_id = info["media_id"]

    # Determine system directory and filename
    info = await get_game_info(game_id)
    title = info.get("title", f"game_{game_id}") if info else f"game_{game_id}"

    # Determine extension from system name on the game page
    ext = ".nes"
    if info and info.get("system_name"):
        ext = get_extension_for_system(info["system_name"])

    filename = body.filename or (title + ext)
    # Clean filename of invalid characters
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|')

    rom_dir = settings.rom_dir
    dest_dir = os.path.join(rom_dir, system)
    os.makedirs(dest_dir, exist_ok=True)
    filepath = os.path.join(dest_dir, filename)

    dl_url = f"https://dl3.vimm.net/?mediaId={media_id}"
    referer = f"https://vimm.net/vault/{game_id}"

    # Use emulatorjs container (not VPN-routed) to download via docker exec.
    # emulatorjs mounts rom-data at /data, slothflix mounts it at /data/roms
    emu_dir = f"/data/{system}"
    emu_filepath = f"{emu_dir}/{filename}"

    try:
        # Create directory in emulatorjs container
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "emulatorjs", "mkdir", "-p", emu_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)

        # Download via wget inside emulatorjs container
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "emulatorjs",
            "wget", "-qO", emu_filepath,
            "--header", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--header", f"Referer: {referer}",
            "--timeout=120",
            dl_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=130)

        if (
            proc.returncode == 0
            and os.path.isfile(filepath)
            and os.path.getsize(filepath) > 100
        ):
            log.info(
                f"Downloaded {filename} via emulatorjs ({os.path.getsize(filepath)} bytes)"
            )
            return DownloadResponse(
                status="ok",
                path=filepath,
                filename=filename,
                system=system,
            )
        else:
            stderr = ""
            if proc.stderr:
                stderr_bytes = await proc.stderr.read()
                stderr = stderr_bytes.decode(errors="replace")[:200]
            log.error(
                f"Emulatorjs download failed: rc={proc.returncode} stderr={stderr}"
            )
            if os.path.isfile(filepath):
                os.remove(filepath)
    except Exception as e:
        log.error(f"Emulatorjs download error: {e}")

    # Fallback: try through VPN (might work for some regions)
    result = await download_rom(game_id, media_id, dest_dir, filename)
    if not result:
        raise HTTPException(
            status_code=500, detail="Download failed (vimm.net may block VPN)"
        )

    return DownloadResponse(
        status="ok",
        path=result,
        filename=os.path.basename(result),
        system=system,
    )


@router.get("/vimm/cover")
async def vimm_cover_proxy(
    game_id: int = Query(..., description="Vimm vault game ID"),
):
    """Proxy cover art from vimm.net with local caching."""
    # Cache directory next to the database
    cache_dir = os.path.join(
        os.path.dirname(settings.cache_db_path), "covers"
    )
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{game_id}.jpg")

    # Serve from cache if available
    if os.path.isfile(cache_file) and os.path.getsize(cache_file) > 100:
        return Response(
            content=Path(cache_file).read_bytes(),
            media_type="image/jpeg",
        )

    # Fetch from vimm.net (tries box then cart art)
    result = await fetch_cover_bytes(game_id)
    if not result:
        raise HTTPException(status_code=404, detail="Cover art not found")

    image_bytes, content_type = result

    # Cache to disk
    with open(cache_file, "wb") as f:
        f.write(image_bytes)

    return Response(content=image_bytes, media_type=content_type)
