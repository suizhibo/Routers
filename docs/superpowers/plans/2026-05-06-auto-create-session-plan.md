# 智能体自动创建会话实现计划

> **目标**：客户端首次请求无 session_id 时，路由层自动调用 create-session 获取 session_id，然后继续处理原请求。

**范围**：修改 Forwarder 和路由处理逻辑，支持内部自动创建会话。

**技术栈**：FastAPI, Pydantic v2, SQLAlchemy 2.x async, redis-py async, httpx, pytest-asyncio

---

## 设计概览

```
客户端请求（无 session_id）
    │
    ▼
┌─────────────────────────────────────────┐
│ 路由层                                   │
│ 1. 检查 session_id                      │
│    - 有 → 直接路由                       │
│    - 无 → 自动创建流程                   │
│                                         │
│ 2. 自动创建流程：                        │
│    a. 选择 Agent（通过 input 匹配）      │
│    b. 调用 create-session（block HTTP）  │
│    c. 从响应提取 session_id              │
│    d. 缓存 session → agent 映射          │
│    e. 继续处理原请求                     │
└─────────────────────────────────────────┘
    │
    ▼
返回响应（block 或 stream）
```

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `agent_routers/services/forwarder.py` | 添加自动创建会话逻辑 |
| `agent_routers/services/session_manager.py` | 添加按 agent_id 查询 session 的方法 |
| `agent_routers/api/routes_forward.py` | 可能不需要修改 |
| `tests/unit/test_forwarder.py` | 添加自动创建会话测试 |
| `tests/unit/test_auto_session.py` | **新增** 自动创建会话集成测试 |

---

## Task 1: 修改 Forwarder 支持自动创建会话

**文件**：
- 修改：`agent_routers/services/forwarder.py`

### Step 1: 添加自动创建会话方法

在 `Forwarder` 类中添加：

```python
    async def _auto_create_session(
        self,
        request: Request,
        route_req: RouteRequest,
        agent_id: str,
    ) -> str:
        """自动创建会话并返回 session_id"""
        
        # 构建 create-session 请求
        create_req = RouteRequest(
            input=route_req.input,
            context={
                "operation": "session.create",
                **{k: v for k, v in route_req.context.items() if k != "operation"}
            },
            options=route_req.options,
        )
        
        # 调用 create-session 端点
        agent = await self._agent_repo.get_by_id(agent_id)
        if not agent:
            raise AgentNotFoundError(f"Agent '{agent_id}' not found")
        
        endpoint = None
        for ep in agent.endpoints:
            if ep.endpoint_id == "create-session":
                endpoint = ep
                break
        
        if not endpoint:
            raise EndpointNotFoundError(f"Agent '{agent_id}' has no create-session endpoint")
        
        # 构建请求
        req_dict = create_req.model_dump()
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
        base_url = agent.instances[0].base_url
        full_url = f"{base_url.rstrip('/')}/{url_path.lstrip('/')}"
        
        body_bytes = b""
        if endpoint.method not in IDEMPOTENT_METHODS and mapping and mapping.get("body"):
            body_value = _extract_value(req_dict, mapping["body"])
            body_bytes = _serialize_body(body_value)
        
        # 发送请求
        client = self._pool.get(agent_id)
        if client is None:
            client = self._pool.create(agent_id, base_url)
        
        upstream = await client.request(
            endpoint.method, full_url,
            headers=dict(request.headers), content=body_bytes
        )
        upstream.raise_for_status()
        
        # 提取 session_id
        session_id = None
        session_config = endpoint.session_config
        if session_config:
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
        
        if not session_id:
            raise AgentUnavailableError("Failed to extract session_id from create-session response")
        
        # 缓存
        if self._session_manager:
            await self._session_manager.set_route(session_id, agent_id, "chat")
        
        return session_id
```

### Step 2: 修改 forward 方法

```python
    async def forward(
        self,
        request: Request,
        route_req: RouteRequest,
        cancel_event: asyncio.Event | None,
    ) -> Response:
        # 检查是否需要自动创建会话
        session_id = route_req.context.get("session_id")
        operation = route_req.context.get("operation", "chat")
        
        if not session_id and operation != "session.create":
            # 需要自动创建会话
            # 先选择 Agent
            agent_id, _ = await self._routing_engine.resolve(
                route_req, dict(request.headers)
            )
            
            # 自动创建会话
            session_id = await self._auto_create_session(request, route_req, agent_id)
            
            # 更新 route_req
            route_req.context["session_id"] = session_id
        
        # 继续正常转发流程
        agent_id, endpoint_id = await self._routing_engine.resolve(
            route_req, dict(request.headers)
        )
        
        # ... 原有转发逻辑
```

### Step 3: 运行测试

```bash
pytest tests/unit/test_forwarder.py -v
```

### Step 4: Commit

```bash
git add agent_routers/services/forwarder.py
git commit -m "feat: auto-create session when no session_id provided"
```

---

## Task 2: 添加集成测试

**文件**：
- 创建：`tests/unit/test_auto_session.py`

### Step 1: 创建测试文件

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx
from starlette.requests import Request
from starlette.responses import Response

from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.models.agent import Agent, AgentEndpoint, AgentInstance
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.forwarder import Forwarder
from agent_routers.services.routing import RoutingDecisionEngine
from agent_routers.services.session_manager import SessionManager


class FakeAgentRepo:
    def __init__(self, agent: Agent | None):
        self._agent = agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agent

    async def list_all(self) -> list[Agent]:
        return [self._agent] if self._agent else []


class FakeRoutingEngine:
    def __init__(self, result: tuple[str, str]):
        self._result = result

    async def resolve(self, route_req: RouteRequest, headers: dict) -> tuple[str, str]:
        return self._result


def _make_agent_with_create_session() -> Agent:
    agent = Agent(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
    )
    agent.instances = [
        AgentInstance(agent_id="weather-agent", instance_id="inst-1", base_url="http://localhost:8001", weight=1),
    ]
    agent.endpoints = [
        AgentEndpoint(
            agent_id="weather-agent",
            endpoint_id="create-session",
            method="POST",
            path="/sessions",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config={"response_body_path": "data.id"},
            operation_types=["session.create"],
        ),
        AgentEndpoint(
            agent_id="weather-agent",
            endpoint_id="chat",
            method="POST",
            path="/chat/{session_id}",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="stream",
            idempotent=False,
            param_mapping={"path_params": {"session_id": "context.session_id"}},
            session_config=None,
            operation_types=["chat"],
        ),
    ]
    return agent


def _make_request(body: bytes = b"{}") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
        "path": "/v1/route",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request._body = body
    return request


@pytest.fixture
def pool():
    return PerAgentClientPool()


@pytest.mark.asyncio
async def test_auto_create_session_then_chat(pool):
    """测试无 session_id 时自动创建会话并继续 chat"""
    agent = _make_agent_with_create_session()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(("weather-agent", "chat"))
    
    mock_session_mgr = AsyncMock(spec=SessionManager)
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)
    
    # Mock create-session 响应
    create_response = MagicMock(spec=httpx.Response)
    create_response.status_code = 200
    create_response.headers = {"content-type": "application/json"}
    create_response.json = MagicMock(return_value={"data": {"id": "sess-abc123"}})
    create_response.raise_for_status = MagicMock()
    
    # Mock chat 响应（stream）
    async def _aiter_bytes():
        yield b"data: hello\n\n"
    
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=create_response)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    
    pool.create("weather-agent", "http://localhost:8001")
    pool._clients["weather-agent"] = mock_client
    
    # 客户端请求（无 session_id）
    route_req = RouteRequest(
        input="今天天气怎么样？",
        context={"operation": "chat"},
        options={},
    )
    request = _make_request()
    
    response = await fwd.forward(request, route_req, None)
    
    # 验证 create-session 被调用
    assert mock_client.request.called
    
    # 验证 session 被缓存
    mock_session_mgr.set_route.assert_awaited_once_with("sess-abc123", "weather-agent", "chat")
    
    # 验证 chat 被调用（stream）
    assert mock_client.stream.called


@pytest.mark.asyncio
async def test_with_existing_session_id(pool):
    """测试有 session_id 时不自动创建"""
    agent = _make_agent_with_create_session()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(("weather-agent", "chat"))
    
    mock_session_mgr = AsyncMock(spec=SessionManager)
    mock_session_mgr.get_route = AsyncMock(return_value=("weather-agent", "chat"))
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)
    
    async def _aiter_bytes():
        yield b"data: hello\n\n"
    
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    
    pool.create("weather-agent", "http://localhost:8001")
    pool._clients["weather-agent"] = mock_client
    
    # 客户端请求（有 session_id）
    route_req = RouteRequest(
        input="明天呢？",
        context={"session_id": "sess-abc123", "operation": "chat"},
        options={},
    )
    request = _make_request()
    
    response = await fwd.forward(request, route_req, None)
    
    # 验证 create-session 没有被调用
    assert not mock_client.request.called
    
    # 验证 chat 被直接调用
    assert mock_client.stream.called
```

### Step 2: 运行测试

```bash
pytest tests/unit/test_auto_session.py -v
```

### Step 3: Commit

```bash
git add tests/unit/test_auto_session.py
git commit -m "test: add auto-create session integration tests"
```

---

## Task 3: 全量测试验证

### Step 1: 运行所有单元测试

```bash
pytest tests/unit/ -v --tb=short
```

### Step 2: Commit

```bash
git commit -m "test: all tests pass after auto-create session feature" --allow-empty
```

---

## 验证清单

| 检查项 | 状态 |
|--------|------|
| Forwarder 支持自动创建会话 | ☐ |
| 从 create-session 响应提取 session_id | ☐ |
| 自动缓存 session → agent 映射 | ☐ |
| 有 session_id 时跳过自动创建 | ☐ |
| create-session 失败时正确报错 | ☐ |
| 单元测试全部通过 | ☐ |

---

## 回滚计划

如需回滚：

```bash
git revert HEAD~2..HEAD
```
