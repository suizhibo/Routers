from __future__ import annotations

import jwt
from typing import Any

from agent_routers.config.settings import settings


def verify_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        key=settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
