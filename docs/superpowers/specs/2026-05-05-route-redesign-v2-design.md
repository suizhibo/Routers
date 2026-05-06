# Route 重新设计 v2 — 设计文档

| 项 | 值 |
|----|----|
| 版本 | v0.2 route redesign |
| 日期 | 2026-05-05 |
| 范围 | 路由接口改为固定 POST 路径，5级流水线选择 agent+endpoint，操作类型匹配，移除 instance 选择 |

---

## 背景

当前 `/v1/route/{agent_id}/{endpoint_id}` 路径携带 `agent_id` 和 `endpoint_id`，客户端需要显式指定目标。需求改为：客户端只发操作类型，路由系统通过5级流水线自动推断 agent 和 endpoint。

## 目标

1. 路由接口改为固定路径：`POST /v1/route`
2. 客户端通过 `context.operation` 传递操作类型（如 `create_session`, `chat`, `terminate_session`）
3. 5级流水线自动选择 agent + endpoint：`preferred → cache → rule → operation match → default`
4. Forwarder 直接转发到 Agent 首个 instance 的 base_url，不选 instance
5. Session 缓存简化为只存 `agent_id:endpoint_id`

---

## §1 对外接口

### 1.1 路由请求

```
POST /v1/route
Content-Type: application/json

{
  "input": "用户输入内容",
  "context": {
    "operation": "chat",
    "session_id": "abc123"
  },
  "options": {
    "temperature": 0.7
  }
}
```

### 1.2 固定请求体模型

```python
class RouteRequest(BaseModel):
    input: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
```

操作类型从 `context.operation` 或 `options.action` 中提取，优先 `context.operation`。

---

## §2 Agent 注册 EndpointSpec 变更

Agent 注册时，endpoint 新增 `operation_types`：

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
    operation_types: list[str] = Field(default_factory=list)  # 新增
    param_mapping: ParamMapping = Field(default_factory=ParamMapping)
    session_config: SessionConfig | None = None
```

### 2.1 注册示例

```json
{
  "agent_id": "assistant-agent",
  "name": "Assistant Agent",
  "subject": "svc-assistant",
  "instances": [
    {"instance_id": "i1", "base_url": "https://assistant-svc:8080", "weight": 1}
  ],
  "endpoints": [
    {
      "endpoint_id": "create_session",
      "operation_types": ["create_session"],
      "method": "POST",
      "path": "/api/session",
      "mode": "block",
      "param_mapping": {"body": "input"},
      "session_config": {"response_header": "X-Session-ID"}
    },
    {
      "endpoint_id": "chat",
      "operation_types": ["chat"],
      "method": "POST",
      "path": "/api/chat/{session_id}",
      "mode": "stream",
      "param_mapping": {
        "path_params": {"session_id": "context.session_id"},
        "body": "input"
      }
    },
    {
      "endpoint_id": "terminate_session",
      "operation_types": ["terminate_session"],
      "method": "DELETE",
      "path": "/api/session/{session_id}",
      "mode": "block",
      "param_mapping": {
        "path_params": {"session_id": "context.session_id"}
      }
    }
  ]
}
```

---

## §3 5级流水线

```
L1 Preferred → L2 Cache → L3 Rule → L4 Operation Match → L5 Default
```

每级要么返回 `(agent_id, endpoint_id)`，要么返回 `None` 进入下一级。

### L1: Preferred Header

输入：`X-Preferred-Agent` + `X-Preferred-Endpoint` headers

```python
agent_id = headers.get("X-Preferred-Agent")
endpoint_id = headers.get("X-Preferred-Endpoint")
if agent_id and endpoint_id:
    return (agent_id, endpoint_id)
```

### L2: Session Cache

输入：`context.session_id`

```python
session_id = _extract_value(req_dict, "context.session_id")
if session_id:
    cached = await redis.get(f"session:{session_id}")
    if cached:
        agent_id, endpoint_id = cached.split(":", 1)
        return (agent_id, endpoint_id)
```

Session 存储格式：
```
key: session:{session_id}
value: {agent_id}:{endpoint_id}
TTL: 86400s (24h)
```

### L3: Rule Match

输入：`RouteRequest` + headers，评估 `when_clause`

```python
rules = await rule_repo.list_enabled()
for rule in rules:
    if _evaluate_when_clause(rule.when_clause, route_req, headers):
        endpoint_id = rule.target_endpoint_id
        if not endpoint_id:
            # 规则未指定 endpoint，取 agent 的第一个 endpoint
            agent = await agent_repo.get_by_id(rule.target_agent_id)
            endpoint_id = agent.endpoints[0].endpoint_id
        return (rule.target_agent_id, endpoint_id)
```

### L4: Operation Type Match

输入：`context.operation`

```python
operation = _extract_value(req_dict, "context.operation")
if not operation:
    operation = _extract_value(req_dict, "options.action")

agents = await agent_repo.list_all()
for agent in agents:
    for ep in agent.endpoints:
        if operation in ep.operation_types:
            return (agent.agent_id, ep.endpoint_id)
```

### L5: Default

输入：配置项 `DEFAULT_AGENT_ID`

```python
default_agent_id = settings.DEFAULT_AGENT_ID
agent = await agent_repo.get_by_id(default_agent_id)
if agent and agent.endpoints:
    return (default_agent_id, agent.endpoints[0].endpoint_id)
```

---

## §4 RoutingDecisionEngine 接口

```python
class RoutingDecisionEngine:
    def __init__(
        self,
        rule_repo: RuleRepository,
        agent_repo: AgentRepository,
        session_manager: SessionManager,
        settings: Settings,
    ):
        ...

    async def resolve(
        self,
        route_req: RouteRequest,
        headers: dict[str, str],
    ) -> tuple[str, str]:
        """5级流水线，返回 (agent_id, endpoint_id)"""
        ...
```

---

## §5 Forwarder 行为

### 5.1 转发流程

```python
async def forward(
    self,
    request: Request,
    route_req: RouteRequest,
    cancel_event: asyncio.Event | None,
) -> Response:
    # 1. 5级流水线决策
    agent_id, endpoint_id = await self._routing_engine.resolve(
        route_req, dict(request.headers)
    )

    # 2. 查 Agent/Endpoint
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

    # 3. 直接取首个 instance 的 base_url
    if not agent.instances:
        raise AgentUnavailableError(f"Agent '{agent_id}' has no instances")
    base_url = agent.instances[0].base_url

    # 4. param_mapping 构建 URL + Body
    req_dict = route_req.model_dump()
    mapping = endpoint.param_mapping

    path_params = {}
    if mapping:
        for key, dot_path in mapping.path_params.items():
            val = _extract_value(req_dict, dot_path)
            if val is not None:
                path_params[key] = str(val)

    query_params = {}
    if mapping:
        for key, dot_path in mapping.query_params.items():
            val = _extract_value(req_dict, dot_path)
            if val is not None:
                query_params[key] = str(val)

    url = _build_url(endpoint.path, path_params, query_params)
    full_url = f"{base_url.rstrip('/')}/{url.lstrip('/')}"

    body_bytes = b""
    if endpoint.method not in IDEMPOTENT_METHODS and mapping and mapping.body:
        body_value = _extract_value(req_dict, mapping.body)
        body_bytes = _serialize_body(body_value)

    # 5. 透明转发
    client = self._pool.get(agent_id)
    if client is None:
        client = self._pool.create(agent_id, base_url)

    if endpoint.mode == "block":
        return await self._forward_block(
            client, endpoint.method, full_url, dict(request.headers), body_bytes,
            endpoint, agent_id,
        )
    else:
        return await self._forward_stream(
            client, endpoint.method, full_url, dict(request.headers), body_bytes, cancel_event,
            endpoint, agent_id,
        )
```

### 5.2 移除内容

- `InstanceTarget` dataclass
- X-Preferred-Instance header 处理
- weighted random + IP hash
- session instance 缓存（session 只存 agent:endpoint）

---

## §6 数据库变更

### 6.1 agent_endpoints 表

```sql
ALTER TABLE agent_endpoints
    ADD COLUMN operation_types JSONB NOT NULL DEFAULT '[]';
```

### 6.2 routing_rules 表

```sql
ALTER TABLE routing_rules
    ADD COLUMN target_endpoint_id TEXT;
```

---

## §7 错误处理

| 场景 | 状态码 | code |
|------|--------|------|
| 5级流水线未命中 | 404 | `agent_not_found` |
| L4 Operation 未匹配 | 404 | `endpoint_not_found` |
| Agent 已注销 | 404 | `agent_not_found` |
| path 模板参数缺失 | 400 | `validation_error` |
| 下游 5xx / 熔断 open | 502 | `agent_unavailable` |
| session_id 找不到 | 不报错，走 L3→L4→L5 | — |

---

## §8 文件变更清单

| 文件 | 操作 | 变更 |
|------|------|------|
| `agent_routers/schemas/agent.py` | 修改 | `EndpointSpec` 新增 `operation_types` |
| `agent_routers/models/agent.py` | 修改 | `AgentEndpoint` 新增 `operation_types` JSONB 列 |
| `agent_routers/models/rule.py` | 修改 | `RoutingRule` 新增 `target_endpoint_id` |
| `alembic/versions/005_operation_types.py` | 新增 | migration |
| `agent_routers/services/routing.py` | 重写 | `resolve()` 实现5级流水线，移除 `select_instance()` |
| `agent_routers/services/forwarder.py` | 修改 | 移除 instance 选择，直接用 `agent.instances[0].base_url` |
| `agent_routers/api/routes_forward.py` | 修改 | 路径改为 `POST /v1/route`，移除 path params |
| `agent_routers/config/settings.py` | 修改 | 新增 `DEFAULT_AGENT_ID` |
| `tests/unit/test_routing.py` | 重写 | 测试5级流水线 |
| `tests/unit/test_forwarder.py` | 修改 | 适配新接口 |
