from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from agent_routers.api.dependencies import get_auth, AuthContext
from agent_routers.services.coordination import get_registry, get_broadcaster, CancelService
from agent_routers.adapters.audit_repo import AuditRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/requests", tags=["cancel"])


def get_cancel_service() -> CancelService:
    registry = get_registry()
    broadcaster = get_broadcaster()
    return CancelService(registry, broadcaster)


@router.post(
    "/{request_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel an in-flight request (creator or admin)",
)
async def cancel_request(
    request_id: str,
    auth: AuthContext = Depends(get_auth),
    cancel_svc: CancelService = Depends(get_cancel_service),
    audit_repo: AuditRepository = Depends(lambda req: req.app.state.audit_repo),
):
    if not auth.is_admin:
        audit_event = await audit_repo.get_by_request_id(request_id)
        if audit_event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
        if audit_event.user_subject != auth.sub:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the request creator or admin can cancel")

    cancelled = await cancel_svc.cancel(request_id)
    logger.info("cancel_requested", extra={"request_id": request_id, "cancelled": cancelled, "caller": auth.sub})
    return {"status": "accepted", "request_id": request_id, "cancelled": cancelled}
