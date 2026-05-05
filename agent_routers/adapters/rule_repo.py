from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_routers.models.rule import RoutingRule


class RuleRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def list_enabled(self) -> list[RoutingRule]:
        async with self._sf() as session:
            result = await session.execute(
                select(RoutingRule)
                .where(RoutingRule.enabled == True)
                .order_by(RoutingRule.priority.desc())
            )
            return list(result.scalars().all())

    async def get_by_id(self, rule_id: str) -> RoutingRule | None:
        async with self._sf() as session:
            return await session.get(RoutingRule, rule_id)

    async def create(self, rule: RoutingRule) -> RoutingRule:
        async with self._sf() as session:
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            return rule

    async def update(self, rule_id: str, **kwargs) -> RoutingRule | None:
        async with self._sf() as session:
            rule = await session.get(RoutingRule, rule_id)
            if rule is None:
                return None
            for key, val in kwargs.items():
                if val is not None:
                    setattr(rule, key, val)
            await session.commit()
            await session.refresh(rule)
            return rule

    async def delete(self, rule_id: str) -> bool:
        async with self._sf() as session:
            rule = await session.get(RoutingRule, rule_id)
            if rule is None:
                return False
            await session.delete(rule)
            await session.commit()
            return True
