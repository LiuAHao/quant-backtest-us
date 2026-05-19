from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas import BatchDeleteRequest, FactorAnalysisCreate, FactorAnalysisResultOut, FactorAnalysisTaskOut, FactorDefinitionCreate
from backend.services.factor_analysis_service import FactorAnalysisService
from backend.services.factor_definition_service import FactorDefinitionService

router = APIRouter()
service = FactorAnalysisService()
definition_service = FactorDefinitionService()


class QuickFactorAnalysisRequest(BaseModel):
    factor_code: str = Field(description="因子分析代码")
    factor_key: str | None = Field(default=None, description="因子定义 key")
    factor_name: str | None = Field(default=None, description="因子定义名称")
    start_date: str = Field(description="分析开始日期 YYYY-MM-DD")
    end_date: str = Field(description="分析结束日期 YYYY-MM-DD")
    windows: list[int] = Field(default_factory=lambda: [1, 5, 10, 20])
    universe: str = "all_a"
    filters: list[str] = Field(default_factory=list)
    rebalance_rule: str = "daily"
    quantiles: int = 5
    ic_method: str = "spearman"
    factor_direction: str = "higher_better"
    preprocessing: dict = Field(default_factory=dict)


@router.get("", response_model=list[FactorAnalysisTaskOut])
def list_factor_analyses():
    return service.list_tasks()


@router.get("/page")
def list_factor_analyses_page(page: int = 1, page_size: int = 20, status: str | None = None, keyword: str | None = None):
    return service.list_tasks_page(page=page, page_size=page_size, status=status, keyword=keyword)


@router.post("/batch-delete")
def batch_delete_factor_analyses(payload: BatchDeleteRequest):
    return service.batch_delete_tasks(payload.ids)


@router.post("", response_model=FactorAnalysisTaskOut)
def create_factor_analysis(payload: FactorAnalysisCreate):
    try:
        return service.create_task(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/quick", response_model=FactorAnalysisTaskOut)
def quick_factor_analysis(payload: QuickFactorAnalysisRequest):
    factor_key = payload.factor_key
    if not factor_key:
        code_hash = hashlib.md5(payload.factor_code.encode()).hexdigest()[:8]
        factor_key = f"agent_factor_{code_hash}"
    factor_name = payload.factor_name or f"因子分析_{factor_key[:20]}"
    try:
        definition = definition_service.create_definition(
            FactorDefinitionCreate(
                key=factor_key,
                name=factor_name,
                description="由 Agent 自动创建",
                source="ai",
                tags=["agent", "因子分析"],
                code=payload.factor_code,
                status="enabled",
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"因子定义创建失败: {str(exc)}") from exc

    try:
        return service.create_task(
            FactorAnalysisCreate(
                factor_definition_id=definition.id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                windows=payload.windows,
                universe=payload.universe,
                filters=payload.filters,
                rebalance_rule=payload.rebalance_rule,
                quantiles=payload.quantiles,
                ic_method=payload.ic_method,
                factor_direction=payload.factor_direction,
                preprocessing=payload.preprocessing,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"因子分析创建失败: {str(exc)}") from exc


@router.get("/{task_id}", response_model=FactorAnalysisTaskOut)
def get_factor_analysis(task_id: int):
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="因子分析任务不存在")
    return task


@router.get("/{task_id}/result", response_model=FactorAnalysisResultOut)
def get_factor_analysis_result(task_id: int):
    result = service.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="因子分析任务不存在")
    return result


@router.post("/{task_id}/cancel", response_model=FactorAnalysisTaskOut)
def cancel_factor_analysis(task_id: int):
    try:
        task = service.cancel_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="因子分析任务不存在")
    return task


@router.delete("/{task_id}", status_code=204)
def delete_factor_analysis(task_id: int):
    try:
        deleted = service.delete_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="因子分析任务不存在")
    return None
