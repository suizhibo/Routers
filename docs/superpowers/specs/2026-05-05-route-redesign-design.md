# Route 重新设计 — 设计文档

| 项 | 值 |
|----|----|
| 版本 | v0.1 route redesign |
| 日期 | 2026-05-05 |
| 范围 | 路由接口改为 POST-only，引入 param_mapping 和 session 管理 |

---

## 背景

当前 `/v1/route/{agent_id}/{endpoint_id}` 使用 `api_route` 接受所有 HTTP 方法（GET/POST/PUT/PATCH/DELETE），与需求偏离。客户端与 Routers 的会话通信应统一为 POST，由 Routers 内部根据 Agent 注册的 endpoint 信息决定转发方法、路径和参数。

## 目标

1. 路由接口改为 **POST-only**：`/v1/route/{agent_id}/{endpoint_id}`
2. 对外暴露**固定格式的请求体**：`{input, context, options}`
3. Agent 注册时提供 **param_mapping**：定义如何从固定请求体中提取值，构建转发 URL 和 body
4. 支持 **session 管理**：Agent 首次响应返回 session_id，Routers 记录并用于后续粘性路由

---

## §1 对外接口

### 1.1 路由请求

```
POST /v1/route/{agent_id}/{endpoint_id}
Content-Type: application/json

{
  "input": "用户输入内容",
  "context": {
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

---

## §2 Agent 注册 EndpointSpec 变更

Agent 注册时，endpoint 新增 `param_mapping` 和 `session_config`：

```python
class ParamMapping(BaseModel):
    path_params: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class SessionConfig(BaseModel):
    response_header: str | None = None       # 从响应 header 提取 session_id
    response_body_path: str | None = None    # 从 block 响应 body JSON 提取


class EndpointSpec(BaseModel):
    endpoint_id: str
    method: HTTPMethod
    path: str
    path_params: list[ParamSpec]
    query_params: list[ParamSpec]
    body_schema: dict | None
    mode: AgentMode
    idempotent: bool = False
    param_mapping: ParamMapping = Field(default_factory=ParamMapping)
    session_config: SessionConfig | None = None
```

### 2.1 注册示例

```json
{
  "agent_id": "weather-agent",
  "endpoints": [
    {
      "endpoint_id": "forecast",
      "method": "GET",
      "path": "/api/forecast/{city}",
      "mode": "block",
      "param_mapping": {
        "path_params": {"city": "input"},
        "query_params": {},
        "body": null
      },
      "session_config": {
        "response_header": "X-Session-ID"
      }
    }
  ]
}
```

---

## §3 Forwarder 行为

### 3.1 参数提取

从 `RouteRequest.model_dump()` 中用**点号路径**提取值：

```python
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
```

### 3.2 转发 URL 构建

```python
def _build_url(path_template: str, path_params: dict, query_params: dict) -> str:
    url = path_template.format(**path_params)
    if query_params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(query_params)}"
    return url
```

### 3.3 Body 构建

- `endpoint.method` 为 GET/HEAD/OPTIONS → body 为空 bytes
- 否则，按 `param_mapping.body` 提取值：
  - `dict/list` → `json.dumps().encode()`
  - `str` → `.encode("utf-8")`
  - 其他 → `str(value).encode()`

### 3.4 Session 管理

**路由决策中加入 session 层：**

```
session match（如果客户端带了 session_id）
  → preferred header
  → rule match
  → default (weighted random + IP hash)
```

- 第一次请求：客户端 `context.session_id` 为空 → 走默认路由
- Agent 返回 session_id（header 或 body）→ Routers 提取并写入 Redis
- 后续请求：客户端带 `context.session_id` → 查 Redis 得 instance_id → 作为 preferred_instance 传入路由决策

**Session 存储（Redis）：**

```
key: session:{agent_id}:{session_id}
value: {instance_id}
TTL: 86400s (24h)
```

**提取来源：**

| 模式 | header | body |
|------|--------|------|
| block | ✅ | ✅（仅 JSON Content-Type） |
| stream | ✅ | ❌（流式不解析） |

---

## §4 数据库变更

`agent_endpoints` 表新增两列：

```sql
ALTER TABLE agent_endpoints
    ADD COLUMN param_mapping JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN session_config JSONB;
```

---

## §5 错误处理

| 场景 | 状态码 | code |
|------|--------|------|
| path 模板参数缺失 | 400 | `validation_error` |
| param_mapping 引用不存在的字段路径 | 400 | `validation_error` |
| session_id 找不到 | 不报错，走默认路由 | — |
| 下游 5xx / 熔断 open | 502 | `agent_unavailable` |

---

## §6 文件变更清单

| 文件 | 操作 |
|------|------|
| `agent_routers/schemas/agent.py` | 修改：添加 ParamMapping, SessionConfig，更新 EndpointSpec |
| `agent_routers/schemas/route.py` | 新增：RouteRequest |
| `agent_routers/models/agent.py` | 修改：AgentEndpoint 添加 param_mapping, session_config |
| `alembic/versions/004_endpoint_mapping.py` | 新增：migration |
| `agent_routers/services/session_manager.py` | 新增：SessionManager |
| `agent_routers/services/forwarder.py` | 修改：POST-only、param_mapping、session 提取 |
| `agent_routers/api/routes_forward.py` | 修改：POST-only、接收 RouteRequest |
| `agent_routers/main.py` | 修改：注入 SessionManager |
| `tests/unit/test_forwarder.py` | 修改：适配新接口 |
| `tests/unit/test_param_mapping.py` | 新增 |
| `tests/unit/test_session_manager.py` | 新增 |
