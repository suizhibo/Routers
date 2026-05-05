from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from agent_routers.api.dependencies import get_auth, get_registry
from agent_routers.adapters.http_client import get_client_pool
from agent_routers.schemas.agent import (
    AgentDetail,
    AgentListItem,
    AgentRegistration,
    AgentRegistrationResponse,
)
from agent_routers.services.registry import AgentRegistry
from agent_routers.api.dependencies import AuthContext

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.post(
    "",
    response_model=AgentRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register or re-register an Agent",
)
async def register_agent(
    registration: AgentRegistration,
    auth: AuthContext = Depends(get_auth),
    registry: AgentRegistry = Depends(get_registry),
) -> AgentRegistrationResponse:
    result = await registry.register(registration, jwt_subject=auth.sub)
    first_instance = registration.instances[0]
    get_client_pool().create(registration.agent_id, first_instance.base_url)
    return result


@router.get(
    "",
    response_model=list[AgentListItem],
    summary="List all registered Agents",
)
async def list_agents(
    registry: AgentRegistry = Depends(get_registry),
) -> list[AgentListItem]:
    return await registry.list_agents()


@router.get(
    "/{agent_id}",
    response_model=AgentDetail,
    summary="Get Agent details with instances and endpoints",
)
async def get_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_registry),
) -> AgentDetail:
    return await registry.get_agent(agent_id)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deregister an Agent",
)
async def deregister_agent(
    agent_id: str,
    auth: AuthContext = Depends(get_auth),
    registry: AgentRegistry = Depends(get_registry),
    response: Response = None,
) -> None:
    get_client_pool().destroy(agent_id)
    await registry.deregister(agent_id, jwt_subject=auth.sub, is_admin=auth.is_admin)
