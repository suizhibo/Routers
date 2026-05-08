import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.api.dependencies import AuthContext, get_auth, get_registry
from agent_routers.api.routes_agents import router as agents_router
from agent_routers.models import Base
from agent_routers.services.registry import AgentRegistry


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest.fixture
def client(db_session):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    from agent_routers.errors import AgentRoutersError

    app = FastAPI()
    repo = AgentRepository(db_session)
    registry = AgentRegistry(repo)

    @app.exception_handler(AgentRoutersError)
    async def agent_routers_error_handler(request: Request, exc: AgentRoutersError) -> JSONResponse:
        body = exc.to_dict()
        body["error"]["request_id"] = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status_code, content=body)

    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_auth] = lambda: AuthContext(sub="svc-test", role=None)
    app.include_router(agents_router)

    with TestClient(app) as tc:
        yield tc


def test_register_agent(client):
    payload = {
        "agent_id": "weather-agent",
        "name": "Weather Agent",
        "subject": "svc-test",
        "base_url": "http://weather:8080",
        "capability": "weather",
        "description": "Provides weather forecasts",
        "endpoints": [
            {
                "endpoint_type": "chat",
                "method": "POST",
                "path": "/api/forecast",
                "mode": "block",
                "idempotent": False,
                "path_params": [],
                "query_params": [],
            }
        ],
    }
    resp = client.post("/v1/agents", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == "weather-agent"

    # Verify detail includes new fields
    resp = client.get("/v1/agents/weather-agent")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["capability"] == "weather"
    assert detail["description"] == "Provides weather forecasts"

    # Verify list includes new fields
    resp = client.get("/v1/agents")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["capability"] == "weather"
    assert items[0]["description"] == "Provides weather forecasts"


def test_register_subject_mismatch(client):
    payload = {
        "agent_id": "agent-1",
        "name": "Agent 1",
        "subject": "svc-wrong",
        "base_url": "http://x:80",
        "endpoints": [
            {"endpoint_type": "chat", "method": "GET", "path": "/", "mode": "block"}
        ],
    }
    resp = client.post("/v1/agents", json=payload)
    assert resp.status_code == 401


def test_list_agents_empty(client):
    resp = client.get("/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_agent_not_found(client):
    resp = client.get("/v1/agents/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "agent_not_found"


def test_register_agent_with_auth(client):
    payload = {
        "agent_id": "auth-agent",
        "name": "Auth Agent",
        "subject": "svc-test",
        "base_url": "http://auth:8080",
        "auth_header": "x-api-key",
        "auth_token": "secret-123",
        "endpoints": [
            {
                "endpoint_type": "chat",
                "method": "POST",
                "path": "/api/chat",
                "mode": "block",
                "idempotent": False,
                "path_params": [],
                "query_params": [],
            }
        ],
    }
    resp = client.post("/v1/agents", json=payload)
    assert resp.status_code == 201

    # Detail masks token
    resp = client.get("/v1/agents/auth-agent")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["auth_header"] == "x-api-key"
    assert detail["auth_token"] == "***"

    # List omits token
    resp = client.get("/v1/agents")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["auth_header"] == "x-api-key"
    assert "auth_token" not in items[0]
