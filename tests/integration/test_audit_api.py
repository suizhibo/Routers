from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_routers.adapters.audit_repo import AuditRepository
from agent_routers.api.dependencies import AuthContext, get_auth
import asyncio

from agent_routers.middleware.audit import AuditMiddleware, audit_task_set
from agent_routers.models import Base
from agent_routers.services.signer import HmacSigner


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

    app = FastAPI()

    @app.post("/test")
    async def test_handler(request: Request):
        body = await request.body()
        return JSONResponse({"received": body.decode("utf-8", errors="replace")})

    repo = AuditRepository(db_session)
    signer = HmacSigner(key="test-key")
    app.state.audit_repo = repo

    class StateMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.request_id = "req-int-1"
            request.state.auth = AuthContext(sub="user-test", role="admin")
            return await call_next(request)

    # AuditMiddleware added first -> innermost; StateMiddleware added after -> outermost
    app.add_middleware(AuditMiddleware, repo=repo, signer=signer)
    app.add_middleware(StateMiddleware)
    app.dependency_overrides[get_auth] = lambda: AuthContext(sub="user-test", role="admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _wait_for_audit_tasks():
    if audit_task_set:
        await asyncio.gather(*audit_task_set, return_exceptions=True)
        audit_task_set.clear()


@pytest.mark.asyncio
async def test_audit_event_contains_request_and_response_body(client, db_session):
    resp = await client.post("/test", content=b'{"query":"hello"}')
    assert resp.status_code == 200

    await _wait_for_audit_tasks()

    repo = AuditRepository(db_session)
    event = await repo.get_by_request_id("req-int-1")
    assert event is not None
    assert event.request_body == '{"query":"hello"}'
    assert event.response_body == '{"received":"{\\"query\\":\\"hello\\"}"}'
    assert event.signature is not None
    assert len(event.signature) > 0


@pytest.mark.asyncio
async def test_audit_event_truncates_large_body(client, db_session, monkeypatch):
    monkeypatch.setattr("agent_routers.middleware.audit.MAX_BODY_BYTES", 5)

    resp = await client.post("/test", content=b"hello world")
    assert resp.status_code == 200

    await _wait_for_audit_tasks()

    repo = AuditRepository(db_session)
    event = await repo.get_by_request_id("req-int-1")
    assert event is not None
    assert event.request_body == "hello…truncated"


@pytest.mark.asyncio
async def test_audit_event_signature_verifies(client, db_session):
    resp = await client.post("/test", content=b"audit-me")
    assert resp.status_code == 200

    await _wait_for_audit_tasks()

    repo = AuditRepository(db_session)
    event = await repo.get_by_request_id("req-int-1")
    assert event is not None

    signer = HmacSigner(key="test-key")
    from agent_routers.middleware.audit import _body_digest

    canonical = signer.canonical(
        request_id=event.request_id,
        timestamp_iso=event.timestamp.isoformat(),
        user_subject=event.user_subject,
        agent_id=event.agent_id or "",
        status_code=event.status_code or 0,
        latency_ms=event.latency_ms or 0,
        request_body_digest=_body_digest(event.request_body or ""),
        response_body_digest=_body_digest(event.response_body or ""),
    )
    assert signer.verify(canonical, event.signature) is True
