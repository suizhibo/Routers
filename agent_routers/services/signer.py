from __future__ import annotations

import hmac
import hashlib

from agent_routers.config.settings import settings


class HmacSigner:
    def __init__(self, key: str | None = None):
        self._key = (key or settings.AUDIT_HMAC_KEY).encode()

    def canonical(self, request_id: str, timestamp_iso: str, user_subject: str,
                  agent_id: str, status_code: int, latency_ms: int,
                  request_body_digest: str, response_body_digest: str) -> str:
        return (
            f"{request_id}|{timestamp_iso}|{user_subject}|{agent_id}|"
            f"{status_code}|{latency_ms}|{request_body_digest}|{response_body_digest}"
        )

    def sign(self, canonical_string: str) -> str:
        return hmac.new(self._key, canonical_string.encode(), hashlib.sha256).hexdigest()

    def verify(self, canonical_string: str, signature: str) -> bool:
        expected = self.sign(canonical_string)
        return hmac.compare_digest(expected, signature)
