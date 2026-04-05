"""Video file streaming with HTTP Range support."""

import os
import subprocess

from flask import Blueprint, Response, request

stream_bp = Blueprint("stream", __name__)

CHUNK_SIZE = 256 * 1024  # 256KB chunks

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


@stream_bp.route("/stream/<session_id>")
def stream_file(session_id):
    """Stream the current torrent file with Range request support."""
    import torrent

    status = torrent.get_stream_status()
    if not status.get("active"):
        return "No active stream", 404

    file_path = status.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return f"File not found: {file_path}", 404

    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    mime_type = MIME_TYPES.get(ext, "video/mp4")

    range_header = request.headers.get("Range", None)

    if range_header:
        range_spec = range_header.replace("bytes=", "")
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def generate():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return Response(
            generate(),
            status=206,
            mimetype=mime_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": length,
                "Accept-Ranges": "bytes",
            },
        )

    # Full file stream (no range)
    def generate():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    return Response(
        generate(),
        status=200,
        mimetype=mime_type,
        headers={
            "Content-Length": file_size,
            "Accept-Ranges": "bytes",
        },
    )


@stream_bp.route("/play/<session_id>")
def play_file(session_id):
    """Serve video for browser playback. MP4 served directly, other formats remuxed via ffmpeg."""
    import torrent

    status = torrent.get_stream_status()
    if not status.get("active"):
        return "No active stream", 404

    file_path = status.get("file_path")
    if not file_path:
        return "File not found", 404

    # Retry loop — file may take time to appear on disk after buffer target
    import time
    import logging
    import glob as globmod
    _log = logging.getLogger(__name__)
    _log.info("play_file: waiting for %s", file_path)

    # The expected filename (without path) to search for
    expected_name = os.path.basename(file_path)

    for i in range(120):  # up to 60s
        # Check exact path
        if os.path.exists(file_path):
            _log.info("play_file: file found after %.1fs", i * 0.5)
            break
        # Check partial download suffixes
        for suffix in (".!qB", ".part"):
            part_path = file_path + suffix
            if os.path.exists(part_path):
                _log.info("play_file: found partial %s after %.1fs", suffix, i * 0.5)
                file_path = part_path
                break
        else:
            # Fallback: search download dir for any file matching the name
            dl_dir = os.getenv("DOWNLOAD_DIR", "/downloads")
            if i % 4 == 0 and expected_name:  # every 2s
                base_name = os.path.splitext(expected_name)[0]
                matches = globmod.glob(os.path.join(dl_dir, "**", base_name + "*"), recursive=True)
                if matches:
                    _log.info("play_file: found via glob: %s", matches[0])
                    file_path = matches[0]
                    break
            time.sleep(0.5)
            continue
        break  # found a partial file
    else:
        dl_dir = os.getenv("DOWNLOAD_DIR", "/downloads")
        # Last-resort glob search
        base_name = os.path.splitext(expected_name)[0] if expected_name else ""
        if base_name:
            matches = globmod.glob(os.path.join(dl_dir, "**", base_name + "*"), recursive=True)
            if matches:
                _log.info("play_file: last-resort glob found: %s", matches[0])
                file_path = matches[0]
            else:
                _log.error("play_file: %s not found after 60s. Contents of %s: %s",
                            file_path, dl_dir, os.listdir(dl_dir) if os.path.isdir(dl_dir) else "dir missing")
                return f"File not found: {file_path}", 404
        else:
            return f"File not found: {file_path}", 404

    ext = os.path.splitext(file_path)[1].lower()

    # MP4/M4V: serve directly with Range support (browser-native)
    if ext in (".mp4", ".m4v"):
        file_size = os.path.getsize(file_path)
        range_header = request.headers.get("Range", None)

        if range_header:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            def generate_range():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return Response(
                generate_range(),
                status=206,
                mimetype="video/mp4",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": length,
                    "Accept-Ranges": "bytes",
                },
            )

        def generate_full():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

        return Response(
            generate_full(),
            status=200,
            mimetype="video/mp4",
            headers={"Content-Length": file_size, "Accept-Ranges": "bytes"},
        )

    # MKV/other: remux to fragmented MP4 via ffmpeg (no re-encoding)
    cmd = [
        "ffmpeg",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        "-i", file_path,
        "-c", "copy",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov",
        "-loglevel", "error",
        "pipe:1",
    ]

    import logging
    _log = logging.getLogger(__name__)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def generate():
        try:
            while True:
                chunk = proc.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            stderr_output = proc.stderr.read().decode(errors="replace").strip()
            if stderr_output:
                _log.warning("ffmpeg stderr: %s", stderr_output)
            proc.terminate()
            proc.wait()

    return Response(
        generate(),
        status=200,
        mimetype="video/mp4",
        headers={"Transfer-Encoding": "chunked"},
    )
