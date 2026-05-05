import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from agent_routers.models import Base
from agent_routers.api.routes_agents import router as agents_router
from agent_routers.api.dependencies import get_auth, AuthContext, get_registry
from agent_routers.services.registry import AgentRegistry
from agent_routers.adapters.agent_repo import AgentRepository


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    from fastapi import FastAPI

    from fastapi import Request
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_agent(client):
    payload = {
        "agent_id": "weather-agent",
        "name": "Weather Agent",
        "subject": "svc-test",
        "instances": [
            {"instance_id": "i1", "base_url": "http://weather:8080", "weight": 1}
        ],
        "endpoints": [
            {
                "endpoint_id": "forecast",
                "method": "POST",
                "path": "/api/forecast",
                "mode": "block",
                "idempotent": False,
                "path_params": [],
                "query_params": [],
            }
        ],
    }
    resp = await client.post("/v1/agents", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == "weather-agent"


@pytest.mark.asyncio
async def test_register_subject_mismatch(client):
    payload = {
        "agent_id": "agent-1",
        "name": "Agent 1",
        "subject": "svc-wrong",
        "instances": [{"instance_id": "i1", "base_url": "http://x:80"}],
        "endpoints": [
            {"endpoint_id": "e1", "method": "GET", "path": "/", "mode": "block"}
        ],
    }
    resp = await client.post("/v1/agents", json=payload)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_agents_empty(client):
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_agent_not_found(client):
    resp = await client.get("/v1/agents/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "agent_not_found"
