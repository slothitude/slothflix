"""Async poster fetching + downscaling service using Pillow + httpx."""

import hashlib
import io
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slothflix.models.models import Poster
from slothflix.services.searxng import SearXNGClient, clean_title

logger = logging.getLogger(__name__)

# Max dimensions for downscaled poster images
MAX_WIDTH = 300
MAX_HEIGHT = 450
JPEG_QUALITY = 75

# Paths to default poster fallback images (checked in order)
_DEFAULT_POSTER_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web", "static", "poster_default.png"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sloth_logo.png"),
]


def _downscale_poster(
    blob: bytes,
    max_w: int = MAX_WIDTH,
    max_h: int = MAX_HEIGHT,
    quality: int = JPEG_QUALITY,
) -> bytes:
    """Downscale poster image to fit within max_w x max_h.

    Converts to RGB JPEG. Returns original blob if Pillow is unavailable
    or the image cannot be processed.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(blob))
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return blob


def _content_hash(blob: bytes) -> str:
    """Compute SHA-256 hex digest for ETag / 304 support."""
    return hashlib.sha256(blob).hexdigest()


class PosterService:
    """Async poster fetching, downscaling, and caching service."""

    def __init__(self, searxng: SearXNGClient | None = None):
        self.searxng = searxng or SearXNGClient()

    async def get_poster(
        self,
        session: AsyncSession,
        title: str,
    ) -> tuple[bytes, str] | None:
        """Get a poster image for a title.

        Returns (image_bytes, content_hash) or None if nothing found.

        Flow:
        1. Check DB cache for existing poster.
        2. Clean the title, search SearXNG for image URLs.
        3. Download + downscale the first viable result.
        4. Cache result in DB with content_hash.
        """
        # 1. Check DB cache
        cached = await self._load_cached(session, title)
        if cached is not None:
            return cached

        # 2. Search SearXNG for poster images
        clean = clean_title(title)
        urls = await self.searxng.search_poster_urls(clean)

        # 3. Download + downscale
        for img_url in urls:
            blob = await self.searxng.download_image(img_url, min_bytes=1000)
            if blob is None:
                continue
            downscaled = _downscale_poster(blob)
            content_hash = _content_hash(downscaled)
            await self._save_to_cache(session, title, downscaled, content_hash)
            return (downscaled, content_hash)

        logger.debug("No poster found for %r (clean: %r)", title, clean)
        return None

    async def get_poster_or_default(
        self,
        session: AsyncSession,
        title: str,
    ) -> tuple[bytes, str]:
        """Get a poster image, falling back to the default sloth logo."""
        result = await self.get_poster(session, title)
        if result is not None:
            return result

        # Return default poster image
        default_blob = self._load_default_poster()
        if default_blob is not None:
            downscaled = _downscale_poster(default_blob)
            return (downscaled, _content_hash(downscaled))

        # Last resort: 1x1 transparent pixel
        placeholder = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x00])
        return (placeholder, "")

    async def check_etag(
        self,
        session: AsyncSession,
        title: str,
        etag: str,
    ) -> bool:
        """Check if the given ETag matches the cached poster's content_hash.

        Returns True if the content has not changed (caller can send 304).
        """
        result = await session.execute(
            select(Poster.content_hash).where(Poster.title == title)
        )
        row = result.scalar_one_or_none()
        return row is not None and row == etag

    # --- Private helpers ---

    async def _load_cached(
        self, session: AsyncSession, title: str
    ) -> tuple[bytes, str] | None:
        """Load a cached poster from the DB."""
        result = await session.execute(
            select(Poster.image_blob, Poster.content_hash).where(
                Poster.title == title
            )
        )
        row = result.first()
        if row is not None and row[0] is not None:
            return (bytes(row[0]), row[1] or "")
        return None

    async def _save_to_cache(
        self,
        session: AsyncSession,
        title: str,
        blob: bytes,
        content_hash: str,
    ) -> None:
        """Save a poster to the DB cache (upsert)."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        result = await session.execute(
            select(Poster).where(Poster.title == title)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.image_blob = blob
            existing.content_hash = content_hash
            existing.updated_at = now
        else:
            session.add(
                Poster(
                    title=title,
                    image_blob=blob,
                    content_hash=content_hash,
                    updated_at=now,
                )
            )
        await session.commit()

    def _load_default_poster(self) -> bytes | None:
        """Try to load the default poster image from disk."""
        for candidate in _DEFAULT_POSTER_CANDIDATES:
            norm = os.path.normpath(candidate)
            if os.path.isfile(norm):
                try:
                    with open(norm, "rb") as f:
                        return f.read()
                except OSError:
                    continue
        return None
