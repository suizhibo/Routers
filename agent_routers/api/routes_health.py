from __future__ import annotations

from fastapi import APIRouter, Response, status

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe — always 200")
async def liveness() -> Response:
    return Response(status_code=status.HTTP_200_OK)


@router.get("/readiness", summary="Readiness probe — checks PG, Redis, JWKS")
async def readiness() -> Response:
    # TODO: implement actual dependency checks in Plan 2 (Auth/Quota/Audit)
    # v0.1 placeholders — always return 200 until infra deps are wired
    return Response(status_code=status.HTTP_200_OK)
