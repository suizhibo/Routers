from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx
from starlette.requests import Request
from starlette.responses import Response

from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.models.agent import Agent, AgentEndpoint, AgentInstance
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
    def __init__(self, result: tuple[str, str]):
        self._result = result

    async def resolve(self, route_req: RouteRequest, headers: dict) -> tuple[str, str]:
        return self._result


def _make_agent_with_create_session() -> Agent:
    agent = Agent(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
    )
    agent.instances = [
        AgentInstance(agent_id="weather-agent", instance_id="inst-1", base_url="http://localhost:8001", weight=1),
    ]
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


@pytest.fixture
def pool():
    return PerAgentClientPool()


@pytest.mark.asyncio
async def test_auto_create_session_then_chat(pool):
    """测试无 session_id 时自动创建会话并继续 chat"""
    agent = _make_agent_with_create_session()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(("weather-agent", "chat"))
    
    mock_session_mgr = AsyncMock(spec=SessionManager)
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)
    
    # Mock create-session 响应
    create_response = MagicMock(spec=httpx.Response)
    create_response.status_code = 200
    create_response.headers = {"content-type": "application/json"}
    create_response.json = MagicMock(return_value={"data": {"id": "sess-abc123"}})
    create_response.raise_for_status = MagicMock()
    
    # Mock chat 响应（stream）
    async def _aiter_bytes():
        yield b"data: hello\n\n"
    
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=create_response)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    
    pool.create("weather-agent", "http://localhost:8001")
    pool._clients["weather-agent"] = mock_client
    
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
    
    assert mock_client.request.called
    mock_session_mgr.set_route.assert_awaited_once_with("weather-agent", "sess-abc123", "create-session")
    assert mock_client.stream.called


@pytest.mark.asyncio
async def test_with_existing_session_id(pool):
    """测试有 session_id 时不自动创建"""
    agent = _make_agent_with_create_session()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(("weather-agent", "chat"))
    
    mock_session_mgr = AsyncMock(spec=SessionManager)
    mock_session_mgr.get_route = AsyncMock(return_value=("weather-agent", "chat"))
    fwd = Forwarder(repo, engine, pool, session_manager=mock_session_mgr)
    
    async def _aiter_bytes():
        yield b"data: hello\n\n"
    
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    
    pool.create("weather-agent", "http://localhost:8001")
    pool._clients["weather-agent"] = mock_client
    
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
    
    assert not mock_client.request.called
    assert mock_client.stream.called
