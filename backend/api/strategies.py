from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas import (
    AiFillRequest,
    StrategyCreate,
    StrategyOut,
    StrategyUpdate,
    StrategyValidateRequest,
    StrategyValidateResponse,
    StrategyVersionOut,
)
from backend.services.strategy_service import StrategyService

router = APIRouter()
service = StrategyService()


class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1)


@router.get("", response_model=list[StrategyOut])
def list_strategies():
    return service.list_strategies()


@router.post("", response_model=StrategyOut)
def create_strategy(payload: StrategyCreate):
    try:
        return service.create_strategy(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{strategy_id}", response_model=StrategyOut)
def get_strategy(strategy_id: int):
    strategy = service.get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy


@router.get("/{strategy_id}/versions", response_model=list[StrategyVersionOut])
def list_strategy_versions(strategy_id: int):
    strategy = service.get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return service.list_versions(strategy_id)


@router.put("/{strategy_id}", response_model=StrategyOut)
def update_strategy(strategy_id: int, payload: StrategyUpdate):
    try:
        strategy = service.update_strategy(strategy_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if strategy is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int):
    try:
        success = service.delete_strategy(strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=404, detail="策略不存在")
    return {"ok": True, "message": "策略定义已删除，历史回测报告保留"}


@router.post("/batch-delete")
def batch_delete_strategies(payload: BatchDeleteRequest):
    deleted_ids: list[int] = []
    failed: list[dict[str, str | int]] = []
    for strategy_id in payload.ids:
        try:
            success = service.delete_strategy(strategy_id)
            if success:
                deleted_ids.append(strategy_id)
            else:
                failed.append({"id": strategy_id, "reason": "策略不存在"})
        except ValueError as exc:
            failed.append({"id": strategy_id, "reason": str(exc)})
    return {"ok": len(failed) == 0, "deleted_ids": deleted_ids, "failed": failed}


@router.post("/{strategy_id}/enable", response_model=StrategyOut)
def enable_strategy(strategy_id: int):
    strategy = service.set_status(strategy_id, "enabled")
    if strategy is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy


@router.post("/{strategy_id}/disable", response_model=StrategyOut)
def disable_strategy(strategy_id: int):
    strategy = service.set_status(strategy_id, "disabled")
    if strategy is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy


@router.post("/validate", response_model=StrategyValidateResponse)
def validate_strategy(payload: StrategyValidateRequest):
    return service.validate_code(payload.code)


@router.post("/ai-fill")
def ai_fill(payload: AiFillRequest):
    try:
        return service.ai_fill(payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/templates/list")
def list_strategy_templates():
    """获取所有可用的策略模板"""
    from backend.storage.strategies.templates import list_templates
    return list_templates()


@router.get("/templates/{template_key}/code")
def get_template_code(template_key: str):
    """获取指定模板的代码"""
    from backend.storage.strategies.templates import get_template_code
    try:
        return {"code": get_template_code(template_key)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
