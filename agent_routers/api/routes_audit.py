from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agent_routers.api.dependencies import get_auth, AuthContext
from agent_routers.adapters.audit_repo import AuditRepository

router = APIRouter(prefix="/v1/audit", tags=["audit"])


def get_audit_repo_from_app(request: Request) -> AuditRepository:
    return request.app.state.audit_repo


@router.get(
    "/{request_id}",
    summary="Get audit event by request ID (Admin only)",
)
async def get_audit_event(
    request_id: str,
    auth: AuthContext = Depends(get_auth),
    repo: AuditRepository = Depends(get_audit_repo_from_app),
):
    if not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    event = await repo.get_by_request_id(request_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit event not found")
    return {
        "request_id": event.request_id,
        "timestamp": event.timestamp.isoformat(),
        "user_subject": event.user_subject,
        "agent_id": event.agent_id,
        "endpoint_id": event.endpoint_id,
        "instance_id": event.instance_id,
        "method": event.method,
        "status_code": event.status_code,
        "latency_ms": event.latency_ms,
        "signature": event.signature,
    }
