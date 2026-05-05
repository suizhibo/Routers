from __future__ import annotations

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_routers.adapters.redis_quota import get_quota, QuotaExceeded

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/readiness"}


class QuotaMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth = getattr(request.state, "auth", None)
        if auth is None:
            return await call_next(request)

        quota = get_quota()
        try:
            await quota.check(auth.sub)
        except QuotaExceeded:
            logger.warning("quota_exceeded", extra={"subject": auth.sub})
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "quota_exceeded", "message": "Rate limit exceeded", "request_id": getattr(request.state, "request_id", None)}},
            )
        except Exception as e:
            logger.error("quota_check_failed", extra={"error": str(e)})
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "dependency_unavailable", "message": "Quota service unavailable", "request_id": getattr(request.state, "request_id", None)}},
            )

        return await call_next(request)
