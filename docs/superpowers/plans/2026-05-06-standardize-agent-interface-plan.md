# 智能体标准化接口实现计划

> **目标**：将所有智能体接口标准化为3个端点（create-session、chat、stop），简化路由配置，统一生命周期管理。

**范围**：修改 Schema、Model、Service、API 层，更新测试，确保向后兼容。

**技术栈**：FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic, redis-py async, httpx, pytest-asyncio

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `agent_routers/schemas/agent.py` | `EndpointSpec` 新增 `operation_types` |
| `agent_routers/models/agent.py` | `AgentEndpoint` 新增 `operation_types` 列 |
| `agent_routers/models/rule.py` | `RoutingRule` 新增 `target_endpoint_id` |
| `alembic/versions/005_operation_types.py` | Migration |
| `agent_routers/services/session_manager.py` | 简化存储格式 |
| `agent_routers/services/routing.py` | 5级流水线，支持 operation match |
| `agent_routers/services/forwarder.py` | 适配新 SessionManager |
| `agent_routers/api/routes_forward.py` | 固定 `POST /v1/route` |
| `agent_routers/config/settings.py` | 新增 `DEFAULT_AGENT_ID` |
| `tests/unit/test_routing.py` | 测试5级流水线 |
| `tests/unit/test_forwarder.py` | 适配新接口 |
| `tests/unit/test_session_manager.py` | 适配简化存储 |

---

## Task 1: Schema 和 Model 变更

**文件**：
- 修改：`agent_routers/schemas/agent.py`
- 修改：`agent_routers/models/agent.py`
- 修改：`agent_routers/models/rule.py`
- 创建：`alembic/versions/005_operation_types.py`
- 修改：`agent_routers/adapters/agent_repo.py`
- 修改：`tests/unit/test_agent_schemas.py`

### Step 1: 添加 `operation_types` 到 `EndpointSpec`

在 `agent_routers/schemas/agent.py`：

```python
class EndpointSpec(BaseModel):
    endpoint_id: str
    method: HTTPMethod
    path: Annotated[str, Field(min_length=1, max_length=2048)]
    path_params: list[ParamSpec] = Field(default_factory=list)
    query_params: list[ParamSpec] = Field(default_factory=list)
    body_schema: dict | None = None
    mode: AgentMode
    idempotent: bool = False
    operation_types: list[str] = Field(default_factory=list)  # NEW
    param_mapping: ParamMapping = Field(default_factory=ParamMapping)
    session_config: SessionConfig | None = None
```

### Step 2: 添加 `operation_types` 到 `AgentEndpoint` model

在 `agent_routers/models/agent.py`：

```python
class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"

    agent_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("agents.agent_id", ondelete="CASCADE"), primary_key=True
    )
    endpoint_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    path_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    query_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    body_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotent: Mapped[bool] = mapped_column(default=False)
    param_mapping: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    session_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operation_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # NEW

    __table_args__ = (
        CheckConstraint("mode IN ('block', 'stream')", name="ck_mode"),
    )

    agent: Mapped[Agent] = relationship(back_populates="endpoints")
```

### Step 3: 添加 `target_endpoint_id` 到 `RoutingRule`

在 `agent_routers/models/rule.py`：

```python
class RoutingRule(Base):
    __tablename__ = "routing_rules"

    rule_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    when_clause: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    target_agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_endpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # NEW
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
```

### Step 4: 更新 `AgentRepository.create()` 持久化 `operation_types`

在 `agent_routers/adapters/agent_repo.py`，`create()` 方法的 endpoint 循环：

```python
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
                        param_mapping=ep.param_mapping.model_dump(),
                        session_config=ep.session_config.model_dump() if ep.session_config else None,
                        operation_types=list(ep.operation_types),  # NEW
                    )
                )
```

### Step 5: 添加 `list_all()` 到 `AgentRepository`

在 `agent_routers/adapters/agent_repo.py`：

```python
    async def list_all(self) -> list[Agent]:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent).options(
                    selectinload(Agent.instances),
                    selectinload(Agent.endpoints),
                )
            )
            return list(result.scalars().all())
```

添加 import：
```python
from sqlalchemy.orm import selectinload
```

### Step 6: 创建 migration

创建 `alembic/versions/005_operation_types.py`：

```python
"""add operation_types and target_endpoint_id

Revision ID: 005
Revises: 004
Create Date: 2026-05-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_endpoints', sa.Column('operation_types', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.add_column('routing_rules', sa.Column('target_endpoint_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('routing_rules', 'target_endpoint_id')
    op.drop_column('agent_endpoints', 'operation_types')
```

### Step 7: 更新 schema 测试

在 `tests/unit/test_agent_schemas.py`：

```python
def test_endpoint_spec_with_session_config():
    ep = EndpointSpec(
        endpoint_id="chat",
        method="POST",
        path="/api/chat/{session_id}",
        mode="stream",
        operation_types=["chat"],  # NEW
        param_mapping=ParamMapping(
            path_params={"session_id": "context.session_id"},
            body="input",
        ),
        session_config=SessionConfig(response_header="X-Session-ID"),
    )
    assert ep.session_config.response_header == "X-Session-ID"
    assert ep.param_mapping.path_params["session_id"] == "context.session_id"
    assert ep.operation_types == ["chat"]  # NEW
```

### Step 8: 运行 migration

```bash
alembic upgrade head
```

### Step 9: 运行 schema 测试

```bash
pytest tests/unit/test_agent_schemas.py -v
```

### Step 10: Commit

```bash
git add agent_routers/schemas/agent.py agent_routers/models/agent.py agent_routers/models/rule.py agent_routers/adapters/agent_repo.py alembic/versions/005_operation_types.py tests/unit/test_agent_schemas.py
git commit -m "feat: operation_types on EndpointSpec/AgentEndpoint, target_endpoint_id on RoutingRule"
```

---

## Task 2: 简化 SessionManager

**文件**：
- 修改：`agent_routers/services/session_manager.py`
- 修改：`tests/unit/test_session_manager.py`

### Step 1: 重写 `SessionManager`

替换 `agent_routers/services/session_manager.py`：

```python
from __future__ import annotations

import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400  # 24 hours


class SessionManager:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _ensure_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def get_route(self, session_id: str) -> tuple[str, str] | None:
        if not session_id:
            return None
        try:
            client = await self._ensure_client()
            value = await client.get(f"session:{session_id}")
            if value:
                parts = value.split(":", 1)
                if len(parts) == 2:
                    return parts[0], parts[1]
            return None
        except Exception:
            logger.exception("session_get_failed", extra={"session_id": session_id})
            return None

    async def set_route(
        self,
        session_id: str,
        agent_id: str,
        endpoint_id: str,
        ttl: int = DEFAULT_TTL,
    ) -> None:
        if not session_id or not agent_id or not endpoint_id:
            return
        try:
            client = await self._ensure_client()
            value = f"{agent_id}:{endpoint_id}"
            await client.set(f"session:{session_id}", value, ex=ttl)
            logger.info("session_set", extra={"session_id": session_id, "agent_id": agent_id, "endpoint_id": endpoint_id})
        except Exception:
            logger.exception("session_set_failed", extra={"session_id": session_id, "agent_id": agent_id})
```

### Step 2: 重写 `test_session_manager.py`

替换 `tests/unit/test_session_manager.py`：

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agent_routers.services.session_manager import SessionManager


@pytest.fixture
def mock_redis():
    with patch("agent_routers.services.session_manager.redis.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_get_route_found(mock_redis):
    mock_redis.get.return_value = "agent-1:ep-chat"
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_route("sess-123")
    assert result == ("agent-1", "ep-chat")
    mock_redis.get.assert_awaited_once_with("session:sess-123")


@pytest.mark.asyncio
async def test_get_route_not_found(mock_redis):
    mock_redis.get.return_value = None
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_route("sess-123")
    assert result is None


@pytest.mark.asyncio
async def test_get_route_empty_session_id(mock_redis):
    mgr = SessionManager("redis://localhost")
    result = await mgr.get_route("")
    assert result is None
    mock_redis.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_route(mock_redis):
    mgr = SessionManager("redis://localhost")
    await mgr.set_route("sess-123", "agent-1", "ep-chat", ttl=3600)
    mock_redis.set.assert_awaited_once_with("session:sess-123", "agent-1:ep-chat", ex=3600)


@pytest.mark.asyncio
async def test_set_route_empty_session_id(mock_redis):
    mgr = SessionManager("redis://localhost")
    await mgr.set_route("", "agent-1", "ep-chat")
    mock_redis.set.assert_not_awaited()
```

### Step 3: 运行测试

```bash
pytest tests/unit/test_session_manager.py -v
```

### Step 4: Commit

```bash
git add agent_routers/services/session_manager.py tests/unit/test_session_manager.py
git commit -m "feat: simplified SessionManager stores agent:endpoint per session"
```

---

## Task 3: 重写 RoutingDecisionEngine

**文件**：
- 修改：`agent_routers/services/routing.py`
- 修改：`tests/unit/test_routing.py`
- 修改：`agent_routers/main.py`
- 修改：`agent_routers/config/settings.py`

### Step 1: 重写 `RoutingDecisionEngine`

替换 `agent_routers/services/routing.py`：

```python
from __future__ import annotations

import logging
from typing import Any

from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _extract_value(data: dict, dot_path: str) -> Any:
    if dot_path == "$":
        return data
    current = data
    for part in dot_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _evaluate_when_clause(when_clause: dict, route_req: RouteRequest, headers: dict[str, str]) -> bool:
    """Simple when_clause evaluator. Supports: header.*, context.*, options.*, input equality."""
    req_dict = route_req.model_dump()
    for key, expected in when_clause.items():
        if key.startswith("header."):
            header_key = key[7:]
            actual = headers.get(header_key) or headers.get(header_key.lower())
        elif key.startswith("context."):
            actual = _extract_value(req_dict, key)
        elif key.startswith("options."):
            actual = _extract_value(req_dict, key)
        elif key == "input":
            actual = req_dict.get("input")
        else:
            actual = _extract_value(req_dict, key)
        if actual != expected:
            return False
    return True


class RoutingDecisionEngine:
    def __init__(
        self,
        rule_repo: RuleRepository,
        agent_repo: AgentRepository,
        session_manager: SessionManager,
        default_agent_id: str = "",
    ):
        self._rule_repo = rule_repo
        self._agent_repo = agent_repo
        self._session_manager = session_manager
        self._default_agent_id = default_agent_id

    async def resolve(
        self,
        route_req: RouteRequest,
        headers: dict[str, str],
    ) -> tuple[str, str]:
        req_dict = route_req.model_dump()

        # L1: Preferred
        preferred_agent = headers.get("X-Preferred-Agent")
        preferred_endpoint = headers.get("X-Preferred-Endpoint")
        if preferred_agent and preferred_endpoint:
            logger.debug("routing_l1_preferred", extra={"agent": preferred_agent, "endpoint": preferred_endpoint})
            return preferred_agent, preferred_endpoint

        # L2: Cache
        session_id = _extract_value(req_dict, "context.session_id")
        if session_id and self._session_manager:
            cached = await self._session_manager.get_route(session_id)
            if cached:
                logger.debug("routing_l2_cache", extra={"session_id": session_id, "route": cached})
                return cached

        # L3: Rule
        rules = await self._rule_repo.list_enabled()
        for rule in rules:
            if _evaluate_when_clause(rule.when_clause, route_req, headers):
                agent_id = rule.target_agent_id
                endpoint_id = rule.target_endpoint_id
                if not endpoint_id:
                    agent = await self._agent_repo.get_by_id(agent_id)
                    if agent and agent.endpoints:
                        endpoint_id = agent.endpoints[0].endpoint_id
                if endpoint_id:
                    logger.debug("routing_l3_rule", extra={"rule_id": rule.rule_id, "route": (agent_id, endpoint_id)})
                    return agent_id, endpoint_id

        # L4: Operation Match
        operation = _extract_value(req_dict, "context.operation")
        if not operation:
            operation = _extract_value(req_dict, "options.action")
        if operation:
            agents = await self._agent_repo.list_all()
            for agent in agents:
                for ep in agent.endpoints:
                    op_types = ep.operation_types or []
                    if operation in op_types:
                        logger.debug("routing_l4_operation", extra={"operation": operation, "route": (agent.agent_id, ep.endpoint_id)})
                        return agent.agent_id, ep.endpoint_id

        # L5: Default
        if self._default_agent_id:
            agent = await self._agent_repo.get_by_id(self._default_agent_id)
            if agent and agent.endpoints:
                ep_id = agent.endpoints[0].endpoint_id
                logger.debug("routing_l5_default", extra={"route": (self._default_agent_id, ep_id)})
                return self._default_agent_id, ep_id

        from agent_routers.errors import AgentNotFoundError
        raise AgentNotFoundError("No route found for request")
```

### Step 2: 重写 `test_routing.py`

替换 `tests/unit/test_routing.py`：

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_routers.errors import AgentNotFoundError
from agent_routers.models.agent import Agent, AgentEndpoint
from agent_routers.models.rule import RoutingRule
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.routing import RoutingDecisionEngine, _evaluate_when_clause


class FakeAgentRepo:
    def __init__(self, agents: list[Agent]):
        self._agents = {a.agent_id: a for a in agents}

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    async def list_all(self) -> list[Agent]:
        return list(self._agents.values())


class FakeRuleRepo:
    def __init__(self, rules: list[RoutingRule]):
        self._rules = rules

    async def list_enabled(self) -> list[RoutingRule]:
        return list(self._rules)


class FakeSessionManager:
    def __init__(self, route: tuple[str, str] | None = None):
        self._route = route

    async def get_route(self, session_id: str) -> tuple[str, str] | None:
        return self._route


def _make_agent(agent_id: str, endpoint_id: str, operation_types: list[str] | None = None) -> Agent:
    if operation_types is None:
        operation_types = []
    agent = Agent(agent_id=agent_id, name=f"Agent {agent_id}", subject=f"sub-{agent_id}")
    agent.endpoints = [
        AgentEndpoint(
            agent_id=agent_id,
            endpoint_id=endpoint_id,
            method="POST",
            path="/api/chat",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config=None,
            operation_types=operation_types,
        ),
    ]
    return agent


def _make_engine(
    agents: list[Agent] = None,
    rules: list[RoutingRule] = None,
    session_route: tuple[str, str] | None = None,
    default_agent_id: str = "",
):
    if agents is None:
        agents = []
    if rules is None:
        rules = []
    return RoutingDecisionEngine(
        rule_repo=FakeRuleRepo(rules),
        agent_repo=FakeAgentRepo(agents),
        session_manager=FakeSessionManager(session_route),
        default_agent_id=default_agent_id,
    )


# --- L1 Preferred ---

@pytest.mark.asyncio
async def test_l1_preferred_header_wins():
    engine = _make_engine()
    req = RouteRequest()
    headers = {"X-Preferred-Agent": "agent-a", "X-Preferred-Endpoint": "ep-1"}
    result = await engine.resolve(req, headers)
    assert result == ("agent-a", "ep-1")


@pytest.mark.asyncio
async def test_l1_preferred_partial_ignored():
    engine = _make_engine()
    req = RouteRequest()
    headers = {"X-Preferred-Agent": "agent-a"}  # missing endpoint
    with pytest.raises(AgentNotFoundError):
        await engine.resolve(req, headers)


# --- L2 Cache ---

@pytest.mark.asyncio
async def test_l2_cache_hit():
    engine = _make_engine(session_route=("agent-a", "ep-1"))
    req = RouteRequest(context={"session_id": "sess-123"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-1")


@pytest.mark.asyncio
async def test_l2_cache_miss_falls_through():
    engine = _make_engine(
        agents=[_make_agent("agent-a", "ep-1", ["chat"])],
        session_route=None,
    )
    req = RouteRequest(context={"session_id": "sess-123", "operation": "chat"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-1")


# --- L3 Rule ---

@pytest.mark.asyncio
async def test_l3_rule_match():
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={"header.region": "us-east"},
        target_agent_id="agent-a",
        target_instance_id="inst-1",
        target_endpoint_id="ep-1",
        enabled=True,
    )
    engine = _make_engine(agents=[_make_agent("agent-a", "ep-1")], rules=[rule])
    req = RouteRequest()
    headers = {"region": "us-east"}
    result = await engine.resolve(req, headers)
    assert result == ("agent-a", "ep-1")


@pytest.mark.asyncio
async def test_l3_rule_no_endpoint_uses_first():
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={},
        target_agent_id="agent-a",
        target_instance_id="inst-1",
        target_endpoint_id=None,
        enabled=True,
    )
    engine = _make_engine(agents=[_make_agent("agent-a", "ep-first")], rules=[rule])
    req = RouteRequest()
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-first")


# --- L4 Operation Match ---

@pytest.mark.asyncio
async def test_l4_operation_match():
    engine = _make_engine(agents=[
        _make_agent("agent-a", "ep-chat", ["chat"]),
        _make_agent("agent-b", "ep-search", ["search"]),
    ])
    req = RouteRequest(context={"operation": "chat"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-chat")


@pytest.mark.asyncio
async def test_l4_operation_from_options():
    engine = _make_engine(agents=[
        _make_agent("agent-a", "ep-chat", ["chat"]),
    ])
    req = RouteRequest(options={"action": "chat"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-chat")


# --- L5 Default ---

@pytest.mark.asyncio
async def test_l5_default():
    engine = _make_engine(
        agents=[_make_agent("agent-default", "ep-1", ["chat"])],
        default_agent_id="agent-default",
    )
    req = RouteRequest()
    result = await engine.resolve(req, {})
    assert result == ("agent-default", "ep-1")


@pytest.mark.asyncio
async def test_l5_no_default_raises():
    engine = _make_engine()
    req = RouteRequest()
    with pytest.raises(AgentNotFoundError):
        await engine.resolve(req, {})


# --- Pipeline priority ---

@pytest.mark.asyncio
async def test_l1_overrides_l2():
    engine = _make_engine(session_route=("agent-cache", "ep-cache"))
    req = RouteRequest(context={"session_id": "sess-123"})
    headers = {"X-Preferred-Agent": "agent-pref", "X-Preferred-Endpoint": "ep-pref"}
    result = await engine.resolve(req, headers)
    assert result == ("agent-pref", "ep-pref")


@pytest.mark.asyncio
async def test_l2_overrides_l3():
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={},
        target_agent_id="agent-rule",
        target_instance_id="inst-1",
        target_endpoint_id="ep-rule",
        enabled=True,
    )
    engine = _make_engine(
        agents=[_make_agent("agent-rule", "ep-rule")],
        rules=[rule],
        session_route=("agent-cache", "ep-cache"),
    )
    req = RouteRequest(context={"session_id": "sess-123"})
    result = await engine.resolve(req, {})
    assert result == ("agent-cache", "ep-cache")


# --- when_clause evaluator ---

def test_evaluate_when_clause_header_match():
    req = RouteRequest()
    headers = {"region": "us-east"}
    assert _evaluate_when_clause({"header.region": "us-east"}, req, headers) is True
    assert _evaluate_when_clause({"header.region": "us-west"}, req, headers) is False


def test_evaluate_when_clause_context_match():
    req = RouteRequest(context={"tenant": "acme"})
    assert _evaluate_when_clause({"context.tenant": "acme"}, req, {}) is True
    assert _evaluate_when_clause({"context.tenant": "other"}, req, {}) is False
```

### Step 3: 更新 `main.py`

在 `agent_routers/main.py`，`_setup_middleware`：

```python
    app.state.session_manager = SessionManager(settings.REDIS_URL)
    app.state.forwarder = Forwarder(
        agent_repo=AgentRepository(session_factory),
        routing_engine=RoutingDecisionEngine(
            rule_repo=app.state.rule_repo,
            agent_repo=AgentRepository(session_factory),
            session_manager=app.state.session_manager,
            default_agent_id=getattr(settings, "DEFAULT_AGENT_ID", ""),
        ),
        client_pool=get_client_pool(),
        session_manager=app.state.session_manager,
    )
```

### Step 4: 添加 `DEFAULT_AGENT_ID` 到 settings

在 `agent_routers/config/settings.py`：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="forbid", env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_routers"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWKS_URL: str = "https://idp.example.com/.well-known/jwks.json"
    JWT_ISS: str = "https://idp.example.com"
    JWT_AUD: str = "agent-routers"
    AUDIT_HMAC_KEY: str = "change-me-in-production"
    QUOTA_DEFAULT_PER_MINUTE: int = 120
    DRAIN_TIMEOUT_SECONDS: int = 15
    DEFAULT_AGENT_ID: str = ""  # NEW
```

### Step 5: 运行路由测试

```bash
pytest tests/unit/test_routing.py -v
```

### Step 6: Commit

```bash
git add agent_routers/services/routing.py tests/unit/test_routing.py agent_routers/main.py agent_routers/config/settings.py
git commit -m "feat: 5-level routing pipeline (preferred→cache→rule→operation→default)"
```

---

## Task 4: 更新 Forwarder

**文件**：
- 修改：`agent_routers/services/forwarder.py`
- 修改：`agent_routers/api/routes_forward.py`
- 修改：`tests/unit/test_forwarder.py`

### Step 1: 更新 `Forwarder.forward()`

在 `agent_routers/services/forwarder.py`，修改 `forward()` 方法：

```python
    async def forward(
        self,
        request: Request,
        route_req: RouteRequest,
        cancel_event: asyncio.Event | None,
    ) -> Response:
        # 1. 5-level pipeline resolves agent + endpoint
        agent_id, endpoint_id = await self._routing_engine.resolve(
            route_req, dict(request.headers)
        )

        # 2. Fetch agent and endpoint
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' not registered")

        endpoint = None
        for ep in agent.endpoints:
            if ep.endpoint_id == endpoint_id:
                endpoint = ep
                break
        if endpoint is None:
            raise EndpointNotFoundError(f"Endpoint '{endpoint_id}' not found on agent '{agent_id}'")

        # 3. Use first instance's base_url directly (no instance selection)
        if not agent.instances:
            raise AgentUnavailableError(f"Agent '{agent_id}' has no instances")
        base_url = agent.instances[0].base_url

        # 4. Build URL from param_mapping
        req_dict = route_req.model_dump()
        mapping = endpoint.param_mapping
        path_params = {}
        if mapping:
            for key, dot_path in mapping.get("path_params", {}).items():
                val = _extract_value(req_dict, dot_path)
                if val is not None:
                    path_params[key] = str(val)

        query_params = {}
        if mapping:
            for key, dot_path in mapping.get("query_params", {}).items():
                val = _extract_value(req_dict, dot_path)
                if val is not None:
                    query_params[key] = str(val)

        url_path = _build_url(endpoint.path, path_params, query_params)
        full_url = f"{base_url.rstrip('/')}/{url_path.lstrip('/')}"

        # 5. Build body
        body_bytes = b""
        if endpoint.method not in IDEMPOTENT_METHODS and mapping and mapping.get("body"):
            body_value = _extract_value(req_dict, mapping["body"])
            body_bytes = _serialize_body(body_value)

        # 6. Circuit breaker
        key = _circuit_key(agent_id, agent.instances[0].instance_id)
        if await _cb.is_open(key):
            raise AgentUnavailableError(f"Circuit open for {key}")

        client = self._pool.get(agent_id)
        if client is None:
            client = self._pool.create(agent_id, base_url)

        if endpoint.mode == "block":
            return await self._forward_block(
                client, endpoint.method, full_url, dict(request.headers), body_bytes, key,
                endpoint, agent_id, agent.instances[0].instance_id,
            )
        else:
            return await self._forward_stream(
                client, endpoint.method, full_url, dict(request.headers), body_bytes, cancel_event, key,
                endpoint, agent_id, agent.instances[0].instance_id,
            )
```

### Step 2: 更新 `_forward_block` session 提取

```python
        # Extract session_id from response
        session_config = endpoint.session_config
        if session_config and self._session_manager:
            session_id = None
            if session_config.get("response_header"):
                session_id = upstream.headers.get(session_config["response_header"])
            if not session_id and session_config.get("response_body_path"):
                content_type = upstream.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body_json = upstream.json()
                        session_id = _extract_value(body_json, session_config["response_body_path"])
                    except Exception:
                        pass
            if session_id:
                await self._session_manager.set_route(session_id, agent_id, endpoint_id)
```

### Step 3: 更新 `_forward_stream` session 提取

```python
                    # Extract session_id from stream response header
                    session_config = endpoint.session_config
                    if session_config and session_config.get("response_header") and self._session_manager:
                        session_id = upstream.headers.get(session_config["response_header"])
                        if session_id:
                            await self._session_manager.set_route(session_id, agent_id, endpoint_id)
```

### Step 4: 更新 `routes_forward.py`

替换 `agent_routers/api/routes_forward.py`：

```python
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from agent_routers.api.dependencies import get_forwarder
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.coordination import get_registry
from agent_routers.services.forwarder import Forwarder

router = APIRouter(prefix="/v1/route", tags=["route"])


@router.post(
    "",
    summary="Forward request to target Agent endpoint",
)
async def route_request(
    request: Request,
    route_req: RouteRequest,
    forwarder: Forwarder = Depends(get_forwarder),
):
    registry = get_registry()
    request_id = getattr(request.state, "request_id", "")
    async with registry.track(request_id) as cancel_event:
        request.state.cancel_event = cancel_event
        return await forwarder.forward(request, route_req, cancel_event)
```

### Step 5: 运行 forwarder 测试

```bash
pytest tests/unit/test_forwarder.py -v
```

### Step 6: Commit

```bash
git add agent_routers/services/forwarder.py agent_routers/api/routes_forward.py tests/unit/test_forwarder.py
git commit -m "feat: Forwarder uses 5-level pipeline, fixed POST /v1/route"
```

---

## Task 5: 全量测试

### Step 1: 运行所有单元测试

```bash
pytest tests/unit/ -v --tb=short
```

### Step 2: Commit

```bash
git commit -m "test: all tests pass after agent interface standardization" --allow-empty
```

---

## 验证清单

| 检查项 | 状态 |
|--------|------|
| Schema 变更 | ☐ |
| Model 变更 | ☐ |
| Migration 运行 | ☐ |
| SessionManager 简化 | ☐ |
| RoutingDecisionEngine 5级流水线 | ☐ |
| Forwarder 适配 | ☐ |
| 路由接口固定为 `POST /v1/route` | ☐ |
| 单元测试全部通过 | ☐ |

---

## 回滚计划

如需回滚：

```bash
# 回滚 migration
alembic downgrade 004

# 回滚代码
git revert HEAD~4..HEAD
```
