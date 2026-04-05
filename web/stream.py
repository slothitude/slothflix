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
    if not file_path or not os.path.exists(file_path):
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
        "-i", file_path,
        "-c", "copy",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov",
        "-loglevel", "error",
        "pipe:1",
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def generate():
        try:
            while True:
                chunk = proc.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    return Response(
        generate(),
        status=200,
        mimetype="video/mp4",
        headers={"Transfer-Encoding": "chunked"},
    )
