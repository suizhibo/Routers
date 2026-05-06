from __future__ import annotations

from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.errors import AgentConflictError, AgentNotFoundError, SubjectMismatchError
from agent_routers.schemas.agent import (
    AgentDetail,
    AgentListItem,
    AgentRegistration,
    AgentRegistrationResponse,
    EndpointSpec,
)


class AgentRegistry:
    def __init__(self, repo: AgentRepository):
        self._repo = repo

    async def register(self, registration: AgentRegistration, jwt_subject: str) -> AgentRegistrationResponse:
        if registration.subject != jwt_subject:
            raise SubjectMismatchError(
                f"Registration subject '{registration.subject}' does not match JWT sub '{jwt_subject}'"
            )

        existing_subject = await self._repo.get_subject(registration.agent_id)
        if existing_subject is not None and existing_subject != registration.subject:
            raise AgentConflictError(
                f"Agent '{registration.agent_id}' already registered with subject '{existing_subject}'"
            )

        agent = await self._repo.create(registration)
        return AgentRegistrationResponse(
            agent_id=agent.agent_id,
            name=agent.name,
            created_at=agent.created_at,
        )

    async def list_agents(self) -> list[AgentListItem]:
        agents = await self._repo.list_agents()
        return [AgentListItem.model_validate(a) for a in agents]

    async def get_agent(self, agent_id: str) -> AgentDetail:
        agent = await self._repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")

        endpoints = []
        for ep in agent.endpoints:
            endpoints.append(
                EndpointSpec(
                    endpoint_type=ep.endpoint_type,
                    method=ep.method,
                    path=ep.path,
                    path_params=ep.path_params,
                    query_params=ep.query_params,
                    body_schema=ep.body_schema,
                    mode=ep.mode,
                    idempotent=ep.idempotent,
                    param_mapping=ep.param_mapping,
                    session_config=ep.session_config,
                )
            )

        return AgentDetail(
            agent_id=agent.agent_id,
            name=agent.name,
            subject=agent.subject,
            base_url=agent.base_url,
            endpoints=endpoints,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    async def deregister(self, agent_id: str, jwt_subject: str, is_admin: bool) -> None:
        agent = await self._repo.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")

        if not is_admin and agent.subject != jwt_subject:
            from agent_routers.errors import ForbiddenError

            raise ForbiddenError("Not authorized to deregister this agent")

        await self._repo.delete(agent_id)
