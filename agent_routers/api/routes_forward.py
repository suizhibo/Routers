from __future__ import annotations

from typing import AsyncIterator, cast

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response, StreamingResponse

from agent_routers.adapters.request_repo import RequestTrackingRepository
from agent_routers.api.dependencies import AuthContext, get_auth, get_forwarder
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.coordination import get_registry
from agent_routers.services.forwarder import Forwarder

router = APIRouter(prefix="/v1/route", tags=["route"])


def get_request_repo(request: Request) -> RequestTrackingRepository:
    return cast(RequestTrackingRepository, request.app.state.request_repo)


@router.post(
    "",
    summary="Forward request to target Agent endpoint",
)
async def route_request(
    request: Request,
    route_req: RouteRequest,
    auth: AuthContext = Depends(get_auth),
    forwarder: Forwarder = Depends(get_forwarder),
    request_repo: RequestTrackingRepository = Depends(get_request_repo),
) -> Response:
    registry = get_registry()
    request_id = getattr(request.state, "request_id", "")
    cancel_event = registry.start_tracking(request_id)
    request.state.cancel_event = cancel_event
    await request_repo.create(request_id=request_id, user_subject=auth.sub)

    async def cleanup() -> None:
        registry.stop_tracking(request_id)
        await request_repo.delete(request_id)

    try:
        response = await forwarder.forward(request, route_req, cancel_event)
    except Exception:
        await cleanup()
        raise

    if isinstance(response, StreamingResponse):
        original_iterator = response.body_iterator

        async def tracked_stream() -> AsyncIterator[str | bytes | memoryview[int]]:
            try:
                async for chunk in original_iterator:
                    yield chunk
            finally:
                await cleanup()

        response.body_iterator = tracked_stream()
        return response

    await cleanup()
    return response
