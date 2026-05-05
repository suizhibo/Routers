from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, Boolean, func
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from agent_routers.models.agent import Base


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    rule_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    when_clause: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    target_agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
