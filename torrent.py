"""Torrent engine using libtorrent (sequential streaming) + Transmission RPC (management)."""

import os
import time
import logging
import shutil
import libtorrent as lt
import transmission_rpc

log = logging.getLogger(__name__)

# Transmission RPC config (shared network namespace with transmission container)
TR_HOST = os.getenv("TRANSMISSION_HOST", "127.0.0.1")
TR_PORT = int(os.getenv("TRANSMISSION_PORT", "9191"))
TR_USER = os.getenv("TRANSMISSION_RPC_USERNAME", "admin")
TR_PASS = os.getenv("TRANSMISSION_RPC_PASSWORD", "adminadmin")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")

# libtorrent session (long-lived)
_lt_session = None
_current_torrent = None  # lt.torrent_handle
_current_magnet = None
_selected_file_path = None


def _get_lt_session():
    global _lt_session
    if _lt_session is None:
        settings = {
            "listen_interfaces": "0.0.0.0:6881",
            "enable_dht": True,
            "enable_lsd": True,
            "active_downloads": 1,
            "active_seeds": 1,
            "active_limit": 2,
            "connections_limit": 50,
        }
        _lt_session = lt.session(settings)
        _lt_session.add_dht_router("router.bittorrent.com", 6881)
        _lt_session.add_dht_router("router.utorrent.com", 6881)
        _lt_session.add_dht_router("dht.transmissionbt.com", 6881)
        _lt_session.start_dht()
    return _lt_session


def _get_tr_client():
    return transmission_rpc.Client(
        host=TR_HOST, port=TR_PORT, username=TR_USER, password=TR_PASS
    )


def _is_media_file(name):
    exts = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".wmv", ".flv", ".m4v"}
    return os.path.splitext(name)[1].lower() in exts


def get_torrent_files(magnet_uri, save_path=None, log_callback=None):
    """Add magnet via libtorrent, return file list from metadata.

    Returns list of dicts: [{"id": int, "name": str, "size": int}, ...]
    Only media files are returned.
    """
    global _current_torrent, _current_magnet

    def _log(msg):
        if log_callback:
            log_callback(msg)
        log.info(msg)

    save_path = save_path or DOWNLOAD_DIR
    os.makedirs(save_path, exist_ok=True)

    # Reuse existing torrent if same magnet
    if _current_magnet == magnet_uri and _current_torrent:
        if _current_torrent.is_valid() and _current_torrent.has_metadata():
            _log("Torrent already loaded, reading file list...")
            return _file_list_from_handle(_current_torrent)

    # Stop previous torrent
    _stop_lt_torrent()
    session = _get_lt_session()

    params = lt.parse_magnet_uri(magnet_uri)
    params.save_path = save_path
    handle = session.add_torrent(params)
    _log("Magnet added, waiting for metadata...")

    # Wait for metadata (up to 60s)
    for _ in range(60):
        if handle.is_valid() and handle.has_metadata():
            break
        time.sleep(1)
    else:
        raise RuntimeError("Timeout waiting for torrent metadata (60s)")

    _current_torrent = handle
    _current_magnet = magnet_uri

    # Also add to Transmission for management/visibility
    try:
        tr = _get_tr_client()
        tr.add_torrent(magnet_uri, download_dir=save_path)
    except Exception:
        pass  # Non-critical — Transmission is just for UI

    return _file_list_from_handle(handle)


def _file_list_from_handle(handle):
    """Extract file list from a libtorrent torrent handle."""
    torrent_info = handle.get_torrent_info()
    files = torrent_info.files()
    result = []
    for i in range(files.num_files()):
        name = files.file_name(i)
        size = files.file_size(i)
        if _is_media_file(name) and size > 1_000_000:  # > 1MB
            result.append({"id": i, "name": name, "size": size})
    return result


def start_torrent(magnet_uri, save_path=None, log_callback=None, file_id=None):
    """Start sequential download and wait for buffer.

    If file_id is provided, prioritizes that file. Otherwise picks the largest.
    Returns the full file path of the selected file.
    """
    global _current_torrent, _current_magnet, _selected_file_path

    def _log(msg):
        if log_callback:
            log_callback(msg)
        log.info(msg)

    save_path = save_path or DOWNLOAD_DIR
    os.makedirs(save_path, exist_ok=True)

    _selected_file_path = None

    # Wipe old downloads (get_torrent_files handles stopping previous torrent)
    _cleanup_downloads(save_path)

    # Ensure torrent is loaded and get file list
    files = get_torrent_files(magnet_uri, save_path, log_callback)
    if not files:
        raise RuntimeError("No media files found in torrent")

    handle = _current_torrent
    torrent_info = handle.get_torrent_info()

    # Select file
    if file_id is not None:
        selected = next((f for f in files if f["id"] == file_id), None)
        if selected is None:
            raise RuntimeError(f"File ID {file_id} not found in torrent.")
    else:
        selected = max(files, key=lambda f: f["size"])

    _log(f"Selected file: {selected['name']} ({selected['size'] / (1024*1024):.1f} MB)")

    # Set file priorities: selected = 7 (high), others = 0 (skip)
    priorities = [0] * torrent_info.files().num_files()
    priorities[selected["id"]] = 7
    handle.prioritize_files(priorities)

    # Enable sequential download
    handle.set_sequential_download(True)
    handle.resume()

    # Build file path — for multi-file torrents, files are saved under
    # save_path/torrent_name/, so we must include torrent_info.name().
    # For single-file torrents, file_path() returns just the filename
    # and the file is saved directly in save_path/torrent_name/.
    file_path = os.path.join(
        save_path, torrent_info.name(), torrent_info.files().file_path(selected["id"])
    )
    _selected_file_path = file_path

    # Wait for 5% buffer
    BUFFER_TARGET = 5
    _log(f"Buffering to {BUFFER_TARGET}%...")
    while True:
        if not handle.is_valid():
            raise RuntimeError("Torrent handle became invalid")
        status = handle.status()
        progress = status.progress * 100
        seeds = status.num_seeds
        dl_speed = status.download_rate / 1024 / 1024
        remaining = max(0, BUFFER_TARGET - progress)
        _log(f"Buffering... {progress:.1f}% ({remaining:.1f}% remaining) | Seeds: {seeds} | Speed: {dl_speed:.1f} MB/s")
        if progress >= BUFFER_TARGET:
            break
        time.sleep(2)

    _log(f"Buffering complete! ({progress:.1f}%)")
    return file_path


def get_stream_status():
    """Return current download progress info."""
    if not _current_torrent or not _current_torrent.is_valid():
        return {"active": False}

    handle = _current_torrent
    status = handle.status()
    return {
        "active": True,
        "progress": round(status.progress * 100, 1),
        "download_rate": round(status.download_rate / 1024 / 1024, 2),
        "seeds": status.num_seeds,
        "peers": status.num_peers,
        "state": str(status.state),
        "file_path": _selected_file_path,
    }


def stop_torrent():
    """Stop current torrent and clean up downloads."""
    global _current_torrent, _current_magnet, _selected_file_path
    _stop_lt_torrent()

    # Remove from Transmission (with data)
    try:
        tr = _get_tr_client()
        torrents = tr.get_torrents()
        for t in torrents:
            tr.remove_torrent(t, delete_data=True)
    except Exception:
        pass

    # Delete downloaded files
    _cleanup_downloads()

    _current_magnet = None
    _selected_file_path = None


def _stop_lt_torrent():
    global _current_torrent
    if _current_torrent and _current_torrent.is_valid():
        session = _get_lt_session()
        session.remove_torrent(_current_torrent)
    _current_torrent = None


def _cleanup_downloads(save_path=None):
    """Delete all files in the downloads directory to free space."""
    dl_dir = save_path or DOWNLOAD_DIR
    if not os.path.isdir(dl_dir):
        return
    for entry in os.listdir(dl_dir):
        entry_path = os.path.join(dl_dir, entry)
        try:
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
                log.info(f"Deleted directory: {entry_path}")
            else:
                os.remove(entry_path)
                log.info(f"Deleted file: {entry_path}")
        except Exception as e:
            log.warning(f"Failed to delete {entry_path}: {e}")


def list_torrents():
    """List active torrents in Transmission."""
    try:
        tr = _get_tr_client()
        torrents = tr.get_torrents()
        return [
            {
                "id": t.id,
                "name": t.name,
                "progress": round(t.progress, 1),
                "status": t.status,
                "rate_download": t.rateDownload,
            }
            for t in torrents
        ]
    except Exception:
        return []
