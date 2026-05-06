from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_routers.models.agent import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    request_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    user_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instance_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_headers_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
