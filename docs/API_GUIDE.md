# Quant Backtest API 完整指南

## 目录
- [概述](#概述)
- [快速开始](#快速开始)
- [API端点详解](#api端点详解)
  - [系统接口](#系统接口)
  - [策略管理](#策略管理)
  - [回测任务](#回测任务)
  - [回测报告](#回测报告)
  - [配置中心](#配置中心)
- [数据模型](#数据模型)
- [策略开发指南](#策略开发指南)
- [事件分析开发指南](#事件分析开发指南)
- [因子分析开发指南](#因子分析开发指南)
- [Agent集成指南](#agent集成指南)
- [常见问题](#常见问题)

---

## 概述

Quant Backtest 是一个本地量化回测系统，提供RESTful API接口，支持：
- 策略代码管理（创建、验证、版本控制）
- 异步回测任务执行
- 事件分析和因子分析任务执行
- 回测报告生成和分析
- 统一配置管理（前端和Agent共用）

**基础信息：**
- API基础地址：`http://127.0.0.1:8000`
- 数据格式：JSON
- 认证方式：无（本地服务）

---

## 快速开始

### 1. 启动服务

```bash
# 启动后端
python -m uvicorn backend.main:app --reload \
  --reload-exclude 'backend/storage/strategies/*' \
  --reload-exclude 'backend/storage/event_analyses/generated/*' \
  --reload-exclude 'backend/storage/factor_analyses/generated/*' \
  --host 127.0.0.1 --port 8000

# 启动前端（可选）
cd frontend && npm run dev
```

### 2. 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

响应：
```json
{"status": "ok"}
```

### 3. Agent快速回测（推荐）

```bash
# 一键回测：一个请求完成策略创建+回测启动
curl -X POST http://127.0.0.1:8000/api/backtests/quick \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_code": "from backtest.strategy import StrategyTemplate\nclass MyStrategy(StrategyTemplate):\n    def __init__(self):\n        super().__init__(\"我的策略\")\n    def init(self, context):\n        pass\n    def next(self, context):\n        pass",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31"
  }'
```

### 3.1 标准化回测结果生成约定（WebAgent 必读）

如果希望回测结果能够被前端“回测结果”和“报告中心”稳定识别，**只能**通过以下两种标准方式创建：

1. `POST /api/backtests/quick`
2. 运行脚本 [run_standard_backtest.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_backtest.py)

不要直接写数据库、不要手工写报告 JSON/HTML、不要只生成策略文件不创建 `backtest_tasks` 记录，否则前端可能出现：

- 列表有任务但详情空白
- 报告文件存在但前端无法加载
- 策略已保存但没有标准化回测结果

标准化链路的定义是：

- 创建或复用一个合法策略
- 创建 `backtest_tasks` 记录
- 由后端异步执行回测
- 由回测引擎自动生成标准 JSON/HTML 报告
- 将 `report_json_path` / `report_html_path` 回填到任务表
- 前端通过 `/api/backtests` 和 `/api/reports/{task_id}` 展示结果

WebAgent 推荐调用顺序：

1. 提交 `POST /api/backtests/quick`
2. 轮询 `GET /api/backtests/{task_id}`，直到 `status=success`
3. 再读取 `GET /api/reports/{task_id}`

### 3.2 标准化回测脚本

如果 agent 更适合通过脚本执行，请使用：

```bash
.venv/bin/python scripts/agent_entry/run_standard_backtest.py \
  --strategy-file backend/storage/strategies/test_buy_and_hold.py \
  --start 2026-04-01 \
  --end 2026-04-29
```

脚本行为：

- 后端在线时：调用标准接口 `POST /api/backtests/quick`
- 后端未启动时：直接在本地运行回测引擎，并写入标准 `backtest_tasks`
- 两种模式都会生成相同格式的标准报告，并回填任务表
- 成功后输出标准报告路径和核心指标

这条链路生成的结果会被前端“回测结果”和“报告中心”正常识别。

### 3.3 标准化事件分析结果生成约定（WebAgent 必读）

如果希望事件分析结果能够被前端“事件分析”页面稳定识别，**只能**通过以下两种标准方式创建：

1. `POST /api/event-analyses/quick`
2. 运行脚本 [run_standard_event_analysis.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_event_analysis.py)

不要直接写数据库、不要手工写结果 JSON、不要只生成事件定义文件不创建 `event_analysis_tasks` 记录。

标准化链路的定义是：

- 创建或复用一个合法事件定义
- 创建 `event_analysis_tasks` 记录
- 由后端异步执行或本地脚本直跑 `EventAnalysisEngine`
- 统一生成标准结果 JSON
- 将 `summary_json` / `result_json_path` 回填到任务表
- 前端通过 `/api/event-analyses` 和 `/api/event-analyses/{task_id}/result` 展示结果

WebAgent 推荐调用顺序：

1. 提交 `POST /api/event-analyses/quick`
2. 轮询 `GET /api/event-analyses/{task_id}`，直到 `status=success`
3. 再读取 `GET /api/event-analyses/{task_id}/result`

### 3.4 标准化事件分析脚本

```bash
.venv/bin/python scripts/agent_entry/run_standard_event_analysis.py \
  --event-file backend/storage/event_analyses/generated/limit_down_rebound_event.py \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 5,10,15 \
  --filter exclude_st \
  --filter exclude_new_stock
```

脚本行为：

- 后端在线时：调用标准接口 `POST /api/event-analyses/quick`
- 后端未启动时：直接在本地运行事件分析引擎，并写入标准 `event_analysis_tasks`
- 两种模式都会生成相同格式的标准结果，并回填任务表
- 成功后输出结果路径、样本数和摘要统计

### 3.5 标准化因子分析结果生成约定（WebAgent 必读）

如果希望因子分析结果能够被前端“因子分析”“因子结果”和“报告中心”稳定识别，**只能**通过以下两种标准方式创建：

1. `POST /api/factor-analyses/quick`
2. 运行脚本 [run_standard_factor_analysis.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_factor_analysis.py)

不要直接写数据库、不要手工写结果 JSON、不要只生成因子定义文件不创建 `factor_analysis_tasks` 记录。

标准化链路的定义是：

- 创建或复用一个合法因子定义
- 创建 `factor_analysis_tasks` 记录
- 由后端异步执行或本地脚本直跑 `FactorAnalysisEngine`
- 统一计算未来收益、IC、RankIC、分组收益、多空收益和覆盖率
- 统一生成标准结果 JSON
- 将 `summary_json` / `result_json_path` 回填到任务表
- 前端通过 `/api/factor-analyses` 和 `/api/factor-analyses/{task_id}/result` 展示结果

WebAgent 推荐调用顺序：

1. 提交 `POST /api/factor-analyses/quick`
2. 轮询 `GET /api/factor-analyses/{task_id}`，直到 `status=success`
3. 再读取 `GET /api/factor-analyses/{task_id}/result`

### 3.6 标准化因子分析脚本

```bash
.venv/bin/python scripts/agent_entry/run_standard_factor_analysis.py \
  --factor-file backend/storage/factor_analyses/generated/momentum_20d.py \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 1,5,10,20 \
  --filter exclude_st \
  --filter exclude_new_stock \
  --quantiles 5
```

脚本行为：

- 后端在线时：调用标准接口 `POST /api/factor-analyses/quick`
- 后端未启动时：直接在本地运行因子分析引擎，并写入标准 `factor_analysis_tasks`
- 两种模式都会生成相同格式的标准结果，并回填任务表
- 成功后输出结果路径、样本数和摘要统计

### 4. 传统回测流程

```bash
# 步骤1：验证策略代码
curl -X POST http://127.0.0.1:8000/api/strategies/validate \
  -H "Content-Type: application/json" \
  -d '{"code": "..."}'

# 步骤2：保存策略（name 必须包含中文）
curl -X POST http://127.0.0.1:8000/api/strategies \
  -H "Content-Type: application/json" \
  -d '{"key": "my_strategy", "name": "我的策略", "code": "..."}'

# 步骤3：创建回测任务
curl -X POST http://127.0.0.1:8000/api/backtests \
  -H "Content-Type: application/json" \
  -d '{"strategy_id": 1, "start_date": "2024-01-01", "end_date": "2024-12-31"}'

# 步骤4：查询回测状态
curl http://127.0.0.1:8000/api/backtests/1
```

---

## API端点详解

### 系统接口

#### 健康检查
```
GET /api/health
```

**响应示例：**
```json
{"status": "ok"}
```

---

### 策略管理

#### 1. 获取所有策略
```
GET /api/strategies
```

**响应示例：**
```json
[
  {
    "id": 1,
    "key": "small_cap_rotation",
    "name": "小市值轮动策略",
    "description": "每5天调仓一次，选取市值最小的10只股票",
    "source": "manual",
    "tags": ["小市值", "轮动"],
    "status": "enabled",
    "current_version_id": 1,
    "version": 1,
    "validation_status": "passed",
    "validation_message": "校验通过",
    "created_at": "2024-01-01 10:00:00",
    "updated_at": "2024-01-01 10:00:00"
  }
]
```

#### 2. 创建策略
```
POST /api/strategies
```

> **注意：`name` 字段必须包含中文，否则返回 400 错误。** 详见 [STRATEGY_BUILD_GUIDE.md](STRATEGY_BUILD_GUIDE.md) 的中文命名规范。

**请求体：**
```json
{
  "key": "my_strategy",
  "name": "策略名称",
  "description": "策略描述",
  "source": "manual",
  "tags": ["标签1", "标签2"],
  "code": "策略代码",
  "status": "enabled"
}
```

#### 3. 验证策略代码
```
POST /api/strategies/validate
```

**请求体：**
```json
{
  "code": "策略代码"
}
```

**响应：**
```json
{
  "ok": true,
  "status": "passed",
  "message": "校验通过：语法、策略类结构和基础安全规则均满足要求",
  "class_name": "MyStrategy",
  "dependencies": ["pandas", "numpy"]
}
```

#### 4. AI生成策略
```
POST /api/strategies/ai-fill
```

**请求体：**
```json
{
  "prompt": "创建一个小市值轮动策略，每5天调仓一次"
}
```

#### 5. 获取策略模板
```
GET /api/strategies/templates/list
```

**响应：**
```json
[
  {
    "key": "small_cap_rotation",
    "name": "小市值轮动",
    "description": "经典的小市值轮动策略，定期调仓",
    "params": {"hold_days": 5, "stock_count": 10}
  }
]
```

#### 6. 获取模板代码
```
GET /api/strategies/templates/{template_key}/code
```

---

### 事件分析开发指南

事件分析 AI 生成与代码编写规范请查看：

- [EVENT_ANALYSIS_BUILD_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/EVENT_ANALYSIS_BUILD_GUIDE.md)

事件分析 AI 生成接口：

```text
POST /api/event-definitions/ai-fill
```

该接口会根据自然语言返回一个可直接保存的 JSON 对象，字段固定为：

- `name`
- `key`
- `description`
- `tags`
- `code`

---

### 因子分析开发指南

因子分析 AI 生成与代码编写规范请查看：

- [FACTOR_ANALYSIS_BUILD_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/FACTOR_ANALYSIS_BUILD_GUIDE.md)

因子分析 AI 生成接口：

```text
POST /api/factor-definitions/ai-fill
```

该接口会根据自然语言返回一个可直接保存的 JSON 对象，字段固定为：

- `name`
- `key`
- `description`
- `tags`
- `code`

因子代码必须继承 `FactorAnalysisTemplate`，实现 `compute(self, context)`，返回包含 `ts_code`、`trade_date`、`factor_value` 的 DataFrame。因子代码只负责计算当日截面因子值，不要自己计算未来收益，也不要写账户、仓位、订单、调仓或回测逻辑。

---

### 回测任务

#### 1. 一键回测（Agent推荐）
```
POST /api/backtests/quick
```

**请求体：**
```json
{
  "strategy_code": "策略代码",
  "strategy_key": "可选，不提供则自动生成",
  "strategy_name": "可选，不提供则自动提取",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 1000000,
  "commission_rate": 0.0003,
  "slippage": 0.001
}
```

**响应：**
```json
{
  "id": 1,
  "strategy_id": 1,
  "strategy_version_id": 1,
  "status": "queued",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 1000000,
  "commission_rate": 0.0003,
  "slippage": 0.001,
  "progress": 0,
  "created_at": "2024-01-01 10:00:00"
}
```

说明：

- 这是当前推荐的标准入口
- 通过该接口创建的成功任务会自动生成标准化报告
- 前端识别依据是 `backtest_tasks` 中的任务记录和 `report_json_path/report_html_path`

#### 2. 获取所有回测任务
```
GET /api/backtests
```

#### 3. 创建回测任务
```
POST /api/backtests
```

**请求体：**
```json
{
  "strategy_id": 1,
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 1000000,
  "commission_rate": 0.0003,
  "slippage": 0.001
}
```

#### 4. 获取单个回测任务
```
GET /api/backtests/{task_id}
```

**响应示例：**
```json
{
  "id": 1,
  "strategy_id": 1,
  "strategy_version_id": 1,
  "status": "success",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 1000000,
  "commission_rate": 0.0003,
  "slippage": 0.001,
  "progress": 100,
  "report_json_path": "/path/to/report.json",
  "report_html_path": "/path/to/report.html",
  "error_message": null,
  "created_at": "2024-01-01 10:00:00",
  "started_at": "2024-01-01 10:00:01",
  "finished_at": "2024-01-01 10:05:30",
  "total_return": 0.15,
  "max_drawdown": -0.08,
  "sharpe_ratio": 1.2
}
```

#### 5. 取消回测任务
```
POST /api/backtests/{task_id}/cancel
```

#### 6. 删除回测任务
```
DELETE /api/backtests/{task_id}
```

---

### 因子定义

#### 1. 获取所有因子定义
```
GET /api/factor-definitions
```

#### 2. 创建因子定义
```
POST /api/factor-definitions
```

**请求体：**
```json
{
  "key": "momentum_20d",
  "name": "20日动量因子",
  "description": "计算当前收盘价相对20个交易日前收盘价的涨跌幅",
  "source": "manual",
  "tags": ["动量", "因子分析"],
  "code": "from factor_analysis.template import FactorAnalysisTemplate\n...",
  "status": "enabled"
}
```

#### 3. 验证因子代码
```
POST /api/factor-definitions/validate
```

**请求体：**
```json
{
  "code": "因子代码"
}
```

**响应：**
```json
{
  "ok": true,
  "status": "passed",
  "message": "校验通过：语法、因子类结构和基础安全规则均满足要求",
  "class_name": "Momentum20dFactor",
  "dependencies": ["pandas"]
}
```

#### 4. AI 生成因子定义
```
POST /api/factor-definitions/ai-fill
```

**请求体：**
```json
{
  "prompt": "构造20日动量因子，因子值为当前收盘价相对20个交易日前收盘价的涨跌幅"
}
```

说明：

- 需要在 `.env` 中配置 `AI_API_KEY` 或 `OPENAI_API_KEY`
- AI 返回的是待保存草稿，仍需通过 validator 校验
- 生成代码必须实现 `compute(self, context)`，不得计算未来收益或交易逻辑

#### 5. 常用管理接口
```
GET    /api/factor-definitions/{definition_id}
PUT    /api/factor-definitions/{definition_id}
DELETE /api/factor-definitions/{definition_id}
POST   /api/factor-definitions/batch-delete
POST   /api/factor-definitions/{definition_id}/enable
POST   /api/factor-definitions/{definition_id}/disable
```

---

### 因子分析任务

#### 1. 一键因子分析（Agent 推荐）
```
POST /api/factor-analyses/quick
```

**请求体：**
```json
{
  "factor_code": "因子代码",
  "factor_key": "momentum_20d",
  "factor_name": "20日动量因子",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "windows": [1, 5, 10, 20],
  "universe": "all_a",
  "filters": ["exclude_st", "exclude_new_stock"],
  "rebalance_rule": "daily",
  "quantiles": 5,
  "ic_method": "spearman",
  "factor_direction": "higher_better",
  "preprocessing": {
    "winsorize": "mad",
    "standardize": "zscore"
  }
}
```

**响应：**
```json
{
  "id": 1,
  "factor_definition_id": 1,
  "factor_definition_version_id": 1,
  "status": "queued",
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "windows": [1, 5, 10, 20],
  "universe": "all_a",
  "filters": ["exclude_st", "exclude_new_stock"],
  "rebalance_rule": "daily",
  "quantiles": 5,
  "ic_method": "spearman",
  "factor_direction": "higher_better",
  "preprocessing": {
    "winsorize": "mad",
    "standardize": "zscore"
  },
  "progress": 0
}
```

#### 2. 创建因子分析任务
```
POST /api/factor-analyses
```

**请求体：**
```json
{
  "factor_definition_id": 1,
  "start_date": "2025-01-01",
  "end_date": "2025-12-31",
  "windows": [1, 5, 10, 20],
  "universe": "all_a",
  "filters": ["exclude_st", "exclude_new_stock"],
  "rebalance_rule": "daily",
  "quantiles": 5,
  "ic_method": "spearman",
  "factor_direction": "higher_better",
  "preprocessing": {
    "winsorize": "mad",
    "standardize": "zscore"
  }
}
```

#### 3. 查询和读取结果
```
GET /api/factor-analyses
GET /api/factor-analyses/page
GET /api/factor-analyses/{task_id}
GET /api/factor-analyses/{task_id}/result
```

结果 payload 主要字段：

```text
summary.ic
summary.rank_ic
summary.group_returns
summary.long_short
summary.coverage
charts.ic_series
charts.group_returns
charts.long_short_curve
charts.coverage_series
tables.latest_factor_samples
details
```

#### 4. 取消和删除
```
POST   /api/factor-analyses/{task_id}/cancel
DELETE /api/factor-analyses/{task_id}
POST   /api/factor-analyses/batch-delete
```

---

### 回测报告

#### 1. 获取所有报告
```
GET /api/reports
```

#### 2. 获取单个报告
```
GET /api/reports/{task_id}
```

**响应示例：**
```json
{
  "task_id": 1,
  "strategy_name": "小市值轮动策略",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 1000000,
  "final_capital": 1150000,
  "total_return": 0.15,
  "annual_return": 0.15,
  "max_drawdown": -0.08,
  "sharpe_ratio": 1.2,
  "win_rate": 0.55,
  "profit_loss_ratio": 1.5,
  "total_trades": 50
}
```

#### 3. 下载报告
```
GET /api/reports/{task_id}/download?format=json
GET /api/reports/{task_id}/download?format=html
```

说明：
- JSON 下载会自动注入 `runtime.logs`（运行日志），内容与页面展示一致
- HTML 下载会在页面末尾追加"运行日志"表格（时间/级别/消息）
- 事件分析结果仅支持 `format=json`
- 因子分析结果仅支持 `format=json`
- 因子分析报告下载需要传 `kind=factor_analysis`，例如 `/api/reports/{task_id}/download?kind=factor_analysis&format=json`

---

### 配置中心

#### 1. 系统信息
```
GET /api/config/system-info
```

**响应：**
```json
{
  "version": "0.1.0",
  "data_dir": "/path/to/data",
  "db_path": "/path/to/meta.duckdb",
  "strategy_dir": "/path/to/strategies",
  "available_data_range": {
    "earliest": "2014-01-02",
    "latest": "2026-04-29"
  },
  "total_strategies": 5,
  "total_backtests": 10,
  "total_presets": 3
}
```

#### 2. 回测预设管理

##### 获取所有预设
```
GET /api/config/presets
```

##### 获取默认预设
```
GET /api/config/presets/default
```

##### 创建预设
```
POST /api/config/presets
```

**请求体：**
```json
{
  "name": "保守型配置",
  "description": "低风险配置，适合稳健策略",
  "initial_capital": 1000000,
  "commission_rate": 0.0003,
  "slippage": 0.001,
  "benchmark": "hs300",
  "is_default": false
}
```

##### 更新预设
```
PUT /api/config/presets/{preset_id}
```

##### 删除预设
```
DELETE /api/config/presets/{preset_id}
```

---

## 数据模型

### 策略模型

```python
class StrategyCreate(BaseModel):
    key: str              # 策略唯一标识
    name: str             # 策略名称
    description: str      # 策略描述
    source: str           # 来源：manual/ai/builtin
    tags: list[str]       # 标签列表
    code: str             # 策略代码
    status: str           # 状态：enabled/disabled/draft/archived
```

### 回测任务模型

```python
class BacktestCreate(BaseModel):
    strategy_id: int      # 策略ID
    start_date: str       # 开始日期 YYYY-MM-DD
    end_date: str         # 结束日期 YYYY-MM-DD
    initial_capital: float # 初始资金
    commission_rate: float # 手续费率
    slippage: float       # 滑点
    benchmark: str | None # 基准，可选，如 hs300
```

### 一键回测模型

```python
class QuickBacktestRequest(BaseModel):
    strategy_code: str    # 策略代码（必填）
    strategy_key: str     # 策略key（可选，自动生成）
    strategy_name: str    # 策略名称（可选，自动提取）
    start_date: str       # 开始日期 YYYY-MM-DD
    end_date: str         # 结束日期 YYYY-MM-DD
    initial_capital: float # 初始资金
    commission_rate: float # 手续费率
    slippage: float       # 滑点
```

REST 回测任务当前使用默认成交时序 `next_open`：`next()` 收盘后生成订单，下一交易日开盘撮合。需要模拟当日尾盘下单并按当日收盘价成交时，直接使用 `BacktestEngine(..., execution_mode="same_close")`，或先扩展 API/任务表字段后再暴露到标准任务链路。

---

## 策略开发指南

### 策略模板

所有策略必须继承 `StrategyTemplate` 基类：

```python
from backtest.strategy import StrategyTemplate

class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("策略名称")
    
    def init(self, context):
        """初始化，回测开始前调用一次"""
        pass
    
    def next(self, context):
        """每日收盘后执行；默认生成下一交易日开盘成交的订单"""
        pass
```

### Context 可用对象

| 对象 | 类型 | 说明 |
|-----|------|------|
| context["current_date"] | datetime | 当前交易日 |
| context["market_data"] | DataFrame | 当日行情数据 |
| context["get_history"] | function | 获取历史数据 |
| context["trade_date_index"] | int | 交易日序号 |
| context["data_loader"].conn | Connection | DuckDB连接 |
| context["broker"].account.positions | dict | 当前持仓 |
| context["order_target_percent"] | function | 调仓函数 |
| context["get_price_limit_status"] | function | 判断涨停/跌停并返回涨跌停价 |
| context["is_limit_up"] / context["is_limit_down"] | function | 快速判断涨停/跌停 |

### 示例策略

#### 示例1：小市值轮动策略

```python
from backtest.strategy import StrategyTemplate

class SmallCapRotation(StrategyTemplate):
    def __init__(self):
        super().__init__("小市值轮动")
        self.hold_days = 5
        self.stock_count = 10
    
    def init(self, context):
        self.day_count = 0
    
    def next(self, context):
        self.day_count += 1
        
        if self.day_count % self.hold_days == 1:
            market_data = context["market_data"]
            
            # 选出市值最小的N只股票
            small_caps = market_data.nsmallest(self.stock_count, "total_mv")
            target_stocks = small_caps["ts_code"].tolist()
            
            # 清仓不在目标列表中的股票
            positions = context["broker"].account.positions
            for stock in positions:
                if stock not in target_stocks:
                    context["order_target_percent"](stock, 0)
            
            # 等权买入目标股票
            if target_stocks:
                weight = 1.0 / len(target_stocks)
                for stock in target_stocks:
                    context["order_target_percent"](stock, weight)
```

#### 示例2：双均线策略

```python
from backtest.strategy import StrategyTemplate

class DualMA(StrategyTemplate):
    def __init__(self):
        super().__init__("双均线策略")
        self.stock = "000001.SZ"
        self.short_window = 5
        self.long_window = 20
    
    def init(self, context):
        pass
    
    def next(self, context):
        history = context["get_history"](self.stock, self.long_window + 10)
        
        if len(history) < self.long_window:
            return
        
        history["ma_short"] = history["close"].rolling(self.short_window).mean()
        history["ma_long"] = history["close"].rolling(self.long_window).mean()
        
        latest = history.iloc[-1]
        prev = history.iloc[-2]
        
        if prev["ma_short"] <= prev["ma_long"] and latest["ma_short"] > latest["ma_long"]:
            context["order_target_percent"](self.stock, 1.0)
        elif prev["ma_short"] >= prev["ma_long"] and latest["ma_short"] < latest["ma_long"]:
            context["order_target_percent"](self.stock, 0)
```

### 策略验证规则

1. **语法检查**：代码必须是有效的Python代码
2. **继承检查**：必须有继承 `StrategyTemplate` 的类
3. **方法检查**：必须实现 `init` 和 `next` 方法
4. **安全检查**：禁止使用危险导入和调用
   - 禁止导入：`os`, `subprocess`, `socket`, `shutil`, `requests`, `httpx`, `urllib`, `ftplib`, `pathlib`
   - 禁止调用：`eval`, `exec`, `compile`, `open`, `__import__`

---

## Agent集成指南

### 基本流程

1. **获取系统信息**：了解数据范围和可用策略
2. **创建/获取策略**：创建或选择要回测的策略
3. **获取回测预设**：获取或创建回测配置
4. **创建回测任务**：提交回测请求
5. **监控任务状态**：轮询任务进度
6. **获取报告**：获取回测结果

### Python示例

```python
import requests
import time

BASE_URL = "http://127.0.0.1:8000"

# 1. 获取系统信息
system_info = requests.get(f"{BASE_URL}/api/config/system-info").json()
print(f"数据范围: {system_info['available_data_range']}")

# 2. 一键回测（推荐）
strategy_code = '''
from backtest.strategy import StrategyTemplate

class AgentStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("Agent策略")
    
    def init(self, context):
        pass
    
    def next(self, context):
        pass
'''

backtest = requests.post(f"{BASE_URL}/api/backtests/quick", json={
    "strategy_code": strategy_code,
    "start_date": "2024-01-01",
    "end_date": "2024-12-31"
}).json()
print(f"回测任务ID: {backtest['id']}")

# 3. 监控任务状态
task_id = backtest["id"]
while True:
    task = requests.get(f"{BASE_URL}/api/backtests/{task_id}").json()
    print(f"状态: {task['status']}, 进度: {task['progress']}%")
    
    if task["status"] in ["success", "failed"]:
        break
    time.sleep(1)

# 4. 获取报告
if task["status"] == "success":
    report = requests.get(f"{BASE_URL}/api/reports/{task_id}").json()
    print(f"总收益: {report['total_return']*100:.2f}%")
    print(f"最大回撤: {report['max_drawdown']*100:.2f}%")
    print(f"夏普比率: {report['sharpe_ratio']:.2f}")
```

### 使用配置中心保持一致性

```python
# 获取默认预设
preset = requests.get(f"{BASE_URL}/api/config/presets/default").json()

# 使用预设创建回测
backtest = requests.post(f"{BASE_URL}/api/backtests/quick", json={
    "strategy_code": strategy_code,
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "initial_capital": preset["initial_capital"],
    "commission_rate": preset["commission_rate"],
    "slippage": preset["slippage"]
}).json()
```

---

## 常见问题

### 1. 策略验证失败

**问题**：`未找到继承 StrategyTemplate 的策略类`

**解决**：确保策略类继承自 `StrategyTemplate`：
```python
from backtest.strategy import StrategyTemplate

class MyStrategy(StrategyTemplate):  # 必须继承
    ...
```

### 2. 回测任务失败

**问题**：`data/ 中没有对应日期区间的数据`

**解决**：先更新数据：
```bash
python scripts/data_download/download_by_date.py --start 20140102 --end 20260429
```

### 3. 如何批量回测

```python
# 批量创建回测任务
tasks = []
for strategy_code in [strategy1, strategy2, strategy3]:
    task = requests.post(f"{BASE_URL}/api/backtests/quick", json={
        "strategy_code": strategy_code,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31"
    }).json()
    tasks.append(task["id"])

# 监控所有任务
while True:
    all_done = True
    for task_id in tasks:
        task = requests.get(f"{BASE_URL}/api/backtests/{task_id}").json()
        if task["status"] not in ["success", "failed"]:
            all_done = False
    if all_done:
        break
    time.sleep(1)
```

### 4. 如何获取可用数据范围

```python
info = requests.get(f"{BASE_URL}/api/config/system-info").json()
data_range = info["available_data_range"]
print(f"最早数据: {data_range['earliest']}")
print(f"最新数据: {data_range['latest']}")
```

---

## 附录

### API端点汇总

| 方法 | 路径 | 说明 |
|-----|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/strategies | 获取所有策略 |
| POST | /api/strategies | 创建策略 |
| GET | /api/strategies/{id} | 获取单个策略 |
| PUT | /api/strategies/{id} | 更新策略 |
| POST | /api/strategies/validate | 验证策略代码 |
| POST | /api/strategies/ai-fill | AI生成策略 |
| GET | /api/strategies/templates/list | 获取策略模板列表 |
| GET | /api/strategies/templates/{key}/code | 获取模板代码 |
| POST | /api/strategies/{id}/enable | 启用策略 |
| POST | /api/strategies/{id}/disable | 禁用策略 |
| GET | /api/backtests | 获取所有回测任务 |
| POST | /api/backtests | 创建回测任务 |
| POST | /api/backtests/quick | 一键回测（Agent推荐） |
| GET | /api/backtests/{id} | 获取单个任务 |
| POST | /api/backtests/{id}/cancel | 取消任务 |
| DELETE | /api/backtests/{id} | 删除任务 |
| GET | /api/reports | 获取所有报告 |
| GET | /api/reports/{id} | 获取单个报告 |
| GET | /api/reports/{id}/download | 下载报告 |
| GET | /api/settings | 获取设置 |
| PUT | /api/settings | 更新设置 |
| GET | /api/config/system-info | 系统信息 |
| GET | /api/config/presets | 获取所有预设 |
| POST | /api/config/presets | 创建预设 |
| GET | /api/config/presets/{id} | 获取单个预设 |
| PUT | /api/config/presets/{id} | 更新预设 |
| DELETE | /api/config/presets/{id} | 删除预设 |
| GET | /api/config/presets/default | 获取默认预设 |
