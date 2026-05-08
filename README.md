# AgentRouters

A Python 3.12+ FastAPI service that routes requests to registered AI agents. It provides dynamic agent registration, intelligent request routing, session management, rate limiting, JWT authentication, and comprehensive audit logging.

## Features

- **Dynamic Agent Registration** — Register agents with typed endpoints, auth headers, and parameter mappings
- **4-Level Routing** — Resolve agents via header preference, session affinity, routing rules, or fallback default
- **Session Management** — Auto-create sessions with upstream agents and cache them in Redis
- **Request Forwarding** — Block and stream (SSE) modes with retries, circuit breaker, and cancellation support
- **JWT Authentication** — RS256 + JWKS verification with role-based access control
- **Rate Limiting** — Per-minute quota with Redis-backed sliding window
- **Audit Logging** — HMAC-signed request/response capture with async drain on shutdown
- **OpenAPI** — Auto-generated docs and interactive Swagger UI

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 16+
- Redis 7+

### Installation

```bash
pip install -e ".[dev]"
```

### Run with Docker Compose

```bash
docker-compose up --build
```

This starts PostgreSQL (port 5433), Redis (port 6380), a mock JWKS server (port 8080), and the app (port 8000).

### Run Locally

```bash
# Start dependencies
docker-compose up postgres redis mock-jwks -d

# Run migrations
alembic upgrade head

# Start the server
uvicorn agent_routers.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. OpenAPI docs at `/docs`.

## Registering an Agent

POST `/v1/agents`

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt>" \
  -d @examples/agents/intelligent-kb-agent.json
```

## Routing a Request

POST `/v1/forward`

```bash
curl -X POST http://localhost:8000/v1/forward \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt>" \
  -d '{
    "input": "What is the capital of France?",
    "options": {"agent_enabled": true}
  }'
```

The router resolves the target agent using:

1. `X-Preferred-Agent` header
2. Session cache (`session_id` → `agent_id`)
3. Matching routing rule (`when_clause`)
4. `DEFAULT_AGENT_ID` setting

## Project Structure

```
agent_routers/
├── api/           # FastAPI routers and dependency injection
├── services/      # Business logic (Forwarder, Registry, Routing, Sessions)
├── adapters/      # External interfaces (DB repos, HTTP client, JWKS, Redis)
├── models/        # SQLAlchemy ORM models
├── schemas/       # Pydantic v2 request/response models
├── middleware/    # Starlette middleware (auth, quota, audit, request ID)
└── config/        # Pydantic-settings configuration

tests/
├── unit/          # Pure logic tests
├── integration/   # FastAPI TestClient with in-memory SQLite
└── contract/      # Behavioral contracts for streaming/cancellation

examples/
├── agents/        # Sample agent registration payloads
└── rules/         # Sample routing rules
```

## Common Commands

| Task | Command |
|------|---------|
| Run all tests | `python3 -m pytest tests/` |
| Run unit tests | `python3 -m pytest tests/unit` |
| Run integration tests | `python3 -m pytest tests/integration` |
| Lint | `python3 -m ruff check agent_routers tests` |
| Lint + fix | `python3 -m ruff check --fix agent_routers tests` |
| Type check | `python3 -m mypy agent_routers` |
| Generate migration | `alembic revision --autogenerate -m "msg"` |
| Apply migrations | `alembic upgrade head` |

## Configuration

Key environment variables (see `.env` for defaults):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL with asyncpg driver |
| `REDIS_URL` | Redis for sessions, quota, and cancellation pub/sub |
| `JWKS_URL` | JWKS endpoint for JWT verification |
| `JWT_ISS`, `JWT_AUD` | JWT issuer/audience validation |
| `AUDIT_HMAC_KEY` | HMAC key for audit log signatures |
| `QUOTA_DEFAULT_PER_MINUTE` | Default rate limit (default: 120) |
| `DRAIN_TIMEOUT_SECONDS` | Audit drain timeout on shutdown (default: 15) |
| `DEFAULT_AGENT_ID` | Fallback agent for L4 routing |

## Architecture

For detailed architecture documentation, see:

- `CLAUDE.md` — codebase guide for contributors
- `docs/superpowers/` — design specs and implementation plans
- `diagrams/` — architecture diagrams and sequence charts
- `openapi.yaml` / `openapi.json` — full API specification

## License

MIT
