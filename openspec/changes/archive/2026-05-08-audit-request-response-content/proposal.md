# Proposal: Audit Request and Response Content

## Problem

The current audit system (`AuditMiddleware` + `AuditEvent` model) only records high-level request metadata:

- `request_id`, `timestamp`, `user_subject`, `agent_id`, `method`, `status_code`, `latency_ms`
- `request_headers_digest` and `response_headers_digest` (both currently hardcoded to empty strings)
- An HMAC `signature` for tamper detection

It does **not** capture the actual request body sent by the client or the response body returned by the upstream agent. For a conversational AI router, this means the audit trail is incomplete — we know *that* a request happened, but not *what was said* or *what was returned*. This makes the audit log unsuitable for:

- Debugging routing or agent behavior after the fact
- Compliance / regulatory review of conversation content
- Security forensics on malicious or anomalous inputs

## Scope

### In Scope
1. Capture the downstream request body in `AuditMiddleware` and persist it in `audit_events.request_body`.
2. Capture the upstream response body in `AuditMiddleware` and persist it in `audit_events.response_body`.
3. Size-limit the stored content (e.g., 64 KiB per body) to prevent unbounded DB growth.
4. Add truncation markers (`…truncated`) when content exceeds the limit.
5. Update the `AuditEvent` SQLAlchemy model and generate an Alembic migration.
6. Update the HMAC `canonical()` / `sign()` payload to include body digests so the signature covers content integrity.
7. Unit and integration tests covering: body capture, truncation, signature verification with new payload.

### Out of Scope
- Streaming response body capture (SSE chunks) — for stream mode, record an empty or placeholder response body to avoid buffering an unbounded stream.
- Retroactive backfill of historical audit records.
- Compression or offloading large bodies to object storage.
- Changes to the non-content audit fields (headers digests remain out of scope unless requested separately).

## Design Decisions

### Synchronous body read via `request.body()` / `response.body`
`starlette.Request` provides `await request.body()` which buffers the entire body. We already buffer the body in the forwarding path, so the additional memory overhead in `AuditMiddleware` (innermost middleware) is acceptable. The response body is accessed via the `body` attribute on `StreamingResponse` subclasses; for non-streaming responses we read it directly.

### Size cap of 64 KiB per body
This matches common log-pipeline limits and keeps row sizes reasonable. The cap is configurable via `settings.AUDIT_MAX_BODY_BYTES` with a sensible default.

### Truncate with a Unicode ellipsis marker
When truncation occurs, replace the tail with `…truncated` so consumers know data was elided. This marker is included in the HMAC digest so tampering with the truncation state is detectable.

### Extend HMAC canonical string
The current canonical is `request_id|timestamp|user_subject|agent_id|status_code|latency_ms`. We append `|request_body_digest|response_body_digest` where each digest is `sha256(truncated_body).hex()[:16]`. Using a truncated hash keeps the canonical string compact while still binding the signature to the content.

### Streaming mode placeholder
For `StreamingResponse` (SSE), the response body cannot be consumed without interfering with the stream. We record `"__stream__"` as the response body and its digest in the canonical string, making it explicit that the audit entry represents a streaming exchange.
