from __future__ import annotations

import random
from dataclasses import dataclass

from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.models.agent import AgentInstance


@dataclass
class InstanceTarget:
    agent_id: str
    instance_id: str
    base_url: str
    weight: int


class RoutingDecisionEngine:
    def __init__(self, rule_repo: RuleRepository):
        self._rule_repo = rule_repo

    async def select_instance(
        self,
        agent_id: str,
        instances: list[AgentInstance],
        client_ip: str | None,
        preferred_instance: str | None,
        request_headers: dict[str, str],
    ) -> InstanceTarget:
        if not instances:
            from agent_routers.errors import AgentNotFoundError
            raise AgentNotFoundError(f"No instances registered for agent '{agent_id}'")

        # Step 1: preferred header
        if preferred_instance:
            for inst in instances:
                if inst.instance_id == preferred_instance:
                    return InstanceTarget(
                        agent_id=agent_id,
                        instance_id=inst.instance_id,
                        base_url=inst.base_url,
                        weight=inst.weight,
                    )

        # Step 2: rule match
        rules = await self._rule_repo.list_enabled()
        for rule in rules:
            if rule.target_agent_id == agent_id:
                for inst in instances:
                    if inst.instance_id == rule.target_instance_id:
                        return InstanceTarget(
                            agent_id=agent_id,
                            instance_id=inst.instance_id,
                            base_url=inst.base_url,
                            weight=inst.weight,
                        )

        # Step 3: default — weighted random with IP hash for session stickiness
        return self._weighted_select(instances, client_ip)

    def _weighted_select(
        self,
        instances: list[AgentInstance],
        client_ip: str | None,
    ) -> InstanceTarget:
        insts = list(instances)
        weights = [i.weight for i in insts]
        total = sum(weights)

        if client_ip and total > 0:
            target = hash(client_ip) % total
            cum = 0
            for inst, w in zip(insts, weights):
                cum += w
                if target < cum:
                    return InstanceTarget(
                        agent_id=inst.agent_id,
                        instance_id=inst.instance_id,
                        base_url=inst.base_url,
                        weight=inst.weight,
                    )

        # Fallback: weighted random
        chosen = random.choices(insts, weights=weights)[0]
        return InstanceTarget(
            agent_id=chosen.agent_id,
            instance_id=chosen.instance_id,
            base_url=chosen.base_url,
            weight=chosen.weight,
        )
