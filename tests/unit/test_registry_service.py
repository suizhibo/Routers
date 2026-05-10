from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from agent_routers.errors import AgentConflictError, AgentNotFoundError, SubjectMismatchError
from agent_routers.schemas.agent import AgentRegistration, EndpointSpec
from agent_routers.services.registry import AgentRegistry


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
async def test_register_conflicting_existing_subject_raises(registry, mock_repo):
    mock_repo.get_subject.return_value = "svc-existing"
    reg = AgentRegistration(
        agent_id="test-agent",
        name="Test Agent",
        subject="svc-test",
        base_url="http://localhost:8000",
        endpoints=[EndpointSpec(endpoint_type="chat", method="GET", path="/", mode="block")],
    )

    with pytest.raises(AgentConflictError):
        await registry.register(reg, jwt_subject="svc-test")

    mock_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_not_found(registry, mock_repo):
    mock_repo.get_by_id.return_value = None
    with pytest.raises(AgentNotFoundError):
        await registry.get_agent("nonexistent")


@pytest.mark.asyncio
async def test_get_agent_masks_auth_token(registry, mock_repo):
    from datetime import datetime, timezone

    from agent_routers.models.agent import Agent

    mock_agent = AsyncMock(spec=Agent)
    mock_agent.agent_id = "agent-1"
    mock_agent.name = "Test Agent"
    mock_agent.subject = "sub-1"
    mock_agent.base_url = "http://localhost:8000"
    mock_agent.capability = None
    mock_agent.description = None
    mock_agent.auth_header = "x-api-key"
    mock_agent.auth_token = "secret-123"
    mock_agent.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_agent.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_agent.endpoints = []
    mock_repo.get_by_id.return_value = mock_agent

    result = await registry.get_agent("agent-1")
    assert result.auth_header == "x-api-key"
    assert result.auth_token == "***"


@pytest.mark.asyncio
async def test_list_agents_omits_auth_token(registry, mock_repo):
    from datetime import datetime, timezone

    from agent_routers.models.agent import Agent

    mock_agent = AsyncMock(spec=Agent)
    mock_agent.agent_id = "agent-1"
    mock_agent.name = "Test Agent"
    mock_agent.subject = "sub-1"
    mock_agent.capability = None
    mock_agent.description = None
    mock_agent.auth_header = "x-api-key"
    mock_agent.auth_token = "secret-123"
    mock_agent.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_repo.list_agents.return_value = [mock_agent]

    result = await registry.list_agents()
    assert len(result) == 1
    assert result[0].auth_header == "x-api-key"
    assert not hasattr(result[0], "auth_token")
