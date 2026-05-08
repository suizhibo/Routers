# Tasks: Audit Request and Response Content

## Task 1: Add settings and utilities
- [x] Add `AUDIT_MAX_BODY_BYTES: int = 65536` to `agent_routers/config/settings.py`
- [x] Add `_truncate_body()` and `_body_digest()` helpers in `agent_routers/middleware/audit.py`

## Task 2: Extend AuditEvent model and migration
- [x] Add `request_body: Mapped[str | None]` and `response_body: Mapped[str | None]` to `agent_routers/models/audit.py`
- [x] Generate Alembic migration: `alembic revision --autogenerate -m "add audit request and response body columns"`
- [x] Verify migration adds nullable `Text` columns with no default

## Task 3: Update HMAC signer
- [x] Extend `HmacSigner.canonical()` signature with `request_body_digest: str` and `response_body_digest: str`
- [x] Update canonical string format to append the two digests
- [x] Update all call sites (currently `audit.py` only) to pass the new arguments

## Task 4: Capture bodies in AuditMiddleware
- [x] Read `request.body()` before `call_next`
- [x] After `call_next`, read response body for non-streaming responses
- [x] Rebuild `Response` after reading body so downstream receives it intact
- [x] Use `"__stream__"` placeholder for `StreamingResponse`
- [x] Truncate bodies to `AUDIT_MAX_BODY_BYTES` with `…truncated` marker
- [x] Include `request_body` and `response_body` in the event dict passed to `_safe_write_audit`

## Task 5: Update AuditRepository
- [x] Map `request_body` and `response_body` from event dict into `AuditEvent` in `agent_routers/adapters/audit_repo.py`

## Task 6: Unit tests
- [x] Update `tests/unit/test_signer.py` for new canonical format
- [x] Test: request body ≤ limit is stored verbatim
- [x] Test: request body > limit is truncated with marker
- [x] Test: response body is captured for standard Response
- [x] Test: streaming response yields `"__stream__"` placeholder
- [x] Test: reconstructed response preserves status, headers, media_type
- [x] Test: signature verifies correctly with body digests

## Task 7: Integration tests
- [x] Create `tests/integration/test_audit_api.py` to assert audit rows contain expected request/response bodies
- [x] Verify truncation works end-to-end with a large body

## Task 8: Manual verification
- [x] Run migration locally and confirm columns exist
- [x] Tests verify audit events with request/response bodies are persisted correctly
- [x] Tests confirm signature verification passes with body digests
