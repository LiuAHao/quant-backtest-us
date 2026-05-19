# Agent 标准化因子分析指南

本指南用于约束外部 Agent、WebAgent 或本地脚本，如何生成前端可识别的标准化单因子分析结果。

如果希望结果能被前端“因子分析”“因子结果”和“报告中心”稳定展示，就按本指南执行。

## 标准入口

Agent 自动运行因子分析时，只允许使用两种标准入口：

1. `POST /api/factor-analyses/quick`
2. `scripts/agent_entry/run_standard_factor_analysis.py`

标准脚本推荐优先使用，因为它支持双模式：

- 后端在线时：自动调用标准 API
- 后端未启动时：自动本地直跑，并回填标准任务结果

## 因子代码规范

因子代码必须继承 `FactorAnalysisTemplate`，并实现 `compute(self, context)`。

推荐写法：

```python
from __future__ import annotations

from factor_analysis.template import FactorAnalysisTemplate


class Momentum20Factor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("20日动量因子")

    def compute(self, context):
        current_date = context["current_date"].strftime("%Y-%m-%d")
        market = context["market_data"][["ts_code"]].drop_duplicates().copy()
        market["ts_code"] = market["ts_code"].astype(str)
        if market.empty:
            return market.assign(trade_date=current_date, factor_value=[])

        sql = f"""
            WITH recent AS (
                SELECT
                    d.ts_code,
                    d.close,
                    ROW_NUMBER() OVER (PARTITION BY d.ts_code ORDER BY d.trade_date DESC) AS rn
                FROM daily_bar d
                WHERE d.trade_date <= '{current_date}'
                  AND d.ts_code IN (
                      SELECT ts_code FROM market_codes
                  )
            ), pivoted AS (
                SELECT
                    ts_code,
                    MAX(CASE WHEN rn = 1 THEN close END) AS close_now,
                    MAX(CASE WHEN rn = 21 THEN close END) AS close_then
                FROM recent
                WHERE rn <= 21
                GROUP BY ts_code
            )
            SELECT
                ts_code,
                '{current_date}' AS trade_date,
                close_now / NULLIF(close_then, 0) - 1 AS factor_value
            FROM pivoted
            WHERE close_now IS NOT NULL
              AND close_then IS NOT NULL
        """
        context["conn"].register("market_codes", market)
        try:
            return context["conn"].execute(sql).fetchdf()
        finally:
            context["conn"].unregister("market_codes")
```

必须返回：

```text
ts_code
trade_date
factor_value
```

禁止在因子代码里做这些事：

- 计算未来收益、未来排名或 forward return。
- 下单、调仓、写账户、仓位、订单、净值逻辑。
- 读写文件、请求网络、执行系统命令。
- 直接绕过平台写结果 JSON。
- 在 `compute()` 里对当前截面逐股票循环调用 `get_history()` 计算历史窗口因子，尤其不要写成“每只股票一次 SQL/一次历史查询”的模式；这会在日频、多股票池、多窗口场景下明显拖慢整条因子分析链路。

性能经验规则：

- 能基于 `context["market_data"]` 直接算的，就不要查历史。
- 需要历史窗口时，优先用 `context["conn"]` 做单次批量 SQL。
- 如果只对当前股票池计算，先从 `market_data` 提取 `ts_code` 列表，再把范围缩到当前股票池，不要全市场无界扫描。

更完整的代码约束见 [FACTOR_ANALYSIS_BUILD_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/FACTOR_ANALYSIS_BUILD_GUIDE.md)。

## 标准脚本

```bash
python scripts/agent_entry/run_standard_factor_analysis.py \
  --factor-file <path> \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 1,5,10,20 \
  --quantiles 5
```

常用参数：

```text
--factor-key
--factor-name
--universe all_a|exclude_beijing|main_board_only
--filter exclude_st
--filter exclude_new_stock
--filter exclude_kcb_cyb
--filter exclude_main_board
--filter exclude_beijing
--rebalance-rule daily|weekly|monthly
--ic-method spearman|pearson
--factor-direction higher_better|lower_better
--winsorize mad|none
--standardize zscore|none
```

脚本会优先调用在线后端 `/api/factor-analyses/quick`。如果后端不可用，则本地运行 engine，并写入标准 SQLite 任务和结果 JSON。

## Quick API

```text
POST /api/factor-analyses/quick
```

请求示例：

```json
{
  "factor_code": "from factor_analysis.template import FactorAnalysisTemplate\n...",
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

Agent 推荐调用顺序：

1. 生成因子代码。
2. 调用 `POST /api/factor-definitions/validate` 做静态校验。
3. 调用 `POST /api/factor-analyses/quick` 创建标准任务。
4. 轮询 `GET /api/factor-analyses/{task_id}`。
5. 成功后读取 `GET /api/factor-analyses/{task_id}/result`。

## 输出结果

标准脚本成功后输出 JSON 行，包含：

```text
mode
task_id
status
result_json_path
sample_count
summary
```

结果文件包含：

```text
task
payload.summary.ic
payload.summary.rank_ic
payload.summary.group_returns
payload.summary.long_short
payload.summary.coverage
payload.charts.ic_series
payload.charts.group_returns
payload.charts.long_short_curve
payload.charts.coverage_series
payload.tables.latest_factor_samples
payload.details
```

## 前端可识别标准

一份因子分析结果要被前端正常识别，至少要满足：

- 存在标准 `factor_definitions` 记录。
- 存在标准 `factor_definition_versions` 记录。
- 存在标准 `factor_analysis_tasks` 记录。
- `factor_analysis_tasks.status = success`。
- `summary_json` 可解析。
- `result_json_path` 指向存在的标准 JSON 文件。

因此，是否被前端识别，不取决于你有没有跑过因子代码，而取决于你有没有产出标准任务记录和标准结果文件。

## 与事件分析的区别

| 维度 | 事件分析 | 因子分析 |
| --- | --- | --- |
| 用户代码方法 | `scan(context)` | `compute(self, context)` |
| 返回核心列 | `ts_code`, `trade_date` | `ts_code`, `trade_date`, `factor_value` |
| 用户代码职责 | 定义事件样本 | 定义当日截面因子值 |
| 平台统计 | 事件后收益 | IC、RankIC、分组、多空、覆盖率 |
| 禁止事项 | 未来收益、交易逻辑 | 未来收益、交易逻辑 |

## 存放边界

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 因子定义代码 | `backend/storage/factor_analyses/generated/` | 通过 API 或服务写入，自动生成，不手工编辑 |
| 因子结果 JSON | `backend/storage/factor_analyses/results/` | 任务运行后自动生成 |
| Agent 临时实验脚本 | `scripts/agent_simulation/` | 不进 git，不作为标准入口 |
| 标准入口脚本 | `scripts/agent_entry/run_standard_factor_analysis.py` | 外部 Agent 应调用它 |

不要把规范因子代码写到 `scripts/agent_simulation/`，也不要只在那里存放需要后端导入的文件。
