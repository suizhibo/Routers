import pytest
from unittest.mock import AsyncMock
from agent_routers.services.registry import AgentRegistry
from datetime import datetime, timezone
from agent_routers.schemas.agent import AgentRegistration, EndpointSpec
from agent_routers.errors import SubjectMismatchError, AgentConflictError, AgentNotFoundError


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def registry(mock_repo):
    return AgentRegistry(mock_repo)


@pytest.mark.asyncio
async def test_register_success(registry, mock_repo):
    mock_repo.get_subject.return_value = None
    mock_agent = AsyncMock()
    mock_agent.agent_id = "test-agent"
    mock_agent.name = "Test Agent"
    mock_agent.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_repo.create.return_value = mock_agent

    reg = AgentRegistration(
        agent_id="test-agent",
        name="Test Agent",
        subject="svc-test",
        base_url="http://localhost:8000",
        endpoints=[EndpointSpec(endpoint_type="chat", method="GET", path="/", mode="block")],
    )
    result = await registry.register(reg, jwt_subject="svc-test")
    assert result.agent_id == "test-agent"
    mock_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_register_subject_mismatch_raises(registry):
    reg = AgentRegistration(
        agent_id="test-agent",
        name="Test Agent",
        subject="svc-other",
        base_url="http://localhost:8000",
        endpoints=[EndpointSpec(endpoint_type="chat", method="GET", path="/", mode="block")],
    )
    with pytest.raises(SubjectMismatchError):
        await registry.register(reg, jwt_subject="svc-mismatch")


@pytest.mark.asyncio
async def test_get_agent_not_found(registry, mock_repo):
    mock_repo.get_by_id.return_value = None
    with pytest.raises(AgentNotFoundError):
        await registry.get_agent("nonexistent")
