from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RouteRequest(BaseModel):
    input: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
