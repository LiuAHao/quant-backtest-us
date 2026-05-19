from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas import AiFillRequest, FactorDefinitionCreate, FactorDefinitionOut, FactorDefinitionUpdate, StrategyValidateRequest, StrategyValidateResponse
from backend.services.factor_definition_service import FactorDefinitionService

router = APIRouter()
service = FactorDefinitionService()


class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1)


@router.get("", response_model=list[FactorDefinitionOut])
def list_factor_definitions():
    return service.list_definitions()


@router.post("", response_model=FactorDefinitionOut)
def create_factor_definition(payload: FactorDefinitionCreate):
    try:
        return service.create_definition(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{definition_id}", response_model=FactorDefinitionOut)
def get_factor_definition(definition_id: int):
    definition = service.get_definition(definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return definition


@router.put("/{definition_id}", response_model=FactorDefinitionOut)
def update_factor_definition(definition_id: int, payload: FactorDefinitionUpdate):
    try:
        definition = service.update_definition(definition_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if definition is None:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return definition


@router.delete("/{definition_id}")
def delete_factor_definition(definition_id: int):
    try:
        success = service.delete_definition(definition_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return {"ok": True, "message": "因子定义已删除，历史分析报告保留"}


@router.post("/batch-delete")
def batch_delete_factor_definitions(payload: BatchDeleteRequest):
    deleted_ids: list[int] = []
    failed: list[dict[str, str | int]] = []
    for definition_id in payload.ids:
        try:
            success = service.delete_definition(definition_id)
            if success:
                deleted_ids.append(definition_id)
            else:
                failed.append({"id": definition_id, "reason": "因子定义不存在"})
        except ValueError as exc:
            failed.append({"id": definition_id, "reason": str(exc)})
    return {"ok": len(failed) == 0, "deleted_ids": deleted_ids, "failed": failed}


@router.post("/{definition_id}/enable", response_model=FactorDefinitionOut)
def enable_factor_definition(definition_id: int):
    definition = service.set_status(definition_id, "enabled")
    if definition is None:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return definition


@router.post("/{definition_id}/disable", response_model=FactorDefinitionOut)
def disable_factor_definition(definition_id: int):
    definition = service.set_status(definition_id, "disabled")
    if definition is None:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return definition


@router.post("/validate", response_model=StrategyValidateResponse)
def validate_factor_definition(payload: StrategyValidateRequest):
    return service.validate_code(payload.code)


@router.post("/ai-fill")
def ai_fill_factor_definition(payload: AiFillRequest):
    try:
        return service.ai_fill(payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
