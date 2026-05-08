# Tasks: Fix Forwarder Content-Length Mismatch

## Task 1: Extend the hop-by-hop set
- [x] Add `"host"` to `_HOP_BY_HOP_HEADERS` in `agent_routers/services/forwarder.py`

## Task 2: Filter request headers in `_auto_create_session()`
- [x] Replace `session_headers = dict(request.headers)` with `session_headers = _filter_headers(dict(request.headers))`
- [x] Confirm agent-auth injection still runs *after* the filter so the agent token wins

## Task 3: Filter request headers in `forward()`
- [x] Replace `upstream_headers = dict(request.headers)` with `upstream_headers = _filter_headers(dict(request.headers))`
- [x] Confirm both block and stream branches receive the filtered dict

## Task 4: Tests (`tests/unit/test_forwarder.py`)
- [x] Test: when downstream sends `Content-Length`, the upstream `client.request` call does NOT include `content-length` in `headers`
- [x] Test: when downstream sends `Host`, the upstream call does NOT include `host`
- [x] Test: a non-hop-by-hop header (e.g. `X-Trace-Id`) is forwarded unchanged
- [x] Test: agent auth header still overrides a matching downstream header after filtering
- [x] Test: streaming path (`_forward_stream`) uses filtered headers as well
- [x] Test: `_auto_create_session()` filters headers before calling `client.request`

## Task 5: Manual verification
- [ ] Start the router locally, register an agent that requires a JSON body, send a downstream POST with a body, and confirm no `LocalProtocolError` is raised
- [ ] Confirm upstream receives the rebuilt body and `Content-Length` matches `len(body_bytes)`
