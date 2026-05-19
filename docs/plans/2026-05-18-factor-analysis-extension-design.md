# 因子分析扩展模块设计方案

> 基于当前项目结构、事件分析模块实现方式，以及 `factor_analysis/engine.py` 已有 IC/分组/覆盖率基础函数整理。  
> 面向后续外部 agent 分工实现，本文只做模块设计和边界定义，不包含具体代码补丁。

## 0. Review 结论

这版方案方向正确：因子分析应该沿用事件分析的定义、版本、任务、结果、前端管理骨架，但引擎、指标、结果语义必须独立。

需要收紧的地方：

- 开发边界要更硬：MVP 只做单因子分析闭环，不做因子库、多因子组合、回测调仓、中性化实装和复杂归因。
- 后端契约要更稳定：新增模块要平行扩展，不能把事件分析接口改成泛化接口，避免影响已完成的事件分析和报告中心。
- 前端一致性要明确：因子页复用事件分析的信息架构和控件密度，不新增一套视觉语言，不做研究平台式大屏。
- 数据处理要避免逐股循环：用户因子代码可以逐股写，但平台引擎计算 forward return、IC、分组收益必须尽量批量化。
- 结果 JSON 要成为前后端、脚本、报告中心的共同契约，所有 agent 先按该结构实现。

本方案按“先复制成熟骨架、后抽公共能力”的路线推进。第一版不要为了抽象而改动 `event_analysis`、`backtest`、`ml_research` 的公开行为。

## 1. 设计结论

因子分析模块可以大量复用事件分析的“定义管理 + 版本管理 + 任务生命周期 + 结果落盘 + 前端展示”骨架，但不能直接把事件分析引擎改造成因子分析引擎。

核心判断：

- **因子定义像事件定义**：都是用户提交一段 Python 代码，由平台校验、版本化、保存、加载和执行。
- **因子任务像事件任务**：都有开始日期、结束日期、股票池、过滤条件、异步执行、运行日志、结果 JSON。
- **因子结果不像事件结果**：事件关心“发生后收益”，因子关心“连续值信号对未来收益的解释力和排序能力”。

因此推荐做一个和 `event_analysis` 平行的正式模块：

```text
factor_analysis/
├── template.py
├── loader.py
├── engine.py
├── result_builder.py
└── metrics.py
```

后端也采用平行结构：

```text
backend/api/factor_definitions.py
backend/api/factor_analyses.py
backend/services/factor_definition_service.py
backend/services/factor_analysis_service.py
backend/services/factor_analysis_validator.py
backend/services/ai_factor_analysis_prompt.py
```

数据库使用三张核心表：

```text
factor_definitions
factor_definition_versions
factor_analysis_tasks
```

生成和结果目录：

```text
backend/storage/factor_analyses/generated/
backend/storage/factor_analyses/results/
```

### 1.1 第一版开发边界

第一版只交付“单因子分析”：

- 一个任务绑定一个 `factor_definition_id`。
- 一个用户类继承 `FactorAnalysisTemplate`。
- `compute(context)` 返回一个因子值列。
- 平台统一计算未来收益、IC、RankIC、分组收益、多空收益、覆盖率。
- 结果能被 Web 前端、标准脚本、报告中心读取。

第一版不做：

- 不做多因子组合打分。
- 不做因子库之间的自动相关性扫描。
- 不做行业、市值中性化的正式实现，只保留 `neutralize` 配置位和结果字段。
- 不做因子到组合持仓的回测调仓，因子分析只评价信号，不下单。
- 不做在线大规模计算优化框架，只在当前 DuckDB + pandas 架构内做批量读取和缓存。
- 不改现有事件分析 API 路径、事件结果 JSON、事件前端页面行为。

### 1.2 允许改动范围

允许新增：

```text
factor_analysis/template.py
factor_analysis/loader.py
factor_analysis/metrics.py
backend/api/factor_definitions.py
backend/api/factor_analyses.py
backend/services/factor_definition_service.py
backend/services/factor_analysis_service.py
backend/services/factor_analysis_validator.py
backend/services/ai_factor_analysis_prompt.py
scripts/agent_entry/run_standard_factor_analysis.py
docs/AGENT_STANDARD_FACTOR_ANALYSIS_GUIDE.md
tests/test_factor_analysis_engine.py
tests/test_factor_analysis_api.py
```

允许扩展：

```text
factor_analysis/engine.py
factor_analysis/__init__.py
backend/db/database.py
backend/schemas.py
backend/main.py
backend/services/report_service.py
frontend/src/api.js
frontend/src/App.jsx
frontend/src/styles.css
docs/API_GUIDE.md
docs/PROJECT_OVERVIEW.md
```

禁止或谨慎：

- 不直接编辑 `backend/storage/strategies/`、`backend/storage/event_analyses/generated/`、未来的 `backend/storage/factor_analyses/generated/` 生成文件。
- 不把 `EventAnalysisEngine` 改名或抽成父类。
- 不在 `backtest/` 引入 backend 依赖。
- 不让 `factor_analysis/` 引入 backend 依赖。
- 不把前端重构成新的大型组件体系；只在当前渐进拆分风格内新增必要组件。

## 2. 当前基线

当前项目已有：

- `event_analysis/template.py`：事件分析模板，要求实现 `scan(context)`。
- `event_analysis/engine.py`：事件扫描、去重、过滤、未来收益计算、summary 生成。
- `event_analysis/loader.py`：加载事件分析代码，并在执行前复验 validator。
- `backend/services/event_definition_service.py`：事件定义 CRUD、版本管理、AI 填充。
- `backend/services/event_analysis_service.py`：事件任务生命周期、异步执行、结果落盘。
- `backend/api/event_definitions.py` 和 `backend/api/event_analyses.py`：事件定义和任务 API。
- `factor_analysis/engine.py`：已有最小因子指标函数：
  - `compute_ic`
  - `compute_rank_ic`
  - `compute_group_returns`
  - `compute_coverage`
  - `build_summary`
- `tests/test_factor_analysis.py`：覆盖上述基础函数。

现状问题是：`factor_analysis` 现在只是一个指标函数包，还没有和平台任务系统、代码定义系统、Web 面板、标准 agent 入口打通。

## 3. 概念模型

### 3.1 事件分析

事件分析用户代码输出离散样本：

```text
ts_code, trade_date
```

平台补充：

```text
entry_date, ret_5d, ret_10d, ret_15d
```

分析问题：

```text
某个事件发生后，未来 N 日收益如何？
```

### 3.2 因子分析

因子分析用户代码输出连续截面信号：

```text
ts_code, trade_date, factor_value
```

平台补充：

```text
ret_1d, ret_5d, ret_10d, ret_20d
```

分析问题：

```text
因子值越高，未来收益是否越高？
排序是否稳定？
分组收益是否单调？
因子覆盖率是否足够？
与其他因子是否高度相关？
```

## 4. 用户代码模板设计

推荐新增 `factor_analysis/template.py`：

```python
from __future__ import annotations

from typing import Any


class FactorAnalysisTemplate:
    """因子分析模板基类。"""

    def __init__(self, name: str):
        self.name = name

    def compute(self, context: dict[str, Any]):
        raise NotImplementedError("因子分析类必须实现 compute(context)")
```

不建议沿用事件分析的 `scan()` 命名。原因：

- `scan()` 更适合事件样本发现。
- 因子本质是计算连续值信号，`compute()` 更准确。
- 后续多因子、标准化、中性化都更像计算流程，不是事件扫描。

### 4.1 单因子输出格式

MVP 第一版只强制支持单因子：

```text
ts_code       str
trade_date    str | datetime
factor_value  float
```

可选列：

```text
factor_name   str
group_hint    str
raw_value     float
```

其中 `factor_name` 缺省时使用定义名称或任务名称。

### 4.2 示例因子代码

```python
from __future__ import annotations

import pandas as pd

from factor_analysis.template import FactorAnalysisTemplate


class Momentum20Factor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("20日动量因子")

    def compute(self, context):
        rows = []
        current_date = context["current_date"]
        market_data = context["market_data"]

        for ts_code in market_data["ts_code"].astype(str).tolist():
            hist = context["get_history"](ts_code, current_date, window=21)
            if len(hist) < 21:
                continue
            value = hist["close"].iloc[-1] / hist["close"].iloc[0] - 1
            rows.append({
                "ts_code": ts_code,
                "trade_date": current_date.strftime("%Y-%m-%d"),
                "factor_value": value,
            })

        return pd.DataFrame(rows)
```

## 5. Engine 设计

新增正式 `FactorAnalysisEngine`，不要复用 `EventAnalysisEngine` 继承链。

### 5.1 初始化参数

```python
FactorAnalysisEngine(
    start_date: str,
    end_date: str,
    windows: list[int] | None = None,
    universe: str = "all_a",
    filters: list[str] | None = None,
    rebalance_rule: str = "daily",
    quantiles: int = 5,
    ic_method: str = "spearman",
    factor_direction: str = "higher_better",
    winsorize: str | None = "mad",
    standardize: str | None = "zscore",
    neutralize: list[str] | None = None,
)
```

字段说明：

- `windows`：未来收益窗口，默认 `[1, 5, 10, 20]`。
- `rebalance_rule`：因子计算频率，MVP 支持 `daily`、`weekly`、`monthly`。
- `quantiles`：分组数量，默认 5。
- `ic_method`：`spearman` 或 `pearson`。
- `factor_direction`：`higher_better` 或 `lower_better`，影响多空组合方向。
- `winsorize`：去极值方式，MVP 可先只实现 `None` 和 `mad`。
- `standardize`：标准化方式，MVP 可先只实现 `None` 和 `zscore`。
- `neutralize`：中性化维度，MVP 先保留字段，不默认实现。

### 5.2 执行流程

```text
1. 构造交易日列表
2. 按 rebalance_rule 生成因子计算日期
3. 对每个日期构造 context
4. 调用 factor.compute(context)
5. 标准化输出 DataFrame
6. 应用 universe 和 filters
7. 去极值、标准化
8. 计算 forward returns
9. 逐窗口计算 IC / RankIC
10. 逐窗口计算分组收益
11. 计算多空收益
12. 计算覆盖率
13. 生成 summary、details、charts
```

### 5.2.1 执行细节边界

日期边界：

- `start_date`、`end_date` 是因子计算日期范围。
- forward return 需要额外读取 `end_date` 之后的交易日，读取长度至少覆盖 `max(windows)`，建议和事件分析一样留足缓冲。
- 输出中的 `trade_date` 永远表示因子暴露日期，不表示未来收益结束日期。

计算频率：

- `daily`：每个交易日计算一次因子。
- `weekly`：每周最后一个可交易日计算一次。
- `monthly`：每月最后一个可交易日计算一次。
- MVP 不支持自定义 cron 或自然日频率。

用户代码职责：

- 只负责生成当前日期的截面因子值。
- 不负责补 forward return。
- 不负责分组。
- 不负责 IC。
- 不负责落盘。

平台职责：

- 过滤股票池。
- 统一预处理因子值。
- 统一计算未来收益。
- 统一聚合指标。
- 统一生成 JSON 和任务状态。

性能边界：

- 引擎内 forward return 计算必须批量读取价格数据，不能对每个 `ts_code`、每个窗口逐条 SQL。
- `context["get_history"]` 允许给用户代码使用，但平台自身指标计算不依赖逐股循环。
- 对每个计算日的 cross section 可以缓存，避免同一日期重复读取。
- 明细 JSON 限制行数，完整中间数据不在 MVP 落盘。

### 5.3 Context 设计

和事件分析共享大部分上下文：

```python
context = {
    "start_date": self.start_date,
    "end_date": self.end_date,
    "current_date": current_date,
    "windows": self.windows,
    "universe": self.universe,
    "filters": self.filters,
    "data_loader": self.data_loader,
    "conn": self.data_loader.conn,
    "market_data": cross_section,
    "get_history": self.data_loader.get_history,
    "get_cross_section": self.data_loader.get_cross_section,
    "trade_date_index": self.data_loader.get_trade_date_index,
    "get_trade_dates": lambda: trade_date_list,
}
```

因子代码不负责计算未来收益，避免偷看未来。

### 5.4 输出列标准化

用户返回列允许是：

```text
factor_value
factor
value
```

引擎内部统一改名为：

```text
factor
```

结果 JSON 面向用户展示时使用：

```text
factor_value
```

标准化规则：

- `ts_code` 转为字符串。
- `trade_date` 转为 `YYYY-MM-DD`。
- `factor` 转为 float，无法转换的值丢弃。
- 同一 `ts_code + trade_date` 多条记录时，MVP 保留最后一条，并在 runtime log 记录去重数量。
- 只保留 `start_date <= trade_date <= end_date` 的记录。

### 5.5 预处理规则

MVP 实现：

- `winsorize=None`
- `winsorize="mad"`
- `standardize=None`
- `standardize="zscore"`

MVP 不实现：

- 行业中性化。
- 市值中性化。
- 缺失值复杂填充。
- Box-Cox、rank normalize 等高级变换。

预处理顺序固定：

```text
过滤无效样本 -> 去极值 -> 标准化 -> 计算 forward return -> 指标计算
```

所有预处理按单日截面执行，不能跨日期使用未来信息。

## 6. 指标设计

当前 `factor_analysis/engine.py` 已经包含基础函数，但建议后续重构为：

```text
factor_analysis/metrics.py
```

职责：

- `compute_ic`
- `compute_rank_ic`
- `compute_group_returns`
- `compute_long_short_returns`
- `compute_coverage`
- `compute_factor_correlation`
- `build_summary`

`factor_analysis/engine.py` 负责调度和数据准备，`metrics.py` 负责纯计算。

### 6.1 IC / RankIC

输出：

```text
trade_date, window, ic, rank_ic, n
```

summary：

```json
{
  "ic": {
    "1d": {"mean": 0.03, "std": 0.12, "icir": 0.25, "positive_rate": 0.56},
    "5d": {"mean": 0.05, "std": 0.14, "icir": 0.36, "positive_rate": 0.61}
  }
}
```

### 6.2 分组收益

输出：

```text
trade_date, window, group, avg_ret, n
```

约定：

- `group=1` 是最低因子值。
- `group=quantiles` 是最高因子值。
- `factor_direction=lower_better` 时，多空方向反转，但原始分组编号不反转。

### 6.3 多空收益

输出：

```text
trade_date, window, long_group, short_group, long_ret, short_ret, long_short_ret
```

summary：

```json
{
  "long_short": {
    "5d": {
      "mean": 0.012,
      "annualized": 0.31,
      "win_rate": 0.57,
      "max_drawdown": -0.08
    }
  }
}
```

### 6.4 覆盖率

输出：

```text
trade_date, factor_count, total_count, coverage
```

覆盖率用于判断因子是否只在少量股票上有效。

### 6.5 因子相关性

MVP 可以先不做多因子任务，但要预留结果结构：

```json
{
  "correlation": {
    "enabled": false,
    "matrix": []
  }
}
```

第二版支持多因子后再补：

- 单日截面相关性
- 时间平均相关性
- 与已有因子库的相关性

## 7. 数据库设计

在 `backend/db/database.py` 增加：

### 7.1 factor_definitions

```sql
CREATE TABLE IF NOT EXISTS factor_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    tags_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'enabled',
    current_version_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 factor_definition_versions

```sql
CREATE TABLE IF NOT EXISTS factor_definition_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_definition_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    code TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    file_path TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validation_message TEXT NOT NULL DEFAULT '',
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(factor_definition_id, version),
    FOREIGN KEY(factor_definition_id) REFERENCES factor_definitions(id)
);
```

### 7.3 factor_analysis_tasks

```sql
CREATE TABLE IF NOT EXISTS factor_analysis_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_definition_id INTEGER NOT NULL,
    factor_definition_version_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    windows_json TEXT NOT NULL DEFAULT '[1, 5, 10, 20]',
    universe TEXT NOT NULL DEFAULT 'all_a',
    filters_json TEXT NOT NULL DEFAULT '[]',
    rebalance_rule TEXT NOT NULL DEFAULT 'daily',
    quantiles INTEGER NOT NULL DEFAULT 5,
    ic_method TEXT NOT NULL DEFAULT 'spearman',
    factor_direction TEXT NOT NULL DEFAULT 'higher_better',
    preprocessing_json TEXT NOT NULL DEFAULT '{}',
    progress INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER,
    summary_json TEXT,
    result_json_path TEXT,
    runtime_logs_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(factor_definition_id) REFERENCES factor_definitions(id),
    FOREIGN KEY(factor_definition_version_id) REFERENCES factor_definition_versions(id)
);
```

### 7.4 索引

```sql
CREATE INDEX IF NOT EXISTS idx_factor_analysis_tasks_def_id ON factor_analysis_tasks(factor_definition_id);
CREATE INDEX IF NOT EXISTS idx_factor_analysis_tasks_status ON factor_analysis_tasks(status);
CREATE INDEX IF NOT EXISTS idx_factor_def_versions_did_ver ON factor_definition_versions(factor_definition_id, version);
```

## 8. 后端 Schema 设计

新增 Pydantic 模型：

```python
class FactorDefinitionCreate(BaseModel):
    key: str
    name: str
    description: str = ""
    source: str = "manual"
    tags: list[str] = Field(default_factory=list)
    code: str
    status: str = "enabled"


class FactorDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: str | None = None
    tags: list[str] | None = None
    code: str | None = None
    status: str | None = None


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
    universe: str = "all_a"
    filters: list[str] = Field(default_factory=list)
    rebalance_rule: str = "daily"
    quantiles: int = 5
    ic_method: str = "spearman"
    factor_direction: str = "higher_better"
    preprocessing: dict[str, Any] = Field(default_factory=dict)
```

## 9. API 设计

### 9.1 Factor Definitions

```text
GET    /api/factor-definitions
POST   /api/factor-definitions
GET    /api/factor-definitions/{definition_id}
PUT    /api/factor-definitions/{definition_id}
DELETE /api/factor-definitions/{definition_id}
POST   /api/factor-definitions/batch-delete
POST   /api/factor-definitions/{definition_id}/enable
POST   /api/factor-definitions/{definition_id}/disable
POST   /api/factor-definitions/validate
POST   /api/factor-definitions/ai-fill
```

### 9.2 Factor Analyses

```text
GET    /api/factor-analyses
GET    /api/factor-analyses/page
POST   /api/factor-analyses
POST   /api/factor-analyses/quick
POST   /api/factor-analyses/batch-delete
GET    /api/factor-analyses/{task_id}
GET    /api/factor-analyses/{task_id}/result
POST   /api/factor-analyses/{task_id}/cancel
DELETE /api/factor-analyses/{task_id}
```

Quick 接口用于外部 agent：

```json
{
  "factor_code": "...",
  "factor_key": "momentum_20",
  "factor_name": "20日动量因子",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "windows": [1, 5, 10, 20],
  "quantiles": 5,
  "universe": "all_a",
  "filters": ["exclude_st", "exclude_new_stock"]
}
```

## 10. Service 设计

### 10.1 FactorDefinitionService

基本复制 `EventDefinitionService`：

- `list_definitions`
- `get_definition`
- `create_definition`
- `update_definition`
- `set_status`
- `delete_definition`
- `validate_code`
- `ai_fill`
- `_sync_current_files`
- `_insert_version`
- `_row_to_out`

差异：

- 生成目录使用 `backend/storage/factor_analyses/generated/`。
- validator 查找 `FactorAnalysisTemplate`。
- 方法名和错误信息使用“因子定义”。

### 10.2 FactorAnalysisService

基本复制 `EventAnalysisService`：

- `list_tasks`
- `list_tasks_page`
- `batch_delete_tasks`
- `get_task`
- `get_result`
- `create_task`
- `cancel_task`
- `delete_task`
- `_run_task`
- `_get_definition_with_version`
- `_get_task_context`
- `_validate_payload`
- `_row_to_out`

差异：

- loader 使用 `FactorAnalysisLoader`。
- engine 使用 `FactorAnalysisEngine`。
- result path 命名：

```text
backend/storage/factor_analyses/results/factor_analysis_task_{task_id}.json
```

### 10.3 后端扩展边界

后端按“平行模块”扩展，不做侵入式泛化：

- `backend/main.py` 只新增 router 注册：
  - `/api/factor-definitions`
  - `/api/factor-analyses`
- `backend/schemas.py` 新增 `Factor*` 模型，不复用 `EventAnalysisCreate`。
- `backend/db/database.py` 只新增三张表和索引，迁移保持幂等。
- `backend/services/report_service.py` 只扩展第三类 `factor_analysis`，保持 `backtest` 和 `event_analysis` 原有行为。
- `EventDefinitionService`、`EventAnalysisService` 不因本次开发改签名。
- `StrategyValidateRequest` 和 `StrategyValidateResponse` 可以继续复用为 validate API 的输入输出，但命名债务记录在后续优化，不在 MVP 阶段重命名。

后端扩展时必须保留这几个稳定契约：

```text
定义层：definition -> current_version -> generated file
任务层：task queued/running/success/failed/cancelled
结果层：result_json_path 指向标准 JSON
日志层：runtime_logs_json 存储结构化运行日志
分页层：/page 返回 items/total/page/page_size
批量层：batch-delete 返回 deleted_ids 和 failed
```

### 10.4 Service 实现细节

`FactorDefinitionService`：

- `create_definition` 必须先校验 `key` 唯一性，再校验代码，再写 definition，再写 version，再更新 `current_version_id`。
- `update_definition` 只有 `code` 变化时才新增 version；仅改名称、描述、标签、状态时不新增 version。
- `_sync_current_files()` 启动时从 DB current version 重建 generated 文件，和策略、事件定义保持一致。
- 删除定义时，如果存在历史任务，不删除结果 JSON；定义可删除或软删除按现有事件定义语义对齐。

`FactorAnalysisService`：

- `create_task` 使用 definition 的 current version，记录 `factor_definition_version_id`，保证历史任务可复现。
- `_run_task` 只读取该 version 的 code/file，不读取最新定义。
- 任务开始时设置 `started_at`、`status=running`、`progress`。
- 成功时写 result JSON、summary_json、sample_count、finished_at、`status=success`。
- 失败时写 `error_message`、runtime logs、`finished_at`、`status=failed`。
- cancel 第一版可只支持 queued 任务直接取消；running 任务如果当前执行器无法中断，需要返回明确错误。

### 10.5 Engine 与 Service 的接口

Service 不应该知道指标内部细节，只调用稳定接口：

```python
factor = FactorAnalysisLoader.load_from_code(code)
engine = FactorAnalysisEngine(...)
engine.set_compute(factor.compute)
result = engine.run()
payload = build_factor_result_payload(task=task, definition=definition, result=result)
```

推荐结果对象：

```python
@dataclass
class FactorAnalysisResult:
    start_date: str
    end_date: str
    sample_count: int
    date_count: int
    stock_count: int
    summary: dict[str, Any]
    charts: dict[str, list[dict[str, Any]]]
    tables: dict[str, list[dict[str, Any]]]
    details: list[dict[str, Any]]
```

`details` 只保留前端需要的样例明细，不能把全量逐日逐股结果无上限塞进 JSON。MVP 建议默认最多 1000 行，并在 summary 中记录真实 `sample_count`。

### 10.6 API 兼容细节

新增 API 命名和事件分析保持同构：

```text
factor_definition_id
factor_definition_version_id
result_json_path
runtime_logs
error_message
```

不要使用混合命名：

```text
factorId
definitionVersion
resultPath
logs
```

前端映射可以使用 camelCase，但后端 JSON 字段保持当前项目的 snake_case 习惯。

`QuickFactorAnalysisRequest` 的创建逻辑对齐事件 quick API：

- 未传 `factor_key` 时基于 `factor_code` md5 前 8 位生成 `agent_factor_{hash}`。
- 未传 `factor_name` 时生成 `因子分析_{factor_key[:20]}`。
- 如果 key 已存在，第一版不要静默覆盖已有代码；应返回清晰错误，或在后续显式支持 `overwrite=true`。
- quick API 创建的 definition `source="ai"`，tags 包含 `agent` 和 `因子分析`。

## 11. Validator 设计

新增 `backend/services/factor_analysis_validator.py`。

第一版规则：

- 必须导入或引用 `FactorAnalysisTemplate`。
- 必须有继承 `FactorAnalysisTemplate` 的类。
- 必须实现 `compute(self, context)`。
- 禁止策略和事件分析同款危险导入与危险调用。
- 禁止在因子代码中直接计算未来收益字段：
  - `ret_1d`
  - `ret_5d`
  - `ret_10d`
  - `ret_20d`
  - `future_return`
  - `forward_return`
- 禁止交易动作：
  - `order`
  - `buy`
  - `sell`
  - `order_target_percent`

验证通过只代表基础静态安全，不代表完整沙箱。

## 12. Loader 设计

新增 `factor_analysis/loader.py`，复制事件分析 loader 的安全模式：

- 支持从 `code` 字符串加载。
- 支持从 `file_path` 文件加载。
- 加载前必须调用 `FactorAnalysisValidator`。
- 使用 `ModuleType + exec(compile(...))`。
- 查找继承 `FactorAnalysisTemplate` 的类。
- 要求类支持无参数初始化。

错误类：

```python
class FactorAnalysisLoadError(RuntimeError):
    pass
```

## 13. Result JSON 设计

结果文件建议结构：

```json
{
  "task_id": 1,
  "name": "20日动量因子",
  "factor_definition_id": 1,
  "factor_definition_version_id": 1,
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "windows": [1, 5, 10, 20],
  "universe": "all_a",
  "filters": ["exclude_st"],
  "settings": {
    "rebalance_rule": "daily",
    "quantiles": 5,
    "ic_method": "spearman",
    "factor_direction": "higher_better",
    "preprocessing": {
      "winsorize": "mad",
      "standardize": "zscore"
    }
  },
  "summary": {
    "sample_count": 100000,
    "date_count": 240,
    "stock_count": 5200,
    "ic": {},
    "rank_ic": {},
    "group_returns": {},
    "long_short": {},
    "coverage": {}
  },
  "charts": {
    "ic_series": [],
    "group_returns": [],
    "long_short_curve": [],
    "coverage_series": []
  },
  "tables": {
    "latest_factor_samples": [],
    "ic_table": [],
    "group_return_table": []
  },
  "runtime": {
    "status": "success",
    "logs": []
  }
}
```

### 13.1 Result JSON 字段契约

结果 JSON 是后端、前端、标准脚本、报告中心的共同接口。字段只能增量扩展，不能在 MVP 后随意改名。

必填顶层字段：

```text
task_id
name
factor_definition_id
factor_definition_version_id
start_date
end_date
windows
settings
summary
charts
tables
runtime
```

`summary` 约定：

- `sample_count`：参与指标计算的有效因子样本数。
- `date_count`：有有效因子样本的交易日数量。
- `stock_count`：覆盖过的不同股票数量。
- `ic`：按窗口聚合的 IC 统计。
- `rank_ic`：按窗口聚合的 RankIC 统计。
- `group_returns`：按窗口聚合的分组收益统计。
- `long_short`：按窗口聚合的多空收益统计。
- `coverage`：覆盖率统计。

`charts` 约定：

- `ic_series`：`trade_date, window, ic, rank_ic, n`
- `group_returns`：`trade_date, window, group, avg_ret, n`
- `long_short_curve`：`trade_date, window, long_short_ret, cumulative_long_short_ret`
- `coverage_series`：`trade_date, factor_count, total_count, coverage`

`tables` 约定：

- `latest_factor_samples`：样本展示，不要求全量。
- `ic_table`：按窗口汇总。
- `group_return_table`：按窗口和分组汇总。

数值约定：

- 收益率使用小数，不使用百分比字符串。
- 前端负责格式化百分比和小数位。
- 空指标使用 `null`，不要使用 `0` 代替。
- 所有日期使用 `YYYY-MM-DD`。

## 14. 标准脚本设计

新增：

```text
scripts/agent_entry/run_standard_factor_analysis.py
```

行为对齐现有标准回测和标准事件分析脚本：

- 后端在线时：调用 `POST /api/factor-analyses/quick`。
- 后端不在线时：本地直接运行 `FactorAnalysisEngine`，并写入标准 SQLite 任务记录。
- 两种模式都生成同一结构的结果 JSON。
- 成功后输出任务 ID、结果路径、核心 IC 和多空指标。

典型调用：

```bash
python3 scripts/agent_entry/run_standard_factor_analysis.py \
  --factor-file backend/storage/factor_analyses/generated/momentum_20.py \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 1,5,10,20 \
  --quantiles 5
```

## 15. 前端设计

前端建议新增两个页面或 tab：

```text
factor_definitions
factor_analyses
```

为了保持当前前端渐进拆分风格，第一版只做最小可用，不引入新的页面框架。

### 15.1 前端一致性边界

必须遵守：

- 继续使用 `activeTab` + URL params 的导航方式。
- `VALID_TABS` 只新增必要 tab，不改变已有 tab 名称。
- 因子定义页视觉结构对齐 `EventAnalysisManagerView`。
- 因子结果页视觉结构对齐 `EventAnalysisResultsView` 和 `EventAnalysisResultView`。
- 表格、筛选栏、批量删除、状态 badge、运行日志使用现有组件或同类 className。
- API 访问统一放在 `frontend/src/api.js`。
- 后端 snake_case 字段在 `api.js` 内映射成前端 camelCase view model。
- 轮询节奏对齐当前 backtest/event analyses 2.5s 机制，不新增更高频轮询。
- 错误、loading、empty state 使用现有 `empty-state`、`notice`、`RuntimeLogPanel` 风格。

禁止：

- 不新增独立 UI 主题。
- 不做全屏研究大屏。
- 不在前端实现因子指标计算。
- 不把复杂图表库引入 MVP，优先使用当前已有小图组件和表格。
- 不在 `App.jsx` 里复制大段无法维护的事件分析代码后再改几个字；可以先轻量复制结构，但要把 API 映射和小型展示组件拆到 `api.js`/`components`。

建议新增状态：

```text
selectedFactorAnalysisId
factorAnalysisDisplayMode
factorDefinitions
factorAnalyses
```

建议新增 URL 参数：

```text
factorAnalysisId
factorView
```

建议新增 tab：

```text
factor_analyses
factor_results
```

是否单独拆 `factor_definitions` tab 可后置。MVP 可以把定义管理和运行入口放在 `factor_analyses` 一个页面里，和当前事件分析页保持一致。

### 15.2 因子定义列表

能力：

- 列表
- 新建/编辑
- 启用/停用
- 删除
- 代码校验
- AI 填充

UI 可复用策略和事件定义弹窗结构。

实现细节：

- 弹窗命名建议 `FactorDefinitionModal`。
- 表单字段对齐事件定义：
  - 因子名称
  - 因子标识
  - 因子来源
  - 标签
  - 因子说明
  - 因子代码预览
- 默认代码模板使用 `FactorAnalysisTemplate` 和 `compute(context)`。
- 校验按钮文案为“校验因子”。
- 保存按钮文案为“保存到因子库”。
- AI 生成提示文案只描述因子计算，不暗示平台会自动调仓。

### 15.3 因子分析任务页

能力：

- 创建因子分析任务。
- 查看任务状态。
- 查看 summary。
- 查看 IC 曲线、分组收益、多空曲线、覆盖率。
- 查看运行日志。
- 删除/批量删除任务。

实现细节：

- 运行弹窗命名建议 `FactorAnalysisRunModal`。
- 运行参数：
  - 日期区间
  - 未来收益窗口
  - 股票池
  - 过滤条件
  - 调仓频率 `rebalance_rule`
  - 分组数 `quantiles`
  - IC 方法 `ic_method`
  - 因子方向 `factor_direction`
  - 预处理 `winsorize`、`standardize`
- MVP 中 `neutralize` 可以出现在后端配置，但前端不暴露或置灰，避免用户误以为已完整支持。
- 列表字段：
  - 任务 ID
  - 因子名称
  - 区间
  - 窗口
  - 状态
  - 样本数
  - 首窗口 IC
  - 多空均值
  - 创建时间
  - 操作

### 15.4 因子结果页

首屏展示：

- 样本数
- 覆盖交易日
- 覆盖股票数
- 首窗口 IC 均值
- 首窗口 RankIC 均值
- 首窗口多空收益均值

图表和表格：

- IC 序列：按窗口切换，MVP 可用简洁折线。
- 分组收益：展示各组平均收益，强调 `group=1` 是最低因子值。
- 多空曲线：展示 long-short 累计走势。
- 覆盖率序列：展示覆盖率随时间变化。
- 样本明细：最多展示前 100 条或 1000 条，由后端结果结构控制。
- 运行日志：复用 `RuntimeLogPanel`。

空数据处理：

- running/queued：显示任务运行中和日志。
- failed/cancelled：显示错误信息和日志。
- success 但结果缺失：显示“结果文件不存在或尚未生成”。
- 指标为空：显示“样本不足，无法计算该指标”，不要显示 0 误导用户。

### 15.5 报告中心接入

`ReportService` 后续支持第三类：

```text
factor_analysis
```

报告列表可以统一展示：

- backtest
- event_analysis
- factor_analysis

前端 `ReportCenterView` 增加 `factor_analysis` 时：

- `download_kind` 使用 `factor_analysis`。
- `open_target.tab` 指向 `factor_results`。
- 删除报告时同步移除 `factorAnalyses` 中对应任务。
- 不影响已有 `backtest` 和 `event_analysis` 打开逻辑。

## 16. 与事件分析的复用边界

可以直接复制或抽象的部分：

- 定义表和版本表模式。
- service CRUD。
- loader 加载前复验。
- validator 的危险导入/调用基础规则。
- task lifecycle。
- runtime logs。
- result JSON 落盘。
- list/page/batch-delete/cancel/delete API。
- quick API 结构。

不要直接复用的部分：

- `EventAnalysisEngine._attach_returns()` 的事件入口价逻辑。
- 事件样本去重逻辑。
- 事件 summary 构造。
- 事件的 `entry_rule` 语义。

可以抽成公共 helper 的部分：

- 交易日历加载。
- universe/filter 过滤。
- forward returns 计算。
- result path 生成。
- task runtime log capture。

公共 helper 可后置，不建议 MVP 一开始过度抽象。

## 17. 实施分期

### Phase 1：后端最小闭环

目标：能通过 API 创建因子定义、创建分析任务、执行并返回结果 JSON。

范围：

- `factor_analysis/template.py`
- `factor_analysis/loader.py`
- `factor_analysis/metrics.py`
- `factor_analysis/engine.py`
- `backend/services/factor_analysis_validator.py`
- `backend/services/factor_definition_service.py`
- `backend/services/factor_analysis_service.py`
- `backend/api/factor_definitions.py`
- `backend/api/factor_analyses.py`
- `backend/db/database.py`
- `backend/schemas.py`
- `backend/main.py`
- `tests/test_factor_analysis_engine.py`
- `tests/test_factor_analysis_api.py`

验收：

```bash
python3 -m unittest tests.test_factor_analysis -v
python3 -m unittest tests.test_factor_analysis_engine -v
python3 -m unittest tests.test_factor_analysis_api -v
python3 -m unittest discover -s tests -v
```

开发细节：

- 先补 `template.py`、`loader.py`、`validator.py`，保证用户代码安全入口成立。
- 再把现有 `factor_analysis/engine.py` 中纯函数迁移或拆分到 `metrics.py`，保留原有测试兼容。
- 新 `FactorAnalysisEngine.run()` 先支持 fixture 数据闭环，不依赖真实 `data/`。
- API 测试必须 patch storage 目录、DB 路径、DATA_DIR，沿用 `tests/test_backend_api.py` 的隔离模式。
- `backend/main.py` 注册 router 后要确认 `/api/health` 不受影响。

交付边界：

- 允许没有前端页面。
- 允许没有标准脚本。
- 必须能用 TestClient 创建定义和任务。
- 必须能读取任务 result。
- 必须覆盖 validator 禁止未来收益字段、禁止危险导入、禁止交易动作。

### Phase 2：标准脚本和 Agent 文档

目标：外部 agent 能稳定生成前端可识别的因子分析结果。

范围：

- `scripts/agent_entry/run_standard_factor_analysis.py`
- `docs/AGENT_STANDARD_FACTOR_ANALYSIS_GUIDE.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/API_GUIDE.md`

验收：

```bash
python3 scripts/agent_entry/run_standard_factor_analysis.py --help
```

并用一个 fixture 因子文件生成标准任务结果。

开发细节：

- 脚本参数风格对齐 `run_standard_event_analysis.py`。
- `--factor-file` 读取用户因子文件。
- `--start`、`--end`、`--windows`、`--quantiles` 必填或有清晰默认值。
- 后端在线时走 quick API。
- 后端离线时直接使用本地 engine，并写标准结果 JSON。
- 输出中必须包含 result path、task id 或 local task 标识、核心 IC、RankIC、多空收益。

交付边界：

- 不要求脚本支持批量因子。
- 不要求脚本生成 HTML。
- 文档必须说明用户代码不能计算未来收益。

### Phase 3：前端最小接入

目标：Web 面板能管理因子定义和查看因子分析结果。

范围：

- `frontend/src/App.jsx`
- `frontend/src/api.js`
- `frontend/src/components/*`

验收：

```bash
cd frontend && npm run build
```

开发细节：

- 先在 `api.js` 增加 factor definitions/tasks 的 request 和 view mapper。
- 再在 `App.jsx` 增加 tab、state、refresh、polling、navigation。
- 页面结构先复用事件分析管理页和结果页的信息架构。
- 图表可以先用已有迷你折线/表格展示，复杂可视化留到 Phase 4。
- 删除报告、打开报告、轮询刷新都要覆盖 factor_analysis。

交付边界：

- 不要求可视化达到研究平台深度。
- 不要求支持多因子。
- 必须保证 `npm run build` 通过。
- 必须保证已有事件分析入口还能正常渲染。

### Phase 4：高级因子能力

目标：补多因子、相关性、中性化、换手率和衰减分析。

范围：

- `factor_analysis/metrics.py`
- `factor_analysis/engine.py`
- 前端结果图表
- 文档和测试

开发细节：

- 多因子任务使用新的 request schema，不复用单因子任务强塞。
- 因子相关性基于多个单因子结果或因子库数据，避免在 MVP 的单因子结果中伪造矩阵。
- 中性化需要明确数据来源：
  - 行业分类从 instruments 或后续行业表读取。
  - 市值从 `daily_basic` 或已有 joined market data 读取。
- 换手率分析需要保存前后期分组成员，第一版结果 JSON 没有该全量结构，因此放到 Phase 4。

交付边界：

- Phase 4 不能破坏 MVP Result JSON，只能增加字段。
- 高级能力必须有独立测试和文档。

## 18. MVP 完成定义

第一版完成应满足：

1. 用户可以创建、校验、编辑、删除因子定义。
2. 因子定义代码必须继承 `FactorAnalysisTemplate` 并实现 `compute(context)`。
3. 用户可以创建因子分析任务。
4. 任务能异步运行并落盘标准 JSON。
5. 结果包含 IC、RankIC、分组收益、多空收益、覆盖率。
6. 外部 agent 可以通过 quick API 或标准脚本创建因子分析结果。
7. 因子分析不要求用户代码计算未来收益。
8. 因子分析代码加载前必须重新 validator 复验。
9. 测试不依赖真实 `data/`，使用 fixture。
10. 全量单元测试和前端 build 稳定通过。

## 19. 主要风险

1. **偷看未来风险**  
   因子代码如果直接查询未来日期或自己计算 forward return，会污染结果。MVP 先靠 validator 和文档约束，后续可增加 context 限权。

2. **计算性能风险**  
   因子分析是逐日横截面计算，数据量远大于事件样本。需要优先使用批量读取和缓存，避免每只股票逐个 SQL 查询。

3. **过早抽象风险**  
   虽然事件分析和因子分析相似，但第一版不建议强行抽公共父类。先复制骨架，跑通闭环，再提取公共 helper。

4. **指标解释风险**  
   IC、分组收益、多空收益容易被误读。前端和文档必须明确方向、窗口、样本量和覆盖率。

5. **前端复杂度风险**  
   因子图表很多，MVP 先展示核心摘要和 3-4 个图，不要一口气做完整研究平台。

## 20. 推荐交给 Agent 的任务拆分

### Agent A：核心因子引擎

负责：

- `factor_analysis/template.py`
- `factor_analysis/loader.py`
- `factor_analysis/metrics.py`
- `factor_analysis/engine.py`
- engine 相关测试

### Agent B：后端定义和任务 API

负责：

- DB schema
- backend schemas
- factor definition service/api
- factor analysis service/api
- backend API 测试

### Agent C：标准脚本和文档

负责：

- `run_standard_factor_analysis.py`
- Agent 指南
- API guide 更新
- Project overview 更新

### Agent D：前端最小接入

负责：

- 因子定义列表
- 因子分析任务列表
- 结果摘要和图表
- build 验证

推荐顺序：

```text
Agent A -> Agent B -> Agent C -> Agent D
```

如果并行，Agent A 和 Agent B 需要先约定 result JSON 和 Pydantic schema，避免接口对不上。
