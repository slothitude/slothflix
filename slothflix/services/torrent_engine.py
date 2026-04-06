"""Thread-safe async torrent engine using libtorrent + Transmission RPC."""

import asyncio
import logging
import os
import shutil
import time

import libtorrent as lt

from slothflix.config import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024  # 256KB
MIME_TYPES = {
    ".mkv": "video/x-matroska",
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".m4v": "video/mp4",
}

MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".wmv", ".flv", ".m4v"}


class TorrentEngine:
    """Async-safe torrent engine with serialization via asyncio.Lock."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._session: lt.session | None = None
        self._handle: lt.torrent_handle | None = None
        self._current_magnet: str | None = None
        self._selected_file_path: str | None = None

    def _get_session(self) -> lt.session:
        if self._session is None:
            lt_settings = {
                "listen_interfaces": "0.0.0.0:6881",
                "enable_dht": True,
                "enable_lsd": True,
                "active_downloads": 1,
                "active_seeds": 1,
                "active_limit": 2,
                "connections_limit": 50,
            }
            self._session = lt.session(lt_settings)
            self._session.add_dht_router("router.bittorrent.com", 6881)
            self._session.add_dht_router("router.utorrent.com", 6881)
            self._session.add_dht_router("dht.transmissionbt.com", 6881)
            self._session.start_dht()
        return self._session

    def _get_tr_client(self):
        import transmission_rpc

        return transmission_rpc.Client(
            host=settings.transmission_host,
            port=settings.transmission_port,
            username=settings.transmission_rpc_username,
            password=settings.transmission_rpc_password,
        )

    @staticmethod
    def _is_media_file(name: str) -> bool:
        return os.path.splitext(name)[1].lower() in MEDIA_EXTENSIONS

    @staticmethod
    def _file_list_from_handle(handle) -> list[dict]:
        torrent_info = handle.get_torrent_info()
        files = torrent_info.files()
        result = []
        for i in range(files.num_file()):
            name = files.file_name(i)
            size = files.file_size(i)
            if TorrentEngine._is_media_file(name) and size > 1_000_000:
                result.append({"id": i, "name": name, "size": size})
        return result

    async def get_torrent_files(self, magnet_uri: str, save_path: str = None) -> list[dict]:
        """Add magnet and return file list from metadata."""
        async with self._lock:
            save_path = save_path or settings.download_dir
            os.makedirs(save_path, exist_ok=True)

            # Reuse if same magnet
            if self._current_magnet == magnet_uri and self._handle:
                if self._handle.is_valid() and self._handle.has_metadata():
                    logger.info("Torrent already loaded, reading file list...")
                    return self._file_list_from_handle(self._handle)

            await self._stop_lt_torrent()
            session = self._get_session()

            # Add magnet in executor (blocking)
            loop = asyncio.get_event_loop()
            handle = await loop.run_in_executor(
                None, self._add_magnet_sync, session, magnet_uri, save_path
            )

            self._handle = handle
            self._current_magnet = magnet_uri

            # Also add to Transmission for management
            try:
                tr = self._get_tr_client()
                tr.add_torrent(magnet_uri, download_dir=save_path)
            except Exception:
                pass

            return self._file_list_from_handle(handle)

    def _add_magnet_sync(self, session, magnet_uri, save_path):
        params = lt.parse_magnet_uri(magnet_uri)
        params.save_path = save_path
        params.storage_mode = lt.storage_mode_t.storage_mode_sparse
        handle = session.add_torrent(params)
        logger.info("Magnet added, waiting for metadata...")
        for _ in range(60):
            if handle.is_valid() and handle.has_metadata():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Timeout waiting for torrent metadata (60s)")
        return handle

    async def start_torrent(
        self, magnet_uri: str, save_path: str = None, file_id: int = None
    ) -> str:
        """Start sequential download and wait for 10% buffer. Returns file path."""
        async with self._lock:
            save_path = save_path or settings.download_dir
            os.makedirs(save_path, exist_ok=True)

            self._selected_file_path = None

            # Cleanup old downloads
            await asyncio.to_thread(self._cleanup_downloads, save_path)

            # Load torrent if not already
            if (
                self._current_magnet != magnet_uri
                or not self._handle
                or not self._handle.is_valid()
                or not self._handle.has_metadata()
            ):
                await self._stop_lt_torrent()
                session = self._get_session()
                loop = asyncio.get_event_loop()
                handle = await loop.run_in_executor(
                    None, self._add_magnet_sync, session, magnet_uri, save_path
                )
                self._handle = handle
                self._current_magnet = magnet_uri

                # Also add to Transmission
                try:
                    tr = self._get_tr_client()
                    tr.add_torrent(magnet_uri, download_dir=save_path)
                except Exception:
                    pass

            handle = self._handle
            files = self._file_list_from_handle(handle)
            if not files:
                raise RuntimeError("No media files found in torrent")

            torrent_info = handle.get_torrent_info()

            # Select file
            if file_id is not None:
                selected = next((f for f in files if f["id"] == file_id), None)
                if selected is None:
                    raise RuntimeError(f"File ID {file_id} not found")
            else:
                selected = max(files, key=lambda f: f["size"])

            logger.info(
                f"Selected: {selected['name']} ({selected['size'] / (1024*1024):.1f} MB)"
            )

            # Set priorities
            priorities = [0] * torrent_info.files().num_file()
            priorities[selected["id"]] = 7
            handle.prioritize_files(priorities)
            handle.set_sequential_download(True)
            handle.resume()

            # Build file path
            file_path = os.path.join(
                save_path,
                torrent_info.name(),
                torrent_info.files().file_path(selected["id"]),
            )
            self._selected_file_path = file_path

            # Wait for 10% buffer (non-blocking poll)
            buffer_target = 10
            logger.info(f"Buffering to {buffer_target}%...")
            while True:
                if not handle.is_valid():
                    raise RuntimeError("Torrent handle became invalid")
                status = handle.status()
                progress = status.progress * 100
                seeds = status.num_seeds
                dl_speed = status.download_rate / 1024 / 1024
                logger.info(
                    f"Buffering... {progress:.1f}% | Seeds: {seeds} | Speed: {dl_speed:.1f} MB/s"
                )
                if progress >= buffer_target:
                    break
                await asyncio.sleep(2)

            logger.info(f"Buffering complete! ({progress:.1f}%)")
            return file_path

    def get_status(self) -> dict:
        """Return current download status."""
        if not self._handle or not self._handle.is_valid():
            return {"active": False}

        status = self._handle.status()
        return {
            "active": True,
            "progress": round(status.progress * 100, 1),
            "download_rate": round(status.download_rate / 1024 / 1024, 2),
            "seeds": status.num_seeds,
            "peers": status.num_peers,
            "state": str(status.state),
            "file_path": self._selected_file_path,
        }

    async def stop(self):
        """Stop torrent and clean up."""
        async with self._lock:
            await self._stop_lt_torrent()

            # Remove from Transmission
            try:
                tr = self._get_tr_client()
                torrents = tr.get_torrents()
                for t in torrents:
                    tr.remove_torrent(t, delete_data=True)
            except Exception:
                pass

            await asyncio.to_thread(self._cleanup_downloads)

            self._current_magnet = None
            self._selected_file_path = None

    async def _stop_lt_torrent(self):
        if self._handle and self._handle.is_valid():
            session = self._get_session()
            await asyncio.to_thread(session.remove_torrent, self._handle)
        self._handle = None

    def _cleanup_downloads(self, save_path: str = None):
        dl_dir = save_path or settings.download_dir
        if not os.path.isdir(dl_dir):
            return
        for entry in os.listdir(dl_dir):
            entry_path = os.path.join(dl_dir, entry)
            try:
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path)
                    logger.info(f"Deleted directory: {entry_path}")
                else:
                    os.remove(entry_path)
                    logger.info(f"Deleted file: {entry_path}")
            except Exception as e:
                logger.warning(f"Failed to delete {entry_path}: {e}")


# Singleton engine instance
engine = TorrentEngine()
