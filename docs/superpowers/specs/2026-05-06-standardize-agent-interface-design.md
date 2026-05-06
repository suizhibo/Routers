# 智能体标准化接口设计

| 项 | 值 |
|----|----|
| 版本 | v1.0 |
| 日期 | 2026-05-06 |
| 范围 | 定义所有智能体的标准3端点接口，简化路由规则，统一生命周期管理 |

---

## 背景

当前系统支持多智能体，但每个智能体的端点定义不统一。为了简化客户端调用和路由配置，需要标准化所有智能体的接口：每个智能体必须实现 **3个标准端点**（创建会话、会话通信、终止会话）。

## 目标

1. **标准化接口**：每个智能体必须实现 `create-session`、`chat`、`stop` 三个端点
2. **简化路由**：通过 `context.operation` 自动匹配端点，无需复杂规则
3. **自动会话管理**：路由层自动处理 session_id 的创建和缓存
4. **统一生命周期**：创建 → 通信 → 终止，三个标准步骤

---

## §1 智能体标准接口规范

### 1.1 三个标准端点

```
┌─────────────────────────────────────────────────────────────┐
│                    智能体标准接口规范                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. create-session    POST /sessions                        │
│     ├── 模式: block                                         │
│     ├── 输入: {title?, description?}                        │
│     └── 输出: {session_id, ...}                             │
│         └── session_config.response_body_path = "data.id"   │
│                                                             │
│  2. chat             POST /chat/{session_id}                │
│     ├── 模式: stream (SSE)                                  │
│     ├── 输入: {query, ...}                                  │
│     └── 输出: SSE 流                                        │
│                                                             │
│  3. stop             POST /stop/{session_id}                │
│     ├── 模式: block                                         │
│     ├── 输入: {message_id?}                                 │
│     └── 输出: {success}                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 端点详细定义

#### create-session

```json
{
  "endpoint_id": "create-session",
  "method": "POST",
  "path": "/sessions",
  "mode": "block",
  "operation_types": ["session.create"],
  "session_config": {
    "response_body_path": "data.id"
  }
}
```

**行为**：
- 接收可选的 `title` 和 `description`
- 返回包含 `session_id` 的响应
- 路由层自动从响应中提取 `session_id` 并缓存到 Redis

#### chat

```json
{
  "endpoint_id": "chat",
  "method": "POST",
  "path": "/chat/{session_id}",
  "mode": "stream",
  "operation_types": ["chat"],
  "param_mapping": {
    "path_params": {
      "session_id": "context.session_id"
    }
  }
}
```

**行为**：
- 必须包含 `session_id`（从 path param 注入）
- 返回 SSE 流式响应
- 支持客户端终止（通过 cancel_event）

#### stop

```json
{
  "endpoint_id": "stop",
  "method": "POST",
  "path": "/stop/{session_id}",
  "mode": "block",
  "operation_types": ["session.stop"],
  "param_mapping": {
    "path_params": {
      "session_id": "context.session_id"
    }
  }
}
```

**行为**：
- 终止指定会话的生成任务
- 可选传入 `message_id` 指定要停止的消息

---

## §2 路由流程

### 2.1 标准调用流程

```
客户端请求
    │
    ├── 无 session_id ──→ 路由到 create-session ──→ 获取 session_id
    │                                                    │
    │                                                    ▼
    │                                            存储到 Redis Cache
    │                                            (session:{id} → agent:endpoint)
    │                                                    │
    └── 有 session_id ───────────────────────────────────┘
                              │
                              ▼
                    L2 Cache 命中
                    (直接路由到 chat 端点)
                              │
                              ▼
                    SSE 流式转发
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
              正常完成            客户端终止
                    │                   │
                    ▼                   ▼
              等待下一条消息      调用 stop 端点
```

### 2.2 路由决策流程

```python
# L1: Preferred Header（手动指定）
X-Preferred-Agent + X-Preferred-Endpoint

# L2: Session Cache（自动）
if context.session_id:
    cached = redis.get(f"session:{session_id}")
    if cached:
        return cached  # (agent_id, endpoint_id)

# L3: Operation Match（自动）
operation = context.operation  # "session.create" / "chat" / "session.stop"
for agent in agents:
    for ep in agent.endpoints:
        if operation in ep.operation_types:
            return (agent.agent_id, ep.endpoint_id)

# L4: Default Agent
return (default_agent_id, default_endpoint_id)
```

---

## §3 客户端调用示例

### 3.1 创建会话

```bash
curl -X POST 'http://router:8000/v1/route' \
  -H 'Content-Type: application/json' \
  -H 'X-Preferred-Agent: intelligent-qa-agent' \
  -d '{
    "input": "创建会话",
    "context": {
      "operation": "session.create"
    },
    "options": {
      "title": "新知识库问答"
    }
  }'
```

**响应**：
```json
{
  "success": true,
  "data": {
    "id": "ceb9babb-1e30-41d7-817d-fd584954304b",
    "title": "新知识库问答",
    "created_at": "2026-03-27T12:26:19.611616+08:00"
  }
}
```

**路由层自动处理**：
- 从 `data.id` 提取 `session_id`
- 存储到 Redis：`session:ceb9babb-... = intelligent-qa-agent:chat`

### 3.2 会话通信

```bash
curl -X POST 'http://router:8000/v1/route' \
  -H 'Content-Type: application/json' \
  -d '{
    "input": "彗尾的形状",
    "context": {
      "session_id": "ceb9babb-1e30-41d7-817d-fd584954304b",
      "operation": "chat"
    },
    "options": {
      "knowledge_base_ids": ["kb-00000001"]
    }
  }'
```

**路由层自动处理**：
1. L2 Cache 命中：`session:ceb9babb-...` → `intelligent-qa-agent:chat`
2. 直接转发到 `/chat/ceb9babb-1e30-41d7-817d-fd584954304b`

### 3.3 终止会话

```bash
curl -X POST 'http://router:8000/v1/route' \
  -H 'Content-Type: application/json' \
  -d '{
    "input": "停止生成",
    "context": {
      "session_id": "ceb9babb-1e30-41d7-817d-fd584954304b",
      "operation": "session.stop"
    },
    "options": {
      "message_id": "ebbf7e53-dfe6-44d5-882f-36a4104910b5"
    }
  }'
```

---

## §4 智能体注册示例

### 4.1 智能问答智能体

```json
{
  "agent_id": "intelligent-qa-agent",
  "name": "智能问答智能体",
  "subject": "intelligent-qa-service",
  "instances": [
    {
      "instance_id": "qa-instance-001",
      "base_url": "http://localhost:8080/api/v1",
      "weight": 1
    }
  ],
  "endpoints": [
    {
      "endpoint_id": "create-session",
      "method": "POST",
      "path": "/sessions",
      "path_params": [],
      "query_params": [],
      "body_schema": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "description": {"type": "string"}
        }
      },
      "mode": "block",
      "idempotent": false,
      "operation_types": ["session.create"],
      "param_mapping": {
        "path_params": {},
        "query_params": {},
        "body": null
      },
      "session_config": {
        "response_header": null,
        "response_body_path": "data.id"
      }
    },
    {
      "endpoint_id": "chat",
      "method": "POST",
      "path": "/chat/{session_id}",
      "path_params": [
        {
          "name": "session_id",
          "type": "string",
          "required": true
        }
      ],
      "query_params": [],
      "body_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "knowledge_base_ids": {"type": "array", "items": {"type": "string"}},
          "knowledge_ids": {"type": "array", "items": {"type": "string"}},
          "agent_id": {"type": "string"},
          "summary_model_id": {"type": "string"},
          "mentioned_items": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "type": {"type": "string", "enum": ["kb", "file"]},
                "kb_type": {"type": "string", "enum": ["document", "faq"]}
              }
            }
          },
          "disable_title": {"type": "boolean"},
          "enable_memory": {"type": "boolean"},
          "images": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "data": {"type": "string"}
              }
            }
          },
          "channel": {"type": "string", "enum": ["web", "api", "im", "browser_extension"]}
        },
        "required": ["query"]
      },
      "mode": "stream",
      "idempotent": false,
      "operation_types": ["chat"],
      "param_mapping": {
        "path_params": {
          "session_id": "context.session_id"
        },
        "query_params": {},
        "body": null
      },
      "session_config": null
    },
    {
      "endpoint_id": "stop",
      "method": "POST",
      "path": "/stop/{session_id}",
      "path_params": [
        {
          "name": "session_id",
          "type": "string",
          "required": true
        }
      ],
      "query_params": [],
      "body_schema": {
        "type": "object",
        "properties": {
          "message_id": {"type": "string"}
        }
      },
      "mode": "block",
      "idempotent": false,
      "operation_types": ["session.stop"],
      "param_mapping": {
        "path_params": {
          "session_id": "context.session_id"
        },
        "query_params": {},
        "body": null
      },
      "session_config": null
    }
  ]
}
```

### 4.2 代码生成智能体

```json
{
  "agent_id": "code-gen-agent",
  "name": "代码生成智能体",
  "subject": "code-gen-service",
  "instances": [
    {
      "instance_id": "code-instance-001",
      "base_url": "http://localhost:8090/api/v1",
      "weight": 1
    }
  ],
  "endpoints": [
    {
      "endpoint_id": "create-session",
      "method": "POST",
      "path": "/sessions",
      "mode": "block",
      "operation_types": ["session.create"],
      "session_config": {
        "response_body_path": "data.id"
      }
    },
    {
      "endpoint_id": "chat",
      "method": "POST",
      "path": "/chat/{session_id}",
      "mode": "stream",
      "operation_types": ["chat"],
      "param_mapping": {
        "path_params": {
          "session_id": "context.session_id"
        }
      }
    },
    {
      "endpoint_id": "stop",
      "method": "POST",
      "path": "/stop/{session_id}",
      "mode": "block",
      "operation_types": ["session.stop"],
      "param_mapping": {
        "path_params": {
          "session_id": "context.session_id"
        }
      }
    }
  ]
}
```

---

## §5 路由规则（通用）

```json
[
  {
    "rule_id": "route-by-operation-create",
    "priority": 100,
    "when_clause": {
      "context.operation": "session.create"
    },
    "target_agent_id": null,
    "target_instance_id": null,
    "target_endpoint_id": "create-session",
    "enabled": true
  },
  {
    "rule_id": "route-by-operation-chat",
    "priority": 90,
    "when_clause": {
      "context.operation": "chat"
    },
    "target_agent_id": null,
    "target_instance_id": null,
    "target_endpoint_id": "chat",
    "enabled": true
  },
  {
    "rule_id": "route-by-operation-stop",
    "priority": 80,
    "when_clause": {
      "context.operation": "session.stop"
    },
    "target_agent_id": null,
    "target_instance_id": null,
    "target_endpoint_id": "stop",
    "enabled": true
  }
]
```

**说明**：
- `target_agent_id` 为 `null` 时，通过 L4 Operation Match 自动匹配智能体
- `target_endpoint_id` 固定为三个标准端点之一
- 优先级：`create` > `chat` > `stop`

---

## §6 关键设计点

| 设计点 | 说明 |
|--------|------|
| **标准化端点** | 所有智能体必须实现 `create-session`, `chat`, `stop` 三个端点 |
| **session_id 提取** | `create-session` 配置 `session_config.response_body_path = "data.id"`，自动提取并缓存 |
| **L2 缓存路由** | 有 `session_id` 的请求直接通过 Redis 缓存路由，无需规则匹配 |
| **operation 路由** | 无 `session_id` 时通过 `context.operation` 匹配端点 |
| **X-Preferred-Agent** | 创建会话时通过 Header 指定智能体，后续通过 session_id 自动路由 |
| **自动会话管理** | 路由层自动处理 session 创建、缓存、注入 |

### 6.1 新增智能体步骤

1. 实现三个标准端点（`create-session`, `chat`, `stop`）
2. 注册 Agent，配置 `operation_types`
3. 无需新增路由规则（通用规则已覆盖）

### 6.2 客户端调用简化

**之前**：
- 需要知道 agent_id、endpoint_id
- 需要手动管理 session_id
- 需要调用多个不同路径

**之后**：
- 首次调用指定 `X-Preferred-Agent` 和 `operation: session.create`
- 后续调用只传 `session_id` 和 `operation: chat`
- 统一路径 `POST /v1/route`

---

## §7 文件变更清单

| 文件 | 操作 | 变更 |
|------|------|------|
| `agent_routers/schemas/agent.py` | 修改 | `EndpointSpec` 新增 `operation_types` |
| `agent_routers/models/agent.py` | 修改 | `AgentEndpoint` 新增 `operation_types` JSONB 列 |
| `agent_routers/models/rule.py` | 修改 | `RoutingRule` 新增 `target_endpoint_id` |
| `alembic/versions/005_operation_types.py` | 新增 | migration |
| `agent_routers/services/routing.py` | 重写 | `resolve()` 实现5级流水线，支持 operation match |
| `agent_routers/services/forwarder.py` | 修改 | session 提取逻辑适配新 SessionManager |
| `agent_routers/services/session_manager.py` | 修改 | 简化存储格式为 `agent_id:endpoint_id` |
| `agent_routers/api/routes_forward.py` | 修改 | 路径改为 `POST /v1/route`，移除 path params |
| `agent_routers/config/settings.py` | 修改 | 新增 `DEFAULT_AGENT_ID` |
| `tests/unit/test_routing.py` | 重写 | 测试5级流水线 |
| `tests/unit/test_forwarder.py` | 修改 | 适配新接口 |
| `tests/unit/test_session_manager.py` | 修改 | 适配简化存储 |

---

## §8 错误处理

| 场景 | 状态码 | code | 说明 |
|------|--------|------|------|
| 无 session_id 且 operation 未匹配 | 404 | `agent_not_found` | 未找到可处理该操作的智能体 |
| Agent 已注销 | 404 | `agent_not_found` | 智能体不存在 |
| Endpoint 不存在 | 404 | `endpoint_not_found` | 智能体没有该端点 |
| path 模板参数缺失 | 400 | `validation_error` | 缺少必要的 path param |
| 下游 5xx / 熔断 open | 502 | `agent_unavailable` | 智能体不可用 |
| session_id 找不到 | 不报错，走 L3→L4→L5 | — | 缓存未命中，继续规则匹配 |

---

## §9 后续扩展

### 9.1 智能体发现

未来可支持智能体自动注册和发现：
- 智能体启动时自动向路由注册
- 健康检查自动注销不可用智能体
- 客户端通过 `/v1/agents` 查询可用智能体列表

### 9.2 会话持久化

当前 session 只存储在 Redis，未来可：
- 持久化到数据库
- 支持会话恢复
- 支持跨实例会话迁移

### 9.3 多模态支持

标准接口可扩展支持：
- 图片上传（当前已有 `images` 字段）
- 文件上传
- 语音输入/输出
