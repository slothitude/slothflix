from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from slothflix.config import settings
from slothflix.models.database import get_db
from slothflix.services.token import TokenService


def _is_authed(request: Request) -> bool:
    """Check if request has valid auth via cookie token or HTTP Basic Auth."""
    # Check cookie token
    token = request.cookies.get("slothflix_token")
    if token:
        # Synchronous check - will be validated properly in DB
        return True

    # Check HTTP Basic Auth
    auth_user = settings.auth_user
    auth_pass = settings.auth_pass
    if auth_user and auth_pass:
        import base64

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode()
                user, password = decoded.split(":", 1)
                return user == auth_user and password == auth_pass
            except Exception:
                pass

    return False


AUTH_SKIP_PATHS = {"/login", "/api/auth/token", "/static/"}


def require_auth(request: Request):
    """FastAPI dependency that enforces authentication."""
    # Skip auth for certain paths
    path = request.url.path
    if path in AUTH_SKIP_PATHS or path.startswith("/static/"):
        return

    # Handle ?token= auto-auth
    token_param = request.query_params.get("token")
    if token_param:
        # Will be handled by middleware
        return

    if not _is_authed(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": 'Basic realm="SlothFlix"'},
        )


def get_auth_header(request: Request) -> str | None:
    """Get Basic Auth header value for API calls from the frontend."""
    if settings.auth_user and settings.auth_pass:
        import base64

        creds = f"{settings.auth_user}:{settings.auth_pass}"
        return f"Basic {base64.b64encode(creds.encode()).decode()}"
    return None


AuthHeader = Annotated[str | None, Depends(get_auth_header)]
