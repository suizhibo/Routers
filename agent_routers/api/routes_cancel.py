from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agent_routers.adapters.audit_repo import AuditRepository
from agent_routers.adapters.request_repo import RequestTrackingRepository
from agent_routers.api.dependencies import AuthContext, get_auth
from agent_routers.services.coordination import CancelService, get_broadcaster, get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/requests", tags=["cancel"])


def get_cancel_service() -> CancelService:
    registry = get_registry()
    broadcaster = get_broadcaster()
    return CancelService(registry, broadcaster)


def get_request_repo(request: Request) -> RequestTrackingRepository:
    return cast(RequestTrackingRepository, request.app.state.request_repo)


def get_audit_repo(request: Request) -> AuditRepository:
    return cast(AuditRepository, request.app.state.audit_repo)


@router.post(
    "/{request_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel an in-flight request (creator or admin)",
)
async def cancel_request(
    request_id: str,
    auth: AuthContext = Depends(get_auth),
    cancel_svc: CancelService = Depends(get_cancel_service),
    request_repo: RequestTrackingRepository = Depends(get_request_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
) -> dict[str, str | bool]:
    if not auth.is_admin:
        active_request = await request_repo.get_by_request_id(request_id)
        user_subject = active_request.user_subject if active_request is not None else None

        if user_subject is None:
            audit_event = await audit_repo.get_by_request_id(request_id)
            user_subject = audit_event.user_subject if audit_event is not None else None

        if user_subject is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
        if user_subject != auth.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the request creator or admin can cancel",
            )

    cancelled = await cancel_svc.cancel(request_id)
    logger.info(
        "cancel_requested",
        extra={"request_id": request_id, "cancelled": cancelled, "caller": auth.sub},
    )
    return {"status": "accepted", "request_id": request_id, "cancelled": cancelled}
