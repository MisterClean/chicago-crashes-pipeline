"""API Key authentication middleware for securing backend endpoints."""

import os
import secrets
from typing import Callable

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Default public routes that don't require authentication
DEFAULT_PUBLIC_ROUTES = [
    "/health",
    "/",
    "/version",
    "/docs",
    "/redoc",
    "/openapi.json",
    # Dashboard read endpoints (public data)
    "/dashboard/stats",
    "/dashboard/trends",
    "/dashboard/crashes/geojson",
    # Places API (read-only geographic data)
    "/places/",
    # Static assets
    "/admin",
    "/documentation",
]

# Routes that always require authentication (even if path matches a public prefix)
PROTECTED_ROUTES = [
    "/sync/trigger",
    "/sync/test",
    "/jobs",
    "/spatial/layers",
    "/dashboard/location-report/export",
]


def get_api_key() -> str | None:
    """Get the API key from environment variable.

    Returns:
        The API key if set, None otherwise.
    """
    return os.getenv("API_KEY")


def get_public_routes() -> list[str]:
    """Get the list of public routes from environment or defaults.

    Returns:
        List of route prefixes that don't require authentication.
    """
    custom_routes = os.getenv("PUBLIC_ROUTES", "")
    if custom_routes:
        return [r.strip() for r in custom_routes.split(",") if r.strip()]
    return DEFAULT_PUBLIC_ROUTES


def is_public_route(path: str) -> bool:
    """Check if a path is a public route.

    Args:
        path: The request path to check.

    Returns:
        True if the route is public, False otherwise.
    """
    # First check if it's an explicitly protected route
    for protected in PROTECTED_ROUTES:
        if path.startswith(protected):
            return False

    # Then check if it matches any public route prefix
    public_routes = get_public_routes()
    for route in public_routes:
        if path == route or path.startswith(route + "/") or path.startswith(route):
            return True

    return False


def get_api_key_header() -> str:
    """Get the header name used for API key authentication.

    Returns:
        The header name (X-API-Key).
    """
    return "X-API-Key"


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware to validate API key for protected endpoints.

    This middleware checks for a valid API key in the X-API-Key header
    for all non-public routes. If no API_KEY environment variable is set,
    authentication is disabled (development mode).

    Usage:
        Set the API_KEY environment variable to enable authentication:

            export API_KEY="your-secure-api-key-here"

        Then include the key in requests:

            curl -H "X-API-Key: your-secure-api-key-here" http://localhost:8000/sync/trigger
    """

    async def dispatch(self, request: Request, call_next: Callable):
        """Process the request and validate API key if required.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            The response from the next handler, or a 401 error if unauthorized.
        """
        path = request.url.path
        method = request.method

        # Get the configured API key
        api_key = get_api_key()

        # If no API key is configured, skip authentication (development mode)
        if not api_key:
            if os.getenv("ENVIRONMENT") == "production":
                logger.warning(
                    "API_KEY not set in production - authentication disabled",
                    path=path
                )
            return await call_next(request)

        # Allow OPTIONS requests for CORS preflight
        if method == "OPTIONS":
            return await call_next(request)

        # Check if this is a public route
        if is_public_route(path):
            return await call_next(request)

        # Get the API key from the request header
        request_key = request.headers.get(get_api_key_header())

        # Validate the API key using constant-time comparison
        if not request_key or not secrets.compare_digest(request_key, api_key):
            logger.warning(
                "Unauthorized API access attempt",
                path=path,
                method=method,
                has_key=bool(request_key),
                client_ip=request.client.host if request.client else "unknown"
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Invalid or missing API key",
                    "error": "unauthorized",
                    "hint": "Include a valid API key in the X-API-Key header"
                },
                headers={"WWW-Authenticate": "ApiKey"}
            )

        # API key is valid, proceed with the request
        return await call_next(request)


def generate_api_key(length: int = 32) -> str:
    """Generate a secure random API key.

    Args:
        length: The length of the key in bytes (default 32 = 256 bits).

    Returns:
        A URL-safe base64-encoded random string.
    """
    return secrets.token_urlsafe(length)
