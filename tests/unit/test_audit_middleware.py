from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from agent_routers.middleware.audit import (
    AuditMiddleware,
    TRUNCATION_MARKER,
    _body_digest,
    _truncate_body,
    audit_task_set,
)
from agent_routers.services.signer import HmacSigner


class FakeRepo:
    def __init__(self):
        self.events: list[dict] = []

    async def insert(self, event: dict) -> None:
        self.events.append(event)


class StateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = "req-test-1"
        request.state.auth = type("Auth", (), {"sub": "user-abc"})()
        return await call_next(request)


@pytest.fixture(autouse=True)
def drain_audit_tasks():
    yield
    while audit_task_set:
        pending = list(audit_task_set)
        for task in pending:
            if not task.done():
                task.cancel()
        audit_task_set.clear()


@pytest.fixture
def fake_repo():
    return FakeRepo()


@pytest.fixture
def signer():
    return HmacSigner(key="test-key")


async def ok_handler(request: Request):
    body = await request.body()
    return JSONResponse({"echo": body.decode("utf-8", errors="replace")})


async def stream_handler(request: Request):
    async def gen():
        yield b"data: hello\n\n"
        yield b"data: world\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@pytest_asyncio.fixture
async def client(fake_repo, signer):
    from starlette.applications import Starlette

    app = Starlette(
        routes=[
            Route("/ok", ok_handler, methods=["POST"]),
            Route("/stream", stream_handler, methods=["GET"]),
        ]
    )
    # AuditMiddleware added first so it becomes inner; StateMiddleware added after so it becomes outer
    app.add_middleware(AuditMiddleware, repo=fake_repo, signer=signer)
    app.add_middleware(StateMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestTruncateBody:
    def test_verbatim_when_under_limit(self):
        body = b"hello world"
        assert _truncate_body(body) == "hello world"

    def test_truncated_when_over_limit(self, monkeypatch):
        monkeypatch.setattr("agent_routers.middleware.audit.MAX_BODY_BYTES", 5)
        body = b"hello world"
        result = _truncate_body(body)
        assert result == "hello" + TRUNCATION_MARKER

    def test_unicode_replacement_on_invalid_utf8(self):
        body = b"\xff\xfe"
        result = _truncate_body(body)
        assert "�" in result


class TestBodyDigest:
    def test_digest_format(self):
        digest = _body_digest("hello")
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)


class TestAuditMiddleware:
    @pytest.mark.asyncio
    async def test_captures_request_and_response_body(self, client, fake_repo):
        resp = await client.post("/ok", content=b'{"msg":"hi"}')
        assert resp.status_code == 200
        assert resp.json() == {"echo": '{"msg":"hi"}'}

        assert len(fake_repo.events) == 1
        event = fake_repo.events[0]
        assert event["request_body"] == '{"msg":"hi"}'
        assert event["response_body"] == '{"echo":"{\\"msg\\":\\"hi\\"}"}'

    @pytest.mark.asyncio
    async def test_truncates_large_request_body(self, client, fake_repo, monkeypatch):
        monkeypatch.setattr("agent_routers.middleware.audit.MAX_BODY_BYTES", 5)
        resp = await client.post("/ok", content=b"hello world")
        assert resp.status_code == 200

        event = fake_repo.events[0]
        assert event["request_body"] == "hello" + TRUNCATION_MARKER

    @pytest.mark.asyncio
    async def test_streaming_response_body_captured(self, client, fake_repo):
        resp = await client.get("/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Wait for background audit task to finish
        await asyncio.sleep(0.1)

        event = fake_repo.events[0]
        assert event["response_body"] == "data: hello\n\ndata: world\n\n"

    @pytest.mark.asyncio
    async def test_streaming_response_truncated(self, client, fake_repo, monkeypatch):
        monkeypatch.setattr("agent_routers.middleware.audit.MAX_BODY_BYTES", 10)

        resp = await client.get("/stream")
        assert resp.status_code == 200

        await asyncio.sleep(0.1)

        event = fake_repo.events[0]
        assert event["response_body"] == "data: hell" + TRUNCATION_MARKER

    @pytest.mark.asyncio
    async def test_reconstructed_response_preserved(self, client):
        resp = await client.post("/ok", content=b"x")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        assert resp.json() == {"echo": "x"}

    @pytest.mark.asyncio
    async def test_signature_includes_body_digests(self, client, fake_repo, signer):
        await client.post("/ok", content=b"test")

        event = fake_repo.events[0]
        sig = event["signature"]
        canonical = signer.canonical(
            request_id=event["request_id"],
            timestamp_iso=event["timestamp"],
            user_subject=event["user_subject"],
            agent_id=event["agent_id"],
            status_code=event["status_code"],
            latency_ms=event["latency_ms"],
            request_body_digest=_body_digest(event["request_body"]),
            response_body_digest=_body_digest(event["response_body"]),
        )
        assert signer.verify(canonical, sig) is True

    @pytest.mark.asyncio
    async def test_tampered_body_fails_verify(self, client, fake_repo, signer):
        await client.post("/ok", content=b"test")

        event = fake_repo.events[0]
        sig = event["signature"]
        canonical = signer.canonical(
            request_id=event["request_id"],
            timestamp_iso=event["timestamp"],
            user_subject=event["user_subject"],
            agent_id=event["agent_id"],
            status_code=event["status_code"],
            latency_ms=event["latency_ms"],
            request_body_digest="tampered",
            response_body_digest=_body_digest(event["response_body"]),
        )
        assert signer.verify(canonical, sig) is False
