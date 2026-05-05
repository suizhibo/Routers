from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_routers.errors import AgentNotFoundError
from agent_routers.models.agent import AgentInstance
from agent_routers.models.rule import RoutingRule
from agent_routers.services.routing import InstanceTarget, RoutingDecisionEngine


class FakeRuleRepo:
    def __init__(self, rules: list[RoutingRule]):
        self._rules = rules

    async def list_enabled(self) -> list[RoutingRule]:
        return list(self._rules)


@pytest.fixture
def instances() -> list[AgentInstance]:
    return [
        AgentInstance(agent_id="agent-1", instance_id="inst-a", base_url="http://a", weight=1),
        AgentInstance(agent_id="agent-1", instance_id="inst-b", base_url="http://b", weight=2),
        AgentInstance(agent_id="agent-1", instance_id="inst-c", base_url="http://c", weight=3),
    ]


@pytest.mark.asyncio
async def test_preferred_header_wins(instances):
    repo = FakeRuleRepo([])
    engine = RoutingDecisionEngine(repo)

    result = await engine.select_instance(
        agent_id="agent-1",
        instances=instances,
        client_ip=None,
        preferred_instance="inst-b",
        request_headers={},
    )

    assert isinstance(result, InstanceTarget)
    assert result.instance_id == "inst-b"
    assert result.base_url == "http://b"


@pytest.mark.asyncio
async def test_rule_match_wins_over_default(instances):
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={},
        target_agent_id="agent-1",
        target_instance_id="inst-c",
        enabled=True,
    )
    repo = FakeRuleRepo([rule])
    engine = RoutingDecisionEngine(repo)

    result = await engine.select_instance(
        agent_id="agent-1",
        instances=instances,
        client_ip=None,
        preferred_instance=None,
        request_headers={},
    )

    assert result.instance_id == "inst-c"


@pytest.mark.asyncio
async def test_weighted_random_default(instances):
    repo = FakeRuleRepo([])
    engine = RoutingDecisionEngine(repo)

    # Patch random.choices to always return the first element
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(random, "choices", lambda pop, weights, **kw: [pop[0]])
        result = await engine.select_instance(
            agent_id="agent-1",
            instances=instances,
            client_ip=None,
            preferred_instance=None,
            request_headers={},
        )

    assert result.instance_id == "inst-a"


@pytest.mark.asyncio
async def test_ip_stickiness(instances):
    repo = FakeRuleRepo([])
    engine = RoutingDecisionEngine(repo)

    result1 = await engine.select_instance(
        agent_id="agent-1",
        instances=instances,
        client_ip="192.168.1.1",
        preferred_instance=None,
        request_headers={},
    )
    result2 = await engine.select_instance(
        agent_id="agent-1",
        instances=instances,
        client_ip="192.168.1.1",
        preferred_instance=None,
        request_headers={},
    )

    assert result1.instance_id == result2.instance_id


@pytest.mark.asyncio
async def test_no_instances_raises():
    repo = FakeRuleRepo([])
    engine = RoutingDecisionEngine(repo)

    with pytest.raises(AgentNotFoundError):
        await engine.select_instance(
            agent_id="agent-1",
            instances=[],
            client_ip=None,
            preferred_instance=None,
            request_headers={},
        )
