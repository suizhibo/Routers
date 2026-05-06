from __future__ import annotations

import logging
from typing import Any

from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.schemas.route import RouteRequest
from agent_routers.services.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _extract_value(data: dict, dot_path: str) -> Any:
    if dot_path == "$":
        return data
    current = data
    for part in dot_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _evaluate_when_clause(when_clause: dict, route_req: RouteRequest, headers: dict[str, str]) -> bool:
    """Simple when_clause evaluator. Supports: header.*, context.*, options.*, input equality."""
    req_dict = route_req.model_dump()
    for key, expected in when_clause.items():
        if key.startswith("header."):
            header_key = key[7:]
            actual = headers.get(header_key) or headers.get(header_key.lower())
        elif key.startswith("context."):
            actual = _extract_value(req_dict, key)
        elif key.startswith("options."):
            actual = _extract_value(req_dict, key)
        elif key == "input":
            actual = req_dict.get("input")
        else:
            actual = _extract_value(req_dict, key)
        if actual != expected:
            return False
    return True


class RoutingDecisionEngine:
    def __init__(
        self,
        rule_repo: RuleRepository,
        agent_repo: AgentRepository,
        session_manager: SessionManager,
        default_agent_id: str = "",
    ):
        self._rule_repo = rule_repo
        self._agent_repo = agent_repo
        self._session_manager = session_manager
        self._default_agent_id = default_agent_id

    async def resolve(
        self,
        route_req: RouteRequest,
        headers: dict[str, str],
    ) -> tuple[str, str]:
        req_dict = route_req.model_dump()

        # L1: Preferred
        preferred_agent = headers.get("X-Preferred-Agent")
        if preferred_agent:
            logger.debug("routing_l1_preferred", extra={"agent": preferred_agent, "endpoint": "chat"})
            return preferred_agent, "chat"

        # L2: Cache
        session_id = _extract_value(req_dict, "context.session_id")
        if session_id and self._session_manager:
            cached = await self._session_manager.get_route(session_id)
            if cached:
                agent_id, _ = cached
                logger.debug("routing_l2_cache", extra={"session_id": session_id, "route": (agent_id, "chat")})
                return agent_id, "chat"

        # L3: Rule
        rules = await self._rule_repo.list_enabled()
        for rule in rules:
            if _evaluate_when_clause(rule.when_clause, route_req, headers):
                agent_id = rule.target_agent_id
                endpoint_id = rule.target_endpoint_id
                if not endpoint_id:
                    agent = await self._agent_repo.get_by_id(agent_id)
                    if agent and agent.endpoints:
                        endpoint_id = agent.endpoints[0].endpoint_id
                if endpoint_id:
                    logger.debug("routing_l3_rule", extra={"rule_id": rule.rule_id, "route": (agent_id, endpoint_id)})
                    return agent_id, endpoint_id

        # L4: Default
        # (Operation Match removed) L4 no longer exists; routing proceeds with L1-L3 and L4-default
        # Note: The default route uses the configured default_agent_id if available.
        if self._default_agent_id:
            agent = await self._agent_repo.get_by_id(self._default_agent_id)
            if agent and agent.endpoints:
                ep_id = agent.endpoints[0].endpoint_id
                logger.debug("routing_l4_default", extra={"route": (self._default_agent_id, ep_id)})
                return self._default_agent_id, ep_id

        from agent_routers.errors import AgentNotFoundError
        raise AgentNotFoundError("No route found for request")
