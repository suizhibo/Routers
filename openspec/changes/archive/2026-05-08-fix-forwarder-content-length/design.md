# Design: Fix Forwarder Content-Length Mismatch

## Header Filtering

Extend the existing hop-by-hop set in `agent_routers/services/forwarder.py`:

```python
_HOP_BY_HOP_HEADERS = {
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "host",  # NEW — must be derived from the upstream URL
}
```

`_filter_headers()` is unchanged.

## Forwarder Call Sites

### `_auto_create_session()` (~line 234)

```python
session_headers = _filter_headers(dict(request.headers))
if agent.auth_header and agent.auth_token:
    session_headers[agent.auth_header] = agent.auth_token

upstream = await client.request(
    endpoint.method, full_url,
    headers=session_headers, content=body_bytes,
)
```

### `forward()` (~line 282)

```python
upstream_headers = _filter_headers(dict(request.headers))
if agent.auth_header and agent.auth_token:
    upstream_headers[agent.auth_header] = agent.auth_token
```

The filtered dict is then passed to `_forward_block()` / `_forward_stream()` unchanged.

## Precedence

`_filter_headers()` runs first (drops content-length, host, etc.), then agent auth is injected. Agent auth therefore continues to override any downstream header that matches `agent.auth_header`, matching the contract established in `agent-auth-credentials`.

## Files to Change

| File | Change |
|------|--------|
| `agent_routers/services/forwarder.py` | Add `host` to `_HOP_BY_HOP_HEADERS`; apply `_filter_headers()` to request headers in `_auto_create_session()` and `forward()`. |
| `tests/unit/test_forwarder.py` | New tests for request-header filtering (Content-Length stripped, Host stripped, custom headers preserved, agent auth precedence preserved). |

No schema, migration, or API surface changes.

## Risk / Compatibility

- Existing callers that depend on `Host` or `Content-Length` reaching the upstream verbatim are broken by design — the upstream agent should be receiving values that describe the router→upstream connection, not the client→router connection.
- Custom application headers (`Authorization`, `X-Trace-Id`, `Accept`, etc.) are unaffected since they are not in the hop-by-hop set.
- The fix is internal; no public API or persisted-state changes, so no migration is needed.
