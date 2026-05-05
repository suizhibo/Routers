from __future__ import annotations

import jwt
import logging
from typing import Any

from jwt import PyJWKClient

from agent_routers.config.settings import settings

logger = logging.getLogger(__name__)


class JWKSClient:
    def __init__(self, jwks_url: str, iss: str, aud: str):
        self._jwks_url = jwks_url
        self._iss = iss
        self._aud = aud
        self._client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=600,  # 10 minutes
        )

    def verify(self, token: str) -> dict[str, Any]:
        key = self._client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=self._iss,
            audience=self._aud,
            options={"require": ["exp", "iat", "sub"]},
        )
        return claims

    def verify_with_retry(self, token: str) -> dict[str, Any]:
        try:
            return self.verify(token)
        except jwt.InvalidTokenError:
            pass

        self._client = PyJWKClient(
            self._jwks_url,
            cache_keys=False,
        )
        try:
            return self.verify(token)
        except jwt.InvalidTokenError:
            logger.error("jwks_verify_failed_after_refresh", extra={"token": token[:20]})
            raise

    def verify_or_use_cached(self, token: str) -> dict[str, Any]:
        try:
            return self.verify_with_retry(token)
        except jwt.InvalidTokenError:
            pass

        logger.warning("jwks_idp_unreachable_using_expired_cache")
        expired_client = PyJWKClient(self._jwks_url, cache_keys=True, lifespan=0)
        try:
            key = expired_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token, key.key, algorithms=["RS256"],
                issuer=self._iss, audience=self._aud,
                options={"require": ["exp", "iat", "sub"], "verify_exp": False},
            )
        except jwt.InvalidTokenError:
            raise


_jwks_client: JWKSClient | None = None


def get_jwks_client() -> JWKSClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = JWKSClient(settings.JWKS_URL, settings.JWT_ISS, settings.JWT_AUD)
    return _jwks_client
