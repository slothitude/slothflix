"""IP check API route."""

import logging

import httpx
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ip"])


@router.get("/ip")
async def check_ip():
    """Return VPN IP address."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.ipify.org?format=json", timeout=10)
            return resp.json()
    except Exception as e:
        logger.error(f"IP check failed: {e}")
        return {"ip": "unknown", "error": str(e)}
