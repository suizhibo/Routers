from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.http_client import PerAgentClientPool
from agent_routers.errors import AgentNotFoundError, AgentTimeoutError, EndpointNotFoundError
from agent_routers.models.agent import Agent, AgentEndpoint
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.forwarder import Forwarder
from agent_routers.services.routing import RoutingDecisionEngine


def _mock_response(
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    json_data=None,
    raise_for_status_exc: BaseException | None = None,
) -> MagicMock:
    resp = MagicMock(spec=aiohttp.ClientResponse)
    resp.status = status
    resp.headers = headers or {}
    resp.read = AsyncMock(return_value=body)
    resp.json = AsyncMock(return_value=json_data)
    if raise_for_status_exc is not None:
        resp.raise_for_status = MagicMock(side_effect=raise_for_status_exc)
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _make_response_error(status: int, message: str = "error") -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=status,
        message=message,
    )


def _request_cm_for(response: MagicMock):
    """Return a fresh async context manager that yields `response`."""
    @asynccontextmanager
    async def _cm(*_a, **_kw):
        yield response
    return _cm


def _stream_cm_yielding(chunks: list[bytes]):
    """Return a fresh async context manager that exposes `.content.iter_any()` yielding chunks."""
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


def _stream_cm_with_gate(chunks: list[bytes], cancel_event: asyncio.Event):
    """Stream CM that sets cancel_event after the first chunk yields."""
    @asynccontextmanager
    async def _cm(*_a, **_kw):
        async def aiter_any():
            for i, chunk in enumerate(chunks):
                yield chunk
                if i == 0:
                    cancel_event.set()
        upstream = MagicMock()
        upstream.content = MagicMock()
        upstream.content.iter_any = aiter_any
        yield upstream
    return _cm


def _mock_session(*, request_side_effect=None) -> MagicMock:
    session = MagicMock(spec=aiohttp.ClientSession)
    if request_side_effect is not None:
        session.request = MagicMock(side_effect=request_side_effect)
    return session


class FakeAgentRepo:
    def __init__(self, agent: Agent | None):
        self._agent = agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agent


class FakeRoutingEngine:
    def __init__(self, result: str):
        self._result = result

    async def resolve(self, route_req: RouteRequest, headers: dict) -> str:
        return self._result


def _make_agent(endpoint_mode: str = "block", param_mapping=None, session_config=None, body_schema=None) -> Agent:
    if param_mapping is None:
        param_mapping = {"path_params": {}, "query_params": {}, "body": None}
    agent = Agent(
        agent_id="agent-1",
        name="Test Agent",
        subject="sub-1",
        base_url="http://localhost:8001",
    )
    agent.endpoints = [
        AgentEndpoint(
            agent_id="agent-1",
            endpoint_type="chat",
            method="POST",
            path="/chat",
            path_params=[],
            query_params=[],
            body_schema=body_schema,
            mode=endpoint_mode,
            idempotent=False,
            param_mapping=param_mapping,
            session_config=session_config,
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


@pytest.fixture
def forwarder(pool):
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    return Forwarder(repo, engine, pool)


@pytest.mark.asyncio
async def test_forward_agent_not_found(pool):
    repo = FakeAgentRepo(None)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)
    request = _make_request()
    route_req = RouteRequest()

    with pytest.raises(AgentNotFoundError):
        await fwd.forward(request, route_req, None)


@pytest.mark.asyncio
async def test_forward_endpoint_not_found(pool):
    agent = _make_agent()
    agent.endpoints = []
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)
    request = _make_request()
    route_req = RouteRequest()

    with pytest.raises(EndpointNotFoundError):
        await fwd.forward(request, route_req, None)


@pytest.mark.asyncio
async def test_forward_block_success(pool):
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(
        status=200,
        headers={"content-type": "application/json"},
        body=b'{"ok": true}',
        json_data={"ok": True},
    )
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: _request_cm_for(response)())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request(body=b'{"msg":"hi"}')
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response_out = await fwd.forward(request, route_req, None)

    assert isinstance(response_out, Response)
    assert response_out.status_code == 200
    assert response_out.body == b'{"ok": true}'


@pytest.mark.asyncio
async def test_forward_stream_success(pool):
    agent = _make_agent("stream")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    cm = _stream_cm_yielding([b"data: hello\n\n", b"data: world\n\n"])
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request()
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response = await fwd.forward(request, route_req, None)

    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_forward_stream_cancelled(pool):
    agent = _make_agent("stream")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    cancel_event = asyncio.Event()
    cm = _stream_cm_with_gate(
        [b"data: hello\n\n", b"data: world\n\n"],
        cancel_event,
    )
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request()
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response = await fwd.forward(request, route_req, cancel_event)

    assert isinstance(response, StreamingResponse)


@pytest.mark.asyncio
async def test_forward_block_retry_on_5xx(pool):
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    bad_response = _mock_response(
        status=500,
        raise_for_status_exc=_make_response_error(500, "Server error"),
    )
    good_response = _mock_response(status=200, body=b'{"ok": true}')

    cm_bad = _request_cm_for(bad_response)
    cm_good = _request_cm_for(good_response)

    calls = {"n": 0}

    def side_effect(*a, **kw):
        calls["n"] += 1
        return cm_bad() if calls["n"] == 1 else cm_good()

    mock_session = _mock_session(request_side_effect=side_effect)

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request()
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response = await fwd.forward(request, route_req, None)

    assert response.status_code == 200
    assert mock_session.request.call_count == 2


@pytest.mark.asyncio
async def test_forward_block_no_retry_on_4xx(pool):
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    bad_response = _mock_response(
        status=404,
        raise_for_status_exc=_make_response_error(404, "Not found"),
    )
    cm_bad = _request_cm_for(bad_response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm_bad())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request()
    route_req = RouteRequest(context={"session_id": "sess-123"})
    with pytest.raises(aiohttp.ClientResponseError):
        await fwd.forward(request, route_req, None)

    assert mock_session.request.call_count == 1


@pytest.mark.asyncio
async def test_forward_block_read_timeout_returns_agent_timeout(pool):
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    timeout_response = _mock_response(status=200)
    timeout_response.read = AsyncMock(side_effect=aiohttp.SocketTimeoutError("read timed out"))
    cm_timeout = _request_cm_for(timeout_response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm_timeout())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request()
    route_req = RouteRequest(context={"session_id": "sess-123"})
    with pytest.raises(AgentTimeoutError):
        await fwd.forward(request, route_req, None)


@pytest.mark.asyncio
async def test_forward_stream_disables_socket_read_timeout(pool):
    agent = _make_agent("stream")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    cm = _stream_cm_yielding([b"data: hello\n\n"])
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request()
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response = await fwd.forward(request, route_req, None)
    assert isinstance(response, StreamingResponse)

    chunks = [chunk async for chunk in response.body_iterator]

    timeout = mock_session.request.call_args.kwargs["timeout"]
    assert chunks == [b"data: hello\n\n"]
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.sock_read is None


@pytest.mark.asyncio
async def test_forward_param_mapping_builds_url_and_body(pool):
    param_mapping = {
        "path_params": {"city": "input"},
        "query_params": {"days": "context.days"},
        "body": "input",
    }
    agent = _make_agent("block", param_mapping=param_mapping)
    agent.endpoints[0].method = "POST"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b"{}")
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    route_req = RouteRequest(input="NYC", context={"days": "7", "session_id": "sess-123"}, options={})
    request = _make_request()
    response_out = await fwd.forward(request, route_req, None)

    assert response_out.status_code == 200
    call_args = mock_session.request.call_args
    assert call_args.kwargs["json"] == "NYC"


@pytest.mark.asyncio
async def test_forward_get_ignores_body(pool):
    param_mapping = {
        "path_params": {"city": "input"},
        "query_params": {},
        "body": "input",
    }
    agent = _make_agent("block", param_mapping=param_mapping)
    agent.endpoints[0].method = "GET"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b"{}")
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    route_req = RouteRequest(input="NYC", context={"session_id": "sess-123"}, options={})
    request = _make_request()
    await fwd.forward(request, route_req, None)

    call_args = mock_session.request.call_args
    assert "json" not in call_args.kwargs


@pytest.mark.asyncio
async def test_forward_dict_body_mapping(pool):
    param_mapping = {
        "path_params": {},
        "query_params": {},
        "body": {"query": "input", "kb_ids": "options.knowledge_base_ids"},
    }
    agent = _make_agent("block", param_mapping=param_mapping)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b"{}")
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    route_req = RouteRequest(
        input="hello",
        context={"session_id": "sess-123"},
        options={"knowledge_base_ids": ["kb1"]},
    )
    request = _make_request()
    response_out = await fwd.forward(request, route_req, None)

    assert response_out.status_code == 200
    call_args = mock_session.request.call_args
    assert call_args.kwargs["json"] == {"query": "hello", "kb_ids": ["kb1"]}


@pytest.mark.asyncio
async def test_forward_dict_body_with_schema_defaults(pool):
    param_mapping = {
        "path_params": {},
        "query_params": {},
        "body": {"query": "input"},
    }
    body_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "disable_title": {"type": "boolean", "default": False},
        },
    }
    agent = _make_agent("block", param_mapping=param_mapping, body_schema=body_schema)
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b"{}")
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    route_req = RouteRequest(input="hello", context={"session_id": "sess-123"}, options={})
    request = _make_request()
    response_out = await fwd.forward(request, route_req, None)

    assert response_out.status_code == 200
    call_args = mock_session.request.call_args
    assert call_args.kwargs["json"] == {"query": "hello", "disable_title": False}


@pytest.mark.asyncio
async def test_forward_injects_auth_headers(pool):
    agent = _make_agent("block")
    agent.auth_header = "x-api-key"
    agent.auth_token = "secret-123"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(
        status=200,
        headers={"content-type": "application/json"},
        body=b'{"ok": true}',
        json_data={"ok": True},
    )
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = _make_request(body=b'{"msg":"hi"}')
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response_out = await fwd.forward(request, route_req, None)

    assert response_out.status_code == 200
    call_kwargs = mock_session.request.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "secret-123"


@pytest.mark.asyncio
async def test_forward_auth_overrides_downstream_header(pool):
    agent = _make_agent("block")
    agent.auth_header = "x-api-key"
    agent.auth_token = "agent-secret"
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b'{"ok": true}')
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-api-key", b"downstream-secret"),
        ],
        "path": "/v1/route",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request._body = b'{}'
    route_req = RouteRequest(context={"session_id": "sess-123"})
    await fwd.forward(request, route_req, None)

    call_kwargs = mock_session.request.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "agent-secret"


def _scope_with_headers(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "headers": headers,
        "path": "/v1/route",
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }


@pytest.mark.asyncio
async def test_forward_strips_hop_by_hop_headers_from_upstream(pool):
    """Content-Length / Host on the downstream request must not leak into
    the upstream call — body_bytes is rebuilt from param_mapping so the
    declared length is wrong and aiohttp would otherwise complain."""
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b'{"ok": true}')
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = Request(_scope_with_headers([
        (b"content-type", b"application/json"),
        (b"content-length", b"999"),
        (b"host", b"router.example.com"),
        (b"transfer-encoding", b"chunked"),
        (b"connection", b"keep-alive"),
    ]))
    request._body = b'{}'
    route_req = RouteRequest(context={"session_id": "sess-123"})
    await fwd.forward(request, route_req, None)

    forwarded = {k.lower() for k in mock_session.request.call_args.kwargs["headers"]}
    assert "content-length" not in forwarded
    assert "host" not in forwarded
    assert "transfer-encoding" not in forwarded
    assert "connection" not in forwarded


@pytest.mark.asyncio
async def test_forward_preserves_non_hop_by_hop_headers(pool):
    """Custom application headers (X-Trace-Id, Authorization, Accept) must
    pass through to the upstream unchanged."""
    agent = _make_agent("block")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    response = _mock_response(status=200, body=b"{}")
    cm = _request_cm_for(response)
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = Request(_scope_with_headers([
        (b"content-type", b"application/json"),
        (b"x-trace-id", b"trace-abc"),
        (b"authorization", b"Bearer ds-token"),
        (b"accept", b"application/json"),
    ]))
    request._body = b'{}'
    route_req = RouteRequest(context={"session_id": "sess-123"})
    await fwd.forward(request, route_req, None)

    forwarded = mock_session.request.call_args.kwargs["headers"]
    assert forwarded["x-trace-id"] == "trace-abc"
    assert forwarded["authorization"] == "Bearer ds-token"
    assert forwarded["accept"] == "application/json"


@pytest.mark.asyncio
async def test_forward_stream_strips_hop_by_hop_headers(pool):
    """Streaming path must apply the same hop-by-hop filtering."""
    agent = _make_agent("stream")
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    cm = _stream_cm_yielding([b"data: hi\n\n"])
    mock_session = _mock_session(request_side_effect=lambda *a, **kw: cm())

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = Request(_scope_with_headers([
        (b"content-type", b"application/json"),
        (b"content-length", b"999"),
        (b"host", b"router.example.com"),
    ]))
    request._body = b'{}'
    route_req = RouteRequest(context={"session_id": "sess-123"})
    response = await fwd.forward(request, route_req, None)
    async for _ in response.body_iterator:
        pass

    forwarded = {k.lower() for k in mock_session.request.call_args.kwargs["headers"]}
    assert "content-length" not in forwarded
    assert "host" not in forwarded


@pytest.mark.asyncio
async def test_auto_create_session_strips_hop_by_hop_headers(pool):
    """_auto_create_session must filter hop-by-hop headers when forwarding
    the create-session call to the upstream."""
    agent = Agent(
        agent_id="agent-1",
        name="Test Agent",
        subject="sub-1",
        base_url="http://localhost:8001",
    )
    agent.endpoints = [
        AgentEndpoint(
            agent_id="agent-1",
            endpoint_type="create_session",
            method="POST",
            path="/sessions",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config={"response_body_path": "session_id"},
        ),
        AgentEndpoint(
            agent_id="agent-1",
            endpoint_type="chat",
            method="POST",
            path="/chat",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={"path_params": {}, "query_params": {}, "body": None},
            session_config=None,
        ),
    ]
    repo = FakeAgentRepo(agent)
    engine = FakeRoutingEngine("agent-1")
    fwd = Forwarder(repo, engine, pool)

    create_response = _mock_response(
        status=200,
        headers={"content-type": "application/json"},
        body=b'{"session_id": "sess-new"}',
        json_data={"session_id": "sess-new"},
    )
    chat_response = _mock_response(status=200, body=b"{}")

    cm_create = _request_cm_for(create_response)
    cm_chat = _request_cm_for(chat_response)

    calls = {"n": 0}

    def side_effect(*a, **kw):
        calls["n"] += 1
        return cm_create() if calls["n"] == 1 else cm_chat()

    mock_session = _mock_session(request_side_effect=side_effect)

    pool.create("agent-1", "http://localhost:8001")
    pool._sessions["agent-1"] = mock_session

    request = Request(_scope_with_headers([
        (b"content-type", b"application/json"),
        (b"content-length", b"999"),
        (b"host", b"router.example.com"),
    ]))
    request._body = b'{}'
    route_req = RouteRequest()  # no session_id triggers _auto_create_session
    await fwd.forward(request, route_req, None)

    create_call_headers = mock_session.request.call_args_list[0].kwargs["headers"]
    forwarded = {k.lower() for k in create_call_headers}
    assert "content-length" not in forwarded
    assert "host" not in forwarded
