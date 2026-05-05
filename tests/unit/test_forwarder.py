from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.errors import AgentNotFoundError, EndpointNotFoundError
from agent_routers.models.agent import Agent, AgentEndpoint, AgentInstance
from agent_routers.services.forwarder import Forwarder
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine


class FakeAgentRepo:
    def __init__(self, agent: Agent | None):
        self._agent = agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agent


class FakeRoutingEngine:
    def __init__(self, target: InstanceTarget):
        self._target = target

    async def select_instance(self, **kwargs) -> InstanceTarget:
        return self._target


def _make_agent(endpoint_mode: str = "block") -> Agent:
    agent = Agent(
        agent_id="agent-1",
        name="Test Agent",
        subject="sub-1",
    )
    agent.instances = [
        AgentInstance(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1),
    ]
    agent.endpoints = [
        AgentEndpoint(
            agent_id="agent-1",
            endpoint_id="ep-1",
            method="POST",
            path="/chat",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode=endpoint_mode,
            idempotent=False,
        ),
    ]
    return agent


def _make_request(method: str = "POST", body: bytes = b"{}") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "headers": [(b"content-type", b"application/json")],
        "path": "/v1/route/agent-1/ep-1",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request._body = body
    return request


@pytest.fixture
def pool():
    return PerAgentClientPool()


@pytest.fixture
def forwarder(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    return Forwarder(repo, engine, pool)


@pytest.mark.asyncio
async def test_forward_agent_not_found(pool):
    repo = FakeAgentRepo(None)
    engine = FakeRoutingEngine(InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://a", weight=1))
    fwd = Forwarder(repo, engine, pool)
    request = _make_request()

    with pytest.raises(AgentNotFoundError):
        await fwd.forward(request, "agent-1", "ep-1", None)


@pytest.mark.asyncio
async def test_forward_endpoint_not_found(pool):
    agent = _make_agent()
    agent.endpoints = []
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://a", weight=1))
    fwd = Forwarder(repo, engine, pool)
    request = _make_request()

    with pytest.raises(EndpointNotFoundError):
        await fwd.forward(request, "agent-1", "ep-1", None)


@pytest.mark.asyncio
async def test_forward_method_mismatch(pool):
    agent = _make_agent()
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://a", weight=1))
    fwd = Forwarder(repo, engine, pool)
    request = _make_request(method="GET")

    response = await fwd.forward(request, "agent-1", "ep-1", None)
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_forward_block_success(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b'{"ok": true}'
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=mock_response)

    pool.create("agent-1", "http://localhost:8001")
    # Replace the client with our mock
    pool._clients["agent-1"] = mock_client

    request = _make_request(body=b'{"msg":"hi"}')
    response = await fwd.forward(request, "agent-1", "ep-1", None)

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b'{"ok": true}'


@pytest.mark.asyncio
async def test_forward_stream_success(pool):
    agent = _make_agent("stream")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    async def _aiter_bytes():
        yield b"data: hello\n\n"
        yield b"data: world\n\n"

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", None)

    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_forward_stream_cancelled(pool):
    agent = _make_agent("stream")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    cancel_event = asyncio.Event()

    async def _aiter_bytes():
        yield b"data: hello\n\n"
        cancel_event.set()
        yield b"data: world\n\n"

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.aiter_bytes = _aiter_bytes
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", cancel_event)

    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_forward_block_retry_on_5xx(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    bad_response = MagicMock(spec=httpx.Response)
    bad_response.status_code = 500
    bad_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=bad_response
    ))

    good_response = MagicMock(spec=httpx.Response)
    good_response.content = b'{"ok": true}'
    good_response.status_code = 200
    good_response.headers = {}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(side_effect=[
        httpx.HTTPStatusError("Server error", request=MagicMock(), response=bad_response),
        good_response,
    ])

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request = _make_request()
    response = await fwd.forward(request, "agent-1", "ep-1", None)

    assert response.status_code == 200
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_forward_block_no_retry_on_4xx(pool):
    agent = _make_agent("block")
    target = InstanceTarget(agent_id="agent-1", instance_id="inst-a", base_url="http://localhost:8001", weight=1)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine(target)
    fwd = Forwarder(repo, engine, pool)

    bad_response = MagicMock(spec=httpx.Response)
    bad_response.status_code = 404
    bad_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "Not found", request=MagicMock(), response=bad_response
    ))

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.request = AsyncMock(return_value=bad_response)

    pool.create("agent-1", "http://localhost:8001")
    pool._clients["agent-1"] = mock_client

    request = _make_request()
    with pytest.raises(httpx.HTTPStatusError):
        await fwd.forward(request, "agent-1", "ep-1", None)

    assert mock_client.request.call_count == 1
