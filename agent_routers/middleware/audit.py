from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agent_routers.adapters.audit_repo import AuditRepository
from agent_routers.services.signer import HmacSigner

logger = logging.getLogger(__name__)

audit_task_set: Set[asyncio.Task] = set()


async def _safe_write_audit(repo: AuditRepository, event: dict) -> None:
    try:
        await repo.insert(event)
    except Exception:
        logger.exception("audit_write_failed", extra={"request_id": event.get("request_id")})


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, repo: AuditRepository, signer: HmacSigner):
        super().__init__(app)
        self._repo = repo
        self._signer = signer

    async def dispatch(self, request: Request, call_next: Callable[..., Awaitable[Response]]):
        request_id = getattr(request.state, "request_id", "")
        start_ms = time.time()
        auth = getattr(request.state, "auth", None)
        user_subject = getattr(auth, "sub", "") if auth else ""

        response = await call_next(request)

        latency_ms = int((time.time() - start_ms) * 1000)
        timestamp = datetime.utcnow().isoformat()

        agent_id = request.path_params.get("agent_id", "")

        canonical = self._signer.canonical(
            request_id=request_id,
            timestamp_iso=timestamp,
            user_subject=user_subject,
            agent_id=agent_id,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        signature = self._signer.sign(canonical)

        event = {
            "request_id": request_id,
            "timestamp": timestamp,
            "user_subject": user_subject,
            "agent_id": agent_id,
            "instance_id": "",
            "method": request.method,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "request_headers_digest": "",
            "response_headers_digest": "",
            "signature": signature,
        }

        task = asyncio.create_task(_safe_write_audit(self._repo, event))
        audit_task_set.add(task)
        task.add_done_callback(audit_task_set.discard)

        return response
