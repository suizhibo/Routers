from __future__ import annotations


class AgentRoutersError(Exception):
    code: str = "internal_error"
    status_code: int = 500

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": str(self), "request_id": None}}


class AgentNotFoundError(AgentRoutersError):
    code = "agent_not_found"
    status_code = 404


class EndpointNotFoundError(AgentRoutersError):
    code = "endpoint_not_found"
    status_code = 404


class AgentConflictError(AgentRoutersError):
    code = "agent_conflict"
    status_code = 409


class SubjectMismatchError(AgentRoutersError):
    code = "auth_invalid"
    status_code = 401


class ForbiddenError(AgentRoutersError):
    code = "forbidden"
    status_code = 403


class ValidationError(AgentRoutersError):
    code = "validation_error"
    status_code = 400
