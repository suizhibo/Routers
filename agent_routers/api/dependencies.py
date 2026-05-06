from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel

from agent_routers.services.forwarder import Forwarder
from agent_routers.services.registry import AgentRegistry


class AuthContext(BaseModel):
    sub: str
    role: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


def get_auth(request: Request) -> AuthContext:
    return request.state.auth


def get_forwarder(request: Request) -> Forwarder:
    return request.app.state.forwarder
