from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_routers.errors import AgentNotFoundError
from agent_routers.models.agent import Agent, AgentEndpoint
from agent_routers.models.rule import RoutingRule
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.routing import RoutingDecisionEngine, _evaluate_when_clause


class FakeAgentRepo:
    def __init__(self, agents: list[Agent]):
        self._agents = {a.agent_id: a for a in agents}

    async def get_by_id(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    async def list_all(self) -> list[Agent]:
        return list(self._agents.values())


class FakeRuleRepo:
    def __init__(self, rules: list[RoutingRule]):
        self._rules = rules

    async def list_enabled(self) -> list[RoutingRule]:
        return list(self._rules)


class FakeSessionManager:
    def __init__(self, route: tuple[str, str] | None = None):
        self._route = route

    async def get_route(self, session_id: str) -> tuple[str, str] | None:
        return self._route


def _make_agent(agent_id: str, endpoint_id: str, operation_types: list[str] | None = None) -> Agent:
    if operation_types is None:
        operation_types = []
    agent = Agent(agent_id=agent_id, name=f"Agent {agent_id}", subject=f"sub-{agent_id}")
    agent.endpoints = [
        AgentEndpoint(
            agent_id=agent_id,
            endpoint_id=endpoint_id,
            method="POST",
            path="/api/chat",
            path_params=[],
            query_params=[],
            body_schema=None,
            mode="block",
            idempotent=False,
            param_mapping={},
            session_config=None,
            operation_types=operation_types,
        ),
    ]
    return agent


def _make_engine(
    agents: list[Agent] = None,
    rules: list[RoutingRule] = None,
    session_route: tuple[str, str] | None = None,
    default_agent_id: str = "",
):
    if agents is None:
        agents = []
    if rules is None:
        rules = []
    return RoutingDecisionEngine(
        rule_repo=FakeRuleRepo(rules),
        agent_repo=FakeAgentRepo(agents),
        session_manager=FakeSessionManager(session_route),
        default_agent_id=default_agent_id,
    )


# --- L1 Preferred ---

@pytest.mark.asyncio
async def test_l1_preferred_header_wins():
    engine = _make_engine()
    req = RouteRequest()
    headers = {"X-Preferred-Agent": "agent-a", "X-Preferred-Endpoint": "ep-1"}
    result = await engine.resolve(req, headers)
    assert result == ("agent-a", "ep-1")


@pytest.mark.asyncio
async def test_l1_preferred_partial_ignored():
    engine = _make_engine()
    req = RouteRequest()
    headers = {"X-Preferred-Agent": "agent-a"}  # missing endpoint
    with pytest.raises(AgentNotFoundError):
        await engine.resolve(req, headers)


# --- L2 Cache ---

@pytest.mark.asyncio
async def test_l2_cache_hit():
    engine = _make_engine(session_route=("agent-a", "ep-1"))
    req = RouteRequest(context={"session_id": "sess-123"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-1")


@pytest.mark.asyncio
async def test_l2_cache_miss_falls_through():
    engine = _make_engine(
        agents=[_make_agent("agent-a", "ep-1", ["chat"])],
        session_route=None,
    )
    req = RouteRequest(context={"session_id": "sess-123", "operation": "chat"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-1")


# --- L3 Rule ---

@pytest.mark.asyncio
async def test_l3_rule_match():
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={"header.region": "us-east"},
        target_agent_id="agent-a",
        target_instance_id="inst-1",
        target_endpoint_id="ep-1",
        enabled=True,
    )
    engine = _make_engine(agents=[_make_agent("agent-a", "ep-1")], rules=[rule])
    req = RouteRequest()
    headers = {"region": "us-east"}
    result = await engine.resolve(req, headers)
    assert result == ("agent-a", "ep-1")


@pytest.mark.asyncio
async def test_l3_rule_no_endpoint_uses_first():
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={},
        target_agent_id="agent-a",
        target_instance_id="inst-1",
        target_endpoint_id=None,
        enabled=True,
    )
    engine = _make_engine(agents=[_make_agent("agent-a", "ep-first")], rules=[rule])
    req = RouteRequest()
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-first")


# --- L4 Operation Match ---

@pytest.mark.asyncio
async def test_l4_operation_match():
    engine = _make_engine(agents=[
        _make_agent("agent-a", "ep-chat", ["chat"]),
        _make_agent("agent-b", "ep-search", ["search"]),
    ])
    req = RouteRequest(context={"operation": "chat"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-chat")


@pytest.mark.asyncio
async def test_l4_operation_from_options():
    engine = _make_engine(agents=[
        _make_agent("agent-a", "ep-chat", ["chat"]),
    ])
    req = RouteRequest(options={"action": "chat"})
    result = await engine.resolve(req, {})
    assert result == ("agent-a", "ep-chat")


# --- L5 Default ---

@pytest.mark.asyncio
async def test_l5_default():
    engine = _make_engine(
        agents=[_make_agent("agent-default", "ep-1", ["chat"])],
        default_agent_id="agent-default",
    )
    req = RouteRequest()
    result = await engine.resolve(req, {})
    assert result == ("agent-default", "ep-1")


@pytest.mark.asyncio
async def test_l5_no_default_raises():
    engine = _make_engine()
    req = RouteRequest()
    with pytest.raises(AgentNotFoundError):
        await engine.resolve(req, {})


# --- Pipeline priority ---

@pytest.mark.asyncio
async def test_l1_overrides_l2():
    engine = _make_engine(session_route=("agent-cache", "ep-cache"))
    req = RouteRequest(context={"session_id": "sess-123"})
    headers = {"X-Preferred-Agent": "agent-pref", "X-Preferred-Endpoint": "ep-pref"}
    result = await engine.resolve(req, headers)
    assert result == ("agent-pref", "ep-pref")


@pytest.mark.asyncio
async def test_l2_overrides_l3():
    rule = RoutingRule(
        rule_id="r1",
        priority=10,
        when_clause={},
        target_agent_id="agent-rule",
        target_instance_id="inst-1",
        target_endpoint_id="ep-rule",
        enabled=True,
    )
    engine = _make_engine(
        agents=[_make_agent("agent-rule", "ep-rule")],
        rules=[rule],
        session_route=("agent-cache", "ep-cache"),
    )
    req = RouteRequest(context={"session_id": "sess-123"})
    result = await engine.resolve(req, {})
    assert result == ("agent-cache", "ep-cache")


# --- when_clause evaluator ---

def test_evaluate_when_clause_header_match():
    req = RouteRequest()
    headers = {"region": "us-east"}
    assert _evaluate_when_clause({"header.region": "us-east"}, req, headers) is True
    assert _evaluate_when_clause({"header.region": "us-west"}, req, headers) is False


def test_evaluate_when_clause_context_match():
    req = RouteRequest(context={"tenant": "acme"})
    assert _evaluate_when_clause({"context.tenant": "acme"}, req, {}) is True
    assert _evaluate_when_clause({"context.tenant": "other"}, req, {}) is False
