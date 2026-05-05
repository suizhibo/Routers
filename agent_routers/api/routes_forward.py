from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request

from agent_routers.api.dependencies import get_forwarder
from agent_routers.services.forwarder import Forwarder

router = APIRouter(prefix="/v1/route", tags=["route"])


@router.api_route(
    "/{agent_id}/{endpoint_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    summary="Forward request to target Agent endpoint",
)
async def route_request(
    request: Request,
    agent_id: str = Path(...),
    endpoint_id: str = Path(...),
    forwarder: Forwarder = Depends(get_forwarder),
):
    cancel_event = getattr(request.state, "cancel_event", None)
    return await forwarder.forward(request, agent_id, endpoint_id, cancel_event)
