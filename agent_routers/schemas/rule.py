from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class RoutingRuleCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    priority: int
    when_clause: dict
    target_agent_id: str | None = None
    target_capability: str | None = None
    target_endpoint_type: str | None = None
    target_instance_id: str = "default"
    enabled: bool = True


class RoutingRuleDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    priority: int
    when_clause: dict
    target_agent_id: str | None
    target_capability: str | None
    target_endpoint_type: str | None
    target_instance_id: str
    enabled: bool
    created_at: datetime


class RoutingRuleUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    priority: int | None = None
    when_clause: dict | None = None
    target_agent_id: str | None = None
    target_capability: str | None = None
    target_endpoint_type: str | None = None
    target_instance_id: str | None = None
    enabled: bool | None = None
