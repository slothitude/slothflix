"""YouTube trailer fetcher for SlothFlix pre-roll entertainment."""

import logging
from datetime import datetime

import cache

log = logging.getLogger(__name__)


def fetch_latest_trailers():
    """Search YouTube for latest official movie trailers, return top 5."""
    try:
        from yt_dlp import YoutubeDL
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(
                "ytsearch5:official movie trailer 2026", download=False
            )
        entries = result.get("entries", [])[:5]
        trailers = []
        for e in entries:
            trailers.append({
                "youtube_id": e["id"],
                "title": e.get("title", ""),
                "thumbnail_url": e.get("thumbnails", [{}])[-1].get("url", "")
                if e.get("thumbnails") else "",
            })
        return trailers
    except Exception as e:
        log.error("Failed to fetch trailers: %s", e)
        return []


def refresh_trailers_if_stale():
    """Fetch trailers only if cache is older than 24 hours."""
    existing = cache.load_trailers()
    if existing:
        updated_at = existing[0].get("updated_at", "")
        if updated_at:
            try:
                last = datetime.fromisoformat(updated_at)
                if (datetime.utcnow() - last).total_seconds() < 86400:
                    log.info("Trailers cache fresh, skipping refresh")
                    return
            except (ValueError, TypeError):
                pass

    trailers = fetch_latest_trailers()
    if trailers:
        cache.save_trailers(trailers)
        log.info("Cached %d trailers", len(trailers))
    else:
        log.warning("No trailers fetched")
