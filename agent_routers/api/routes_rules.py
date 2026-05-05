from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agent_routers.api.dependencies import get_auth, AuthContext
from agent_routers.adapters.rule_repo import RuleRepository
from agent_routers.models.rule import RoutingRule
from agent_routers.schemas.rule import RoutingRuleCreate, RoutingRuleDetail, RoutingRuleUpdate

router = APIRouter(prefix="/v1/rules", tags=["rules"])


def get_rule_repo(request) -> RuleRepository:
    return request.app.state.rule_repo


@router.get("", response_model=list[RoutingRuleDetail])
async def list_rules(
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    rules = await repo.list_enabled()
    return [RoutingRuleDetail.model_validate(r) for r in rules]


@router.post("", response_model=RoutingRuleDetail, status_code=201)
async def create_rule(
    rule: RoutingRuleCreate,
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    model = RoutingRule(**rule.model_dump())
    result = await repo.create(model)
    return RoutingRuleDetail.model_validate(result)


@router.get("/{rule_id}", response_model=RoutingRuleDetail)
async def get_rule(
    rule_id: str,
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    rule = await repo.get_by_id(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RoutingRuleDetail.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    auth: AuthContext = Depends(get_auth),
    repo: RuleRepository = Depends(get_rule_repo),
):
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    deleted = await repo.delete(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
