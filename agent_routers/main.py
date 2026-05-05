from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from agent_routers.config.settings import settings
from agent_routers.adapters.agent_repo import AgentRepository
from agent_routers.adapters.audit_repo import AuditRepository
from agent_routers.adapters.http_client import get_client_pool
from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.api.routes_agents import router as agents_router
from agent_routers.api.routes_cancel import router as cancel_router
from agent_routers.api.routes_forward import router as forward_router
from agent_routers.api.routes_health import router as health_router
from agent_routers.api.routes_audit import router as audit_router
from agent_routers.api.routes_rules import router as rules_router
from agent_routers.errors import AgentRoutersError
from agent_routers.services.forwarder import Forwarder
from agent_routers.services.registry import AgentRegistry
from agent_routers.services.routing import RoutingDecisionEngine
from agent_routers.services.signer import HmacSigner
from agent_routers.services.coordination import init_coordination, get_registry
from agent_routers.middleware.request_id import RequestIdMiddleware
from agent_routers.middleware.jwt_auth import JWTAuthMiddleware
from agent_routers.middleware.quota import QuotaMiddleware
from agent_routers.middleware.audit import AuditMiddleware

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _engine, _session_factory
    _engine = create_async_engine(settings.DATABASE_URL, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    registry, broadcaster = init_coordination(settings.REDIS_URL)
    await broadcaster.start(registry)

    repo = AuditRepository(_session_factory)
    signer = HmacSigner()
    app.state.audit_repo = repo
    app.state.rule_repo = RuleRepository(_session_factory)
    app.state.forwarder = Forwarder(
        agent_repo=AgentRepository(_session_factory),
        routing_engine=RoutingDecisionEngine(app.state.rule_repo),
        client_pool=get_client_pool(),
    )

    _setup_middleware(app)

    yield

    await broadcaster.stop()
    if _engine is not None:
        await _engine.dispose()


def _setup_middleware(app: FastAPI) -> None:
    """Add middleware after lifespan has initialized app.state."""
    repo = app.state.audit_repo
    signer = HmacSigner()
    app.add_middleware(AuditMiddleware, repo=repo, signer=signer)
    app.add_middleware(QuotaMiddleware)
    app.add_middleware(JWTAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)


def make_app() -> FastAPI:
    app = FastAPI(title="AgentRouters", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(AgentRoutersError)
    async def agent_routers_error_handler(request: Request, exc: AgentRoutersError) -> JSONResponse:
        body = exc.to_dict()
        body["error"]["request_id"] = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    app.include_router(health_router)
    app.include_router(agents_router)
    app.include_router(audit_router)
    app.include_router(forward_router)
    app.include_router(rules_router)
    app.include_router(cancel_router)
    return app


app = make_app()
