from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_routers.models.request import RequestTracking


class RequestTrackingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def create(self, request_id: str, user_subject: str, agent_id: str = "") -> None:
        async with self._sf() as session:
            session.add(
                RequestTracking(
                    request_id=request_id,
                    user_subject=user_subject,
                    agent_id=agent_id,
                )
            )
            await session.commit()

    async def get_by_request_id(self, request_id: str) -> RequestTracking | None:
        async with self._sf() as session:
            return await session.get(RequestTracking, request_id)

    async def delete(self, request_id: str) -> None:
        async with self._sf() as session:
            tracked = await session.get(RequestTracking, request_id)
            if tracked is not None:
                await session.delete(tracked)
                await session.commit()
