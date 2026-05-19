from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import BacktestTemplateCreate, BacktestTemplateOut
from backend.services.backtest_template_service import BacktestTemplateService

router = APIRouter()
service = BacktestTemplateService()


@router.get("", response_model=list[BacktestTemplateOut])
def list_backtest_templates():
    return service.list_templates()


@router.post("", response_model=BacktestTemplateOut)
def create_backtest_template(payload: BacktestTemplateCreate):
    try:
        return service.create_template(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{template_id}", status_code=204)
def delete_backtest_template(template_id: int):
    deleted = service.delete_template(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="回测模板不存在")
    return None
