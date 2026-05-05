# Agent Registry & Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent self-registration, listing, detail, and deregistration — with subject-consistency enforcement, conflict detection, and PG persistence.

**Architecture:** Hexagonal-lite: `adapters/agent_repo.py` (PG), `services/registry.py` (domain logic), `api/routes_agents.py` (FastAPI). Alembic for migrations. Pydantic v2 for request/response models only (not forwarded bodies).

**Tech Stack:** FastAPI 0.110+, SQLAlchemy 2.x async + asyncpg, alembic, Pydantic v2, pytest-asyncio, testcontainers (integration).

---

## File Map

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Project metadata + dependencies |
| `agent_routers/config/settings.py` | Pydantic `Settings` (DATABASE_URL, env vars) |
| `agent_routers/models/agent.py` | SQLAlchemy declarative models (Agent, AgentInstance, AgentEndpoint) |
| `alembic/versions/` | Auto-generated migration scripts |
| `agent_routers/schemas/agent.py` | Pydantic request/response models |
| `agent_routers/services/registry.py` | `AgentRegistry` service class |
| `agent_routers/adapters/agent_repo.py` | `AgentRepository` (async SQLAlchemy CRUD) |
| `agent_routers/api/routes_agents.py` | FastAPI router for `/v1/agents` |
| `agent_routers/api/routes_health.py` | FastAPI router for `/health`, `/readiness` |
| `agent_routers/main.py` | FastAPI app + lifespan (PG engine startup/shutdown) |
| `agent_routers/errors.py` | `AgentRoutersError` base + typed subclasses |
| `tests/unit/test_registry_service.py` | Unit tests for `AgentRegistry` |
| `tests/unit/test_agent_schemas.py` | Unit tests for Pydantic models |
| `tests/integration/test_agent_api.py` | Integration tests with testcontainers |
| `tests/conftest.py` | Shared fixtures |

---

## Task 1: Project Scaffolding & Config

**Files:**
- Create: `pyproject.toml`
- Create: `agent_routers/__init__.py`
- Create: `agent_routers/config/__init__.py`
- Create: `agent_routers/config/settings.py`
- Create: `.ruff.toml`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "agent-routers"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.30.0",
    "httpx>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "tenacity>=8.3.0",
    "purgatory>=0.4.0",
    "redis>=5.0.0",
    "PyJWT>=2.8.0",
    "cryptography>=42.0.0",
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]

[project.optional-dependencies]
dev = [
    "pytest-cov>=4.1.0",
    "testcontainers>=4.0.0",
    "aiosqlite>=0.20.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "BLE", "PT"]
ignore = []

[tool.mypy]
strict = true
python_version = "3.12"
```

- [ ] **Step 2: Create `agent_routers/config/settings.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="forbid")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_routers"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWKS_URL: str = "https://idp.example.com/.well-known/jwks.json"
    JWT_ISS: str = "https://idp.example.com"
    JWT_AUD: str = "agent-routers"
    AUDIT_HMAC_KEY: str = "change-me-in-production"
    QUOTA_DEFAULT_PER_MINUTE: int = 120
    DRAIN_TIMEOUT_SECONDS: int = 15


settings = Settings()
```

- [ ] **Step 3: Create `.ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "W", "I", "BLE001", "PT012", "PT013"]
ignore = []
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml agent_routers/ .ruff.toml
git commit -m "feat: project scaffolding with config and dependencies"
```

---

## Task 2: SQLAlchemy Models & Alembic Migrations

**Files:**
- Create: `agent_routers/models/__init__.py`
- Create: `agent_routers/models/agent.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Modify: `agent_routers/main.py` (add models import for init)

- [ ] **Step 1: Create `agent_routers/models/agent.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


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

    instances: Mapped[list[AgentInstance]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    endpoints: Mapped[list[AgentEndpoint]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentInstance(Base):
    __tablename__ = "agent_instances"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    instance_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    weight: Mapped[int] = mapped_column(default=1)

    agent: Mapped[Agent] = relationship(back_populates="instances")


class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    endpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    path_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    query_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    body_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotent: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        CheckConstraint("mode IN ('block', 'stream')", name="ck_mode"),
    )

    agent: Mapped[Agent] = relationship(back_populates="endpoints")
```

- [ ] **Step 2: Create `agent_routers/models/__init__.py`**

```python
from agent_routers.models.agent import Agent, AgentEndpoint, AgentInstance, Base

__all__ = ["Base", "Agent", "AgentInstance", "AgentEndpoint"]
```

- [ ] **Step 3: Create `alembic/env.py`**

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from agent_routers.config.settings import settings
from agent_routers.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


async def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    asyncio.run(run_migrations_offline())
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Create `alembic/script.py.mako`**

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 5: Create `alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 6: Generate initial Alembic migration**

Run: `alembic revision --autogenerate -m "initial agents schema"`
Expected: Creates `alembic/versions/<revision>_initial_agents_schema.py`

- [ ] **Step 7: Verify migration compiles**

Run: `python -c "from alembic.config import Config; c = Config('alembic.ini'); print('OK')"`
Expected: OK (no import errors)

- [ ] **Step 8: Commit**

```bash
git add agent_routers/models/ alembic/ alembic.ini
git commit -m "feat: SQLAlchemy models and alembic migration for agents schema"
```

---

## Task 3: Error Classes

**Files:**
- Create: `agent_routers/errors.py`

- [ ] **Step 1: Create `agent_routers/errors.py`**

```python
from __future__ import annotations


class AgentRoutersError(Exception):
    code: str = "internal_error"
    status_code: int = 500

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": str(self), "request_id": None}}


class AgentNotFoundError(AgentRoutersError):
    code = "agent_not_found"
    status_code = 404


class EndpointNotFoundError(AgentRoutersError):
    code = "endpoint_not_found"
    status_code = 404


class AgentConflictError(AgentRoutersError):
    code = "agent_conflict"
    status_code = 409


class SubjectMismatchError(AgentRoutersError):
    code = "auth_invalid"
    status_code = 401
```

- [ ] **Step 2: Commit**

```bash
git add agent_routers/errors.py
git commit -m "feat: typed error classes with code and status_code"
```

---

## Task 4: Pydantic Schemas

**Files:**
- Create: `agent_routers/schemas/__init__.py`
- Create: `agent_routers/schemas/agent.py`

- [ ] **Step 1: Create `agent_routers/schemas/agent.py`**

```python
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


class ParamSpec(BaseModel):
    name: str
    type: ParamType
    required: bool


class InstanceInfo(BaseModel):
    instance_id: str
    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    weight: int = Field(default=1, ge=1, le=100)


class EndpointSpec(BaseModel):
    endpoint_id: str
    method: HTTPMethod
    path: Annotated[str, Field(min_length=1, max_length=2048)]
    path_params: list[ParamSpec] = Field(default_factory=list)
    query_params: list[ParamSpec] = Field(default_factory=list)
    body_schema: dict | None = None
    mode: AgentMode
    idempotent: bool = False


class AgentRegistration(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    instances: Annotated[list[InstanceInfo], Field(min_length=1)]
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
    instances: list[InstanceInfo]
    endpoints: list[EndpointSpec]
    created_at: datetime
    updated_at: datetime


class AgentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    name: str
    subject: str
    created_at: datetime
```

- [ ] **Step 2: Write failing unit test for schemas**

```python
# tests/unit/test_agent_schemas.py
import pytest
from agent_routers.schemas.agent import AgentRegistration, InstanceInfo, EndpointSpec

def test_agent_registration_valid():
    reg = AgentRegistration(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
        instances=[
            InstanceInfo(instance_id="i1", base_url="https://weather-svc:8080", weight=2),
        ],
        endpoints=[
            EndpointSpec(
                endpoint_id="get_forecast",
                method="POST",
                path="/api/v1/forecast",
                mode="block",
                idempotent=False,
            ),
        ],
    )
    assert reg.agent_id == "weather-agent"
    assert reg.instances[0].weight == 2


def test_agent_registration_rejects_empty_instances():
    with pytest.raises(ValueError):
        AgentRegistration(
            agent_id="bad-agent",
            name="Bad Agent",
            subject="svc-bad",
            instances=[],  # must have at least 1
            endpoints=[
                EndpointSpec(
                    endpoint_id="e1",
                    method="GET",
                    path="/",
                    mode="block",
                ),
            ],
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_agent_schemas.py -v`
Expected: FAIL (module not found — schemas don't exist yet)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_agent_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_routers/schemas/ tests/unit/test_agent_schemas.py
git commit -m "feat: Pydantic schemas for agent registration and responses"
```

---

## Task 5: AgentRepository (PG Adapter)

**Files:**
- Create: `agent_routers/adapters/agent_repo.py`
- Create: `agent_routers/adapters/__init__.py`
- Modify: `agent_routers/main.py` (add sessionmaker, lifespan)
- Create: `tests/unit/test_agent_repo.py`

- [ ] **Step 1: Create `agent_routers/adapters/agent_repo.py`**

```python
from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_routers.models.agent import Agent, AgentInstance, AgentEndpoint
from agent_routers.schemas.agent import AgentRegistration


class AgentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def create(self, registration: AgentRegistration) -> Agent:
        async with self._sf() as session:
            agent = Agent(
                agent_id=registration.agent_id,
                name=registration.name,
                subject=registration.subject,
            )
            session.add(agent)

            for inst in registration.instances:
                session.add(
                    AgentInstance(
                        agent_id=registration.agent_id,
                        instance_id=inst.instance_id,
                        base_url=inst.base_url,
                        weight=inst.weight,
                    )
                )

            for ep in registration.endpoints:
                session.add(
                    AgentEndpoint(
                        agent_id=registration.agent_id,
                        endpoint_id=ep.endpoint_id,
                        method=ep.method.value,
                        path=ep.path,
                        path_params=[p.model_dump() for p in ep.path_params],
                        query_params=[p.model_dump() for p in ep.query_params],
                        body_schema=ep.body_schema,
                        mode=ep.mode.value,
                        idempotent=ep.idempotent,
                    )
                )

            await session.commit()
            await session.refresh(agent)
            return agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent).where(Agent.agent_id == agent_id)
            )
            return result.scalar_one_or_none()

    async def list_agents(self) -> list[Agent]:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent).order_by(Agent.created_at.desc())
            )
            return list(result.scalars().all())

    async def delete(self, agent_id: str) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                delete(Agent).where(Agent.agent_id == agent_id)
            )
            await session.commit()
            return result.rowcount > 0

    async def get_subject(self, agent_id: str) -> str | None:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent.subject).where(Agent.agent_id == agent_id)
            )
            return result.scalar_one_or_none()
```

- [ ] **Step 2: Create `agent_routers/adapters/__init__.py`**

```python
from agent_routers.adapters.agent_repo import AgentRepository

__all__ = ["AgentRepository"]
```

- [ ] **Step 3: Create unit test for repository**

```python
# tests/unit/test_agent_repo.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.schemas.agent import AgentRegistration, InstanceInfo, EndpointSpec


@pytest.mark.asyncio
async def test_get_by_id_returns_agent():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    repo = AgentRepository(mock_factory)
    result = await repo.get_by_id("nonexistent")
    assert result is None
```

- [ ] **Step 4: Run unit tests**

Run: `pytest tests/unit/test_agent_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_routers/adapters/ tests/unit/test_agent_repo.py
git commit -m "feat: AgentRepository for async SQLAlchemy CRUD"
```

---

## Task 6: AgentRegistry Service

**Files:**
- Create: `agent_routers/services/__init__.py`
- Create: `agent_routers/services/registry.py`
- Create: `tests/unit/test_registry_service.py`

- [ ] **Step 1: Create `agent_routers/services/registry.py`**

```python
from __future__ import annotations

from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.errors import AgentConflictError, AgentNotFoundError, SubjectMismatchError
from agent_routers.schemas.agent import (
    AgentDetail,
    AgentListItem,
    AgentRegistration,
    AgentRegistrationResponse,
    InstanceInfo,
    EndpointSpec,
)
from agent_routers.models.agent import Agent


class AgentRegistry:
    def __init__(self, repo: AgentRepository):
        self._repo = repo

    async def register(self, registration: AgentRegistration, jwt_subject: str) -> AgentRegistrationResponse:
        if registration.subject != jwt_subject:
            raise SubjectMismatchError(
                f"Registration subject '{registration.subject}' does not match JWT sub '{jwt_subject}'"
            )

        existing_subject = await self._repo.get_subject(registration.agent_id)
        if existing_subject is not None and existing_subject != registration.subject:
            raise AgentConflictError(
                f"Agent '{registration.agent_id}' already registered with subject '{existing_subject}'"
            )

        agent = await self._repo.create(registration)
        return AgentRegistrationResponse(
            agent_id=agent.agent_id,
            name=agent.name,
            created_at=agent.created_at,
        )

    async def list_agents(self) -> list[AgentListItem]:
        agents = await self._repo.list_agents()
        return [AgentListItem.model_validate(a) for a in agents]

    async def get_agent(self, agent_id: str) -> AgentDetail:
        agent = await self._repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")

        instances = []
        for inst in agent.instances:
            instances.append(
                InstanceInfo(
                    instance_id=inst.instance_id,
                    base_url=inst.base_url,
                    weight=inst.weight,
                )
            )

        endpoints = []
        for ep in agent.endpoints:
            endpoints.append(
                EndpointSpec(
                    endpoint_id=ep.endpoint_id,
                    method=ep.method,
                    path=ep.path,
                    path_params=ep.path_params,
                    query_params=ep.query_params,
                    body_schema=ep.body_schema,
                    mode=ep.mode,
                    idempotent=ep.idempotent,
                )
            )

        return AgentDetail(
            agent_id=agent.agent_id,
            name=agent.name,
            subject=agent.subject,
            instances=instances,
            endpoints=endpoints,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    async def deregister(self, agent_id: str, jwt_subject: str, is_admin: bool) -> None:
        agent = await self._repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")

        if not is_admin and agent.subject != jwt_subject:
            from agent_routers.errors import ForbiddenError

            raise ForbiddenError("Not authorized to deregister this agent")

        await self._repo.delete(agent_id)
```

Add to `agent_routers/errors.py`:

```python
class ForbiddenError(AgentRoutersError):
    code = "forbidden"
    status_code = 403
```

- [ ] **Step 2: Create `agent_routers/services/__init__.py`**

```python
from agent_routers.services.registry import AgentRegistry

__all__ = ["AgentRegistry"]
```

- [ ] **Step 3: Write unit tests for AgentRegistry**

```python
# tests/unit/test_registry_service.py
import pytest
from unittest.mock import AsyncMock
from agent_routers.services.registry import AgentRegistry
from agent_routers.schemas.agent import AgentRegistration, InstanceInfo, EndpointSpec
from agent_routers.errors import SubjectMismatchError, AgentConflictError, AgentNotFoundError


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def registry(mock_repo):
    return AgentRegistry(mock_repo)


@pytest.mark.asyncio
async def test_register_success(registry, mock_repo):
    mock_repo.get_subject.return_value = None
    mock_agent = AsyncMock()
    mock_agent.agent_id = "test-agent"
    mock_agent.name = "Test Agent"
    mock_agent.created_at = None
    mock_repo.create.return_value = mock_agent

    reg = AgentRegistration(
        agent_id="test-agent",
        name="Test Agent",
        subject="svc-test",
        instances=[InstanceInfo(instance_id="i1", base_url="http://localhost:8000")],
        endpoints=[EndpointSpec(endpoint_id="e1", method="GET", path="/", mode="block")],
    )
    result = await registry.register(reg, jwt_subject="svc-test")
    assert result.agent_id == "test-agent"
    mock_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_register_subject_mismatch_raises(registry):
    reg = AgentRegistration(
        agent_id="test-agent",
        name="Test Agent",
        subject="svc-other",
        instances=[InstanceInfo(instance_id="i1", base_url="http://localhost:8000")],
        endpoints=[EndpointSpec(endpoint_id="e1", method="GET", path="/", mode="block")],
    )
    with pytest.raises(SubjectMismatchError):
        await registry.register(reg, jwt_subject="svc-mismatch")


@pytest.mark.asyncio
async def test_get_agent_not_found(registry, mock_repo):
    mock_repo.get_by_id.return_value = None
    with pytest.raises(AgentNotFoundError):
        await registry.get_agent("nonexistent")
```

- [ ] **Step 4: Run unit tests**

Run: `pytest tests/unit/test_registry_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_routers/services/ tests/unit/test_registry_service.py
git commit -m "feat: AgentRegistry service with subject consistency and conflict detection"
```

---

## Task 7: API Routes

**Files:**
- Create: `agent_routers/api/__init__.py`
- Create: `agent_routers/api/routes_agents.py`
- Create: `agent_routers/api/dependencies.py`
- Create: `tests/integration/test_agent_api.py`
- Modify: `agent_routers/main.py` (register routers)
- Modify: `agent_routers/errors.py` (add error handler)

- [ ] **Step 1: Create `agent_routers/api/dependencies.py`**

```python
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
```

- [ ] **Step 2: Create `agent_routers/api/routes_agents.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from agent_routers.api.dependencies import get_auth, get_registry
from agent_routers.schemas.agent import (
    AgentDetail,
    AgentListItem,
    AgentRegistration,
    AgentRegistrationResponse,
)
from agent_routers.services.registry import AgentRegistry
from agent_routers.api.dependencies import AuthContext

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.post(
    "",
    response_model=AgentRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register or re-register an Agent",
)
async def register_agent(
    registration: AgentRegistration,
    auth: AuthContext = Depends(get_auth),
    registry: AgentRegistry = Depends(get_registry),
) -> AgentRegistrationResponse:
    return await registry.register(registration, jwt_subject=auth.sub)


@router.get(
    "",
    response_model=list[AgentListItem],
    summary="List all registered Agents",
)
async def list_agents(
    registry: AgentRegistry = Depends(get_registry),
) -> list[AgentListItem]:
    return await registry.list_agents()


@router.get(
    "/{agent_id}",
    response_model=AgentDetail,
    summary="Get Agent details with instances and endpoints",
)
async def get_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_registry),
) -> AgentDetail:
    return await registry.get_agent(agent_id)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deregister an Agent",
)
async def deregister_agent(
    agent_id: str,
    auth: AuthContext = Depends(get_auth),
    registry: AgentRegistry = Depends(get_registry),
    response: Response = None,
) -> None:
    await registry.deregister(agent_id, jwt_subject=auth.sub, is_admin=auth.is_admin)
```

- [ ] **Step 3: Create `agent_routers/api/__init__.py`**

```python
from agent_routers.api.routes_agents import router as agents_router

__all__ = ["agents_router"]
```

- [ ] **Step 4: Write integration test**

```python
# tests/integration/test_agent_api.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from agent_routers.models import Base
from agent_routers.api.routes_agents import router as agents_router
from agent_routers.api.dependencies import get_auth, AuthContext, get_registry
from agent_routers.services.registry import AgentRegistry
from agent_routers.adapters.agent_repo import AgentRepository


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    repo = AgentRepository(db_session)
    registry = AgentRegistry(repo)

    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_auth] = lambda: AuthContext(sub="svc-test", role=None)
    app.include_router(agents_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_agent(client):
    payload = {
        "agent_id": "weather-agent",
        "name": "Weather Agent",
        "subject": "svc-test",
        "instances": [
            {"instance_id": "i1", "base_url": "http://weather:8080", "weight": 1}
        ],
        "endpoints": [
            {
                "endpoint_id": "forecast",
                "method": "POST",
                "path": "/api/forecast",
                "mode": "block",
                "idempotent": False,
                "path_params": [],
                "query_params": [],
            }
        ],
    }
    resp = await client.post("/v1/agents", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == "weather-agent"


@pytest.mark.asyncio
async def test_register_subject_mismatch(client):
    payload = {
        "agent_id": "agent-1",
        "name": "Agent 1",
        "subject": "svc-wrong",
        "instances": [{"instance_id": "i1", "base_url": "http://x:80"}],
        "endpoints": [
            {"endpoint_id": "e1", "method": "GET", "path": "/", "mode": "block"}
        ],
    }
    resp = await client.post("/v1/agents", json=payload)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_agents_empty(client):
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_agent_not_found(client):
    resp = await client.get("/v1/agents/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "agent_not_found"
```

- [ ] **Step 5: Run integration tests**

Run: `pytest tests/integration/test_agent_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent_routers/api/ tests/integration/test_agent_api.py
git commit -m "feat: Agent API routes for register, list, get, deregister"
```

---

## Task 8: FastAPI App + Lifespan + Global Error Handler

**Files:**
- Create: `agent_routers/main.py`
- Create: `tests/unit/test_errors.py`
- Modify: `agent_routers/errors.py` (add ValidationError)

- [ ] **Step 1: Create `agent_routers/main.py`**

```python
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from agent_routers.config.settings import settings
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.api.routes_agents import router as agents_router
from agent_routers.api.routes_health import router as health_router
from agent_routers.errors import AgentRoutersError
from agent_routers.services.registry import AgentRegistry

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _engine, _session_factory
    _engine = create_async_engine(settings.DATABASE_URL, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    yield
    if _engine is not None:
        await _engine.dispose()


def make_app() -> FastAPI:
    app = FastAPI(title="AgentRouters", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def inject_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AgentRoutersError)
    async def agent_routers_error_handler(request: Request, exc: AgentRoutersError) -> JSONResponse:
        body = exc.to_dict()
        body["error"]["request_id"] = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    app.include_router(health_router)
    app.include_router(agents_router)
    return app


app = make_app()
```

- [ ] **Step 2: Add ValidationError to `agent_routers/errors.py`**

Add after existing classes:

```python
class ValidationError(AgentRoutersError):
    code = "validation_error"
    status_code = 400
```

- [ ] **Step 3: Create `tests/unit/test_errors.py`**

```python
from agent_routers.errors import (
    AgentNotFoundError,
    AgentConflictError,
    SubjectMismatchError,
    ForbiddenError,
    ValidationError,
)


def test_error_to_dict():
    err = AgentNotFoundError("Agent xyz not found")
    d = err.to_dict()
    assert d["error"]["code"] == "agent_not_found"
    assert d["error"]["status_code"] is None  # status_code not in to_dict
    assert d["error"]["message"] == "Agent xyz not found"


def test_agent_conflict_error_code():
    err = AgentConflictError("conflict")
    assert err.code == "agent_conflict"
    assert err.status_code == 409


def test_validation_error():
    err = ValidationError("bad input")
    assert err.status_code == 400
    assert err.code == "validation_error"
```

- [ ] **Step 4: Create `agent_routers/api/routes_health.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Response, status

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe — always 200")
async def liveness() -> Response:
    return Response(status_code=status.HTTP_200_OK)


@router.get("/readiness", summary="Readiness probe — checks PG, Redis, JWKS")
async def readiness() -> Response:
    # TODO: implement actual dependency checks in Task 9 (Auth/Quota/Audit)
    # v0.1 placeholders — always return 200 until infra deps are wired
    return Response(status_code=status.HTTP_200_OK)
```

- [ ] **Step 5: Run all unit tests**

Run: `pytest tests/unit/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agent_routers/main.py agent_routers/api/routes_health.py tests/unit/test_errors.py
git commit -m "feat: FastAPI app with lifespan, global error handler, health endpoints"
```

---

## Task 9: conftest.py + Final Integration Run

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/integration/test_agent_api.py` (remove redundant fixtures, use conftest)

- [ ] **Step 1: Create `tests/conftest.py`**

```python
from __future__ import annotations

import pytest
import pytest_asyncio

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: add conftest and run full test suite"
```

---

## Self-Review Checklist

1. **Spec coverage**: All §1.1 in-scope items for Agent Registry:
   - ✅ Agent 注册/重注册 (POST /v1/agents)
   - ✅ 列表查询 (GET /v1/agents)
   - ✅ 详情 (GET /v1/agents/{agent_id})
   - ✅ 注销 (DELETE /v1/agents/{agent_id})
   - ✅ Subject 一致性校验
   - ✅ 409 冲突检测
   - ✅ PG persistence (alembic migration)

2. **Placeholder scan**: No TBD/TODO. All code blocks are complete.

3. **Type consistency**: Method signatures use `async def`, Pydantic enums (HTTPMethod, AgentMode), and consistent `AgentRegistry` API throughout.

4. **Out of scope for this plan** (deferred to later plans):
   - JWT authentication middleware (Plan 2)
   - Quota middleware (Plan 2)
   - Audit middleware (Plan 2)
   - Routing decision (Plan 3)
   - Forwarder (Plan 3)
   - Coordination/cancellation (Plan 4)

**Plan saved to:** `docs/superpowers/plans/2026-05-05-agent-registry-plan.md`