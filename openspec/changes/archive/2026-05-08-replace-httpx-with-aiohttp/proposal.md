# Proposal: Replace httpx with aiohttp

## Problem

The codebase uses `httpx` as the async HTTP client for upstream agent forwarding (`agent_routers/adapters/http_client.py`, `agent_routers/services/forwarder.py`), as well as in test mocks and integration scaffolding. The user's preferred client for new work is `aiohttp` (see `test.py`, which uses `aiohttp.ClientSession` directly). Maintaining two async HTTP clients in the same project hurts consistency and forces contributors to context-switch between two different client APIs (`AsyncClient.request` / `client.stream` vs `ClientSession.request` / `response.content.iter_chunked`).

## Scope

### In Scope
1. Replace `httpx.AsyncClient` in production code with `aiohttp.ClientSession` (per-agent session pool with shared `TCPConnector` semantics that mirror current `httpx.Limits`).
2. Replace block-mode forwarding (`Forwarder._forward_block`) — `await session.request(...)` then `await response.read()`.
3. Replace stream-mode forwarding (`Forwarder._forward_stream`) — switch from `client.stream(...) as upstream` + `upstream.aiter_bytes()` to `session.request(...) as response` + `response.content.iter_any()`.
4. Replace error type `httpx.HTTPStatusError` → `aiohttp.ClientResponseError`; update `_is_retryable_http_error` and the circuit-breaker failure callback.
5. Update auto-create-session response parsing (`_extract_session_id`) to use `aiohttp.ClientResponse` (`response.headers`, `await response.json()`).
6. Update `pyproject.toml`: drop `httpx>=0.27.0`, add `aiohttp>=3.9`.
7. Replace `httpx` mocks in unit/contract tests (`test_forwarder.py`, `test_auto_session.py`, `test_cancel_sse.py`) with `aiohttp.ClientSession` / `ClientResponse` mocks that match the new call shape.
8. Replace `httpx.AsyncClient(transport=ASGITransport(app=app))` in `tests/integration/test_agent_api.py` with `fastapi.testclient.TestClient` (sync API; rewrite `await client.post(...)` → `client.post(...)`).
9. Replace `httpx.AsyncClient` in `scripts/dynamic_test.py` with `aiohttp.ClientSession`.

### Out of Scope
- Switching the streaming protocol; SSE chunk semantics remain unchanged.
- Tuning timeouts/limits — preserve current values byte-for-byte.
- Changing routing, circuit-breaker thresholds, retry backoff — refactor only.
- Migrating the `redis` async client or any other async dependency.
- Removing `tenacity` or `purgatory`.

## Design Decisions

### One `ClientSession` per agent, mirroring the existing `PerAgentClientPool`
`aiohttp.ClientSession` is the conceptual equivalent of `httpx.AsyncClient`: stateful, holds a connection pool, must be `await session.close()`-d. We keep the per-agent pool shape so `forward()` / `_auto_create_session` continue to receive a session from `PerAgentClientPool.get(agent_id)`. No fan-in to a single shared session — per-agent isolation is preserved.

### Manual URL construction (no `base_url` reliance)
`aiohttp.ClientSession(base_url=...)` exists in 3.8+ but has stricter rules (must be absolute, no path component). Existing `Forwarder` already builds the full URL (`f"{base_url.rstrip('/')}/{url_path.lstrip('/')}"`) before calling the client, so we drop `base_url` from the session and continue to pass full URLs. This avoids edge cases when `base_url` has a path prefix.

### Limits → `TCPConnector`, Timeout → `ClientTimeout`
| httpx | aiohttp |
|-------|---------|
| `httpx.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=60.0)` | `aiohttp.TCPConnector(limit=50, limit_per_host=20, keepalive_timeout=60.0)` |
| `httpx.Timeout(connect=2.0, read=30.0, write=10.0, pool=5.0)` | `aiohttp.ClientTimeout(connect=2.0, sock_read=30.0, sock_connect=2.0, total=None)` |

`httpx.Timeout.write` and `pool` have no exact aiohttp counterpart. We map `connect` → `sock_connect`, `read` → `sock_read`. `pool` (acquire-from-pool wait) is unbounded in aiohttp — acceptable because `limit_per_host=20` already caps concurrency. `write` is dropped (aiohttp handles write timeouts via `sock_read` once the request is in flight).

### Streaming via `response.content.iter_any()`
`aiohttp` does not expose a `.stream()` context manager. Instead, the response itself is the async context manager and chunks are read off `response.content`:

```python
async with session.request(method, url, headers=headers, json=body) as response:
    async for chunk in response.content.iter_any():
        if cancel_event is not None and cancel_event.is_set():
            break
        yield chunk
```

`iter_any()` yields chunks as they arrive (preferred over `iter_chunked(N)` for SSE so we don't buffer until N bytes accumulate).

### Error mapping
- `httpx.HTTPStatusError` → `aiohttp.ClientResponseError`. Both carry `.status` (`status_code` in httpx) and trigger `raise_for_status()`.
- `_is_retryable_http_error` checks `isinstance(exc, aiohttp.ClientResponseError) and 500 <= exc.status <= 599`.
- aiohttp's `raise_for_status()` raises *immediately* inside the response context, before we can inspect headers — to keep the existing 5xx-then-circuit-breaker flow, we read `response.status` *before* calling `raise_for_status()`, exactly as the current code reads `upstream.status_code`.

### Integration test: `fastapi.testclient.TestClient`
`httpx.ASGITransport` has no aiohttp equivalent (aiohttp is a real-socket client). Rather than spin up a uvicorn server in-test (slow, flaky), we switch the integration test to FastAPI's bundled `TestClient` (which itself wraps starlette's `TestClient`, sync API on top of `httpx`). This keeps tests in-process, removes our explicit `httpx` import, and is the canonical way to test FastAPI apps when you don't need an event loop. Test bodies become sync (`response = client.post(...)` instead of `await ac.post(...)`).

### Test mocks
Unit tests currently `MagicMock(spec=httpx.AsyncClient)` and `MagicMock(spec=httpx.Response)`. We switch to `MagicMock(spec=aiohttp.ClientSession)` and a hand-rolled async-context-manager response factory, since `aiohttp.ClientResponse` is awkward to spec (constructor takes many args). The streaming mocks become async context managers returning an object with `.content.iter_any()`. We provide a small `_aiohttp_response()` helper in test files to keep mock construction concise.
