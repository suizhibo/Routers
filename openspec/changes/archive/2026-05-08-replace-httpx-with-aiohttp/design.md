# Design: Replace httpx with aiohttp

## Dependency Changes

```toml
# pyproject.toml
[project]
dependencies = [
    ...
    "aiohttp>=3.9",        # was: "httpx>=0.27.0"
    ...
]
```

`httpx` is removed from `[project].dependencies`. Keep `httpx` *only* as a transitive dependency if something else pulls it; we don't import it anywhere after this change.

## Per-Agent Client Pool (`agent_routers/adapters/http_client.py`)

```python
from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)


class PerAgentClientPool:
    # Mirrors the prior httpx.Limits — 50 total, 20 keep-alive per host, 60s idle.
    CONNECTOR_KW = dict(
        limit=50,
        limit_per_host=20,
        keepalive_timeout=60.0,
    )
    # connect/read map directly; write/pool have no aiohttp counterpart and are dropped.
    TIMEOUT = aiohttp.ClientTimeout(
        sock_connect=2.0,
        sock_read=30.0,
        total=None,
    )

    def __init__(self) -> None:
        self._sessions: dict[str, aiohttp.ClientSession] = {}

    def create(self, agent_id: str, base_url: str) -> aiohttp.ClientSession:
        if agent_id in self._sessions:
            raise ValueError(f"Client for agent '{agent_id}' already exists")
        connector = aiohttp.TCPConnector(**self.CONNECTOR_KW)
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=self.TIMEOUT,
        )
        self._sessions[agent_id] = session
        logger.info("agent_client_created", extra={"agent_id": agent_id, "base_url": base_url})
        return session

    def get(self, agent_id: str) -> aiohttp.ClientSession | None:
        return self._sessions.get(agent_id)

    def destroy(self, agent_id: str) -> None:
        session = self._sessions.pop(agent_id, None)
        if session is not None:
            logger.info("agent_client_destroyed", extra={"agent_id": agent_id})

    async def close_all(self) -> None:
        for _agent_id, session in list(self._sessions.items()):
            await session.close()
        self._sessions.clear()
```

Note: `PerAgentClientPool.destroy()` does *not* close the session synchronously (matches current behavior). `close_all()` awaits session.close() for each — `aiohttp` requires `await` here. The class-level constants and the `get_client_pool()` singleton stay unchanged.

## Forwarder (`agent_routers/services/forwarder.py`)

### Imports
```python
import aiohttp        # was: import httpx
```

### Type signatures
- `_forward_block(self, client: aiohttp.ClientSession, ...)`
- `_forward_stream(self, client: aiohttp.ClientSession, ...)`
- `_extract_session_id(upstream: aiohttp.ClientResponse, endpoint: AgentEndpoint)` — and read body via `await upstream.json()`. Because `_extract_session_id` is currently `staticmethod` and synchronous, we change it to **async** and `await upstream.json()` inside the conditional branch. Callers (`_auto_create_session`) already run in an async context so this is a one-line `await` change.

### Block path
```python
async def _forward_block(
    self,
    client: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: dict[str, Any],
    body: Any,
    circuit_key: str,
) -> Response:
    kwargs: dict[str, Any] = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    try:
        async with client.request(method, url, **kwargs) as upstream:
            status = upstream.status
            content = await upstream.read()
            resp_headers = dict(upstream.headers)
            if 500 <= status <= 599:
                await _cb.record_failure(circuit_key)
                upstream.raise_for_status()  # raises ClientResponseError
            else:
                await _cb.record_success(circuit_key)
                upstream.raise_for_status()  # 4xx still raises; 2xx/3xx no-op
    except aiohttp.ClientResponseError as e:
        if 500 <= e.status <= 599:
            # already recorded above; no double-count
            pass
        raise
    return Response(
        content=content,
        status_code=status,
        headers=_filter_headers(resp_headers),
    )
```

Note: `aiohttp.ClientResponse.raise_for_status()` raises `ClientResponseError` for ≥400 statuses. We capture `status`, `content`, `resp_headers` *before* calling `raise_for_status()` so `tenacity` can retry on the resulting exception, and so that `_is_retryable_http_error` works on the propagated `ClientResponseError`.

### Stream path
```python
async def _forward_stream(
    self,
    client: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: dict[str, Any],
    body: Any,
    cancel_event: asyncio.Event | None,
    agent_id: str,
    session_id: str | None,
) -> StreamingResponse:
    kwargs: dict[str, Any] = {"headers": headers}
    if body is not None:
        kwargs["json"] = body

    async def generator() -> AsyncIterator[bytes]:
        try:
            async with client.request(method, url, **kwargs) as upstream:
                async for chunk in upstream.content.iter_any():
                    if cancel_event is not None and cancel_event.is_set():
                        logger.info("stream_cancelled")
                        break
                    yield chunk
        except asyncio.CancelledError:
            logger.info("stream_cancelled")
            raise

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "X-Preferred-Agent": agent_id,
            "X-Session-Id": session_id or "",
        },
    )
```

`response.content.iter_any()` yields whatever bytes have arrived on the socket, suitable for SSE. `iter_chunked(N)` would buffer until N bytes; not what we want.

### Auto-create-session path
```python
upstream = await client.request(
    endpoint.method, full_url,
    headers=session_headers, json=body_dict,
)
# Replace the `print(upstream.content)` debug line and switch to async context.
async with client.request(
    endpoint.method, full_url,
    headers=session_headers, json=body_dict,
) as upstream:
    upstream.raise_for_status()
    session_id = await self._extract_session_id(upstream, endpoint)
```

The current `print(upstream.content)` (forwarder.py:242) is a stray debug statement and is removed in this change.

### `_is_retryable_http_error`
```python
def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, aiohttp.ClientResponseError):
        return False
    return 500 <= exc.status <= 599
```

## Test Mocks (Unit + Contract)

We add a small helper to each affected test file (or a shared `tests/_aiohttp_mocks.py` if duplicated):

```python
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

def _mock_response(*, status=200, headers=None, body=b"", json_data=None) -> MagicMock:
    resp = MagicMock(spec=aiohttp.ClientResponse)
    resp.status = status
    resp.headers = headers or {}
    resp.read = AsyncMock(return_value=body)
    resp.json = AsyncMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    return resp

def _mock_request_cm(response):
    @asynccontextmanager
    async def _cm(*_a, **_kw):
        yield response
    return _cm

def _mock_session(*, request_response=None, stream_chunks=None, request_side_effect=None):
    session = MagicMock(spec=aiohttp.ClientSession)
    if request_response is not None:
        session.request = MagicMock(side_effect=lambda *a, **kw: _mock_request_cm(request_response)(*a, **kw))
    if request_side_effect is not None:
        session.request = MagicMock(side_effect=request_side_effect)
    if stream_chunks is not None:
        @asynccontextmanager
        async def _stream_cm(*_a, **_kw):
            upstream = MagicMock()
            async def aiter_any():
                for c in stream_chunks:
                    yield c
            upstream.content = MagicMock()
            upstream.content.iter_any = aiter_any
            yield upstream
        session.request = _stream_cm
    return session
```

Existing assertions on call args (`mock_client.request.call_args.kwargs["headers"]`) keep working because `session.request` is still the recorded MagicMock when we assign side effects. For the streaming flow, where `session.request` is replaced by a real async-context-manager function, tests that check call args switch to recording via a `MagicMock` wrapper around the CM.

## Integration Test (`tests/integration/test_agent_api.py`)

```python
import pytest
from starlette.testclient import TestClient

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
```

Test bodies drop `await` and `async`:
```python
def test_register_agent(client):
    resp = client.post("/v1/agents", json=payload)
    assert resp.status_code == 201
    ...
```

Fixture `db_session` remains async (`pytest_asyncio.fixture`); `client` becomes a sync fixture but accepts the async-yielded `db_session`. `pytest-asyncio` allows mixing — the async fixture is awaited by the framework before the sync fixture function runs.

## Script (`scripts/dynamic_test.py`)

Drop-in replacement of `httpx.AsyncClient(base_url=..., timeout=30)` with `aiohttp.ClientSession`:

```python
import aiohttp

async def run_tests():
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(base_url=BASE_URL, timeout=timeout) as client:
        async with client.get("/health") as r:
            record("GET /health", "PASS" if r.status == 200 else "FAIL", f"status={r.status}")
        ...
```

Each request becomes an `async with`. Status access changes from `r.status_code` → `r.status`. JSON body access changes from `r.json()` → `await r.json()`. Text body changes from `r.text` → `await r.text()`. The script does not introspect response headers, so most call sites are minimal one-liners.

## Files Touched

| File | Change |
|------|--------|
| `pyproject.toml` | swap `httpx>=0.27.0` for `aiohttp>=3.9` |
| `agent_routers/adapters/http_client.py` | `httpx.AsyncClient` → `aiohttp.ClientSession`; `Limits`+`Timeout` → `TCPConnector`+`ClientTimeout`; `aclose()` → `close()` |
| `agent_routers/services/forwarder.py` | switch type hints; rewrite `_forward_block`/`_forward_stream`; `_extract_session_id` becomes async; remove `print(upstream.content)` debug; update `_is_retryable_http_error` |
| `tests/unit/test_forwarder.py` | replace all `httpx.*` mocks with aiohttp helper; update streaming assertions; replace `httpx.HTTPStatusError` with `aiohttp.ClientResponseError` |
| `tests/unit/test_auto_session.py` | same as above |
| `tests/contract/test_cancel_sse.py` | replace `httpx.AsyncClient` mock; switch the inner upstream mock to expose `.content.iter_any` |
| `tests/integration/test_agent_api.py` | switch to `starlette.testclient.TestClient`; remove `await` in test bodies |
| `scripts/dynamic_test.py` | `httpx.AsyncClient` → `aiohttp.ClientSession`; `r.status_code` → `r.status`; `r.json()` → `await r.json()` |

No changes to `agent_routers/main.py` (only imports `get_client_pool()`, signature unchanged) or to `tests/integration/test_cancel_integration.py` (does not reference httpx).

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| aiohttp's `raise_for_status()` consumes the response, blocking subsequent `.read()` | We call `await upstream.read()` *before* `raise_for_status()` in `_forward_block`. |
| `_is_retryable_http_error` now matches a different exception class — tenacity's `retry_if_exception` will silently stop retrying if we miss this | Migration of `_is_retryable_http_error` is in the same commit as the import switch; covered by `test_forward_block_retry_on_5xx`. |
| `iter_any()` may yield `b""` empty chunks at EOF | `StreamingResponse` tolerates empty chunks; SSE consumers ignore them. No behavior change. |
| `TestClient` requires the app's lifespan to run — current fixture builds a fresh `FastAPI()` without a lifespan, so this is fine | Verified by reading `tests/integration/test_agent_api.py` lines 25-46: app is bare. |
| `aiohttp.TCPConnector` defaults `force_close=False` and shares DNS cache — same as our prior httpx setup | No mitigation needed. |
| Existing per-test `pool._clients["agent-1"] = mock_client` uses the dict directly — needs renaming to `_sessions` to match new attribute | Update test files in lockstep; renaming is mechanical. |
