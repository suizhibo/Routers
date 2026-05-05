from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class RoutingRuleCreate(BaseModel):
    rule_id: str
    priority: int
    when_clause: dict
    target_agent_id: str
    target_instance_id: str
    enabled: bool = True


class RoutingRuleDetail(BaseModel):
    rule_id: str
    priority: int
    when_clause: dict
    target_agent_id: str
    target_instance_id: str
    enabled: bool
    created_at: datetime


class RoutingRuleUpdate(BaseModel):
    priority: int | None = None
    when_clause: dict | None = None
    target_agent_id: str | None = None
    target_instance_id: str | None = None
    enabled: bool | None = None
