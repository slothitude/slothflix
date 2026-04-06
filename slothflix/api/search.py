"""Search API routes."""

import httpx
from fastapi import APIRouter, Query

from slothflix.services.search_provider import search

router = APIRouter(tags=["search"])


@router.get("/search")
async def search_torrents(q: str = Query(..., description="Search query")):
    """Search for torrents across multiple providers."""
    async with httpx.AsyncClient() as client:
        return await search(client, q)
