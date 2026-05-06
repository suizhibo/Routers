# AgentRouters — Agent Workspace Guide

> Compact, high-signal reference for AI agents working in this repo.  
> Every line answers: "Would an agent likely miss this without help?"

---

## Project at a Glance

- **Language / runtime**: Python 3.12+ (strict mypy enabled)
- **Framework**: FastAPI + SQLAlchemy 2 (async) + Pydantic v2
- **Infra deps**: PostgreSQL (asyncpg), Redis (quota + session cache + cancellation Pub/Sub)
- **Auth**: JWT via RS256 + JWKS endpoint (PyJWT)
- **App entry**: `agent_routers.main:app` (uvicorn)
- **Package name**: `agent_routers` (import root)

---

## Quick Commands

| Task | Command |
|------|---------|
| Install deps | `pip install -e ".[dev]"` |
| Run all tests | `python3 -m pytest tests/` |
| Run unit only | `python3 -m pytest tests/unit` |
| Run integration | `python3 -m pytest tests/integration` |
| Run contract | `python3 -m pytest tests/contract` |
| Lint | `python3 -m ruff check agent_routers tests` |
| Lint + fix | `python3 -m ruff check --fix agent_routers tests` |
| Type check | `python3 -m mypy agent_routers` |
| Run app locally | `uvicorn agent_routers.main:app --reload` |
| Run with Docker | `docker-compose up --build` |
| DB migrations | `alembic upgrade head` |
| Generate migration | `alembic revision --autogenerate -m "msg"` |

**Note**: `python` may not be available; use `python3` on this machine.

---

## Test Strategy

- **Unit** (`tests/unit/`): Pure logic, no external services. Fast, always pass.  
  Use `pytest.mark.asyncio` for async tests; `AsyncMock` / `MagicMock` for dependencies.
- **Integration** (`tests/integration/`): FastAPI `TestClient` / `AsyncClient` with in-memory SQLite (`sqlite+aiosqlite:///:memory:`). Tests API layer wiring.
- **Contract** (`tests/contract/`): Behavioral contracts for streaming/cancellation. Currently **4 failures** in `test_cancel_sse.py` — `_forward_stream()` signature changed (now requires `endpoint`, `agent_id`, `target_instance_id`) but tests weren't updated.

**Pre-existing issues** (do not fix unless asked):
- Contract tests fail due to signature mismatch.
- `ruff` reports 93 errors (mostly import sorting + unused imports).
- `mypy` reports 72 errors (missing type annotations, untyped defs).

---

## Architecture

```
agent_routers/
├── main.py              # App factory (make_app), lifespan, middleware wiring
├── config/settings.py   # Pydantic-settings; reads .env; extra="forbid"
├── api/                 # FastAPI routers (agents, rules, forward, audit, cancel, health)
│   └── dependencies.py  # AuthContext, get_auth, get_registry, get_forwarder
├── services/            # Business logic
│   ├── forwarder.py     # HTTP forwarding (block + stream), circuit breaker, retries
│   ├── routing.py       # 5-level routing pipeline (L1 preferred → L5 default)
│   ├── registry.py      # Agent CRUD with subject/auth checks
│   ├── coordination.py  # Cancellation registry + Redis broadcaster
│   ├── session_manager.py  # Redis-backed session→route cache
│   └── signer.py        # HMAC audit signing
├── adapters/            # Repository + external clients
│   ├── agent_repo.py    # SQLAlchemy agent CRUD
│   ├── rule_repo.py     # Routing rule CRUD
│   ├── audit_repo.py    # Audit event persistence
│   ├── http_client.py   # Per-agent httpx client pool
│   ├── jwks.py          # JWT verification with cache + fallback
│   └── redis_quota.py   # Lua-based sliding-window rate limiter
├── middleware/          # Starlette middleware (order matters!)
│   ├── request_id.py    # Injects request_id (outermost)
│   ├── jwt_auth.py      # JWT validation (public paths exempt)
│   ├── quota.py         # Redis rate limiting
│   └── audit.py         # Async audit logging (innermost)
├── models/              # SQLAlchemy ORM models
│   ├── agent.py         # Agent, AgentInstance, AgentEndpoint
│   ├── rule.py          # RoutingRule
│   ├── audit.py         # AuditEvent
│   └── request.py       # RequestTracking
├── schemas/             # Pydantic v2 request/response models
│   ├── agent.py         # AgentRegistration, EndpointSpec, etc.
│   ├── route.py         # RouteRequest
│   └── rule.py          # RoutingRuleCreate, RoutingRuleDetail
└── obs/logging.py       # JSON structured logging
```

---

## Key Conventions

### Middleware Order (critical)
Middleware is added **outer → inner** in `main.py::_setup_middleware()`:

```python
app.add_middleware(AuditMiddleware, ...)   # innermost — sees final response
app.add_middleware(QuotaMiddleware)
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(RequestIdMiddleware)    # outermost
```

Starlette dispatches outermost first, so `RequestIdMiddleware` runs before `JWTAuthMiddleware`.

### Routing Pipeline (5 levels)
`RoutingDecisionEngine.resolve()` priority:
1. **L1**: `X-Preferred-Agent` header (endpoint defaults to `"chat"`)
2. **L2**: Session cache (Redis `session:{session_id}` → `agent_id:endpoint_id`)
3. **L3**: Matching routing rule (`when_clause` on headers/context/options)
4. **L4**: Operation type match (`context.operation` or `options.action` → `endpoint.operation_types`)
5. **L5**: Default agent (`DEFAULT_AGENT_ID` setting)

### Auth & Roles
- JWT `sub` claim = agent subject (must match on register/deregister)
- JWT `role` claim = `"admin"` for admin-only endpoints (`/v1/rules`, `/v1/audit`)
- Public paths (no auth): `/health`, `/readiness`, `/docs`, `/openapi.json`

### Forwarding Modes
- **block**: Standard request/response; retries on 5xx (3 attempts, exponential backoff)
- **stream**: SSE streaming; checks `cancel_event.is_set()` between chunks

### Circuit Breaker
- Per `(agent_id, instance_id)` key using `purgatory` library
- Threshold: 5 failures; recovery: 60s

### Session Extraction
Only the auto-create-session flow extracts `session_id` from upstream responses.
When `context.session_id` is missing, `Forwarder._auto_create_session()` calls the
agent's `create-session` endpoint and extracts the new id from:
1. Response header (configured in `endpoint.session_config.response_header`), or
2. JSON body path (configured in `endpoint.session_config.response_body_path`).

Then stores in Redis: `session:{session_id} = {agent_id}:{endpoint_id}` (TTL 24h).
chat/stop responses do **not** contribute to the session cache — `session_id`
flows in via `context.session_id` and is forwarded to the upstream through
`param_mapping`.

---

## Database & Migrations

- **ORM**: SQLAlchemy 2.0 async with `AsyncAttrs` + `DeclarativeBase`
- **Migrations**: Alembic; async setup in `alembic/env.py`
- **Models**: All models inherit from `agent_routers.models.agent.Base`
- **JSON columns**: Use `sqlalchemy.JSON` (model) → `postgresql.JSONB` (migration)
- **Migration files**: `alembic/versions/` — check existing ones before creating new

### Important Model Quirk
`AgentEndpoint` has a `CheckConstraint` on `mode IN ('block', 'stream')`.  
The model default for `path_params`/`query_params` is `list` (in model) but migrations use `JSONB` with `default=list` — ensure schema and migration stay consistent.

---

## Environment & Configuration

Settings are loaded from `.env` via `pydantic-settings` (`env_file=".env"`, `extra="forbid"`).

Key env vars:
- `DATABASE_URL` — PostgreSQL with asyncpg driver
- `REDIS_URL` — Redis for quota, sessions, cancellation
- `JWKS_URL` — JWKS endpoint for JWT verification
- `JWT_ISS`, `JWT_AUD` — JWT issuer/audience validation
- `AUDIT_HMAC_KEY` — HMAC key for audit signatures
- `QUOTA_DEFAULT_PER_MINUTE` — Rate limit (default 120)
- `DRAIN_TIMEOUT_SECONDS` — Audit drain timeout on shutdown (default 15)
- `DEFAULT_AGENT_ID` — Fallback agent for L5 routing

**Docker Compose** (`docker-compose.yml`) spins up: PostgreSQL (port 5433), Redis (port 6380), mock JWKS server (port 8080), and the app (port 8000).

---

## Development Workflow

### Running the Full Stack Locally
```bash
# 1. Start infra
docker-compose up postgres redis mock-jwks -d

# 2. Run migrations
alembic upgrade head

# 3. Start app
uvicorn agent_routers.main:app --reload --port 8000

# 4. Run dynamic API tests (requires running app + JWKS)
python3 scripts/dynamic_test.py
```

### Dynamic Testing
`scripts/dynamic_test.py` — end-to-end API test against a running service.  
Requires: app on `:8000`, JWKS server on `:8080`.  
Generates JWTs using `/tmp/mock_jwks_private.pem` (created by `scripts/mock_jwks_server.py`).

### OpenAPI / Swagger
- Static schema: `openapi.json`, `openapi.yaml` (generated)
- Docs server: `swagger_server.py` — standalone FastAPI serving Swagger UI

---

## Code Style

- **Ruff**: line-length 100, target py312, lint rules: E, F, W, I, BLE001, PT012, PT013
- **MyPy**: strict mode, python_version = 3.12
- **Imports**: `from __future__ import annotations` at top of every file
- **Type hints**: Required everywhere (mypy strict). Use `|` union syntax (py312).
- **Async**: All I/O is async; use `async_sessionmaker`, `AsyncMock` in tests.

---

## Common Pitfalls

1. **Middleware ordering**: Adding middleware in wrong order breaks auth/quota/audit chain.
2. **Forwarder signature changes**: `_forward_block()` takes `circuit_key` only; `_forward_stream()` takes `cancel_event` only. Contract tests need corresponding updates.
3. **Redis connection lazy init**: `SessionManager`, `CancellationBroadcaster`, `RedisQuota` all lazily create Redis clients on first use. Ensure Redis is up before first request.
4. **JWT subject matching**: Agent registration `subject` must match JWT `sub` claim. Admin endpoints check `role == "admin"`.
5. **Circuit breaker state**: `purgatory` circuit breaker is in-memory; not shared across processes.
6. **Audit drain timeout**: On shutdown, pending audit writes are drained with `DRAIN_TIMEOUT_SECONDS` timeout. If exceeded, audit events may be lost.
7. **Mypy is strict**: Missing type annotations or `Any` returns will fail CI. Use explicit types.
8. **Ruff import sorting**: Run `ruff check --fix` before committing.

---

## Design Docs

Implementation plans and specs live in `docs/superpowers/`:
- `plans/` — step-by-step implementation plans
- `specs/` — design specifications

These are **human-written** reference docs, not generated. Check them before major changes.

---

## External Dependencies Worth Knowing

| Library | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `sqlalchemy[asyncio]` | Async ORM |
| `asyncpg` | PostgreSQL async driver |
| `alembic` | DB migrations |
| `pydantic`, `pydantic-settings` | Validation & config |
| `httpx` | HTTP client (forwarding) |
| `redis` | Async Redis client |
| `PyJWT` | JWT verification |
| `cryptography` | RSA key handling (JWKS mock) |
| `tenacity` | Retry logic |
| `purgatory` | Circuit breaker |
| `pytest-asyncio` | Async test support |

---

*Last updated: 2026-05-06*
