from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


StrategySource = Literal["manual", "ai", "builtin", "手动导入", "AI生成", "内置"]
StrategyStatus = Literal["enabled", "disabled", "draft", "archived"]
EventSource = Literal["manual", "ai", "builtin", "手动导入", "AI生成", "内置"]
EventStatus = Literal["enabled", "disabled", "draft", "archived"]
FactorSource = Literal["manual", "ai", "builtin", "手动导入", "AI生成", "内置"]
FactorStatus = Literal["enabled", "disabled", "draft", "archived"]


class StrategyCreate(BaseModel):
    key: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    source: StrategySource = "manual"
    tags: list[str] = Field(default_factory=list)
    code: str = Field(min_length=1)
    status: StrategyStatus = "enabled"


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: StrategySource | None = None
    tags: list[str] | None = None
    code: str | None = None
    status: StrategyStatus | None = None


class StrategyOut(BaseModel):
    id: int
    key: str
    name: str
    description: str
    source: str
    tags: list[str]
    status: str
    current_version_id: int | None
    version: int | None = None
    validation_status: str | None = None
    validation_message: str | None = None
    code: str | None = None
    created_at: str
    updated_at: str


class StrategyVersionOut(BaseModel):
    id: int
    strategy_id: int
    version: int
    code_hash: str
    file_path: str
    validation_status: str
    validation_message: str
    code_length: int
    created_at: str


class StrategyValidateRequest(BaseModel):
    code: str


class StrategyValidateResponse(BaseModel):
    ok: bool
    status: str
    message: str
    class_name: str | None = None
    dependencies: list[str] = Field(default_factory=list)


class AiFillRequest(BaseModel):
    prompt: str = Field(min_length=1)


class EventDefinitionCreate(BaseModel):
    key: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    source: EventSource = "manual"
    tags: list[str] = Field(default_factory=list)
    code: str = Field(min_length=1)
    status: EventStatus = "enabled"


class EventDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: EventSource | None = None
    tags: list[str] | None = None
    code: str | None = None
    status: EventStatus | None = None


class EventDefinitionOut(BaseModel):
    id: int
    key: str
    name: str
    description: str
    source: str
    tags: list[str]
    status: str
    current_version_id: int | None
    version: int | None = None
    validation_status: str | None = None
    validation_message: str | None = None
    code: str | None = None
    created_at: str
    updated_at: str


class EventAnalysisCreate(BaseModel):
    event_definition_id: int
    start_date: str
    end_date: str
    windows: list[int] = Field(default_factory=lambda: [5, 10, 15])
    entry_rule: Literal["event_close", "next_open", "next_close"] = "next_open"
    dedup_rule: Literal["none", "per_stock_per_day", "per_stock_gap_5", "per_stock_gap_10"] = "none"
    universe: Literal["all_a", "exclude_beijing", "main_board_only"] = "all_a"
    filters: list[Literal["exclude_st", "exclude_new_stock", "exclude_kcb_cyb", "exclude_main_board", "exclude_beijing"]] = Field(default_factory=list)


class EventAnalysisTaskOut(BaseModel):
    id: int
    event_definition_id: int
    event_definition_version_id: int
    status: str
    start_date: str
    end_date: str
    windows: list[int] = Field(default_factory=list)
    entry_rule: str
    dedup_rule: str
    universe: str
    filters: list[str] = Field(default_factory=list)
    progress: int
    sample_count: int | None = None
    summary: dict[str, Any] | None = None
    result_json_path: str | None = None
    runtime_logs: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class EventAnalysisResultOut(BaseModel):
    task: EventAnalysisTaskOut
    payload: dict[str, Any] | None = None


class FactorDefinitionCreate(BaseModel):
    key: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    source: FactorSource = "manual"
    tags: list[str] = Field(default_factory=list)
    code: str = Field(min_length=1)
    status: FactorStatus = "enabled"


class FactorDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: FactorSource | None = None
    tags: list[str] | None = None
    code: str | None = None
    status: FactorStatus | None = None


class FactorDefinitionOut(BaseModel):
    id: int
    key: str
    name: str
    description: str
    source: str
    tags: list[str]
    status: str
    current_version_id: int | None
    version: int | None = None
    validation_status: str | None = None
    validation_message: str | None = None
    code: str | None = None
    created_at: str
    updated_at: str


class FactorAnalysisCreate(BaseModel):
    factor_definition_id: int
    start_date: str
    end_date: str
    windows: list[int] = Field(default_factory=lambda: [1, 5, 10, 20])
    universe: Literal["all_a", "exclude_beijing", "main_board_only"] = "all_a"
    filters: list[Literal["exclude_st", "exclude_new_stock", "exclude_kcb_cyb", "exclude_main_board", "exclude_beijing"]] = Field(default_factory=list)
    rebalance_rule: Literal["daily", "weekly", "monthly"] = "daily"
    quantiles: int = Field(default=5, ge=2, le=20)
    ic_method: Literal["spearman", "pearson"] = "spearman"
    factor_direction: Literal["higher_better", "lower_better"] = "higher_better"
    preprocessing: dict[str, Any] = Field(default_factory=dict)


class FactorAnalysisTaskOut(BaseModel):
    id: int
    factor_definition_id: int
    factor_definition_version_id: int
    status: str
    start_date: str
    end_date: str
    windows: list[int] = Field(default_factory=list)
    universe: str
    filters: list[str] = Field(default_factory=list)
    rebalance_rule: str
    quantiles: int
    ic_method: str
    factor_direction: str
    preprocessing: dict[str, Any] = Field(default_factory=dict)
    progress: int
    sample_count: int | None = None
    summary: dict[str, Any] | None = None
    result_json_path: str | None = None
    runtime_logs: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class FactorAnalysisResultOut(BaseModel):
    task: FactorAnalysisTaskOut
    payload: dict[str, Any] | None = None


class BacktestCreate(BaseModel):
    strategy_id: int
    start_date: str
    end_date: str
    initial_capital: float = 1_000_000
    commission_rate: float = 0.0003
    slippage: float = 0.001
    benchmark: str | None = None


class BacktestTaskOut(BaseModel):
    id: int
    strategy_id: int
    strategy_version_id: int
    status: str
    start_date: str
    end_date: str
    initial_capital: float
    commission_rate: float
    slippage: float
    benchmark: str | None = None
    progress: int
    report_json_path: str | None = None
    report_html_path: str | None = None
    runtime_logs: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    total_return: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None


class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1)


class BatchDeleteResult(BaseModel):
    ok: bool
    deleted_ids: list[int] = Field(default_factory=list)
    failed: list[dict[str, str | int]] = Field(default_factory=list)


class PageOut(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class BacktestTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start_date: str
    end_date: str
    initial_capital: float = 1_000_000
    commission_rate: float = 0.0003
    slippage: float = 0.001
    benchmark: str = "hs300"


class BacktestTemplateOut(BaseModel):
    id: str
    db_id: int | None = None
    name: str
    kind: str
    start_date: str
    end_date: str
    initial_capital: float
    commission_rate: float
    slippage: float
    benchmark: str = "hs300"
    created_at: str | None = None
    updated_at: str | None = None


class SettingOut(BaseModel):
    key: str
    value: Any


class AiSettingsUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)


class BacktestSettingsUpdate(BaseModel):
    initial_capital: float | None = Field(default=None, ge=10000)
    commission_rate: float | None = Field(default=None, ge=0, le=0.01)
    slippage: float | None = Field(default=None, ge=0, le=0.05)


class UiSettingsUpdate(BaseModel):
    theme: Literal["light", "dark"] | None = None


class SettingsUpdate(BaseModel):
    ai: AiSettingsUpdate | None = None
    backtest: BacktestSettingsUpdate | None = None
    ui: UiSettingsUpdate | None = None
    custom: dict[str, Any] | None = None


class BacktestPreset(BaseModel):
    """回测预设配置"""
    name: str = Field(min_length=1, max_length=80, description="预设名称")
    description: str = Field(default="", description="预设描述")
    initial_capital: float = Field(default=1_000_000, ge=10000, description="初始资金")
    commission_rate: float = Field(default=0.0003, ge=0, le=0.01, description="手续费率")
    slippage: float = Field(default=0.001, ge=0, le=0.05, description="滑点")
    benchmark: str = Field(default="hs300", description="基准指数")
    is_default: bool = Field(default=False, description="是否为默认预设")


class BacktestPresetOut(BacktestPreset):
    """回测预设配置输出"""
    id: int
    created_at: str
    updated_at: str


class AgentConfig(BaseModel):
    """Agent配置"""
    name: str = Field(min_length=1, max_length=80, description="Agent名称")
    description: str = Field(default="", description="Agent描述")
    api_endpoint: str = Field(description="API端点地址")
    api_key: str | None = Field(default=None, description="API密钥")
    default_strategy_key: str | None = Field(default=None, description="默认策略key")
    default_preset_id: int | None = Field(default=None, description="默认预设ID")
    auto_run: bool = Field(default=False, description="是否自动运行")
    schedule_cron: str | None = Field(default=None, description="定时任务cron表达式")


class AgentConfigOut(AgentConfig):
    """Agent配置输出"""
    id: int
    created_at: str
    updated_at: str


class SystemInfo(BaseModel):
    """系统信息"""
    version: str
    data_dir: str
    db_path: str
    strategy_dir: str
    available_data_range: dict[str, str | None]
    total_strategies: int
    total_backtests: int
    total_presets: int
