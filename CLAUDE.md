# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentRouters is a Python 3.12+ FastAPI service that routes requests to registered AI agents. It uses async SQLAlchemy 2 with PostgreSQL (asyncpg), Redis for sessions/quota/cancellation Pub-Sub, and JWT (RS256 + JWKS) for auth.

The project uses an **OpenSpec workflow**: implementation plans and design specs live in `docs/superpowers/`. Check existing plans before major changes.

## Common Commands

| Task | Command |
|------|---------|
| Install deps | `pip install -e ".[dev]"` |
| Run all tests | `python3 -m pytest tests/` |
| Run single test | `python3 -m pytest tests/unit/test_forwarder.py::test_name -v` |
| Run unit only | `python3 -m pytest tests/unit` |
| Run integration | `python3 -m pytest tests/integration` |
| Run contract | `python3 -m pytest tests/contract` |
| Lint | `python3 -m ruff check agent_routers tests` |
| Lint + fix | `python3 -m ruff check --fix agent_routers tests` |
| Type check | `python3 -m mypy agent_routers` |
| Run app locally | `uvicorn agent_routers.main:app --reload --port 8000` |
| Run with Docker | `docker-compose up --build` |
| DB migrations | `alembic upgrade head` |
| Generate migration | `alembic revision --autogenerate -m "msg"` |
| Dynamic API test | `python3 scripts/dynamic_test.py` |

Use `python3`, not `python`, on this machine.

## Development Environment

`.env` is committed with `DEV_MODE=true`. In dev mode, docs are enabled and external dependencies can be mocked. Docker Compose spins up PostgreSQL (port 5433), Redis (port 6380), and a mock JWKS server (port 8080).

To run the full stack locally:

```bash
docker-compose up postgres redis mock-jwks -d
alembic upgrade head
uvicorn agent_routers.main:app --reload --port 8000
```

## Architecture

### Layered Structure

The codebase follows a layered architecture:

- **`api/`** — FastAPI routers and dependency injection (`AuthContext`, `get_registry`, `get_forwarder`). Routes do not contain business logic.
- **`services/`** — Business logic: `Forwarder`, `RoutingDecisionEngine`, `AgentRegistry`, `SessionManager`, `CoordinationBroadcaster`, `HmacSigner`.
- **`adapters/`** — External interfaces: SQLAlchemy repos (`agent_repo`, `rule_repo`, `audit_repo`), `http_client` (per-agent aiohttp client pool), `jwks` (JWT verification with cache), `redis_quota` (Lua-based sliding-window rate limiter).
- **`models/`** — SQLAlchemy ORM models. All inherit from `agent_routers.models.agent.Base`.
- **`schemas/`** — Pydantic v2 request/response models.
- **`middleware/`** — Starlette middleware stacked in a specific order.
- **`config/settings.py`** — Pydantic-settings with `extra="forbid"`, loaded from `.env`.

### Middleware Order (Critical)

Middleware is added **outer → inner** in `main.py::_setup_middleware()`:

```python
app.add_middleware(AuditMiddleware, ...)   # innermost — sees final response
app.add_middleware(QuotaMiddleware)
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(RequestIdMiddleware)    # outermost
```

Starlette dispatches outermost first, so `RequestIdMiddleware` runs before `JWTAuthMiddleware`. Changing this order breaks the auth/quota/audit chain.

### Routing Pipeline

`RoutingDecisionEngine.resolve()` selects an agent via a 4-level priority:

1. **L1**: `X-Preferred-Agent` header
2. **L2**: Session cache (`session:{session_id}` → `agent_id` in Redis)
3. **L3**: Matching routing rule (`when_clause` evaluated against headers/context/options/input)
4. **L4**: `DEFAULT_AGENT_ID` setting

### Request Forwarding

`Forwarder.forward()` is the core request path:

- Resolves the target agent via the routing engine.
- If no `session_id` in context, calls `_auto_create_session()` using the agent's `create_session` endpoint, extracts the new session ID from the response (header or JSON body path), and caches it in Redis.
- Finds the agent's `chat` endpoint (hardcoded endpoint type).
- Builds the upstream request using `param_mapping` (path params, query params, body mapping with schema defaults).
- Applies per-agent auth headers if configured (`agent.auth_header` + `agent.auth_token`).
- **Block mode**: standard request/response with retries on 5xx (3 attempts, exponential backoff).
- **Stream mode**: SSE streaming; checks `cancel_event.is_set()` between chunks.

### Circuit Breaker

Per `agent_id:session_id` key using `purgatory`. Threshold: 5 failures; recovery: 60s. In-memory only — not shared across processes.

### Auth

- JWT `sub` claim = agent subject (must match on register/deregister).
- JWT `role` claim = `"admin"` for admin-only endpoints (`/v1/rules`, `/v1/audit`).
- Public paths (no auth): `/health`, `/readiness`, `/docs`, `/openapi.json`.

## Test Strategy

- **Unit** (`tests/unit/`): Pure logic, no external services. Use `pytest.mark.asyncio` and `AsyncMock`/`MagicMock`.
- **Integration** (`tests/integration/`): FastAPI `TestClient` / `AsyncClient` with in-memory SQLite (`sqlite+aiosqlite:///:memory:`).
- **Contract** (`tests/contract/`): Behavioral contracts for streaming/cancellation.

## Known Issues (Do Not Fix Unless Asked)

- Contract tests in `test_cancel_sse.py` fail due to a `_forward_stream()` signature mismatch — the method now requires `agent_id` and `session_id` parameters.
- `ruff` reports ~93 errors (mostly import sorting and unused imports).
- `mypy` reports ~72 errors (missing type annotations, untyped defs).

## Code Style

- Ruff: line-length 100, target py312, lint rules: E, F, W, I, BLE001, PT012, PT013.
- MyPy: strict mode, python_version = 3.12.
- `from __future__ import annotations` at the top of every file.
- Use `|` union syntax (py312). All I/O is async.

## Database

- SQLAlchemy 2.0 async with `AsyncAttrs` + `DeclarativeBase`.
- Alembic for migrations; async setup in `alembic/env.py`.
- JSON columns in models use `sqlalchemy.JSON`; migrations use `postgresql.JSONB`.
- `AgentEndpoint` has a `CheckConstraint` on `mode IN ('block', 'stream')`.

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL with asyncpg driver |
| `REDIS_URL` | Redis for quota, sessions, cancellation |
| `JWKS_URL` | JWKS endpoint for JWT verification |
| `JWT_ISS`, `JWT_AUD` | JWT issuer/audience validation |
| `AUDIT_HMAC_KEY` | HMAC key for audit signatures |
| `QUOTA_DEFAULT_PER_MINUTE` | Rate limit (default 120) |
| `DRAIN_TIMEOUT_SECONDS` | Audit drain timeout on shutdown (default 15) |
| `DEFAULT_AGENT_ID` | Fallback agent for L4 routing |

## Shutdown Sequence

Defined in `main.py::lifespan()`:

1. Close per-agent HTTP clients (in-flight forwards stop cleanly).
2. Stop cancellation broadcaster (terminates Pub/Sub listener).
3. Drain pending audit writes with `DRAIN_TIMEOUT_SECONDS` timeout.
4. Dispose DB engine last so audit drain can write.
