from __future__ import annotations

import logging
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_routers.adapters.jwks import verify_token
from agent_routers.api.dependencies import AuthContext

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/readiness", "/docs", "/openapi.json"}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "auth_invalid", "message": "Missing Bearer token", "request_id": getattr(request.state, "request_id", None)}},
            )

        token = auth_header[7:]
        try:
            claims = verify_token(token)
        except jwt.InvalidTokenError as e:
            logger.warning("jwt_verify_failed", extra={"reason": str(e)})
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "auth_invalid", "message": "Invalid token", "request_id": getattr(request.state, "request_id", None)}},
            )

        sub = claims.get("sub")
        role = claims.get("role")
        request.state.auth = AuthContext(sub=sub, role=role)
        return await call_next(request)
