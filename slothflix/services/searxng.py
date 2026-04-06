"""Async SearXNG client for blurb/poster lookups."""

import logging
import re

import httpx

from slothflix.config import settings

logger = logging.getLogger(__name__)


def clean_title(raw: str) -> str:
    """Strip S01E01, 720p, HDTV, x264, etc. to get a searchable title."""
    t = re.sub(r"[.\-_]", " ", raw)
    t = re.sub(r"\b(S\d{1,2}E\d{1,2}|S\d{1,2})\b.*", "", t, flags=re.IGNORECASE)
    t = re.sub(
        r"\b(720p|1080p|2160p|4K|HDTV|WEBRip|WEBDL|WEB-DL|BRRip|BDRip|BluRay"
        r"|x264|x265|HEVC|H264|H265|AAC|DD5?\.?1| Atmos|10bit|HDR)\b.*",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\[.*?\]|\(.*?\)", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # remove trailing year-like patterns
    t = re.sub(r"\s+\d{4}\s*$", "", t)
    return t


class SearXNGClient:
    """Async client for SearXNG search queries."""

    def __init__(self, base_url: str | None = None, timeout: float = 8.0):
        self.base_url = (base_url or settings.searxng_host).rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(
        self,
        query: str,
        categories: str = "general",
        format: str = "json",
    ) -> dict:
        """Run a SearXNG search and return the parsed JSON response."""
        client = await self._get_client()
        resp = await client.get(
            f"{self.base_url}/search",
            params={"q": query, "format": format, "categories": categories},
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch_blurb(self, clean_t: str) -> str | None:
        """Fetch a description via SearXNG Wikipedia search.

        Returns blurb text or None.
        """
        try:
            data = await self.search(
                clean_t + " wikipedia",
                categories="general",
            )
            for res in data.get("results", []):
                url = res.get("url", "")
                if "wikipedia.org" in url:
                    content = res.get("content", "").strip()
                    if content:
                        return content
        except Exception:
            logger.debug("SearXNG blurb lookup failed for %r", clean_t)
        return None

    async def search_poster_urls(self, clean_t: str) -> list[str]:
        """Search SearXNG for image URLs matching a movie poster query.

        Returns a list of candidate image URLs (may be empty).
        """
        try:
            data = await self.search(
                clean_t + " movie poster",
                categories="images",
            )
            urls: list[str] = []
            for res in data.get("results", []):
                img_url = res.get("thumbnail_src", "") or ""
                if img_url:
                    urls.append(img_url)
            return urls
        except Exception:
            logger.debug("SearXNG image search failed for %r", clean_t)
            return []

    async def download_image(self, url: str, min_bytes: int = 1000) -> bytes | None:
        """Download an image from a URL. Returns bytes or None."""
        try:
            client = await self._get_client()
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > min_bytes:
                return resp.content
        except Exception:
            logger.debug("Image download failed for %r", url)
        return None
