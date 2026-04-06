"""YouTube trailer service for SlothFlix pre-roll entertainment."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete

from slothflix.models.database import async_session
from slothflix.models.models import Trailer

logger = logging.getLogger(__name__)


async def fetch_latest_trailers() -> list[dict]:
    """Search YouTube for latest official movie trailers, return top 5."""
    try:
        from yt_dlp import YoutubeDL

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }

        def _fetch():
            with YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(
                    "ytsearch5:official movie trailer 2026", download=False
                )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _fetch)
        entries = result.get("entries", [])[:5]

        trailers = []
        for e in entries:
            thumbnails = e.get("thumbnails", [])
            thumb_url = thumbnails[-1].get("url", "") if thumbnails else ""
            trailers.append({
                "video_id": e["id"],
                "title": e.get("title", ""),
                "thumbnail_url": thumb_url,
            })
        return trailers
    except Exception as e:
        logger.error(f"Failed to fetch trailers: {e}")
        return []


async def save_trailers(trailers: list[dict]):
    """Save trailers to database, replacing existing ones."""
    now = datetime.now(timezone.utc).isoformat()
    async with async_session() as session:
        await session.execute(delete(Trailer))
        for i, t in enumerate(trailers):
            trailer = Trailer(
                video_id=t["video_id"],
                position=i,
                updated_at=now,
            )
            session.add(trailer)
        await session.commit()


async def load_trailers() -> list[dict]:
    """Load cached trailers from database."""
    async with async_session() as session:
        result = await session.execute(
            select(Trailer).order_by(Trailer.position)
        )
        trailers = result.scalars().all()
        return [
            {
                "video_id": t.video_id,
                "position": t.position,
                "updated_at": t.updated_at,
            }
            for t in trailers
        ]


async def refresh_trailers_if_stale():
    """Fetch trailers only if cache is older than 24 hours."""
    trailers = await load_trailers()
    if trailers:
        updated_at = trailers[0].get("updated_at", "")
        if updated_at:
            try:
                last = datetime.fromisoformat(updated_at)
                now = datetime.now(timezone.utc)
                if (now - last).total_seconds() < 86400:
                    logger.info("Trailers cache fresh, skipping refresh")
                    return
            except (ValueError, TypeError):
                pass

    new_trailers = await fetch_latest_trailers()
    if new_trailers:
        await save_trailers(new_trailers)
        logger.info(f"Cached {len(new_trailers)} trailers")
    else:
        logger.warning("No trailers fetched")


async def refresh_trailers_on_startup():
    """Refresh trailers on startup."""
    await refresh_trailers_if_stale()
