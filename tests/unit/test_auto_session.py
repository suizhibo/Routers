from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from starlette.requests import Request

from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.models.agent import Agent, AgentEndpoint
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.forwarder import Forwarder
from agent_routers.services.routing import RoutingDecisionEngine
from agent_routers.services.session_manager import SessionManager


class FakeAgentRepo:
    def __init__(self, agent: Agent | None):
        self._agent = agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agent

    async def list_all(self) -> list[Agent]:
        return [self._agent] if self._agent else []


class FakeRoutingEngine:
    def __init__(self, result: str):
        self._result = result

    async def resolve(self, route_req: RouteRequest, headers: dict) -> str:
        return self._result


def _make_agent_with_create_session() -> Agent:
    agent = Agent(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
        base_url="http://localhost:8001",
    )
    agent.endpoints = [
        AgentEndpoint(
            agent_id="weather-agent",
            endpoint_type="create_session",
            method="POST",
            path="/sessions",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config={"response_body_path": "data.id"},
        ),
        AgentEndpoint(
            agent_id="weather-agent",
            endpoint_type="chat",
            method="POST",
            path="/chat/{session_id}",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="stream",
            idempotent=False,
            param_mapping={"path_params": {"session_id": "context.session_id"}},
            session_config=None,
        ),
    ]
    return agent


def _make_request(body: bytes = b"{}") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
        "path": "/v1/route",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request._body = body
    return request


def _mock_response(
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    json_data=None,
) -> MagicMock:
    resp = MagicMock(spec=aiohttp.ClientResponse)
    resp.status = status
    resp.headers = headers or {}
    resp.read = AsyncMock(return_value=body)
    resp.json = AsyncMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    return resp


def _request_cm_for(response: MagicMock):
    @asynccontextmanager
    async def _cm(*_a, **_kw):
        yield response
    return _cm


def _stream_cm_yielding(chunks: list[bytes]):
    @asynccontextmanager
    async def _cm(*_a, **_kw):
        async def aiter_any():
            for chunk in chunks:
                yield chunk
        upstream = MagicMock()
        upstream.content = MagicMock()
        upstream.content.iter_any = aiter_any
        yield upstream
    return _cm


@pytest.fixture
def pool():
    return PerAgentClientPool()


@pytest.mark.asyncio
async def test_auto_create_session_then_chat(pool):
    """测试无 session_id 时自动创建会话并继续 chat"""
    agent = _make_agent_with_create_session()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("weather-agent")

    mock_session_mgr = AsyncMock(spec=SessionManager)
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)

    create_response = _mock_response(
        status=200,
        headers={"content-type": "application/json"},
        json_data={"data": {"id": "sess-abc123"}},
    )

    cm_create = _request_cm_for(create_response)
    cm_chat = _stream_cm_yielding([b"data: hello\n\n"])

    calls = {"n": 0}

    def side_effect(*a, **kw):
        calls["n"] += 1
        return cm_create() if calls["n"] == 1 else cm_chat()

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.request = MagicMock(side_effect=side_effect)

    pool.create("weather-agent", "http://localhost:8001")
    pool._sessions["weather-agent"] = mock_session

    route_req = RouteRequest(
        input="今天天气怎么样？",
        context={},
        options={},
    )
    request = _make_request()

    response = await fwd.forward(request, route_req, None)

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    assert mock_session.request.call_count == 2
    mock_session_mgr.set_route.assert_awaited_once_with("sess-abc123", "weather-agent")


@pytest.mark.asyncio
async def test_with_existing_session_id(pool):
    """测试有 session_id 时不自动创建"""
    agent = _make_agent_with_create_session()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("weather-agent")

    mock_session_mgr = AsyncMock(spec=SessionManager)
    mock_session_mgr.get_route = AsyncMock(return_value="weather-agent")
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)

    cm_chat = _stream_cm_yielding([b"data: hello\n\n"])
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.request = MagicMock(side_effect=lambda *a, **kw: cm_chat())

    pool.create("weather-agent", "http://localhost:8001")
    pool._sessions["weather-agent"] = mock_session

    route_req = RouteRequest(
        input="明天呢？",
        context={"session_id": "sess-abc123"},
        options={},
    )
    request = _make_request()

    response = await fwd.forward(request, route_req, None)

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    assert mock_session.request.call_count == 1
