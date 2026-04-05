"""Vimm.net vault scraper for browsing and downloading ROMs."""

import re
import os
import logging
import requests
from html.parser import HTMLParser
from urllib.parse import urljoin

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

# Reverse map: Vimm system name → our system key
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

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0"})


class _GameListParser(HTMLParser):
    """Parse the vimm.net game list table."""

    def __init__(self):
        super().__init__()
        self.games = []
        self._in_td = False
        self._in_link = False
        self._current = {}
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a":
            href = attrs_dict.get("href", "")
            m = re.match(r"/vault/(\d+)", href)
            if m:
                self._in_link = True
                self._current = {"id": int(m.group(1))}
                self._capture = "title"
        if tag == "td":
            self._in_td = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
            self._capture = None
        if tag == "td":
            self._in_td = False

    def handle_data(self, data):
        if self._capture == "title" and self._current:
            title = data.strip()
            if title:
                self._current["title"] = title
                self.games.append(self._current)
                self._current = {}
                self._capture = None


def browse(system, letter="A"):
    """Browse games on vimm.net by system and letter.

    Uses regex extraction since the table format is consistent.
    Returns list of dicts with id, title, rating keys.
    """
    url = f"{BASE}/vault/"
    params = {"p": "list", "system": system, "section": letter}
    try:
        resp = _session.get(url, params=params, timeout=15)
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


def get_game_info(game_id):
    """Get detailed info for a game from its vault page.

    Returns dict with id, title, media_id, size, version, box_art_url.
    """
    url = f"{BASE}/vault/{game_id}"
    try:
        resp = _session.get(url, timeout=15)
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
            import json
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

    # Determine system from page title (e.g. "Vimm's Lair: Super Mario Bros.")
    # Or from the og:description which says "for the Nintendo"
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


def download_rom(game_id, media_id, dest_dir, filename=None):
    """Download a ROM from vimm.net.

    Args:
        game_id: Vimm vault ID
        media_id: Media ID from the game page
        dest_dir: Directory to save the ROM
        filename: Optional filename override

    Returns:
        Path to the downloaded file, or None on failure.
    """
    if not media_id:
        log.error(f"No media_id for game {game_id}")
        return None

    try:
        resp = _session.get(
            f"{BASE}/vault/{game_id}",
            timeout=15,
        )
        # Extract system for extension
        sys_m = re.search(r'for the\s+([^"<]+)', resp.text)
        ext = ".nes"
        if sys_m:
            sys_name = sys_m.group(1).strip().lower()
            for vimm_key, ext_val in SYSTEM_EXTENSIONS.items():
                if vimm_key.lower() in sys_name:
                    ext = ext_val
                    break

        # GET from download server (form changes method to GET on submit)
        dl_resp = _session.get(
            DL_BASE,
            params={"mediaId": str(media_id)},
            timeout=120,
            allow_redirects=True,
        )
        dl_resp.raise_for_status()

        # Check content type — should be a zip or binary
        cd = dl_resp.headers.get("Content-Disposition", "")
        if not filename:
            fname_m = re.search(r'filename="([^"]+)"', cd)
            if fname_m:
                filename = fname_m.group(1)
            else:
                # Build filename from game page title
                info = get_game_info(game_id)
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


def download_cover(game_id, dest_dir):
    """Download box art for a game.

    Returns path to the saved image or None.
    """
    try:
        resp = _session.get(
            f"{IMAGE_BASE}?type=box&id={game_id}",
            timeout=15,
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
