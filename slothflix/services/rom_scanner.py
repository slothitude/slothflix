"""Async ROM directory scanner for SlothFlix game library."""

import asyncio
import logging
from pathlib import Path

from slothflix.config import settings

logger = logging.getLogger(__name__)

SYSTEM_CORE_MAP = {
    "nes": "fceumm",
    "snes": "snes9x",
    "n64": "mupen64plus_next",
    "gba": "mgba",
    "gbc": "gambatte",
    "gb": "gambatte",
    "genesis": "genesis_plus_gx",
    "segacd": "genesis_plus_gx",
    "sega32x": "picodrive",
    "atari2600": "stella",
    "ps1": "pcsx_rearmed",
    "atarilynx": "mednafen_lynx",
    "ngp": "mednafen_ngp",
    "ws": "mednafen_wswan",
    "pcengine": "mednafen_pce",
    "vb": "mednafen_vb",
    "fba": "fbalpha2012",
    "mame": "mame2003",
    "atari7800": "prosystem",
    "coleco": "squirreljong",
    "sms": "genesis_plus_gx",
    "gg": "genesis_plus_gx",
}

ROM_EXTENSIONS = {
    ".nes", ".sfc", ".smc", ".n64", ".z64", ".v64",
    ".gba", ".gbc", ".gb", ".gen", ".smd", ".md",
    ".iso", ".bin", ".cue", ".chd", ".32x",
    ".a26", ".lnx", ".ngp", ".ws", ".pce",
    ".vb", ".zip", ".7z", ".a78", ".col", ".sms", ".gg",
}

_SYSTEM_DISPLAY = {
    "nes": "Nintendo (NES)",
    "snes": "Super Nintendo",
    "n64": "Nintendo 64",
    "gba": "Game Boy Advance",
    "gbc": "Game Boy Color",
    "gb": "Game Boy",
    "genesis": "Sega Genesis",
    "segacd": "Sega CD",
    "sega32x": "Sega 32X",
    "atari2600": "Atari 2600",
    "ps1": "PlayStation",
    "atarilynx": "Atari Lynx",
    "ngp": "Neo Geo Pocket",
    "ws": "WonderSwan",
    "pcengine": "PC Engine",
    "vb": "Virtual Boy",
    "fba": "Final Burn Alpha",
    "mame": "MAME",
    "atari7800": "Atari 7800",
    "coleco": "ColecoVision",
    "sms": "Master System",
    "gg": "Game Gear",
}


async def scan_roms() -> dict:
    """Walk ROM_DIR/<system>/ directories and return ROMs grouped by system.

    Returns a dict of the form:
        {
            "systems": {
                "<system_dir>": {
                    "core": "<emulatorjs core id>",
                    "display_name": "<human-readable name>",
                    "count": <int>,
                    "roms": [
                        {"filename": "<name>", "size": <bytes>, "system": "<system_dir>"},
                        ...
                    ]
                }
            }
        }
    """
    rom_dir = Path(settings.rom_dir)
    systems: dict = {}

    # Run filesystem scan in a thread so we don't block the event loop
    systems = await asyncio.to_thread(_scan_sync, rom_dir)
    return {"systems": systems}


def _scan_sync(rom_dir: Path) -> dict:
    """Synchronous filesystem walk -- called via asyncio.to_thread."""
    systems: dict = {}

    if not rom_dir.is_dir():
        logger.debug("ROM directory %s does not exist", rom_dir)
        return systems

    for system_dir in sorted(rom_dir.iterdir()):
        if not system_dir.is_dir():
            continue

        system_name = system_dir.name
        core = SYSTEM_CORE_MAP.get(system_name)
        if not core:
            continue

        roms = []
        for fpath in sorted(system_dir.iterdir()):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in ROM_EXTENSIONS:
                continue
            try:
                size = fpath.stat().st_size
            except OSError:
                size = 0
            roms.append({
                "filename": fpath.name,
                "size": size,
                "system": system_name,
            })

        if roms:
            systems[system_name] = {
                "core": core,
                "display_name": _SYSTEM_DISPLAY.get(system_name, system_name),
                "count": len(roms),
                "roms": roms,
            }

    return systems
