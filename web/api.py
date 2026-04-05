"""SlothFlix REST API."""

import os
import threading
import logging

from flask import Blueprint, jsonify, request, Response, send_file

import search
import cache
import torrent

log = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")

# Background refresh state
_refresh_lock = threading.Lock()
_catalog_refreshing = {"movies": False, "tv": False, "games": False}

# ROM scanning config
ROM_BASE_DIR = os.getenv("ROM_DIR", "/data/roms")

SYSTEM_CORE_MAP = {
    "nes": "nes", "snes": "snes", "gba": "gba", "gbc": "gbc",
    "n64": "n64", "psx": "psx", "segamd": "segaMD", "atari2600": "atari2600",
    "nds": "nds", "vb": "vb", "ms": "ms", "gg": "gg",
    "snes-msu1": "snes", "segacd": "segaCD", "32x": "sega32x",
    "atari7800": "atari7800", "lynx": "lynx", "pcfx": "pcfx",
    "ngp": "ngp", "ws": "ws", "coleco": "coleco",
    "pce": "pce", "fds": "fds", "saturn": "saturn",
}

ROM_EXTENSIONS = {
    ".nes", ".fds", ".unf", ".unif",
    ".smc", ".sfc", ".fig", ".bs",
    ".gba", ".gbc", ".gb", ".dmg",
    ".z64", ".n64", ".v64",
    ".bin", ".iso", ".img", ".cue", ".chd",
    ".smd", ".gen", ".md",
    ".a26", ".a78", ".lnx",
    ".nds",
    ".ws", ".wsc",
    ".ngp", ".ngc",
    ".pce", ".sgx",
    ".col",
    ".sat",
    ".32x",
}

_SYSTEM_DISPLAY = {
    "nes": "Nintendo (NES)", "snes": "Super Nintendo", "gba": "Game Boy Advance",
    "gbc": "Game Boy Color", "n64": "Nintendo 64", "psx": "PlayStation",
    "segamd": "Sega Genesis", "atari2600": "Atari 2600", "nds": "Nintendo DS",
    "snes-msu1": "SNES MSU-1", "segacd": "Sega CD", "32x": "Sega 32X",
    "atari7800": "Atari 7800", "lynx": "Atari Lynx", "pcfx": "PC-FX",
    "ngp": "Neo Geo Pocket", "ws": "WonderSwan", "coleco": "ColecoVision",
    "pce": "PC Engine", "fds": "Famicom Disk", "saturn": "Sega Saturn",
    "ms": "Master System", "gg": "Game Gear", "vb": "Virtual Boy",
}


def _background_refresh(category, fetch_fn, cache_key):
    """Refresh catalog in background thread."""
    with _refresh_lock:
        if _catalog_refreshing.get(category):
            return
        _catalog_refreshing[category] = True
    try:
        results = fetch_fn()
        cache.save_catalog(cache_key, results)
        log.info(f"Refreshed {category} catalog: {len(results)} items")
    except Exception as e:
        log.error(f"Failed to refresh {category} catalog: {e}")
    finally:
        _catalog_refreshing[category] = False


@api_bp.route("/catalog/movies")
def catalog_movies():
    """Top 100 movies (cached, background refresh)."""
    cached = cache.load_catalog("movies")
    if cached:
        threading.Thread(
            target=_background_refresh,
            args=("movies", search.fetch_top_movies, "movies"),
            daemon=True,
        ).start()
        return jsonify(cached)

    # No cache — fetch synchronously
    try:
        results = search.fetch_top_movies()
        cache.save_catalog("movies", results)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/catalog/tv")
def catalog_tv():
    """Top 100 TV shows (cached, background refresh)."""
    cached = cache.load_catalog("tv")
    if cached:
        threading.Thread(
            target=_background_refresh,
            args=("tv", search.fetch_top_tv, "tv"),
            daemon=True,
        ).start()
        return jsonify(cached)

    try:
        results = search.fetch_top_tv()
        cache.save_catalog("tv", results)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/search")
def search_torrents():
    """Search torrents via multiple providers."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' required"}), 400

    try:
        results = search.search(q)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/stream/start", methods=["POST"])
def stream_start():
    """Start sequential torrent download for streaming."""
    data = request.get_json(force=True)
    magnet = data.get("magnet")
    if not magnet:
        return jsonify({"error": "magnet required"}), 400

    file_id = data.get("file_id")
    download_dir = os.getenv("DOWNLOAD_DIR", "/downloads")

    # Run in background thread, return session id
    result = {"status": "starting"}

    def _start():
        try:
            path = torrent.start_torrent(
                magnet,
                save_path=download_dir,
                log_callback=lambda msg: log.info(msg),
                file_id=file_id,
            )
            result["status"] = "buffering"
            result["file_path"] = path
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

    thread = threading.Thread(target=_start, daemon=True)
    thread.start()
    thread.join(timeout=120)  # wait up to 2min for buffer

    if result.get("error"):
        return jsonify(result), 500

    # Generate a simple session id from the magnet hash
    session_id = magnet.split(":")[3][:12] if ":" in magnet else "default"
    result["session_id"] = session_id
    result["stream_url"] = f"/stream/{session_id}"
    return jsonify(result)


@api_bp.route("/stream/status")
def stream_status():
    """Poll current stream buffer/download progress."""
    return jsonify(torrent.get_stream_status())


@api_bp.route("/stream/stop", methods=["POST"])
def stream_stop():
    """Stop current stream."""
    torrent.stop_torrent()
    return jsonify({"status": "stopped"})


@api_bp.route("/torrent/files", methods=["POST"])
def torrent_files():
    """Get file list for a magnet URI (for episode picker)."""
    data = request.get_json(force=True)
    magnet = data.get("magnet")
    if not magnet:
        return jsonify({"error": "magnet required"}), 400

    download_dir = os.getenv("DOWNLOAD_DIR", "/downloads")
    try:
        files = torrent.get_torrent_files(magnet, save_path=download_dir)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _downscale_poster(blob, max_w=120, max_h=170, quality=60):
    """Downscale poster image to small thumbnail for cards."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(blob))
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return blob


@api_bp.route("/poster/<path:title>")
def poster(title):
    """Proxy poster image via SearXNG image search with fallback."""
    cached = cache.load_poster(title)
    if cached:
        blob, w, h = cached
        return Response(blob, mimetype="image/jpeg")

    import requests as req

    clean = cache.clean_title(title)

    # Try SearXNG image search
    try:
        searxng = os.getenv("SEARXNG_HOST", "http://127.0.0.1:8890")
        resp = req.get(
            f"{searxng}/search",
            params={"q": clean + " movie poster", "format": "json", "categories": "images"},
            timeout=8,
        )
        data = resp.json()
        for res in data.get("results", []):
            img_url = res.get("thumbnail_src", "") or ""
            if img_url:
                try:
                    img_resp = req.get(img_url, timeout=8)
                    if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                        blob = _downscale_poster(img_resp.content)
                        cache.save_poster(title, blob, 0, 0)
                        return Response(blob, mimetype="image/jpeg")
                except Exception:
                    continue
    except Exception:
        pass

    # Return default poster image (sloth logo, downscaled)
    for candidate in [
        os.path.join(os.path.dirname(__file__), "static", "poster_default.png"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "sloth_logo.png"),
    ]:
        if os.path.exists(candidate):
            with open(candidate, "rb") as f:
                blob = _downscale_poster(f.read())
            return Response(blob, mimetype="image/jpeg")
    return "", 404


@api_bp.route("/blurb/<path:title>")
def blurb(title):
    """Get description for a title via SearXNG Wikipedia search."""
    clean = cache.clean_title(title)
    cached = cache.load_blurb(clean)
    if cached:
        return jsonify({"blurb": cached, "title": clean})

    fetched = cache.fetch_blurb(clean)
    if fetched:
        return jsonify({"blurb": fetched, "title": clean})

    return jsonify({"blurb": "", "title": clean})


@api_bp.route("/trailers")
def trailers():
    """Return cached YouTube trailer IDs for pre-roll playback."""
    cached = cache.load_trailers()
    return jsonify(cached)


@api_bp.route("/vlc/open", methods=["POST"])
def vlc_open():
    """Open a file path in the VLC container."""
    data = request.get_json(force=True)
    path = data.get("path", "")
    vlc_url = os.getenv("VLC_URL", "http://vlc:5800")
    return jsonify({"vlc_url": vlc_url, "path": path})


@api_bp.route("/ip")
def check_ip():
    """Check external IP (should show VPN IP)."""
    try:
        import requests as req
        resp = req.get("https://api.ipify.org?format=json", timeout=5)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"ip": "unknown", "error": str(e)})


@api_bp.route("/games")
def games():
    """Scan ROM directories and return available games grouped by system."""
    systems = {}
    rom_dir = ROM_BASE_DIR
    if not os.path.isdir(rom_dir):
        return jsonify({"systems": systems})

    for system_dir in sorted(os.listdir(rom_dir)):
        sys_path = os.path.join(rom_dir, system_dir)
        if not os.path.isdir(sys_path):
            continue
        core = SYSTEM_CORE_MAP.get(system_dir)
        if not core:
            continue
        roms = []
        for fname in sorted(os.listdir(sys_path)):
            _, ext = os.path.splitext(fname)
            if ext.lower() not in ROM_EXTENSIONS:
                continue
            fpath = os.path.join(sys_path, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = 0
            roms.append({
                "filename": fname,
                "size": size,
                "system": system_dir,
            })
        if roms:
            systems[system_dir] = {
                "core": core,
                "display_name": _SYSTEM_DISPLAY.get(system_dir, system_dir),
                "count": len(roms),
                "roms": roms,
            }

    return jsonify({"systems": systems})


@api_bp.route("/games/rom/<system>/<path:filename>")
def serve_rom(system, filename):
    """Serve a ROM file with path traversal protection."""
    # Validate system name
    if "/" in system or "\\" in system or ".." in system:
        return jsonify({"error": "Invalid system"}), 400

    full_path = os.path.normpath(os.path.join(ROM_BASE_DIR, system, filename))
    if not full_path.startswith(os.path.normpath(ROM_BASE_DIR)):
        return jsonify({"error": "Invalid path"}), 400

    _, ext = os.path.splitext(filename)
    if ext.lower() not in ROM_EXTENSIONS:
        return jsonify({"error": "Invalid file type"}), 400

    if not os.path.isfile(full_path):
        return jsonify({"error": "File not found"}), 404

    return send_file(full_path)


@api_bp.route("/catalog/games")
def catalog_games():
    """Top 100 game torrents (cached, background refresh)."""
    cached = cache.load_catalog("games")
    if cached:
        threading.Thread(
            target=_background_refresh,
            args=("games", search.fetch_top_games, "games"),
            daemon=True,
        ).start()
        return jsonify(cached)

    try:
        results = search.fetch_top_games()
        cache.save_catalog("games", results)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
