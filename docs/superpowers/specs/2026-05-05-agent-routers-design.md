# AgentRouters · 顶层骨架设计文档

| 项 | 值 |
|----|----|
| 版本 | v0.1 MVP 设计骨架 |
| 日期 | 2026-05-05 |
| 范围 | 顶层模块/接口/职责边界(不含内部实现细节) |
| 对齐图 | `agent-routers-architecture.html`(4 层) |

---

## 概览

AgentRouters 是面向**团队内多 Agent 协作**场景的 HTTP 路由网关。前端把请求发给 Routers,Routers 完成认证、路由决策、转发到目标 Agent、审计与签名。多实例 Docker 部署,Redis 做跨实例协调。

### 设计原则

1. **透明转发**:不做协议适配,只做路由 + 转发(block↔block,SSE↔SSE),形态不匹配 → 400
2. **JWT-only**:Routers 不签发任何凭证,所有身份外部化到 User Service;Agent 也是 service account
3. **失败隔离**:每 Agent 独立连接池/熔断,一个 Agent 故障不影响其他
4. **可审计**:v0.1 审计入 PG + HMAC-SHA256 签名;结构化日志/指标/Tracing 推 v0.x
5. **YAGNI**:LLM Judge、协议适配、一致性 hash 等推到 v0.x;骨架预留扩展点

---

## §1 范围与角色

### 1.1 v0.1 In Scope

- 多 Agent 注册与发现
- 基于规则的路由决策(preferred → rule → default)
- HTTP 转发(block 与 SSE)
- JWT 鉴权(JWKS 验签) + 滑窗配额
- 请求级取消(creator 或 admin),跨实例
- 审计入库 + HMAC-SHA256 签名

### 1.2 v0.x Out of Scope

- LLM Judge 路由决策
- structlog / Prometheus / OpenTelemetry 全套观测
- 协议适配(block↔SSE 互转)
- 一致性 hash(v0.1 用 weighted random + IP hash)
- 全局熔断器状态共享

### 1.3 角色

| 角色 | 描述 | 凭证 |
|------|------|------|
| Client App | 前端,发起业务请求 | JWT(User) |
| Admin | 运维:管理路由规则、查看审计、强制取消 | JWT(role=admin) |
| Agent | 业务后端,自注册到 Routers | JWT(service account) |
| User Service | 外部身份服务,签发 JWT,持有 Agent service account | — |

---

## §2 架构总览

### 2.1 四层结构(对齐架构图)

```
┌─────────────────────────────────────────────────────────────┐
│ Inbound 接入层                                              │
│   FastAPI Router → JWT Auth → Quota                         │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Core 业务层                                                 │
│   Routing Decision → Registry(查询)                        │
│   → Forwarder(透明转发)→ Coordination(跨实例取消)        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Cross-cutting 横切层                                        │
│   Audit + HMAC / Retry / Timeout / Circuit Breaker / Log    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Infra 基础层                                                │
│   PostgreSQL / Redis(配额 + 取消通道)/ JWKS Client        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 代码布局(Hexagonal-lite)

```
agent_routers/
├── api/             # FastAPI 路由器、请求/响应模型
├── domain/          # 实体、值对象(Agent / Endpoint / Request)
├── services/        # 应用服务(routing / registry / forwarder / coordination)
├── adapters/        # PG / Redis / JWKS / HTTP 客户端
├── middleware/      # 鉴权 / 配额 / 审计 / RequestID
├── obs/             # 日志(v0.1 仅 stdlib logging)
├── config/          # 配置加载(Pydantic Settings)
└── main.py          # FastAPI app + lifespan
```

### 2.3 技术栈

| 类别 | 选型 | 备注 |
|------|------|------|
| 语言 | Python 3.12 | |
| 框架 | FastAPI 0.110+ | |
| 模型 | Pydantic v2 | 仅注册/管理 API 用,转发不解析 |
| ORM | SQLAlchemy 2.x async | 配 asyncpg |
| 迁移 | alembic | |
| Redis | redis-py 5.x async | |
| HTTP 客户端 | httpx AsyncClient | 每 Agent 一个 client |
| 重试 | tenacity | |
| 熔断 | purgatory | 进程内 |
| 测试 | pytest + pytest-asyncio + testcontainers | |
| 质检 | ruff + mypy --strict | |
| 运行时 | uvicorn + uvloop | Linux 部署 |

---

## §3 Inbound 接入层

### 3.1 API 接口清单

| 路径 | 方法 | 用途 | 鉴权 |
|------|------|------|------|
| `POST /v1/agents` | POST | Agent 注册/重注册 | JWT(Agent service account,sub=subject) |
| `GET /v1/agents` | GET | 列表查询 | JWT(User/Admin) |
| `GET /v1/agents/{agent_id}` | GET | 详情 | JWT(User/Admin) |
| `DELETE /v1/agents/{agent_id}` | DELETE | 注销 | JWT(Agent self / Admin) |
| `* /v1/route/{agent_id}/{endpoint_id}` | * | 转发到目标 Agent endpoint | JWT(User) |
| `POST /v1/requests/{request_id}/cancel` | POST | 取消请求 | JWT(creator 或 Admin) |
| `GET /v1/audit/{request_id}` | GET | 审计查询 | JWT(Admin) |
| `GET /v1/rules` / `POST /v1/rules` / ... | CRUD | 路由规则管理 | JWT(Admin) |
| `GET /health` | GET | liveness | 无 |
| `GET /readiness` | GET | readiness(检 PG / Redis / JWKS) | 无 |

### 3.2 endpoint_id 的 URL 形式

URL 用**逻辑解耦**形式:`/v1/route/{agent_id}/{endpoint_id}`,而非透传 Agent 的实际 path。

- 优势:Agent 内部改 path 不影响前端
- 实际转发 path 由 Registry 中 endpoint.path 决定
- path/query 参数沿用客户端原始请求
- **method 校验**:客户端发起的 HTTP method 必须与注册的 `endpoint.method` 一致;不一致 → 405 `method_not_allowed`

### 3.3 中间件链路

```
Request
  ↓ [1] CORS
  ↓ [2] RequestID 注入(contextvars)
  ↓ [3] JWT 鉴权(JWKS 验签)
  ↓ [4] 配额(Redis ZSET 滑窗)
  ↓ [5] 审计起点(注册 request_id 到 CancellationRegistry)
  ↓ [6] Handler(Core 业务层)
  ↓ [7] 审计终点(异步 fire-and-forget 写 PG)
Response
```

约束:
- [3]/[4] 失败 → 立即返回,不进 [5]
- [7] 失败 → 仅日志,不影响响应
- [5] `track()` 必须 `@asynccontextmanager` 保证异常路径释放

---

## §4 Core 业务层

### 4.1 Routing Decision

**输入**:解析后的请求(method/path/headers/JWT claims) + URL 解析的 (agent_id, endpoint_id)。

**决策流水线**:

```
preferred(请求 header X-Preferred-Instance)
  → rule(数据库规则匹配,按 priority 降序)
  → default(weighted random + IP hash)
```

**Rule 模型**:

```python
class RoutingRule(BaseModel):
    rule_id: str
    priority: int                       # 高优先级先匹配
    when: dict[str, Any]                # {"header.region": "us-east", ...}
    target: tuple[str, str]             # (agent_id, instance_id)
    enabled: bool
```

**默认实例选择**(加权 + IP 粘性的组合算法):

```python
def select_instance(instances: list[InstanceInfo], client_ip: str | None) -> InstanceInfo:
    weights = [i.weight for i in instances]
    total = sum(weights)
    if client_ip:
        # 同一 IP 永远落到同一 instance,但 instances 间按 weight 分布
        target = hash(client_ip) % total
        cum = 0
        for inst, w in zip(instances, weights):
            cum += w
            if target < cum:
                return inst
    # 退化:无 client_ip → 加权随机
    return random.choices(instances, weights=weights)[0]
```

这是一个简化版的"加权 hash 环",同 IP 稳定到同实例,实现会话粘性的同时尊重 weight。

**v0.x 扩展点**:LLM Judge 作为 rule 之后第 4 层,通过插件接口注入。

### 4.2 Agent Registry

**注册 body(自定义 JSON,非 OpenAPI)**:

```python
class AgentRegistration(BaseModel):
    agent_id: str
    name: str
    subject: str                        # 必须等于 JWT 'sub'
    instances: list[InstanceInfo]
    endpoints: list[EndpointSpec]

class InstanceInfo(BaseModel):
    instance_id: str
    base_url: AnyHttpUrl
    weight: int = 1                     # weighted random 用

class EndpointSpec(BaseModel):
    endpoint_id: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str                           # 实际转发 path
    path_params: list[ParamSpec]
    query_params: list[ParamSpec]
    body_schema: dict | None            # JSONSchema 仅记录,Routers 不强校验
    mode: Literal["block", "stream"]
    idempotent: bool                    # 信任边界声明(见下)

class ParamSpec(BaseModel):
    name: str
    type: Literal["string", "int", "bool", "float"]
    required: bool
```

**信任边界(P0 #6)**:
- `idempotent` 由 Agent 自报,Routers 据此决定是否重试
- v0.1 接受信任(团队内场景),但 §4.3 用**保守重试策略**降低误声明影响
- Registry 必须记录每次声明的 endpoint(审计/日志)

**Subject 一致性**:
- 注册时 `subject` 字段必须等于 JWT `sub`,否则 401
- 重注册(同 agent_id)需通过同一 subject

**冲突**:同 `agent_id` 但不同 `subject` → 409 `agent_conflict`

### 4.3 Forwarder

**职责**:接收路由决策结果,把客户端请求**透明转发**到 (agent, instance, endpoint)。

#### 客户端策略(P0 #3)

**每 Agent 一个独立 `httpx.AsyncClient`**,带各自的连接池。**不全局共享**,避免 head-of-line blocking。

```python
httpx.Limits(
    max_connections=50,
    max_keepalive_connections=20,
    keepalive_expiry=60.0,
)
httpx.Timeout(
    connect=2.0, read=30.0, write=10.0, pool=5.0,
)
```

- 客户端在 lifespan startup 实例化,shutdown 关闭
- Agent 注册 / 注销 → 创建 / 销毁对应 client

#### 透明转发(P1 A)

**转发请求体绝对不走 Pydantic**:

```python
# ✅ 转发路径
body_bytes = await request.body()
upstream = await client.request(method, url, headers=hdrs, content=body_bytes)

# ❌ 禁止
async def forward(request: Request, body: SomeBodyModel): ...
```

仅注册/管理 API 用 Pydantic。

#### Block 模式

```python
upstream = await client.request(method, url, headers=hdrs, content=body_bytes)
return Response(
    content=upstream.content,
    status_code=upstream.status_code,
    headers=upstream.headers,
)
```

#### Stream 模式(SSE)

```python
async with client.stream(method, url, headers=hdrs, content=body_bytes) as up:
    async def gen() -> AsyncIterator[bytes]:
        async for chunk in up.aiter_bytes():
            if cancel_event.is_set():     # O(1) 内存检查
                break
            yield chunk
    return StreamingResponse(gen(), media_type="text/event-stream")
```

**SSE 取消中断点(P0 #2)**:
- **仅检查 `cancel_event.is_set()`**(本地 / Pub/Sub 唤醒)
- **不**主动调用 `request.is_disconnected()`(代价高;客户端断开依赖 httpx 的 `CancelledError` 自然传播)

#### Form 不匹配处理

Agent 声明 `mode=block` 但下游返回 SSE,或反之 → **400 `protocol_mismatch`**,不做形态适配。

#### 重试策略(P0 #6)

| Method | 默认重试 | 上限 | 退避 |
|--------|---------|------|------|
| GET / HEAD / OPTIONS | 是 | 3 | 指数退避 100ms~1s |
| POST / PUT / PATCH / DELETE | **仅当 `idempotent=true`** | **1 次** | 200ms 固定 |
| 任意 method,5xx 之外的网络错误 | 同上规则 | 同上 | 同上 |

- 使用 tenacity,`wait_random_exponential` / `wait_fixed`
- **重试期间收到 cancel → 立即抛 `CancelledError`,不再重试**(P1 E)

#### 熔断器

- `purgatory`,**进程内作用域**
- Per-(agent_id, instance_id) 维度
- 阈值:60s 内连续 5 次 5xx → open;60s 后 half-open
- v0.x 改 Redis 共享状态(§10 风险)

### 4.4 Coordination(跨实例取消)

#### 两个组件

```python
class CancellationRegistry:
    """实例本地的 in-flight 请求登记,提供 asyncio.Event。"""
    @asynccontextmanager
    async def track(self, request_id: str) -> AsyncIterator[asyncio.Event]:
        event = asyncio.Event()
        self._events[request_id] = event
        try:
            yield event
        finally:
            self._events.pop(request_id, None)
    
    def cancel_local(self, request_id: str) -> bool:
        if event := self._events.get(request_id):
            event.set()
            return True
        return False


class CancellationBroadcaster:
    """Pub/Sub 广播 + Redis key 兜底。"""
    async def cancel(self, request_id: str) -> None:
        # 1. PUBLISH router:cancel <request_id>
        # 2. SET cancel:{request_id}=1 EX 30  (Pub/Sub 丢消息时的兜底)
        ...
    
    async def listen(self) -> None:
        # 后台任务:订阅 channel,收到 → registry.cancel_local()
        ...
```

#### 取消语义(P0 #1) — best-effort

- Redis Pub/Sub 是 **at-most-once**:订阅者重连期间消息会丢
- 兜底:Forwarder 在每个 chunk 边界**额外**轮询 `cancel:{request_id}` key(轻量 GET)
- 客户端不能假设 `202 Accepted` = 一定取消成功;**可重复发送**

#### 取消触发路径

```
POST /v1/requests/{request_id}/cancel
  → 鉴权(creator 或 admin)
  → broadcaster.cancel(request_id)
  → 所有实例的 listen task 收到 → registry.cancel_local()
  → 对应 in-flight 的 cancel_event.set()
  → Forwarder 流读循环退出
  → 释放 httpx stream + 客户端连接
```

#### 取消权限

- creator:JWT `sub` 等于审计记录里的 `user_subject`
- 或 JWT 含 `role=admin`
- 都不满足 → 403 `forbidden`

---

## §5 Cross-cutting 横切层

### 5.1 鉴权(JWT + JWKS)

**库**:`PyJWT.PyJWKClient`

**配置**:
- JWKS URL:从 config 注入
- 缓存 TTL:**10 分钟**
- 验签 401 → **强制刷新一次 JWKS 再验**(应对密钥轮换),再失败才真返回 401
- IDP 不可达 → 使用过期 cache + ERROR 日志(failure isolation)

**Claims 校验**:
- `iss`、`aud`、`exp`、`iat`(允许 ±60s clock skew)
- `sub`(用户/Agent 主体)
- `role`(可选,admin 权限判定)

**Agent 与 User**:Routers 不区分,统一看 JWT。Agent service account 的 `sub` 与注册时的 `subject` 一致。

### 5.2 配额

**算法**:Redis ZSET 滑动窗口

**Lua 脚本(原子)**:
- key = `quota:{subject}`,滑窗 60s,上限 N(配置)
- `ZREMRANGEBYSCORE` 清旧 → `ZCARD` 计数 → 超限返回 -1 → 否则 `ZADD` 当前 ts → `EXPIRE`

**Redis 故障行为**:**fail-closed**(团队内偏好正确性)。Redis 不可达 → 503 `dependency_unavailable`。

**Lua 加载**:`SCRIPT LOAD` + SHA → `EVALSHA`;NOSCRIPT 时回退 `EVAL`。

**v0.x**:支持 fail-open + 阈值告警。

### 5.3 审计 + HMAC 签名

#### 写入策略(P0 #4) — 异步 fire-and-forget

```python
async def audit_middleware(request, call_next):
    response = await call_next(request)
    event = build_audit_event(request, response)
    task = asyncio.create_task(_safe_write_audit(event))
    audit_task_set.add(task)             # 追踪用于 graceful drain
    task.add_done_callback(audit_task_set.discard)
    return response

async def _safe_write_audit(event: AuditEvent) -> None:
    try:
        async with audit_sessionmaker() as session:   # 独立 session,与请求 session 解耦
            await audit_repo.insert(session, event)
    except Exception:
        logger.exception("audit_write_failed", extra={"request_id": event.request_id})
```

要点:
- **追踪**:所有 fire-and-forget task 加入 `audit_task_set`,shutdown 阶段 `gather` 等待
- **独立 DB session**:审计写入用单独的 sessionmaker,不复用请求级 session(请求 session 已随响应关闭)
- **独立异常处理**:`_safe_write_audit` 必须捕获并记录,绝不向 task scheduler 抛出未处理异常

理由:审计是观测性,不是业务正确性。失败 SLO 告警 + 日志可追,不阻塞主请求。

**风险接受**:进程崩溃丢 in-flight 审计 → 通过 graceful shutdown gather + 监控 in-flight 任务数缓解(§5.6 / §10)。

#### 事件字段

```python
class AuditEvent(BaseModel):
    request_id: str
    timestamp: datetime
    user_subject: str
    agent_id: str
    endpoint_id: str
    instance_id: str
    method: str
    status_code: int
    latency_ms: int
    request_headers_digest: str        # SHA-256 摘要,不存原 headers
    response_headers_digest: str
    signature: str                      # HMAC-SHA256
```

#### 签名算法

- 算法:HMAC-SHA256
- 密钥:环境变量 `AUDIT_HMAC_KEY` 注入,人工轮换
- 验证:`hmac.compare_digest`(防时序攻击)
- canonical 字段:`{request_id}|{timestamp_iso}|{user_subject}|{agent_id}|{endpoint_id}|{status_code}|{latency_ms}`

**v0.x**:KMS 管理 + 双密钥并行轮换。

### 5.4 重试 / 超时 / 熔断

集中策略见 §4.3。本节仅强调横切边界:
- 重试 / 超时由 Forwarder 应用,不渗透到上层中间件
- 熔断 open 时直接返回 502 `agent_unavailable`,不消耗下游连接

### 5.5 日志(v0.1 stdlib)

- stdlib `logging` + 自定义 JSON formatter
- `request_id` 通过 `contextvars.ContextVar` 注入
- 自定义 `Filter` 把 contextvar 写入 `LogRecord`
- 输出到 stdout(由容器收集)
- v0.x → 升级到 structlog

### 5.6 Graceful Shutdown(P1 B)

FastAPI `lifespan` 关停顺序:

1. 切换"拒绝新请求"模式(中间件检测 shutdown flag → 直接返回 503),保留已进入的请求
2. 触发 `CancellationRegistry` 中所有 in-flight 的 cancel event(让流式响应自然结束)
3. 等待 `drain_timeout=15s`,期间:
   - 等待请求处理完成
   - `await asyncio.gather(*audit_task_set, return_exceptions=True)` 排空审计 fire-and-forget 任务
4. 关闭所有 per-Agent httpx clients
5. 取消 Pub/Sub 后台 listen task
6. 关闭 PG engine + Redis 连接

**部署侧**:Docker `stop_grace_period: 30s`(compose)/ `terminationGracePeriodSeconds: 30`(k8s)。

### 5.7 健康检查(P1 G)

| 路径 | 检查项 | 失败响应 |
|------|--------|----------|
| `/health` | 进程活着 | 200(永远) |
| `/readiness` | PG / Redis / JWKS 可达 | 503 |

`/health` 不绑依赖,避免 Redis 抖动 → k8s 重启全 pod → 雪崩。

---

## §6 Infra 基础层

### 6.1 PostgreSQL

- **连接**:asyncpg,SQLAlchemy 2.x async engine
- **直连**(v0.1 不上 PgBouncer)
- **预留 PgBouncer 兼容**(P1 F):`statement_cache_size` 配置项,未来切 transaction pool 不改代码
- **连接池**:`pool_size = max_concurrent_request × 1.2`,`max_overflow = pool_size × 0.5`
- **session 范式**:per-request `AsyncSession`,`expire_on_commit=False`,短事务
- **迁移**:alembic,版本号入库

### 6.2 Redis

| 用途 | 数据结构 | Key |
|------|---------|-----|
| 配额滑窗 | ZSET | `quota:{subject}` |
| 取消兜底 | STRING(EX 30s) | `cancel:{request_id}` |
| 取消通道 | Pub/Sub | channel `router:cancel` |

**连接**:redis-py 5.x async,带连接池

**Pub/Sub 启动**:
- lifespan startup → 后台 task 订阅 `router:cancel`
- 收到消息 → `CancellationRegistry.cancel_local()`
- 重连:指数退避,断开期间消息**会丢**(at-most-once)→ 由 §4.4 兜底 key 缓解

### 6.3 JWKS

- 见 §5.1
- 实例级缓存,无需 Redis

### 6.4 部署形态

- 至少 **2 实例**,前置 LB(Nginx / k8s Service)
- 共享同一 PG + Redis
- 实例间通过 Redis Pub/Sub 协调取消

### 6.5 配置(关键 env)

| Key | 含义 |
|-----|------|
| `DATABASE_URL` | PG 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `JWKS_URL` | IDP 的 JWKS endpoint |
| `JWT_ISS` | 期望 iss |
| `JWT_AUD` | 期望 aud |
| `AUDIT_HMAC_KEY` | 审计签名密钥 |
| `QUOTA_DEFAULT_PER_MINUTE` | 默认配额 |
| `DRAIN_TIMEOUT_SECONDS` | shutdown 排空超时(默 15) |

---

## §7 数据模型

### 7.1 PG 表

```sql
-- agents
CREATE TABLE agents (
    agent_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    subject    TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- agent_instances
CREATE TABLE agent_instances (
    agent_id    TEXT REFERENCES agents(agent_id) ON DELETE CASCADE,
    instance_id TEXT,
    base_url    TEXT NOT NULL,
    weight      INT  DEFAULT 1,
    PRIMARY KEY (agent_id, instance_id)
);

-- agent_endpoints
CREATE TABLE agent_endpoints (
    agent_id      TEXT REFERENCES agents(agent_id) ON DELETE CASCADE,
    endpoint_id   TEXT,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    path_params   JSONB NOT NULL DEFAULT '[]',
    query_params  JSONB NOT NULL DEFAULT '[]',
    body_schema   JSONB,
    mode          TEXT NOT NULL CHECK (mode IN ('block','stream')),
    idempotent    BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (agent_id, endpoint_id)
);

-- routing_rules
CREATE TABLE routing_rules (
    rule_id            TEXT PRIMARY KEY,
    priority           INT NOT NULL,
    when_clause        JSONB NOT NULL,
    target_agent_id    TEXT NOT NULL,
    target_instance_id TEXT NOT NULL,
    enabled            BOOLEAN DEFAULT TRUE,
    created_at         TIMESTAMPTZ DEFAULT now()
);

-- audit_events
CREATE TABLE audit_events (
    request_id              TEXT PRIMARY KEY,
    timestamp               TIMESTAMPTZ NOT NULL,
    user_subject            TEXT NOT NULL,
    agent_id                TEXT,
    endpoint_id             TEXT,
    instance_id             TEXT,
    method                  TEXT,
    status_code             INT,
    latency_ms              INT,
    request_headers_digest  TEXT,
    response_headers_digest TEXT,
    signature               TEXT NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_audit_user_time  ON audit_events(user_subject, timestamp DESC);
CREATE INDEX idx_audit_agent_time ON audit_events(agent_id, timestamp DESC);
```

### 7.2 Redis Keys 概览

| Key / Channel | 类型 | TTL | 写者 | 读者 |
|--------------|------|-----|------|------|
| `quota:{subject}` | ZSET | 60s 自然过期 | 配额中间件 | 配额中间件 |
| `cancel:{request_id}` | STRING | 30s | Broadcaster | Forwarder(轮询) |
| `router:cancel` | Pub/Sub channel | — | Broadcaster | listen task |

---

## §8 错误处理与状态码

### 8.1 错误响应格式

```json
{
  "error": {
    "code": "agent_not_found",
    "message": "Agent xyz is not registered",
    "request_id": "..."
  }
}
```

### 8.2 状态码 / code 对照

| HTTP | code | 含义 |
|------|------|------|
| 400 | `protocol_mismatch` | Agent 声明 mode 与实际响应不符 |
| 400 | `validation_error` | 请求参数不通过 |
| 401 | `auth_invalid` | JWT 无效 / 过期 / sub 与 subject 不一致 |
| 403 | `forbidden` | 权限不足(如 cancel 非 creator/admin) |
| 404 | `agent_not_found` / `endpoint_not_found` | 路由失败 |
| 405 | `method_not_allowed` | 客户端 method 与注册的 endpoint.method 不一致 |
| 409 | `agent_conflict` | 注册 agent_id 冲突(同 id 不同 subject) |
| 429 | `quota_exceeded` | 配额超限 |
| 502 | `agent_unavailable` | 下游 5xx 或熔断 open |
| 503 | `dependency_unavailable` | PG / Redis / JWKS 不可达(fail-closed) |
| 504 | `agent_timeout` | 转发 read 超时 |

### 8.3 异常处理规约(P1 E)

- **禁止 `except:` / `except BaseException:`**
- **禁止吞 `asyncio.CancelledError`**;cancel 必须自然向上传播
- ruff 强制开启:`BLE001`(blind-except)、`PT012`(测试断言)
- 全局异常处理器:未捕获异常 → 500 `internal_error`,日志带 traceback,响应不含细节

---

## §9 测试与质量基线

### 9.1 测试金字塔

| 层 | 工具 | 覆盖目标 |
|----|------|---------|
| Unit | pytest | 路由决策、签名、Pydantic 模型、Lua 脚本(mock) |
| Integration | pytest + testcontainers(PG + Redis) | Registry CRUD、配额、审计写入、Pub/Sub |
| Contract | pytest + httpx mock | Forwarder 行为、SSE 流、重试/熔断 |
| E2E | docker-compose 拉真环境 | 注册→路由→转发→取消 全链路 |

### 9.2 关键场景必测

- **取消**:本地 / 跨实例 / SSE 中途 / Pub/Sub 丢消息(关闭 sub 后发 cancel,验证 key 兜底生效)
- **重试**:GET 5xx → 3 次,POST `idempotent=true` → 1 次,POST `idempotent=false` → 0 次
- **熔断**:连续失败 5 次 → open,半开探测恢复
- **配额**:滑窗边界 / Redis 故障 fail-closed
- **JWKS**:正常验签 / 密钥轮换(401→刷新→通过)/ IDP 不可达使用过期 cache
- **审计**:fire-and-forget 失败不影响主请求;签名验证可重放
- **Graceful shutdown**:SIGTERM → drain → 退出
- **Form mismatch**:Agent 声明 block 但流式 → 400
- **失败隔离**:Agent A 慢 → Agent B 不受影响(per-Agent client 验证)

### 9.3 质量门槛

- ruff 全通过(含 BLE001、PT 规则、async lints)
- mypy --strict 通过
- 单测覆盖 ≥ 80%(Forwarder / Coordination / 鉴权 ≥ 90%)
- testcontainers session-scoped fixture,truncate-between-tests

---

## §10 里程碑与风险

### 10.1 里程碑

| 版本 | 范围 |
|------|------|
| **v0.1 MVP**(本规格) | §1–§9 全部;双实例 Docker;团队内试运行 |
| **v0.2 可观测增强** | structlog + Prometheus + OTel;audit 批写;JWT verify cache |
| **v0.3 智能路由 + 韧性** | LLM Judge 路由;Redis 共享熔断状态;路由策略热更新 |
| **v0.4+** | 协议适配(可选);一致性 hash;KMS 密钥管理 |

### 10.2 已知风险与债务

| 风险 | 影响 | 缓解 / 计划 |
|------|------|-----------|
| 取消是 best-effort(Pub/Sub at-most-once) | 极端情况漏取消 | 文档明示 + Redis key 兜底 + 客户端可重试 |
| 进程内熔断,跨实例独立计数 | 故障检测慢 ~3× | v0.3 改 Redis 共享 |
| stdlib logging 无结构化 | 排障痛苦,字段不规范 | v0.2 升级 structlog |
| 审计 fire-and-forget | 进程崩溃丢 in-flight 审计 | 监控 + graceful shutdown 排空 |
| HMAC 密钥手工轮换 | 操作风险 | v0.x KMS + 双密钥并行 |
| JWT RS256 验签 CPU 热点 | 高 QPS 占 CPU | v0.2 verify cache(token hash → exp) |
| `idempotent` 信任 Agent 自报 | 误声明可能重复写 | 团队内可信 + §4.3 保守重试默认值 |
| 无 PgBouncer | PG 连接数受限于 pool_size | 预留 statement_cache_size 配置 |
| `is_disconnected()` 不主动轮询 | 客户端断开延迟到下个 chunk 才感知 | 心跳 chunk 间隔 ≤ 1s 缓解 |

### 10.3 v0.1 验收标准

- [ ] 注册一个 Agent(2 instances,1 endpoint)→ 可路由并转发
- [ ] block 模式转发回包正确
- [ ] SSE 模式流式正常,客户端断开 → Routers 同步释放
- [ ] 用户取消 in-flight SSE → 跨实例生效(主流路径)
- [ ] 关闭 Pub/Sub 订阅后取消仍能在 30s 内通过 key 兜底命中
- [ ] 配额超限返回 429
- [ ] JWT 过期返回 401;轮换后旧缓存被强制刷新
- [ ] 审计入库且签名可验证
- [ ] 一个 Agent 慢 → 其他 Agent 转发 P99 不退化
- [ ] SIGTERM → 30s 内优雅退出,无 in-flight 泄漏

---

## 附录 A · 顶层模块到代码包映射

| 顶层模块 | 代码位置 | 主要类型 |
|---------|---------|---------|
| API Gateway | `api/` | FastAPI routers |
| 鉴权 | `middleware/auth.py` + `adapters/jwks.py` | `JWKSClient` |
| 配额 | `middleware/quota.py` + `adapters/redis_quota.py` | `SlidingWindowQuota` |
| 路由决策 | `services/routing.py` | `RoutingDecisionEngine` |
| Registry | `services/registry.py` + `adapters/agent_repo.py` | `AgentRegistry` |
| Forwarder | `services/forwarder.py` + `adapters/http_client.py` | `Forwarder`, `PerAgentClientPool` |
| Coordination | `services/coordination.py` | `CancellationRegistry`, `CancellationBroadcaster` |
| 审计 + 签名 | `middleware/audit.py` + `adapters/audit_repo.py` | `AuditEvent`, `Signer` |
| 重试 / 超时 / 熔断 | `services/forwarder.py` 内部 | tenacity / purgatory 装饰 |
| 日志 | `obs/logging.py` | JSON formatter + contextvars filter |
| 配置 | `config/settings.py` | Pydantic `Settings` |

## 附录 B · 待 v0.x 启动的扩展点列表

1. LLM Judge 路由(`services/routing.py` 中第 4 层 hook)
2. structlog / Prometheus / OTel(替换 `obs/`)
3. 一致性 hash(替换 §4.1 default 选择策略)
4. Redis 共享熔断(替换 purgatory 后端)
5. JWT verify cache(`adapters/jwks.py` 加二级缓存)
6. 协议适配(在 Forwarder 前插一层 adapter,默认 passthrough)
7. KMS 密钥管理(替换 `AUDIT_HMAC_KEY` env 注入)
