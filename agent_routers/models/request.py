from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from agent_routers.models.agent import Base


class RequestTracking(Base):
    __tablename__ = "request_tracking"

    request_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
