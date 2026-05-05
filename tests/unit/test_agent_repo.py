import pytest
from unittest.mock import AsyncMock, MagicMock
from agent_routers.adapters.agent_repo import AgentRepository


@pytest.mark.asyncio
async def test_get_by_id_returns_agent():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    repo = AgentRepository(mock_factory)
    result = await repo.get_by_id("nonexistent")
    assert result is None
