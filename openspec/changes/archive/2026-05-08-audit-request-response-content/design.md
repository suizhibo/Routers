# Design: Audit Request and Response Content

## Database Schema

Add two columns to `audit_events`:

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `request_body` | `Text` | Yes | `NULL` | Truncated downstream request body (UTF-8) |
| `response_body` | `Text` | Yes | `NULL` | Truncated upstream response body (UTF-8) or `"__stream__"` |

Alembic migration: add nullable `Text` columns. No backfill required — existing rows remain `NULL`.

## Model Changes

### `agent_routers/models/audit.py`

```python
request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
```

## Middleware Changes

### `agent_routers/middleware/audit.py`

```python
MAX_BODY_BYTES = settings.AUDIT_MAX_BODY_BYTES  # default 65536
TRUNCATION_MARKER = "…truncated"


def _truncate_body(body: bytes) -> str:
    if len(body) <= MAX_BODY_BYTES:
        return body.decode("utf-8", errors="replace")
    truncated = body[:MAX_BODY_BYTES]
    return truncated.decode("utf-8", errors="replace") + TRUNCATION_MARKER


def _body_digest(body_text: str) -> str:
    return hashlib.sha256(body_text.encode()).hexdigest()[:16]
```

In `dispatch()`:

```python
request_body_bytes = await request.body()
request_body_text = _truncate_body(request_body_bytes)
request_body_digest = _body_digest(request_body_text)

response = await call_next(request)

if isinstance(response, StreamingResponse):
    response_body_text = "__stream__"
else:
    response_body_bytes = await response.body()
    response_body_text = _truncate_body(response_body_bytes)

response_body_digest = _body_digest(response_body_text)

# Update canonical and signature
canonical = self._signer.canonical(
    request_id=request_id,
    timestamp_iso=timestamp,
    user_subject=user_subject,
    agent_id=agent_id,
    status_code=response.status_code,
    latency_ms=latency_ms,
    request_body_digest=request_body_digest,
    response_body_digest=response_body_digest,
)
signature = self._signer.sign(canonical)

event = {
    ...,
    "request_body": request_body_text,
    "response_body": response_body_text,
    "signature": signature,
}
```

### Important: preserve response for downstream
After reading `response.body()`, reconstruct the response so the caller still receives it. For standard `Response` objects, create a new `Response` with the same status, headers, and media_type.

```python
if not isinstance(response, StreamingResponse):
    response_body_bytes = await response.body()
    response_body_text = _truncate_body(response_body_bytes)
    # Rebuild response so downstream gets the body
    response = Response(
        content=response_body_bytes,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
```

## Signer Changes

### `agent_routers/services/signer.py`

```python
def canonical(self, request_id: str, timestamp_iso: str, user_subject: str,
              agent_id: str, status_code: int, latency_ms: int,
              request_body_digest: str, response_body_digest: str) -> str:
    return (
        f"{request_id}|{timestamp_iso}|{user_subject}|{agent_id}|"
        f"{status_code}|{latency_ms}|{request_body_digest}|{response_body_digest}"
    )
```

All existing callers must be updated to pass the two new digest arguments.

## Repository Changes

### `agent_routers/adapters/audit_repo.py`

Map `request_body` and `response_body` from the event dict into the `AuditEvent` constructor.

## Files to Change

| File | Change |
|------|--------|
| `agent_routers/models/audit.py` | Add `request_body` and `response_body` mapped columns. |
| `agent_routers/middleware/audit.py` | Read and truncate request/response bodies; rebuild non-streaming response; pass digests to signer; include bodies in event dict. |
| `agent_routers/services/signer.py` | Extend `canonical()` signature with `request_body_digest` and `response_body_digest`. |
| `agent_routers/adapters/audit_repo.py` | Map new fields from event dict to model. |
| `agent_routers/config/settings.py` | Add `AUDIT_MAX_BODY_BYTES` setting (default 65536). |
| `alembic/versions/` | New migration adding `request_body` and `response_body` columns. |
| `tests/unit/test_signer.py` | Update canonical/signature tests for new payload format. |
| `tests/unit/test_audit_middleware.py` (or new file) | Tests for body capture, truncation, stream placeholder, response reconstruction. |
| `tests/integration/test_audit_api.py` | Integration tests verifying persisted rows contain expected bodies. |

## Risk / Compatibility

- **Breaking change for signature verification**: Any external system verifying audit signatures must update its canonical string construction to include the two new digest fields. Document this in the PR.
- **Memory pressure**: Buffering both request and response bodies in middleware increases per-request memory. The 64 KiB cap limits this.
- **Response reconstruction**: Rebuilding `Response` after reading `.body()` must preserve all headers and media types. Missing headers could break clients.
- **Streaming**: SSE responses will show `"__stream__"` as the response body in audit. This is explicit and avoids consuming the generator.
