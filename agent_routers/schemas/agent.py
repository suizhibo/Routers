from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class AgentMode(str, Enum):
    BLOCK = "block"
    STREAM = "stream"


class ParamType(str, Enum):
    STRING = "string"
    INT = "int"
    BOOL = "bool"
    FLOAT = "float"


class HTTPMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class ParamMapping(BaseModel):
    path_params: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class SessionConfig(BaseModel):
    response_header: str | None = None
    response_body_path: str | None = None


class ParamSpec(BaseModel):
    name: str
    type: ParamType
    required: bool


class EndpointSpec(BaseModel):
    endpoint_type: str
    method: HTTPMethod
    path: Annotated[str, Field(min_length=1, max_length=2048)]
    path_params: list[ParamSpec] = Field(default_factory=list)
    query_params: list[ParamSpec] = Field(default_factory=list)
    body_schema: dict | None = None
    mode: AgentMode
    idempotent: bool = False

    param_mapping: ParamMapping = Field(default_factory=ParamMapping)
    session_config: SessionConfig | None = None


class AgentRegistration(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    capability: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None)
    endpoints: Annotated[list[EndpointSpec], Field(min_length=1)]


class AgentRegistrationResponse(BaseModel):
    agent_id: str
    name: str
    created_at: datetime


class AgentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    name: str
    subject: str
    base_url: str
    capability: str | None
    description: str | None
    endpoints: list[EndpointSpec]
    created_at: datetime
    updated_at: datetime


class AgentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    name: str
    subject: str
    capability: str | None
    description: str | None
    created_at: datetime
