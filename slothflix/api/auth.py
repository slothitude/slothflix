"""Auth API routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from slothflix.models.database import get_db
from slothflix.services.token import TokenService

router = APIRouter(tags=["auth"])


@router.post("/auth/token")
async def auth_token(request: Request, db: AsyncSession = Depends(get_db)):
    """Validate token and set cookie."""
    body = await request.json()
    token_str = body.get("token", "").strip()
    if not token_str:
        return JSONResponse({"detail": "Token required"}, status_code=400)

    token = await TokenService.validate(db, token_str)
    if not token:
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    response = JSONResponse({"ok": True})
    response.set_cookie(
        "slothflix_token",
        token_str,
        max_age=86400 * 7,
        httponly=False,
        path="/",
    )
    return response
