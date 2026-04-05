"""SlothFlix REST API."""

import os
import threading
import logging

from flask import Blueprint, jsonify, request, Response

import search
import cache
import torrent

log = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")

# Background refresh state
_refresh_lock = threading.Lock()
_catalog_refreshing = {"movies": False, "tv": False}


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
                        blob = img_resp.content
                        cache.save_poster(title, blob, 0, 0)
                        return Response(blob, mimetype="image/jpeg")
                except Exception:
                    continue
    except Exception:
        pass

    # Return default poster image (sloth logo)
    for candidate in [
        os.path.join(os.path.dirname(__file__), "static", "poster_default.png"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "sloth_logo.png"),
    ]:
        if os.path.exists(candidate):
            with open(candidate, "rb") as f:
                return Response(f.read(), mimetype="image/png")
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
