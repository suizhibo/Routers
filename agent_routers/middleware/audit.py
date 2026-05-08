from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.audit_repo import AuditRepository
from agent_routers.config.settings import settings
from agent_routers.services.signer import HmacSigner

logger = logging.getLogger(__name__)

audit_task_set: Set[asyncio.Task] = set()

MAX_BODY_BYTES: int = settings.AUDIT_MAX_BODY_BYTES
TRUNCATION_MARKER = "…truncated"


def _truncate_body(body: bytes) -> str:
    if len(body) <= MAX_BODY_BYTES:
        return body.decode("utf-8", errors="replace")
    truncated = body[:MAX_BODY_BYTES]
    return truncated.decode("utf-8", errors="replace") + TRUNCATION_MARKER


def _body_digest(body_text: str) -> str:
    return hashlib.sha256(body_text.encode()).hexdigest()[:16]


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

    async def _write_audit_event(
        self,
        *,
        request_id: str,
        start_ms: float,
        user_subject: str,
        request_body_text: str,
        response_body_text: str,
        status_code: int,
        method: str,
        agent_id: str,
    ) -> None:
        request_body_digest = _body_digest(request_body_text)
        response_body_digest = _body_digest(response_body_text)

        latency_ms = int((time.time() - start_ms) * 1000)
        timestamp = datetime.utcnow().isoformat()

        canonical = self._signer.canonical(
            request_id=request_id,
            timestamp_iso=timestamp,
            user_subject=user_subject,
            agent_id=agent_id,
            status_code=status_code,
            latency_ms=latency_ms,
            request_body_digest=request_body_digest,
            response_body_digest=response_body_digest,
        )
        signature = self._signer.sign(canonical)

        event = {
            "request_id": request_id,
            "timestamp": timestamp,
            "user_subject": user_subject,
            "agent_id": agent_id,
            "instance_id": "",
            "method": method,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "request_headers_digest": "",
            "response_headers_digest": "",
            "request_body": request_body_text,
            "response_body": response_body_text,
            "signature": signature,
        }

        task = asyncio.create_task(_safe_write_audit(self._repo, event))
        audit_task_set.add(task)
        task.add_done_callback(audit_task_set.discard)

    async def dispatch(self, request: Request, call_next: Callable[..., Awaitable[Response]]):
        request_id = getattr(request.state, "request_id", "")
        start_ms = time.time()
        auth = getattr(request.state, "auth", None)
        user_subject = getattr(auth, "sub", "") if auth else ""

        request_body_bytes = await request.body()
        request_body_text = _truncate_body(request_body_bytes)

        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        is_stream = "text/event-stream" in content_type

        if is_stream:
            collected_chunks: list[bytes] = []
            stream_done = asyncio.Event()
            original_iterator = response.body_iterator

            async def tee():
                try:
                    async for chunk in original_iterator:
                        if isinstance(chunk, bytes):
                            collected_chunks.append(chunk)
                        yield chunk
                finally:
                    stream_done.set()

            response.body_iterator = tee()

            async def _write_stream_audit():
                await stream_done.wait()
                body_bytes = b"".join(collected_chunks)
                response_body_text = _truncate_body(body_bytes)
                await self._write_audit_event(
                    request_id=request_id,
                    start_ms=start_ms,
                    user_subject=user_subject,
                    request_body_text=request_body_text,
                    response_body_text=response_body_text,
                    status_code=response.status_code,
                    method=request.method,
                    agent_id=request.path_params.get("agent_id", ""),
                )

            asyncio.create_task(_write_stream_audit())
            return response

        if hasattr(response, "body_iterator"):
            chunks: list[bytes | dict] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            body_bytes = b"".join(c for c in chunks if isinstance(c, bytes))
            response_body_text = _truncate_body(body_bytes)

            async def _replay():
                for chunk in chunks:
                    yield chunk

            response = StreamingResponse(
                content=_replay(),
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
            if hasattr(response, "background") and response.background:
                response.background = response.background
        else:
            response_body_bytes = response.body
            response_body_text = _truncate_body(response_body_bytes)
            response = Response(
                content=response_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        await self._write_audit_event(
            request_id=request_id,
            start_ms=start_ms,
            user_subject=user_subject,
            request_body_text=request_body_text,
            response_body_text=response_body_text,
            status_code=response.status_code,
            method=request.method,
            agent_id=request.path_params.get("agent_id", ""),
        )

        return response
