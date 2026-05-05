from agent_routers.errors import (
    AgentNotFoundError,
    AgentConflictError,
    SubjectMismatchError,
    ForbiddenError,
    ValidationError,
)


def test_error_to_dict():
    err = AgentNotFoundError("Agent xyz not found")
    d = err.to_dict()
    assert d["error"]["code"] == "agent_not_found"
    assert d["error"]["message"] == "Agent xyz not found"


def test_agent_conflict_error_code():
    err = AgentConflictError("conflict")
    assert err.code == "agent_conflict"
    assert err.status_code == 409


def test_validation_error():
    err = ValidationError("bad input")
    assert err.status_code == 400
    assert err.code == "validation_error"
