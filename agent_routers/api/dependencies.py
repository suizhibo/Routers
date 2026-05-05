from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel

from agent_routers.services.registry import AgentRegistry


class AuthContext(BaseModel):
    sub: str
    role: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_registry(request: Request) -> AgentRegistry:
    return request.state.registry


def get_auth(request: Request) -> AuthContext:
    return request.state.auth
