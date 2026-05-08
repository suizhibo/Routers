# Tasks: Replace httpx with aiohttp

## Task 1: Dependency Swap
- [x] In `pyproject.toml`, remove `"httpx>=0.27.0"` from `[project].dependencies`
- [x] Add `"aiohttp>=3.9"` to `[project].dependencies`
- [x] Re-install: `pip install -e ".[dev]"` and confirm `aiohttp` is importable

## Task 2: Rewrite `PerAgentClientPool`
- [x] Replace `import httpx` with `import aiohttp` in `agent_routers/adapters/http_client.py`
- [x] Replace class attribute `LIMITS = httpx.Limits(...)` with a `CONNECTOR_KW = dict(limit=50, limit_per_host=20, keepalive_timeout=60.0)` dict
- [x] Replace `TIMEOUT = httpx.Timeout(...)` with `aiohttp.ClientTimeout(sock_connect=2.0, sock_read=30.0, total=None)`
- [x] Rename `self._clients` to `self._sessions` (or keep `_clients` if you prefer; whichever you choose, propagate to test files in Task 6)
- [x] In `create()`, build `aiohttp.TCPConnector(**self.CONNECTOR_KW)` and pass it to `aiohttp.ClientSession(connector=..., timeout=self.TIMEOUT)`
- [x] Drop `base_url`, `http2`, `follow_redirects` arguments — Forwarder builds full URLs already; aiohttp follows redirects by default
- [x] Update `get()` return type to `aiohttp.ClientSession | None`
- [x] In `close_all()`, call `await session.close()` instead of `await client.aclose()`
- [x] Confirm `destroy()` still pops without awaiting (pool dictates lifecycle, not the call site)

## Task 3: Rewrite Forwarder Block Path
- [x] Replace `import httpx` with `import aiohttp` in `agent_routers/services/forwarder.py`
- [x] Update `_is_retryable_http_error` to check `aiohttp.ClientResponseError` and `exc.status` (not `exc.response.status_code`)
- [x] Change `_forward_block` signature: `client: aiohttp.ClientSession`
- [x] Inside `_forward_block`, replace `upstream = await client.request(...)` with `async with client.request(...) as upstream:`
- [x] Inside the context, capture `status = upstream.status`, `content = await upstream.read()`, `resp_headers = dict(upstream.headers)` *before* `raise_for_status()`
- [x] Move circuit-breaker `record_failure` / `record_success` to use `status` (now an int from `upstream.status`)
- [x] Replace `except httpx.HTTPStatusError as e: ... e.response.status_code` with `except aiohttp.ClientResponseError as e: ... e.status`
- [x] Build the returned `Response(content=content, status_code=status, headers=_filter_headers(resp_headers))` from the captured values

## Task 4: Rewrite Forwarder Stream Path
- [x] Change `_forward_stream` signature: `client: aiohttp.ClientSession`
- [x] Replace `async with client.stream(method, url, **kwargs) as upstream:` with `async with client.request(method, url, **kwargs) as upstream:`
- [x] Replace `async for chunk in upstream.aiter_bytes():` with `async for chunk in upstream.content.iter_any():`
- [x] Keep the `cancel_event.is_set()` check in the loop body unchanged
- [x] Keep the outer `except asyncio.CancelledError` re-raise unchanged

## Task 5: Rewrite Auto-Create-Session Path
- [x] In `_auto_create_session`, replace `upstream = await client.request(...)` with `async with client.request(...) as upstream:` block
- [x] Move `upstream.raise_for_status()` and `session_id = ...` *inside* the `async with`
- [x] **Delete the stray `print(upstream.content)` debug line** (forwarder.py:242)
- [x] Convert `_extract_session_id` to `async`; replace `upstream.json()` with `await upstream.json()`
- [x] Update the call site to `await self._extract_session_id(upstream, endpoint)`
- [x] Update `_extract_session_id` type hint: `upstream: aiohttp.ClientResponse`
- [x] Wrap `await upstream.json()` in `try/except (aiohttp.ContentTypeError, ValueError, json.JSONDecodeError)` (currently catches `json.JSONDecodeError, ValueError`) — `ContentTypeError` is what aiohttp raises when content-type doesn't match

## Task 6: Update Unit Test Mocks (`tests/unit/test_forwarder.py`)
- [x] Replace `import httpx` with `import aiohttp` and (if helpful) add `from contextlib import asynccontextmanager`
- [x] Add the `_mock_response`, `_mock_request_cm`, `_mock_session` helpers from design.md (or create `tests/_aiohttp_mocks.py` if you'd rather share)
- [x] Replace every `MagicMock(spec=httpx.Response)` with a `_mock_response(...)` call passing `status`, `headers`, `body`, `json_data`
- [x] Replace every `MagicMock(spec=httpx.AsyncClient)` with `_mock_session(...)` returning the right CM
- [x] Where the existing `pool._clients["agent-1"] = mock_client` is set: rename to `pool._sessions["agent-1"] = mock_session` (matching the rename from Task 2)
- [x] Update `test_forward_block_retry_on_5xx`: replace `side_effect=[httpx.HTTPStatusError(...), good_response]` with a side-effect list whose CMs raise `aiohttp.ClientResponseError(...)` then yield the good response
- [x] Update `test_forward_block_no_retry_on_4xx`: `pytest.raises(aiohttp.ClientResponseError)` instead of `httpx.HTTPStatusError`
- [x] Update assertions on `mock_client.request.call_args.kwargs["headers"]` etc. — `session.request` is now a `MagicMock` whose side effect returns a CM, so `call_args` is still recorded
- [x] Update streaming tests (`test_forward_stream_success`, `test_forward_stream_cancelled`, `test_forward_stream_strips_hop_by_hop_headers`): the inner upstream mock now exposes `.content.iter_any` instead of `.aiter_bytes`
- [x] Update `test_auto_create_session_strips_hop_by_hop_headers`: the create_response mock needs `read = AsyncMock`, `json = AsyncMock`, and to be yielded from a CM that the side-effect-list returns

## Task 7: Update Unit Test Mocks (`tests/unit/test_auto_session.py`)
- [x] Same import swap (`import aiohttp` instead of `httpx`)
- [x] Adapt the create-session response mock to expose `await response.json()` returning `{"data": {"id": "sess-abc123"}}`
- [x] Wrap it in an async context manager so the new `async with client.request(...)` form works
- [x] Adapt the chat-stream mock so `.content.iter_any` yields the test chunks

## Task 8: Update Contract Test (`tests/contract/test_cancel_sse.py`)
- [x] Replace `import httpx` with `import aiohttp`
- [x] In `_stream_client`, the inner `upstream` mock currently sets `upstream.aiter_bytes = aiter_bytes`. Replace with `upstream.content = MagicMock(); upstream.content.iter_any = aiter_bytes` (where `aiter_bytes` is the same async generator function)
- [x] Replace `client = MagicMock(spec=httpx.AsyncClient)` with `client = MagicMock(spec=aiohttp.ClientSession)`
- [x] Replace `client.stream = stream_cm` with `client.request = stream_cm` (the `_forward_stream` now uses `client.request(...)`)
- [x] **Note**: contract tests currently call `_forward_stream(..., circuit_key=...)` — design.md uses `agent_id`/`session_id`; do not change the test signature unless the prod signature is also being updated. The pre-existing 4 failures noted in AGENTS.md should remain pre-existing failures.

## Task 9: Update Integration Test (`tests/integration/test_agent_api.py`)
- [x] Replace `from httpx import AsyncClient, ASGITransport` with `from starlette.testclient import TestClient`
- [x] Change the `client` fixture: drop `pytest_asyncio.fixture`, use plain `@pytest.fixture`; replace the `async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac` with `with TestClient(app) as tc: yield tc`
- [x] Convert each test from `async def test_...(client)` + `await client.post(...)` to `def test_...(client)` + `client.post(...)`
- [x] Drop `@pytest.mark.asyncio` decorators on these tests
- [x] `db_session` fixture stays async (it owns the engine lifecycle)

## Task 10: Update Script (`scripts/dynamic_test.py`)
- [x] Replace `import httpx` with `import aiohttp`
- [x] Replace `httpx.AsyncClient(base_url=BASE_URL, timeout=30)` with `aiohttp.ClientSession(base_url=BASE_URL, timeout=aiohttp.ClientTimeout(total=30))`
- [x] For every `r = await client.get(...)` / `r = await client.post(...)` / `r = await client.delete(...)`, switch to `async with client.<method>(...) as r:` and indent the assertions/`record(...)` call into the block
- [x] Replace `r.status_code` with `r.status` everywhere
- [x] Replace `r.text[:500]` with `(await r.text())[:500]` (aiohttp's `.text()` is async)
- [ ] Confirm the script still passes by running `python3 scripts/dynamic_test.py` against a running server (manual smoke test)

## Task 11: Verification
- [x] Run `python3 -m ruff check agent_routers tests scripts` — no new lint violations from the changes
- [x] Run `python3 -m mypy agent_routers` — no new type errors (existing 72 pre-existing errors stay, but the diff should not add)
- [x] Run `python3 -m pytest tests/unit` — 85 passed, 1 pre-existing failure (`test_register_subject_mismatch_raises`)
- [x] Run `python3 -m pytest tests/integration` — 9 passed, 1 pre-existing failure (`test_register_subject_mismatch`)
- [x] Run `python3 -m pytest tests/contract` — same 4 pre-existing failures, no new ones
- [x] `grep -rn "httpx" agent_routers tests scripts pyproject.toml` returns nothing (or only false positives)
- [ ] Manual smoke: start the app (`uvicorn agent_routers.main:app`) plus a stub upstream, register an agent, send `POST /v1/route` with a streaming endpoint, observe SSE chunks delivered without buffering
