import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from slothflix.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("SlothFlix starting up")

    # Initialize database
    from slothflix.models.database import engine
    from slothflix.models.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start Telegram bot if configured (non-blocking, errors don't crash app)
    bot_task = None
    if settings.telegram_bot_token:
        import asyncio

        from slothflix.bot.bot import run_bot

        async def _start_bot():
            try:
                await run_bot()
            except Exception as e:
                logger.warning(f"Telegram bot failed: {e}")

        bot_task = asyncio.create_task(_start_bot())
        logger.info("Telegram bot task created")

    # Schedule trailer refresh
    try:
        from slothflix.services.trailer import refresh_trailers_on_startup

        await refresh_trailers_on_startup()
    except Exception as e:
        logger.warning(f"Trailer refresh failed: {e}")

    yield

    # Shutdown
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass

    from slothflix.models.database import engine

    await engine.dispose()
    logger.info("SlothFlix shut down")


app = FastAPI(title="SlothFlix", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Auth middleware
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Skip auth for these paths
    skip_paths = {"/login", "/api/auth/token", "/docs", "/openapi.json", "/redoc"}
    if path in skip_paths or path.startswith("/static/"):
        return await call_next(request)

    # Handle ?token= auto-auth
    token_param = request.query_params.get("token")
    if token_param:
        from slothflix.models.database import async_session
        from slothflix.services.token import TokenService

        async with async_session() as session:
            token_data = await TokenService.validate(session, token_param)
            if token_data:
                response = await call_next(request)
                response.set_cookie(
                    "slothflix_token",
                    token_param,
                    max_age=settings.token_expiry_days * 86400,
                    httponly=False,
                    path="/",
                )
                return response

    # Check auth
    authed = False

    # Cookie token
    cookie_token = request.cookies.get("slothflix_token")
    if cookie_token:
        from slothflix.models.database import async_session
        from slothflix.services.token import TokenService

        async with async_session() as session:
            token_data = await TokenService.validate(session, cookie_token)
            if token_data:
                authed = True

    # HTTP Basic Auth
    if not authed and settings.auth_user and settings.auth_pass:
        import base64

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode()
                user, password = decoded.split(":", 1)
                if user == settings.auth_user and password == settings.auth_pass:
                    authed = True
            except Exception:
                pass

    if not authed:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=401, content={"detail": "Not authenticated"}
            )
        return RedirectResponse(url="/login")

    return await call_next(request)


# Register API routers
from slothflix.api.auth import router as auth_router
from slothflix.api.catalog import router as catalog_router
from slothflix.api.games import router as games_router
from slothflix.api.ip import router as ip_router
from slothflix.api.search import router as search_router
from slothflix.api.stream import router as stream_router
from slothflix.api.vimm import router as vimm_router

app.include_router(auth_router, prefix="/api")
app.include_router(catalog_router, prefix="/api")
app.include_router(games_router, prefix="/api")
app.include_router(ip_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(stream_router, prefix="/api")
app.include_router(vimm_router, prefix="/api")

# Streaming routes (no /api prefix)
from slothflix.streaming.file_server import router as stream_router_fs

app.include_router(stream_router_fs)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index(request: Request):
    """Serve main SPA with injected auth header."""
    from fastapi.responses import FileResponse

    # Inject Basic Auth header into the HTML so the JS authFetch can use it
    auth_header = ""
    if settings.auth_user and settings.auth_pass:
        import base64
        creds = f"{settings.auth_user}:{settings.auth_pass}"
        auth_header = f"Basic {base64.b64encode(creds.encode()).decode()}"

    with open("frontend/index.html", "r") as f:
        html = f.read()

    if auth_header:
        html = html.replace(
            '<html lang="en">',
            f'<html lang="en" data-auth-header="{auth_header}">',
        )

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@app.get("/login")
async def login_page():
    """Serve login page."""
    from fastapi.responses import FileResponse

    return FileResponse("frontend/login.html")
