from __future__ import annotations

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_routers.models.audit import AuditEvent


class AuditRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def insert(self, event: dict) -> None:
        async with self._sf() as session:
            audit_event = AuditEvent(
                request_id=event["request_id"],
                timestamp=datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                user_subject=event["user_subject"],
                agent_id=event.get("agent_id") or None,
                instance_id=event.get("instance_id") or None,
                method=event.get("method") or None,
                status_code=event.get("status_code"),
                latency_ms=event.get("latency_ms"),
                request_headers_digest=event.get("request_headers_digest") or None,
                response_headers_digest=event.get("response_headers_digest") or None,
                request_body=event.get("request_body") or None,
                response_body=event.get("response_body") or None,
                signature=event["signature"],
            )
            session.add(audit_event)
            await session.commit()

    async def get_by_request_id(self, request_id: str) -> AuditEvent | None:
        async with self._sf() as session:
            return await session.get(AuditEvent, request_id)
