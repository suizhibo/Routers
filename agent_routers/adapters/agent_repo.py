from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from agent_routers.models.agent import Agent, AgentInstance, AgentEndpoint
from agent_routers.schemas.agent import AgentRegistration


class AgentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def create(self, registration: AgentRegistration) -> Agent:
        async with self._sf() as session:
            agent = Agent(
                agent_id=registration.agent_id,
                name=registration.name,
                subject=registration.subject,
            )
            session.add(agent)

            for inst in registration.instances:
                session.add(
                    AgentInstance(
                        agent_id=registration.agent_id,
                        instance_id=inst.instance_id,
                        base_url=inst.base_url,
                        weight=inst.weight,
                    )
                )

            for ep in registration.endpoints:
                session.add(
                    AgentEndpoint(
                        agent_id=registration.agent_id,
                        endpoint_type=ep.endpoint_type,
                        method=ep.method.value,
                        path=ep.path,
                        path_params=[p.model_dump() for p in ep.path_params],
                        query_params=[p.model_dump() for p in ep.query_params],
                        body_schema=ep.body_schema,
                        mode=ep.mode.value,
                        idempotent=ep.idempotent,
                        param_mapping=ep.param_mapping.model_dump(),
                        session_config=ep.session_config.model_dump() if ep.session_config else None,
                    )
                )

            await session.commit()
            await session.refresh(agent)
            return agent

    async def get_by_id(self, agent_id: str) -> Agent | None:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent).where(Agent.agent_id == agent_id)
            )
            return result.scalar_one_or_none()

    async def list_agents(self) -> list[Agent]:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent).order_by(Agent.created_at.desc())
            )
            return list(result.scalars().all())

    async def list_all(self) -> list[Agent]:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.instances),
                    selectinload(Agent.endpoints),
                )
                .order_by(Agent.created_at.desc())
            )
            return list(result.scalars().all())

    async def delete(self, agent_id: str) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                delete(Agent).where(Agent.agent_id == agent_id)
            )
            await session.commit()
            return result.rowcount > 0

    async def get_subject(self, agent_id: str) -> str | None:
        async with self._sf() as session:
            result = await session.execute(
                select(Agent.subject).where(Agent.agent_id == agent_id)
            )
            return result.scalar_one_or_none()
