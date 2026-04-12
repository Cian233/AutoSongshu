"""Simple token-based API authentication middleware.

The auth token is read from the ``AUTOSONGSHU_API_TOKEN`` environment variable.
When set, all ``/api/*`` endpoints (except ``/api/health``) require an
``Authorization: Bearer <token>`` header.  When the variable is absent or empty,
authentication is disabled — this preserves backward compatibility for local
development.
"""

from __future__ import annotations

import os
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _get_api_token() -> str | None:
    token = os.getenv("AUTOSONGSHU_API_TOKEN", "")
    return token.strip() or None


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Require a Bearer token for ``/api/*`` routes.

    Routes that are always accessible without authentication:

    * ``/api/health`` — health-check endpoint used by load balancers.
    * ``GET /`` and static asset routes — served by FastAPI's static mount.

    Everything under ``/api/`` (except health) must include::

        Authorization: Bearer <token>
    """

    _PUBLIC_PATHS = {"/api/health"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip non-API routes
        if not path.startswith("/api/"):
            return await call_next(request)

        # Always allow health checks
        if path in self._PUBLIC_PATHS:
            return await call_next(request)

        # If no token is configured, skip auth (backward compatible)
        token = _get_api_token()
        if token is None:
            return await call_next(request)

        # Validate Bearer token
        # Also accept token via query parameter (for EventSource compatibility)
        token_query = request.query_params.get("token", "")
        if token_query:
            provided = token_query.strip()
            if provided and provided == token:
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API token."},
            )

        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header."},
            )

        provided = authorization[len("Bearer "):].strip()
        if not provided or provided != token:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API token."},
            )

        return await call_next(request)


__all__ = ["TokenAuthMiddleware", "_get_api_token"]
