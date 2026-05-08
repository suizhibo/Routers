# Proposal: Fix Forwarder Content-Length Mismatch

## Problem

`Forwarder._auto_create_session()` and `Forwarder.forward()` build the upstream request by copying the downstream `request.headers` verbatim (`session_headers = dict(request.headers)` / `upstream_headers = dict(request.headers)`), then pass a freshly serialized `body_bytes` produced from the agent's `param_mapping`. The two are unrelated:

- `Content-Length` in the copied headers describes the **incoming** body the client sent to us.
- `body_bytes` is whatever `_build_request()` synthesized from the route request's mapped fields — typically a different length, often shorter or empty.

`httpx` honours an explicit `Content-Length` header rather than recomputing it from `content`, so when the declared length exceeds the actual bytes we get:

```
httpx._util.LocalProtocolError: Too little data for declared Content-Length
```

Other downstream-only headers (`Host`, `Transfer-Encoding`, `Content-Encoding`, etc.) have the same shape of bug — they describe the connection between the client and the router, not the connection between the router and the upstream agent.

We already have `_filter_headers()` and `_HOP_BY_HOP_HEADERS`, but they are only applied to the *response* side (line 337). Request-side forwarding is unfiltered.

## Scope

### In Scope
1. Apply `_filter_headers()` to the request-side headers in `_auto_create_session()` and `forward()` before injecting agent auth and calling `client.request()` / `client.stream()`.
2. Add `host` to `_HOP_BY_HOP_HEADERS` so the upstream `Host` header is derived from the upstream URL by `httpx`, not from the downstream client.
3. Unit tests covering: (a) Content-Length is not forwarded, (b) Host is not forwarded, (c) other custom headers (e.g. `X-Trace-Id`) still pass through, (d) agent auth still wins over a downstream header with the same name.

### Out of Scope
- Changes to the response-side header filtering (already correct).
- Retry, streaming, or circuit-breaker behavior.
- Body transformation rules in `_build_request()`.
- Adding compression / re-encoding support.

## Design Decisions

### Reuse existing `_filter_headers()`
The function and the hop-by-hop set already exist for the response path. Applying the same filter on the request path keeps a single source of truth for which headers are connection-scoped vs end-to-end.

### Strip `Host` along with the standard hop-by-hop set
`Host` is technically end-to-end per RFC, but in a forwarding proxy it must reflect the upstream origin, not the downstream one. `httpx` populates it correctly from the request URL when no explicit value is supplied. Adding it to `_HOP_BY_HOP_HEADERS` keeps the filtering centralized rather than introducing a separate "request-only strip" list.

### Filter before injecting agent auth
Agent auth (`agent.auth_header` / `agent.auth_token`) must remain authoritative — filtering first and injecting after preserves the existing precedence rule from the agent-auth-credentials change: the agent's token always wins over any matching downstream header.
