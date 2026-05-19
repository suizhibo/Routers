# AgentRouters 中台对外接口与 Agent 对接协议

## 一、中台对外接口

### 1.1 基础信息

| 项目 | 说明 |
|------|------|
| **Base URL** | `http://<host>:8000` |
| **认证方式** | JWT Bearer Token (`Authorization: Bearer <token>`) |
| **Token 算法** | 当前实现使用 `JWT_ALGORITHM` 配置，默认 `HS256`，密钥为 `JWT_SECRET` |
| **Content-Type** | `application/json` |
| **公共路径**（免认证） | `/health`, `/readiness`, `/docs`, `/openapi.json` |
| **请求 ID** | 可传入 `X-Request-ID`；未传入时中台自动生成，并在响应头返回 |

### 1.2 JWT Token 要求

中台通过 `JWTAuthMiddleware` 验证所有请求（公共路径除外）。Token 需包含以下 Claims：

| Claim | 说明 |
|-------|------|
| `sub` | 用户/Agent 主体标识，Agent 注册时的 `subject` 必须与此匹配 |
| `role` | 可选。值为 `"admin"` 时可访问管理接口（`/v1/rules`, `/v1/audit`） |

> 当前实现只校验 Token 签名和算法，不校验 `iss` / `aud`。

### 1.3 接口清单

---

#### 1.3.1 健康检查

##### `GET /health`
存活探针，始终返回 200。

**响应**：
```http
HTTP/1.1 200 OK
```

##### `GET /readiness`
就绪探针（当前为占位实现，始终返回 200）。

**响应**：
```http
HTTP/1.1 200 OK
```

---

#### 1.3.2 Agent 管理（`/v1/agents`）

##### `POST /v1/agents` — 注册 Agent

注册一个新 Agent 到路由中台。注册后中台会为该 Agent 创建一个专用的 aiohttp 客户端会话。

**认证**：需要 JWT Token，且 `sub` 必须与请求体中的 `subject` 匹配。

**重复注册限制**：当前接口不支持覆盖式重新注册；相同 `agent_id` 应先注销后再注册。若 `agent_id` 已存在且 `subject` 不同，返回 `409 agent_conflict`。

**请求体** (`AgentRegistration`)：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | string | 是 | Agent 唯一标识，1-255 字符 |
| `name` | string | 是 | Agent 名称，1-255 字符 |
| `subject` | string | 是 | JWT subject，1-255 字符，全局唯一 |
| `base_url` | string | 是 | Agent 服务基础 URL，1-2048 字符 |
| `capability` | string | 否 | Agent 能力标签 |
| `description` | string | 否 | Agent 描述 |
| `auth_header` | string | 否 | 向 Agent 转发请求时附加的认证 Header 名称 |
| `auth_token` | string | 否 | 向 Agent 转发请求时附加的认证 Token 值 |
| `endpoints` | `EndpointSpec[]` | 是 | Agent 暴露的端点列表，至少 1 个 |

**`EndpointSpec` 结构**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `endpoint_type` | string | 是 | 端点类型：`"chat"`、`"create_session"`、`"stop"` 等 |
| `method` | enum | 是 | HTTP 方法：`GET`、`POST`、`PUT`、`PATCH`、`DELETE` |
| `path` | string | 是 | 路径模板，如 `/chat/{session_id}`，1-2048 字符 |
| `path_params` | `ParamSpec[]` | 否 | 路径参数定义，默认 `[]` |
| `query_params` | `ParamSpec[]` | 否 | 查询参数定义，默认 `[]` |
| `body_schema` | object | 否 | JSON Schema 描述请求体结构 |
| `mode` | enum | 是 | 模式：`"block"`（同步）或 `"stream"`（SSE 流式） |
| `idempotent` | boolean | 否 | 是否幂等，默认 `false` |
| `param_mapping` | `ParamMapping` | 否 | 参数映射规则 |
| `session_config` | `SessionConfig` | 否 | 会话提取配置（仅 `create_session` 端点需要） |

**`ParamMapping` 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `path_params` | `dict<string, string>` | 路径参数映射，key=目标参数名，value=`RouteRequest` 中的 dot path |
| `query_params` | `dict<string, string>` | 查询参数映射，格式同上 |
| `body` | string \| dict \| null | body 映射规则：string 表示单值提取路径；dict 表示多字段映射 |

**`SessionConfig` 结构**（用于自动提取 session_id）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `response_header` | string \| null | 从响应 Header 中提取 session_id 的 Header 名称 |
| `response_body_path` | string \| null | 从响应 JSON Body 中提取 session_id 的 dot path |

**请求示例**：
```json
{
  "agent_id": "chatbot-v1",
  "name": "智能客服",
  "subject": "service-account-chatbot",
  "base_url": "http://chatbot-service:8080",
  "capability": "customer_service",
  "auth_header": "X-API-Key",
  "auth_token": "sk-abc123",
  "endpoints": [
    {
      "endpoint_type": "chat",
      "method": "POST",
      "path": "/api/v1/chat/{session_id}",
      "mode": "stream",
      "param_mapping": {
        "path_params": {"session_id": "context.session_id"},
        "body": {"message": "input", "metadata": "context"}
      }
    },
    {
      "endpoint_type": "create_session",
      "method": "POST",
      "path": "/api/v1/sessions",
      "mode": "block",
      "param_mapping": {
        "body": {"initial_message": "input"}
      },
      "session_config": {
        "response_body_path": "data.session_id"
      }
    }
  ]
}
```

**响应** (`201 Created`)：
```json
{
  "agent_id": "chatbot-v1",
  "name": "智能客服",
  "created_at": "2024-01-15T08:30:00"
}
```

**错误码**：
- `409` — Agent 已存在且 subject 不匹配（`agent_conflict`）
- `401` — Subject 不匹配（`auth_invalid`）
- `400` — 请求体校验失败（`validation_error`）

---

##### `GET /v1/agents` — 列出所有 Agent

**认证**：需要 JWT Token

**响应** (`200 OK`) — `AgentListItem[]`：
```json
[
  {
    "agent_id": "chatbot-v1",
    "name": "智能客服",
    "subject": "service-account-chatbot",
    "capability": "customer_service",
    "description": null,
    "auth_header": "X-API-Key",
    "created_at": "2024-01-15T08:30:00"
  }
]
```

---

##### `GET /v1/agents/{agent_id}` — 获取 Agent 详情

**认证**：需要 JWT Token

**响应** (`200 OK`) — `AgentDetail`：
```json
{
  "agent_id": "chatbot-v1",
  "name": "智能客服",
  "subject": "service-account-chatbot",
  "base_url": "http://chatbot-service:8080",
  "capability": "customer_service",
  "description": null,
  "auth_header": "X-API-Key",
  "auth_token": "***",
  "endpoints": [...],
  "created_at": "2024-01-15T08:30:00",
  "updated_at": "2024-01-15T08:30:00"
}
```

**错误码**：
- `404` — Agent 不存在（`agent_not_found`）

---

##### `DELETE /v1/agents/{agent_id}` — 注销 Agent

注销 Agent 并释放其 HTTP 连接池。

**认证**：需要 JWT Token。非 admin 用户只能注销 `subject` 与自己匹配的 Agent。

**响应**：`204 No Content`

**错误码**：
- `404` — Agent 不存在
- `403` — 无权注销（`forbidden`）

---

#### 1.3.3 请求路由（`/v1/route`）

##### `POST /v1/route` — 转发请求到目标 Agent

中台核心接口。根据路由策略选择目标 Agent，构建上游请求并转发。

**认证**：需要 JWT Token

**请求体** (`RouteRequest`)：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input` | string | 否 | 用户输入内容 |
| `context` | object | 否 | 上下文数据，可包含 `session_id` 等 |
| `options` | object | 否 | 可选参数 |

字段默认值：
- `input`: `""`
- `context`: `{}`
- `options`: `{}`

**请求示例**：
```json
{
  "input": "你好，我想查询订单",
  "context": {
    "session_id": "sess-123",
    "user_id": "u-456"
  },
  "options": {
    "temperature": 0.7
  }
}
```

**响应**：

- **Block 模式**：返回 Agent 上游响应的 status、body 和 headers（过滤掉 hop-by-hop headers），并附加 `X-Preferred-Agent` 与 `X-Session-Id`。
- **Stream 模式**：返回 `text/event-stream`，响应头包含：
  - `X-Preferred-Agent`: 目标 Agent ID
  - `X-Session-Id`: 会话 ID

**错误码**：
- `404` — Agent 未找到（`agent_not_found`）
- `404` — Endpoint 未找到（`endpoint_not_found`）
- `502` — Agent 不可用 / 熔断器开启（`agent_unavailable`）
- `504` — Agent 读取或建会话超时（`agent_timeout`）
- `429` — 配额超限（`quota_exceeded`）
- `503` — 配额服务不可用（`dependency_unavailable`）

---

#### 1.3.4 路由规则管理（`/v1/rules`）— Admin Only

所有接口需要 `role == "admin"`。

##### `GET /v1/rules` — 列出所有启用的规则

**响应** (`200 OK`) — `RoutingRuleDetail[]`：
```json
[
  {
    "rule_id": "rule-001",
    "priority": 1,
    "when_clause": {"header.X-Channel": "wechat", "context.user_type": "vip"},
    "target_agent_id": "chatbot-vip",
    "target_capability": null,
    "target_endpoint_type": null,
    "target_instance_id": "default",
    "enabled": true,
    "created_at": "2024-01-15T08:30:00"
  }
]
```

---

##### `POST /v1/rules` — 创建规则

**请求体** (`RoutingRuleCreate`)：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rule_id` | string | 是 | 规则唯一标识 |
| `priority` | int | 是 | 优先级（数字越小越优先） |
| `when_clause` | object | 是 | 匹配条件，见下方说明 |
| `target_agent_id` | string | 否 | 目标 Agent ID |
| `target_capability` | string | 否 | 目标 Agent 能力（按 capability 匹配） |
| `target_endpoint_type` | string | 否 | 目标端点类型 |
| `target_instance_id` | string | 否 | 目标实例 ID，默认 `"default"` |
| `enabled` | boolean | 否 | 是否启用，默认 `true` |

**`when_clause` 匹配规则**：

条件 Key 支持以下前缀：

| 前缀 | 示例 | 匹配来源 |
|------|------|----------|
| `header.` | `header.X-Channel` | HTTP 请求 Header（大小写不敏感） |
| `context.` | `context.session_id` | `RouteRequest.context` |
| `options.` | `options.temperature` | `RouteRequest.options` |
| `input` | `input` | `RouteRequest.input` |
| 无前缀 | `user_type` | `RouteRequest` 顶层字段 |

所有条件为 **AND** 关系，必须全部匹配规则才生效。

**请求示例**：
```json
{
  "rule_id": "rule-vip",
  "priority": 1,
  "when_clause": {
    "header.X-User-Type": "vip",
    "context.channel": "app"
  },
  "target_agent_id": "chatbot-vip",
  "enabled": true
}
```

**响应** (`201 Created`)：
```json
{
  "rule_id": "rule-vip",
  "priority": 1,
  "when_clause": {"header.X-User-Type": "vip", "context.channel": "app"},
  "target_agent_id": "chatbot-vip",
  "target_capability": null,
  "target_endpoint_type": null,
  "target_instance_id": "default",
  "enabled": true,
  "created_at": "2024-01-15T08:30:00"
}
```

---

##### `GET /v1/rules/{rule_id}` — 获取规则详情

**响应** (`200 OK`)：`RoutingRuleDetail`

**错误码**：
- `404` — 规则不存在

---

##### `DELETE /v1/rules/{rule_id}` — 删除规则

**响应**：`204 No Content`

**错误码**：
- `404` — 规则不存在

---

#### 1.3.5 审计日志（`/v1/audit`）— Admin Only

##### `GET /v1/audit/{request_id}` — 获取审计事件

**认证**：需要 JWT Token，且 `role == "admin"`

**响应** (`200 OK`)：
```json
{
  "request_id": "req-abc123",
  "timestamp": "2024-01-15T08:30:00",
  "user_subject": "user-001",
  "agent_id": "chatbot-v1",
  "instance_id": "",
  "method": "POST",
  "status_code": 200,
  "latency_ms": 145,
  "signature": "hmac-sha256-signature"
}
```

**错误码**：
- `403` — 非 admin 用户
- `404` — 审计事件不存在

---

#### 1.3.6 请求取消（`/v1/requests`）

##### `POST /v1/requests/{request_id}/cancel` — 取消正在执行的请求

取消一个正在进行的请求，主要用于流式转发。通过 Redis Pub/Sub 广播到所有中台实例。

**认证**：需要 JWT Token
**权限**：仅请求创建者或 admin 可操作。非 admin 场景下，中台优先查询活动请求表；若未找到，再查询审计记录中的 `user_subject`。

**响应** (`202 Accepted`)：
```json
{
  "status": "accepted",
  "request_id": "req-abc123",
  "cancelled": true
}
```

**错误码**：
- `404` — 请求不存在
- `403` — 无权取消

---

## 二、Agent 对接协议

### 2.1 概述

Agent 是中台路由的下游服务。Agent 需要：

1. **注册到中台**：通过 `POST /v1/agents` 提供元数据和端点规范。
2. **暴露标准端点**：必须实现 `chat` 端点；需要无会话自动建会话能力时，还必须实现 `create_session` 端点。
3. **接受中台转发**：中台通过 HTTP 将用户请求转发到 Agent，Agent 处理后将响应回传给中台。

### 2.2 Agent 必须实现的端点

#### 2.2.1 `chat` 端点（必需）

处理用户对话请求。这是中台转发用户请求时固定使用的端点类型。

**端点规范示例**：
```json
{
  "endpoint_type": "chat",
  "method": "POST",
  "path": "/api/v1/chat/{session_id}",
  "mode": "stream",
  "param_mapping": {
    "path_params": {"session_id": "context.session_id"},
    "query_params": {},
    "body": {"message": "input", "metadata": "context"}
  }
}
```

**中台转发行为**：
- 构建 URL：将 `base_url` + `path` 模板填充后拼接。
- 构建 Body：根据 `param_mapping.body` 从 `RouteRequest` 提取字段。如果 `body` 是 dict，则逐字段映射；如果是 string，则提取单值。
- Body 默认值：如果 `body_schema` 中定义了 `properties` 且包含 `default`，缺失字段会自动注入默认值。
- 转发 Headers：原始请求 Headers（过滤 hop-by-hop headers）+ Agent 自有的 `auth_header`/`auth_token`。

**Agent 应实现的响应**：

| `mode` | Agent 响应要求 |
|--------|---------------|
| `block` | 标准 HTTP 响应，中台直接透传 status/body/headers |
| `stream` | SSE 流（`text/event-stream`），中台以 `StreamingResponse` 透传。每收到一个 chunk 会检查 `cancel_event` |

**流式响应 Headers**（中台会附加到 SSE 响应）：
- `X-Preferred-Agent`: Agent ID
- `X-Session-Id`: 当前会话 ID

---

#### 2.2.2 `create_session` 端点（按需必需）

当用户请求中未携带 `session_id` 时，中台自动调用该端点创建新会话。

如果中台路由到的 Agent 没有配置 `create_session` 端点，且 `RouteRequest.context.session_id` 为空，请求会失败并返回 `404 endpoint_not_found`。

**端点规范示例**：
```json
{
  "endpoint_type": "create_session",
  "method": "POST",
  "path": "/api/v1/sessions",
  "mode": "block",
  "param_mapping": {
    "body": {"initial_message": "input"}
  },
  "session_config": {
    "response_header": "X-Session-Id",
    "response_body_path": "data.session_id"
  }
}
```

**Agent 响应要求**：

Agent 必须能在响应中返回 `session_id`，中台按以下优先级提取：

1. **Header 提取**：如果配置了 `session_config.response_header`，中台从响应 Header 中读取对应字段。
2. **Body 提取**：如果配置了 `session_config.response_body_path`，中台解析 JSON 响应，按 dot path 提取。

**示例响应（Header 方式）**：
```http
HTTP/1.1 201 Created
X-Session-Id: sess-abc123
Content-Type: application/json

{"status": "created"}
```

**示例响应（Body 方式）**：
```http
HTTP/1.1 201 Created
Content-Type: application/json

{
  "data": {
    "session_id": "sess-abc123",
    "created_at": "2024-01-15T08:30:00"
  }
}
```

提取成功后，中台将 `session:{session_id} = {agent_id}` 写入 Redis（TTL 24 小时）。后续同 `session_id` 的请求将直接路由到该 Agent（L2 缓存）。

---

#### 2.2.3 `stop` 端点（可选）

用于终止生成。当前中台路由逻辑中未主动调用，但可预留。

---

### 2.3 参数映射协议

中台通过 `param_mapping` 将 `RouteRequest` 映射到 Agent 上游请求。映射使用 **dot path** 语法。

#### Dot Path 规则

| Dot Path | 来源 | 示例值 |
|----------|------|--------|
| `input` | `RouteRequest.input` | `"你好"` |
| `context.xxx` | `RouteRequest.context[xxx]` | `"sess-123"` |
| `options.xxx` | `RouteRequest.options[xxx]` | `0.7` |
| `$` | 整个 `RouteRequest` 对象 | — |

#### 映射示例

**`RouteRequest`**：
```json
{
  "input": "你好",
  "context": {"session_id": "sess-123", "user_id": "u-456"},
  "options": {"temperature": 0.7}
}
```

**`param_mapping`**：
```json
{
  "path_params": {"session_id": "context.session_id"},
  "query_params": {"user_id": "context.user_id"},
  "body": {
    "message": "input",
    "session_id": "context.session_id",
    "config": "options"
  }
}
```

**生成的上游请求**：
```http
POST /api/v1/chat/sess-123?user_id=u-456
Content-Type: application/json

{
  "message": "你好",
  "session_id": "sess-123",
  "config": {"temperature": 0.7}
}
```

#### Body 默认值注入

如果 `EndpointSpec.body_schema` 定义了 `type: object` 和 `properties`，且某些字段有 `default`，中台会在 body 构建后自动注入缺失字段的默认值：

```json
{
  "body_schema": {
    "type": "object",
    "properties": {
      "temperature": {"type": "number", "default": 0.5},
      "max_tokens": {"type": "integer", "default": 2048}
    }
  }
}
```

如果映射后的 body 不包含 `temperature`，中台会自动添加 `"temperature": 0.5`。

---

### 2.4 Agent 认证协议

Agent 可选择是否启用认证。注册时通过以下字段配置：

| 字段 | 说明 |
|------|------|
| `auth_header` | 认证 Header 的名称，如 `"Authorization"`、`"X-API-Key"` |
| `auth_token` | 认证 Token 值 |

**中台转发行为**：
- 每次向 Agent 转发请求时，中台会将 `auth_header: auth_token` 附加到上游请求 Headers 中。
- 该 Header 是在过滤 hop-by-hop headers **之后** 添加的，不会与原始客户端 Headers 冲突（如有冲突则覆盖）。
- `auth_token` 在 Agent 详情查询时返回 `"***"` 脱敏。

---

### 2.5 流式响应协议

当 `mode == "stream"` 时，Agent 应返回 SSE 流式响应。

**中台行为**：
1. 向 Agent 发送请求，使用 `client.request()` 获取响应流。
2. 通过 `upstream.content.iter_any()` 逐 chunk 读取。
3. 每收到一个 chunk，检查 `cancel_event.is_set()`。如果已取消，停止读取并断开连接。
4. 将 chunk 通过 `StreamingResponse` 返回给客户端，`media_type="text/event-stream"`。
5. 流式请求无固定读取超时；连接超时时间为 2 秒。

**Agent 实现建议**：
- 使用 `Content-Type: text/event-stream`
- 按 SSE 格式输出（`data: {...}\n\n`）
- 中台会在 chunk 级别透传，不做格式解析

---

### 2.6 熔断与重试协议

#### 重试策略（仅 Block 模式）

- 中台对 Block 模式的 `chat` 请求自动重试：
  - 最多 3 次尝试
  - 指数退避，随机因子，最大 1 秒
  - 仅对 5xx HTTP 错误重试
  - 如果收到 `CancelledError`，立即停止重试

#### 熔断器

- 基于 `purgatory` 库，按 `agent_id:session_id` 维度隔离
- 阈值：5 次失败开启熔断
- 恢复时间：60 秒
- 熔断开启后，中台直接返回 `502 agent_unavailable`，不再向 Agent 发请求

**Agent 建议**：
- 非业务错误（如超时、内部异常）返回 5xx，触发中台重试
- 业务错误（如参数非法）返回 4xx，中台不重试

---

### 2.7 取消协议

Agent 的流式响应可能被客户端取消。取消流程：

1. 客户端调用 `POST /v1/requests/{request_id}/cancel`
2. 中台在本地 `CancellationRegistry` 中标记该 `request_id` 为取消状态
3. 如果当前中台实例不持有该请求，通过 Redis Pub/Sub 广播到所有实例
4. 持有该请求的中台实例在读取下一个 SSE chunk 前检测到 `cancel_event.is_set()`，停止读取并断开与 Agent 的连接

**Agent 侧注意事项**：
- 中台断开连接时，Agent 会收到 TCP 连接关闭或 asyncio `CancelledError`
- Agent 应妥善处理连接中断，避免资源泄漏

---

### 2.8 错误码对照表

中台定义的统一错误码，Agent 可参考以返回恰当的 HTTP Status：

| 错误码 | HTTP Status | 含义 | 触发场景 |
|--------|-------------|------|----------|
| `agent_not_found` | 404 | Agent 未注册 | 路由无法找到目标 Agent |
| `endpoint_not_found` | 404 | 端点未定义 | Agent 未配置 `chat` 端点 |
| `agent_unavailable` | 502 | Agent 不可用 | 熔断器开启或 session 创建失败 |
| `agent_timeout` | 504 | Agent 超时 | 上游读取超时或创建 session 时连接超时 |
| `agent_conflict` | 409 | Agent 冲突 | 注册时 ID 已存在且 subject 不同 |
| `auth_invalid` | 401 | 认证失败 | JWT 验证失败或缺失 Token |
| `forbidden` | 403 | 权限不足 | 非 admin 访问管理接口 |
| `validation_error` | 400 | 参数校验失败 | 请求体不符合 Schema |
| `quota_exceeded` | 429 | 配额超限 | Redis 滑动窗口限流触发 |
| `dependency_unavailable` | 503 | 依赖不可用 | Redis 配额检查失败 |
| `internal_error` | 500 | 内部错误 | 未捕获的异常 |

---

### 2.9 完整 Agent 注册示例

```json
{
  "agent_id": "customer-service-bot",
  "name": "智能客服机器人",
  "subject": "svc-customer-service",
  "base_url": "https://agent.example.com",
  "capability": "customer_service",
  "description": "处理客户咨询和订单查询",
  "auth_header": "Authorization",
  "auth_token": "Bearer agent-secret-token",
  "endpoints": [
    {
      "endpoint_type": "create_session",
      "method": "POST",
      "path": "/v1/sessions",
      "mode": "block",
      "idempotent": false,
      "param_mapping": {
        "body": {"user_message": "input", "user_context": "context"}
      },
      "session_config": {
        "response_body_path": "session_id"
      }
    },
    {
      "endpoint_type": "chat",
      "method": "POST",
      "path": "/v1/sessions/{session_id}/messages",
      "mode": "stream",
      "idempotent": false,
      "param_mapping": {
        "path_params": {"session_id": "context.session_id"},
        "body": {
          "content": "input",
          "metadata": "context",
          "settings": "options"
        }
      },
      "body_schema": {
        "type": "object",
        "properties": {
          "temperature": {"type": "number", "default": 0.7},
          "max_tokens": {"type": "integer", "default": 4096}
        }
      }
    }
  ]
}
```

---

## 三、附录：Hop-by-Hop Headers 过滤列表

中台转发请求时会过滤以下 Headers，Agent 不会收到：

```
content-length
content-encoding
transfer-encoding
connection
keep-alive
upgrade
proxy-authenticate
proxy-authorization
te
trailers
host
```

---

*Last updated: 2026-05-19*
