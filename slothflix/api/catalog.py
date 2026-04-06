"""Catalog API routes — movies, TV, trailers, posters, blurbs."""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from slothflix.models.database import async_session, get_db
from slothflix.models.models import CatalogEntry, Poster, Blurb
from slothflix.services.searxng import clean_title

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])

# Background refresh state
_refresh_locks = {"movies": asyncio.Lock(), "tv": asyncio.Lock(), "games": asyncio.Lock()}


async def _background_refresh(category: str, fetch_fn, cache_key: str):
    """Refresh catalog in background."""
    if _refresh_locks[category].locked():
        return
    async with _refresh_locks[category]:
        try:
            async with httpx.AsyncClient() as client:
                results = await fetch_fn(client)
            await _save_catalog(cache_key, results)
            logger.info(f"Refreshed {category} catalog: {len(results)} items")
        except Exception as e:
            logger.error(f"Failed to refresh {category} catalog: {e}")


async def _save_catalog(category: str, results: list[dict]):
    """Save catalog entries to DB."""
    now = datetime.now(timezone.utc).isoformat()
    async with async_session() as session:
        await session.execute(
            delete(CatalogEntry).where(CatalogEntry.category == category)
        )
        for r in results:
            entry = CatalogEntry(
                title=r["title"],
                info_hash=r.get("info_hash", ""),
                seeders=r.get("seeders", 0),
                leechers=r.get("leechers", 0),
                size=r.get("size", ""),
                magnet_uri=r.get("magnet", ""),
                uploader=r.get("source", ""),
                category=category,
                updated_at=now,
            )
            session.add(entry)
        await session.commit()


async def _load_catalog(category: str) -> list[dict]:
    """Load catalog entries from DB."""
    async with async_session() as session:
        result = await session.execute(
            select(CatalogEntry).where(CatalogEntry.category == category)
        )
        entries = result.scalars().all()
        return [
            {
                "title": e.title,
                "magnet": e.magnet_uri,
                "seeders": e.seeders,
                "leechers": e.leechers,
                "size": e.size,
                "info_hash": e.info_hash,
                "source": e.uploader,
            }
            for e in entries
        ]


@router.get("/catalog/movies")
async def catalog_movies(request: Request):
    """Top 100 movies (cached, background refresh)."""
    cached = await _load_catalog("movies")
    if cached:
        from slothflix.services.search_provider import fetch_top_movies

        asyncio.create_task(_background_refresh("movies", fetch_top_movies, "movies"))
        return cached

    try:
        from slothflix.services.search_provider import fetch_top_movies

        async with httpx.AsyncClient() as client:
            results = await fetch_top_movies(client)
        await _save_catalog("movies", results)
        return results
    except Exception as e:
        return {"error": str(e)}


@router.get("/catalog/tv")
async def catalog_tv(request: Request):
    """Top 100 TV shows (cached, background refresh)."""
    cached = await _load_catalog("tv")
    if cached:
        from slothflix.services.search_provider import fetch_top_tv

        asyncio.create_task(_background_refresh("tv", fetch_top_tv, "tv"))
        return cached

    try:
        from slothflix.services.search_provider import fetch_top_tv

        async with httpx.AsyncClient() as client:
            results = await fetch_top_tv(client)
        await _save_catalog("tv", results)
        return results
    except Exception as e:
        return {"error": str(e)}


@router.get("/catalog/games")
async def catalog_games(request: Request):
    """Top 100 game torrents."""
    cached = await _load_catalog("games")
    if cached:
        from slothflix.services.search_provider import fetch_top_games

        asyncio.create_task(_background_refresh("games", fetch_top_games, "games"))
        return cached

    try:
        from slothflix.services.search_provider import fetch_top_games

        async with httpx.AsyncClient() as client:
            results = await fetch_top_games(client)
        await _save_catalog("games", results)
        return results
    except Exception as e:
        return {"error": str(e)}


# --- Posters ---

def _downscale_poster(blob: bytes, max_w: int = 300, max_h: int = 450, quality: int = 80) -> bytes:
    """Downscale poster image."""
    import io
    img = Image.open(io.BytesIO(blob))
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


@router.get("/poster/{title:path}")
async def poster(title: str, request: Request):
    """Proxy and cache poster image."""
    # Check cache
    async with async_session() as session:
        result = await session.execute(
            select(Poster).where(Poster.title == title)
        )
        cached = result.scalar_one_or_none()

        if cached:
            # Check ETag
            if cached.content_hash:
                etag = request.headers.get("if-none-match")
                if etag == cached.content_hash:
                    return Response(status_code=304)
            return Response(
                content=bytes(cached.image_blob),
                media_type="image/jpeg",
                headers={"ETag": cached.content_hash or "", "Cache-Control": "public, max-age=86400"},
            )

    # Fetch from SearXNG
    from slothflix.config import settings

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.searxng_host}/search",
                params={"q": f"{title} movie poster", "format": "json", "categories": "images"},
                timeout=8,
            )
            data = resp.json()
            img_url = None
            for r in data.get("results", []):
                img_url = r.get("img_src") or r.get("url")
                if img_url:
                    break

            if not img_url:
                return Response(
                    content=open("static/poster_default.webp", "rb").read(),
                    media_type="image/webp",
                )

            img_resp = await client.get(img_url, timeout=10, follow_redirects=True)
            if img_resp.status_code != 200:
                raise Exception(f"Image download failed: {img_resp.status_code}")

            blob = _downscale_poster(img_resp.content)
    except Exception as e:
        logger.error(f"Poster fetch failed for {title}: {e}")
        try:
            return Response(
                content=open("static/poster_default.webp", "rb").read(),
                media_type="image/webp",
            )
        except FileNotFoundError:
            return Response(status_code=404)

    # Cache
    content_hash = hashlib.sha256(blob).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    async with async_session() as session:
        poster_obj = Poster(
            title=title,
            image_blob=blob,
            content_hash=content_hash,
            updated_at=now,
        )
        session.add(poster_obj)
        await session.commit()

    return Response(
        content=blob,
        media_type="image/jpeg",
        headers={"ETag": content_hash, "Cache-Control": "public, max-age=86400"},
    )


# --- Blurbs ---

@router.get("/blurb/{title:path}")
async def blurb(title: str):
    """Get movie/show description."""
    ct = clean_title(title)

    # Check cache
    async with async_session() as session:
        result = await session.execute(
            select(Blurb).where(Blurb.title == ct)
        )
        cached = result.scalar_one_or_none()
        if cached and cached.text:
            return {"blurb": cached.text}

    # Fetch from SearXNG
    from slothflix.config import settings

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.searxng_host}/search",
                params={"q": ct + " wikipedia", "format": "json", "categories": "general"},
                timeout=8,
            )
            data = resp.json()
            for r in data.get("results", []):
                url = r.get("url", "")
                if "wikipedia.org" in url:
                    content = r.get("content", "").strip()
                    if content:
                        # Cache
                        now = datetime.now(timezone.utc).isoformat()
                        async with async_session() as session:
                            blurb_obj = Blurb(
                                title=ct,
                                text=content,
                                updated_at=now,
                            )
                            session.add(blurb_obj)
                            await session.commit()
                        return {"blurb": content}
    except Exception as e:
        logger.error(f"Blurb fetch failed for {ct}: {e}")

    return {"blurb": ""}


# --- Trailers ---

@router.get("/trailers")
async def trailers():
    """Return cached trailer video IDs."""
    from slothflix.services.trailer import load_trailers

    return await load_trailers()
