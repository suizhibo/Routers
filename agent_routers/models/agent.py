from __future__ import annotations

from datetime import datetime
from enum import Enum
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class EndpointType(str, Enum):
    CHAT = "chat"
    CREATE_SESSION = "create_session"
    STOP = "stop"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    capability: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    endpoints: Mapped[list[AgentEndpoint]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    endpoint_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    path_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    query_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    body_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotent: Mapped[bool] = mapped_column(default=False)
    param_mapping: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    session_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)


    __table_args__ = (
        CheckConstraint("mode IN ('block', 'stream')", name="ck_mode"),
    )

    agent: Mapped[Agent] = relationship(back_populates="endpoints")
