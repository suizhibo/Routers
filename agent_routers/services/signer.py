from __future__ import annotations

import hmac
import hashlib

from agent_routers.config.settings import settings


class HmacSigner:
    def __init__(self, key: str | None = None):
        self._key = (key or settings.AUDIT_HMAC_KEY).encode()

    def canonical(self, request_id: str, timestamp_iso: str, user_subject: str,
                  agent_id: str, status_code: int, latency_ms: int) -> str:
        return f"{request_id}|{timestamp_iso}|{user_subject}|{agent_id}|{status_code}|{latency_ms}"

    def sign(self, canonical_string: str) -> str:
        return hmac.new(self._key, canonical_string.encode(), hashlib.sha256).hexdigest()

    def verify(self, canonical_string: str, signature: str) -> bool:
        expected = self.sign(canonical_string)
        return hmac.compare_digest(expected, signature)
