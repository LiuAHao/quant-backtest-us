from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas import BacktestCreate, BacktestTaskOut, BatchDeleteRequest
from backend.services.backtest_service import BacktestService
from backend.services.strategy_service import StrategyService

router = APIRouter()
service = BacktestService()
strategy_service = StrategyService()


class QuickBacktestRequest(BaseModel):
    """一键回测请求"""
    strategy_code: str = Field(description="策略代码")
    strategy_key: str | None = Field(default=None, description="策略key，不提供则自动生成")
    strategy_name: str | None = Field(default=None, description="策略名称，不提供则自动提取")
    start_date: str = Field(description="回测开始日期 YYYY-MM-DD")
    end_date: str = Field(description="回测结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1_000_000, description="初始资金")
    commission_rate: float = Field(default=0.0003, description="手续费率")
    slippage: float = Field(default=0.001, description="滑点")


@router.get("", response_model=list[BacktestTaskOut])
def list_backtests():
    return service.list_tasks()


@router.get("/page")
def list_backtests_page(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    keyword: str | None = None,
):
    return service.list_tasks_page(
        page=page, page_size=page_size, status=status, keyword=keyword
    )


@router.post("/batch-delete")
def batch_delete_backtests(payload: BatchDeleteRequest):
    return service.batch_delete_tasks(payload.ids)


@router.post("", response_model=BacktestTaskOut)
def create_backtest(payload: BacktestCreate):
    try:
        return service.create_task(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/quick", response_model=BacktestTaskOut)
def quick_backtest(payload: QuickBacktestRequest):
    """一键回测：创建策略并立即开始回测
    
    Agent友好接口，一个请求完成策略创建+回测启动。
    """
    import hashlib
    from uuid import uuid4
    
    # 生成策略key
    if not payload.strategy_key:
        code_hash = hashlib.md5(payload.strategy_code.encode()).hexdigest()[:8]
        payload.strategy_key = f"agent_strategy_{code_hash}"
    
    # 生成策略名称
    if not payload.strategy_name:
        payload.strategy_name = f"Agent策略_{payload.strategy_key[:20]}"
    
    # 创建策略
    try:
        from backend.schemas import StrategyCreate
        metadata = strategy_service.derive_metadata_from_code(payload.strategy_code, fallback_name=payload.strategy_name)
        strategy_payload = StrategyCreate(
            key=payload.strategy_key,
            name=str(metadata.get("name") or payload.strategy_name),
            description=str(metadata.get("description") or payload.strategy_name),
            source="ai",
            tags=metadata.get("tags") if isinstance(metadata.get("tags"), list) else [],
            code=payload.strategy_code,
            status="enabled",
        )
        strategy = strategy_service.create_strategy(strategy_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"策略创建失败: {str(exc)}") from exc
    except Exception as exc:
        # 策略可能已存在，尝试获取
        strategies = strategy_service.list_strategies()
        existing = next((s for s in strategies if s.key == payload.strategy_key), None)
        if existing:
            strategy = existing
        else:
            raise HTTPException(status_code=400, detail=f"策略创建失败: {str(exc)}") from exc
    
    # 创建回测任务
    try:
        backtest_payload = BacktestCreate(
            strategy_id=strategy.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            initial_capital=payload.initial_capital,
            commission_rate=payload.commission_rate,
            slippage=payload.slippage,
        )
        return service.create_task(backtest_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"回测创建失败: {str(exc)}") from exc


@router.get("/{task_id}", response_model=BacktestTaskOut)
def get_backtest(task_id: int):
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    return task


@router.post("/{task_id}/cancel", response_model=BacktestTaskOut)
def cancel_backtest(task_id: int):
    try:
        task = service.cancel_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    return task


@router.delete("/{task_id}", status_code=204)
def delete_backtest(task_id: int):
    try:
        deleted = service.delete_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    return None
