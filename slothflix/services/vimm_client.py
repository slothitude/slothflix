"""Async Vimm.net vault scraper using httpx."""

import json
import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

BASE = "https://vimm.net"
DL_BASE = "https://dl3.vimm.net"
IMAGE_BASE = "https://dl.vimm.net/image.php"

# Map SlothFlix system names to Vimm system params
SYSTEM_MAP = {
    "nes": "NES",
    "snes": "SNES",
    "gba": "GBA",
    "gbc": "GBC",
    "n64": "N64",
    "psx": "PS1",
    "segamd": "Genesis",
    "atari2600": "Atari2600",
    "nds": "DS",
    "saturn": "Saturn",
    "segacd": "SegaCD",
    "32x": "32X",
    "atari7800": "Atari7800",
    "lynx": "Lynx",
    "gg": "GG",
    "vb": "VB",
    "ms": "SMS",
    "pce": "TG16",
}

# Reverse map: Vimm system name -> our system key
VIMM_TO_SYSTEM = {v.lower(): k for k, v in SYSTEM_MAP.items()}
# Add some aliases
VIMM_TO_SYSTEM["nintendo"] = "nes"
VIMM_TO_SYSTEM["super nintendo"] = "snes"
VIMM_TO_SYSTEM["game boy adv"] = "gba"
VIMM_TO_SYSTEM["game boy color"] = "gbc"
VIMM_TO_SYSTEM["turbografx-16"] = "pce"
VIMM_TO_SYSTEM["master system"] = "ms"
VIMM_TO_SYSTEM["game gear"] = "gg"
VIMM_TO_SYSTEM["virtual boy"] = "vb"

# Extensions by Vimm system
SYSTEM_EXTENSIONS = {
    "NES": ".nes", "SNES": ".sfc", "GBA": ".gba", "GBC": ".gbc",
    "N64": ".z64", "PS1": ".bin", "Genesis": ".md", "Atari2600": ".a26",
    "DS": ".nds", "Saturn": ".bin", "SegaCD": ".bin", "32X": ".32x",
    "Atari7800": ".a78", "Lynx": ".lnx", "GG": ".gg", "VB": ".vb",
    "SMS": ".sms", "TG16": ".pce",
}

# Shared httpx client (lazy-initialized)
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient, creating one if needed."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )
    return _client


async def close_client():
    """Close the shared httpx client (call on shutdown)."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def browse(system: str, letter: str = "A") -> list[dict]:
    """Browse games on vimm.net by system and letter.

    Returns list of dicts with id, title, rating keys.
    """
    client = await _get_client()
    url = f"{BASE}/vault/"
    params = {"p": "list", "system": system, "section": letter}
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Failed to browse vimm.net: {e}")
        return []

    games = []
    # Match: <a href="/vault/123" ...>Game Title</a>
    # Rating from: <a href="/vault/?p=rating&id=123">8.7</a>
    pattern = re.compile(
        r'<a\s+href\s*=\s*"/vault/(\d+)"[^>]*>\s*([^<]+?)\s*</a>.*?'
        r'href="/vault/\?p=rating&amp;id=\d+">([\d.]+)</a>',
        re.DOTALL,
    )
    for m in pattern.finditer(resp.text):
        game_id = int(m.group(1))
        title = m.group(2).strip()
        rating = m.group(3)
        games.append({"id": game_id, "title": title, "rating": rating})

    return games


async def get_game_info(game_id: int) -> dict:
    """Get detailed info for a game from its vault page.

    Returns dict with id, title, media_id, size, system_name, box_art_url, cart_url.
    """
    client = await _get_client()
    url = f"{BASE}/vault/{game_id}"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Failed to get game info for {game_id}: {e}")
        return {}

    html = resp.text

    # Parse title from og:title
    title_m = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    title = title_m.group(1) if title_m else f"Game {game_id}"

    # Parse the media JS array for mediaId and size
    # media=[{"ID":818,"ZippedText":"31 KB",...}]
    media_m = re.search(r'let\s+media=\[({[^]]+})\]', html)
    media_id = None
    size_text = ""
    if media_m:
        try:
            media = json.loads(media_m.group(1))
            media_id = media.get("ID")
            size_text = media.get("ZippedText", "")
        except Exception:
            pass

    # Fallback: find mediaId from form
    if not media_id:
        mid_m = re.search(r'name="mediaId"\s+value="(\d+)"', html)
        if mid_m:
            media_id = int(mid_m.group(1))

    box_art_url = f"{IMAGE_BASE}?type=box&id={game_id}"
    cart_url = f"{IMAGE_BASE}?type=cart&id={game_id}&size=1"

    # Determine system from page content (e.g. "for the Nintendo")
    sys_m = re.search(r'for the\s+([^"<]+)', html)
    system_name = sys_m.group(1).strip() if sys_m else ""

    return {
        "id": game_id,
        "title": title,
        "media_id": media_id,
        "size": size_text,
        "system_name": system_name,
        "box_art_url": box_art_url,
        "cart_url": cart_url,
    }


async def download_rom(
    game_id: int, media_id: int, dest_dir: str, filename: str | None = None
) -> str | None:
    """Download a ROM from vimm.net via the download server.

    Args:
        game_id: Vimm vault ID.
        media_id: Media ID from the game page.
        dest_dir: Directory to save the ROM.
        filename: Optional filename override.

    Returns:
        Path to the downloaded file, or None on failure.
    """
    if not media_id:
        log.error(f"No media_id for game {game_id}")
        return None

    client = await _get_client()

    try:
        # Fetch game page to determine system extension
        resp = await client.get(f"{BASE}/vault/{game_id}")
        sys_m = re.search(r'for the\s+([^"<]+)', resp.text)
        ext = ".nes"
        if sys_m:
            sys_name = sys_m.group(1).strip().lower()
            for vimm_key, ext_val in SYSTEM_EXTENSIONS.items():
                if vimm_key.lower() in sys_name:
                    ext = ext_val
                    break

        # GET from download server
        dl_resp = await client.get(
            DL_BASE,
            params={"mediaId": str(media_id)},
            timeout=httpx.Timeout(120.0),
        )
        dl_resp.raise_for_status()

        # Determine filename
        if not filename:
            cd = dl_resp.headers.get("content-disposition", "")
            fname_m = re.search(r'filename="([^"]+)"', cd)
            if fname_m:
                filename = fname_m.group(1)
            else:
                info = await get_game_info(game_id)
                title = info.get("title", f"game_{game_id}")
                filename = title + ext

        if not filename:
            filename = f"game_{game_id}{ext}"

        os.makedirs(dest_dir, exist_ok=True)
        filepath = os.path.join(dest_dir, filename)
        with open(filepath, "wb") as f:
            f.write(dl_resp.content)

        log.info(f"Downloaded {filename} ({len(dl_resp.content)} bytes)")
        return filepath

    except Exception as e:
        log.error(f"Failed to download ROM {game_id}: {e}")
        return None


async def download_cover(game_id: int, dest_dir: str) -> str | None:
    """Download box art for a game.

    Returns path to the saved image or None.
    """
    client = await _get_client()
    try:
        resp = await client.get(
            f"{IMAGE_BASE}?type=box&id={game_id}",
        )
        resp.raise_for_status()
        if len(resp.content) < 100:
            return None

        os.makedirs(dest_dir, exist_ok=True)
        filepath = os.path.join(dest_dir, f"{game_id}.jpg")
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath
    except Exception as e:
        log.error(f"Failed to download cover for {game_id}: {e}")
        return None


async def fetch_cover_bytes(game_id: int) -> tuple[bytes, str] | None:
    """Fetch cover image bytes from vimm.net (tries box then cart).

    Returns (image_bytes, content_type) or None.
    """
    client = await _get_client()
    for img_type in ("box", "cart"):
        try:
            resp = await client.get(
                f"{IMAGE_BASE}?type={img_type}&id={game_id}",
            )
            if resp.status_code == 200 and len(resp.content) > 100:
                ct = resp.headers.get("content-type", "image/jpeg")
                return (resp.content, ct)
        except Exception:
            continue
    return None


def get_extension_for_system(system_name: str) -> str:
    """Determine file extension from a Vimm system name string."""
    ext = ".nes"
    sys_lower = system_name.lower()
    for vimm_key, ext_val in SYSTEM_EXTENSIONS.items():
        if vimm_key.lower() in sys_lower:
            ext = ext_val
            break
    return ext
