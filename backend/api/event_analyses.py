from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas import EventAnalysisCreate, EventAnalysisResultOut, EventAnalysisTaskOut, BatchDeleteRequest
from backend.services.event_analysis_service import EventAnalysisService
from backend.services.event_definition_service import EventDefinitionService

router = APIRouter()
service = EventAnalysisService()
definition_service = EventDefinitionService()


class QuickEventAnalysisRequest(BaseModel):
    event_code: str = Field(description="事件分析代码")
    event_key: str | None = Field(default=None, description="事件定义 key")
    event_name: str | None = Field(default=None, description="事件定义名称")
    start_date: str = Field(description="分析开始日期 YYYY-MM-DD")
    end_date: str = Field(description="分析结束日期 YYYY-MM-DD")
    windows: list[int] = Field(default_factory=lambda: [5, 10, 15])
    entry_rule: str = "next_open"
    dedup_rule: str = "none"
    universe: str = "all_a"
    filters: list[str] = Field(default_factory=list, description="事件分析过滤条件")


@router.get("", response_model=list[EventAnalysisTaskOut])
def list_event_analyses():
    return service.list_tasks()


@router.get("/page")
def list_event_analyses_page(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    keyword: str | None = None,
):
    return service.list_tasks_page(
        page=page, page_size=page_size, status=status, keyword=keyword
    )


@router.post("/batch-delete")
def batch_delete_event_analyses(payload: BatchDeleteRequest):
    return service.batch_delete_tasks(payload.ids)


@router.post("", response_model=EventAnalysisTaskOut)
def create_event_analysis(payload: EventAnalysisCreate):
    try:
        return service.create_task(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/quick", response_model=EventAnalysisTaskOut)
def quick_event_analysis(payload: QuickEventAnalysisRequest):
    import hashlib

    if not payload.event_key:
        code_hash = hashlib.md5(payload.event_code.encode()).hexdigest()[:8]
        payload.event_key = f"agent_event_{code_hash}"
    if not payload.event_name:
        payload.event_name = f"事件分析_{payload.event_key[:20]}"

    try:
        from backend.schemas import EventDefinitionCreate

        definition = definition_service.create_definition(
            EventDefinitionCreate(
                key=payload.event_key,
                name=payload.event_name,
                description="由 Agent 自动创建",
                source="ai",
                tags=["agent", "事件分析"],
                code=payload.event_code,
                status="enabled",
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"事件定义创建失败: {str(exc)}") from exc
    except Exception as exc:
        definitions = definition_service.list_definitions()
        existing = next((item for item in definitions if item.key == payload.event_key), None)
        if existing:
            definition = existing
        else:
            raise HTTPException(status_code=400, detail=f"事件定义创建失败: {str(exc)}") from exc

    try:
        return service.create_task(
            EventAnalysisCreate(
                event_definition_id=definition.id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                windows=payload.windows,
                entry_rule=payload.entry_rule,
                dedup_rule=payload.dedup_rule,
                universe=payload.universe,
                filters=payload.filters,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"事件分析创建失败: {str(exc)}") from exc


@router.get("/{task_id}", response_model=EventAnalysisTaskOut)
def get_event_analysis(task_id: int):
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    return task


@router.get("/{task_id}/result", response_model=EventAnalysisResultOut)
def get_event_analysis_result(task_id: int):
    result = service.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    return result


@router.post("/{task_id}/cancel", response_model=EventAnalysisTaskOut)
def cancel_event_analysis(task_id: int):
    try:
        task = service.cancel_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    return task


@router.delete("/{task_id}", status_code=204)
def delete_event_analysis(task_id: int):
    try:
        deleted = service.delete_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    return None
