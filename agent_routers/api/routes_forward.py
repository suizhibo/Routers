from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from agent_routers.api.dependencies import get_forwarder
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.coordination import get_registry
from agent_routers.services.forwarder import Forwarder

router = APIRouter(prefix="/v1/route", tags=["route"])


@router.post(
    "",
    summary="Forward request to target Agent endpoint",
)
async def route_request(
    request: Request,
    route_req: RouteRequest,
    forwarder: Forwarder = Depends(get_forwarder),
):
    registry = get_registry()
    request_id = getattr(request.state, "request_id", "")
    async with registry.track(request_id) as cancel_event:
        request.state.cancel_event = cancel_event
        return await forwarder.forward(request, route_req, cancel_event)
