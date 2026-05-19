# 因子分析代码构建指南

本指南用于外部 Agent、WebAgent 或开发者，把自然语言因子需求转换成可保存、可校验、可运行的单因子分析代码。

## 因子分析是什么

因子分析不是交易策略，也不是事件样本扫描。

- 策略：决定何时买卖、持仓多少、如何调仓。
- 事件分析：扫描“某股票某天是否发生事件”，平台统计事件后收益。
- 因子分析：计算“某股票某天的截面因子值”，平台统计 IC、RankIC、分组收益、多空收益和覆盖率。

因子代码只负责输出当日可解释的 `factor_value`。未来收益、分组收益、IC 和报告都由平台统一计算。

## 标准执行入口

如果希望结果能被前端“因子分析 / 因子结果 / 报告中心”稳定识别，优先使用标准脚本：

```bash
python scripts/agent_entry/run_standard_factor_analysis.py \
  --factor-file <path> \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 1,5,10,20 \
  --quantiles 5
```

脚本会优先调用在线后端 `POST /api/factor-analyses/quick`。后端不可用时，会本地运行 `FactorAnalysisEngine`，并写入标准 SQLite 任务和结果 JSON。

## 最小代码接口

因子代码必须继承：

```python
from factor_analysis.template import FactorAnalysisTemplate
```

必须实现：

```python
compute(self, context)
```

`compute(self, context)` 必须返回 `pandas.DataFrame`，至少包含：

```text
ts_code
trade_date
factor_value
```

其中：

- `ts_code`：股票代码。
- `trade_date`：因子所属交易日，格式建议为 `YYYY-MM-DD`。
- `factor_value`：数值型因子值。

## 可用 context

常用字段：

| 字段 | 说明 |
| --- | --- |
| `context["start_date"]` | 分析开始日期，`datetime` |
| `context["end_date"]` | 分析结束日期，`datetime` |
| `context["current_date"]` | 当前截面日期，`datetime` |
| `context["windows"]` | 未来收益观察窗口，如 `[1, 5, 10, 20]` |
| `context["universe"]` | 股票池配置 |
| `context["filters"]` | 前端过滤条件 |
| `context["market_data"]` | 当前截面行情，已按股票池和过滤条件处理 |
| `context["data_loader"]` | `DataLoader` 实例 |
| `context["conn"]` | DuckDB 连接 |
| `context["get_history"]` | 个股历史数据查询函数 |
| `context["get_cross_section"]` | 横截面查询函数 |
| `context["trade_date_index"]` | 交易日序号查询函数 |
| `context["get_trade_dates"]` | 当前分析相关交易日列表 |

优先使用 `context["market_data"]` 计算当日截面因子。需要历史窗口时，优先使用 `context["conn"]` 一次性批量查询，避免逐股票循环 SQL。

## 性能反例与规避规则

已经确认过一个高频错误模式：

- 在 `compute(self, context)` 中遍历 `market_data["ts_code"]`
- 对每只股票都调用一次 `context["get_history"](...)`
- 再拼装 `factor_value`

这种写法在日频因子分析里会退化成：

- `分析日数量 × 股票数量 × 单股历史查询成本`

当区间较长、股票池较大时，耗时会显著放大。

反例（不要这样写）：

```python
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

推荐替代方式：

- 先从 `context["market_data"]` 提取当前股票池
- 用 `context["conn"]` 对当前股票池做一次批量 SQL
- 在 SQL 里完成历史窗口取值和因子计算

核心原则：

1. 不要逐股票查历史。
2. 不要把历史窗口计算写成 Python 层 N 次小查询。
3. 优先把历史窗口问题改写成 DuckDB 的窗口函数 / 分组聚合。
4. 如果只是当前股票池分析，务必把 SQL 范围限制在当前股票池，而不是无界全市场扫描。

## 可查询数据表

因子代码常用表：

| 表 | 常用字段 |
| --- | --- |
| `daily_bar` | `ts_code`, `trade_date`, `open`, `high`, `low`, `close`, `pre_close`, `volume`, `amount` |
| `daily_basic` | `turnover_rate`, `turnover_rate_f`, `volume_ratio`, `pe`, `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `total_mv`, `circ_mv` |
| `stk_limit` | `ts_code`, `trade_date`, `up_limit`, `down_limit` |
| `suspend_d` | 停复牌相关字段 |
| `instruments` | `ts_code`, `symbol`, `exchange`, `list_date`, `status` |

DuckDB 查询日期统一使用 `YYYY-MM-DD` 字符串。

## 平台统一处理的部分

不要在因子代码中实现这些逻辑：

- 未来收益计算。
- IC / RankIC。
- 分组收益。
- 多空收益。
- 覆盖率。
- 报告生成。
- 前端展示结构。
- 账户、仓位、订单、调仓和净值。

平台当前支持的运行参数：

| 参数 | 说明 |
| --- | --- |
| `windows` | 未来收益窗口 |
| `universe` | `all_a`, `exclude_beijing`, `main_board_only` |
| `filters` | `exclude_st`, `exclude_new_stock`, `exclude_kcb_cyb`, `exclude_main_board`, `exclude_beijing` |
| `rebalance_rule` | `daily`, `weekly`, `monthly` |
| `quantiles` | 分组数量，2 到 20 |
| `ic_method` | `spearman` 或 `pearson` |
| `factor_direction` | `higher_better` 或 `lower_better` |
| `preprocessing` | 当前落地 `winsorize`, `standardize`；`neutralize` 为后续扩展字段 |

## AI 生成边界

AI 生成因子代码时应遵守：

- 只输出 JSON 对象，字段为 `name`, `key`, `description`, `tags`, `code`。
- `code` 必须是完整 Python 代码字符串。
- 代码只定义一个因子类。
- 因子类必须支持无参数初始化。
- 不要自己计算未来收益。
- 不要写账户、仓位、订单、买卖、调仓、回测逻辑。
- 不要请求网络，不要读写文件。
- 不要臆造字段，例如 `daily_basic.roe`、`daily_bar.factor_value`、`instruments.industry`。

AI 接口：

```text
POST /api/factor-definitions/ai-fill
```

请求：

```json
{
  "prompt": "构造20日动量因子，因子值为当前收盘价相对20个交易日前收盘价的涨跌幅"
}
```

响应字段：

```text
name
key
description
tags
code
```

## 标准示例

```python
from __future__ import annotations

from factor_analysis.template import FactorAnalysisTemplate


class Momentum20dFactor(FactorAnalysisTemplate):
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
                    ROW_NUMBER() OVER (
                        PARTITION BY d.ts_code
                        ORDER BY d.trade_date DESC
                    ) AS rn
                FROM daily_bar d
                WHERE d.trade_date <= '{current_date}'
                  AND d.ts_code IN (
                      SELECT ts_code FROM market_codes
                  )
            ),
            pivoted AS (
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

## 标准 API

因子定义：

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

因子任务：

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

标准 quick 请求：

```json
{
  "factor_code": "...",
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

## 结果结构

结果 JSON 主要包含：

```text
task
payload.summary
payload.charts
payload.tables
payload.details
```

常用字段：

| 字段 | 说明 |
| --- | --- |
| `summary.ic` | 各窗口 IC 摘要 |
| `summary.rank_ic` | 各窗口 RankIC 摘要 |
| `summary.group_returns` | 各窗口分组收益 |
| `summary.long_short` | 多空收益摘要 |
| `summary.coverage` | 覆盖率摘要 |
| `charts.ic_series` | IC / RankIC 时间序列 |
| `charts.group_returns` | 分组收益序列 |
| `charts.long_short_curve` | 多空累计曲线 |
| `charts.coverage_series` | 覆盖率序列 |
| `tables.latest_factor_samples` | 因子样本展示 |

## 常见错误

- 返回列名写成 `value` 但未被平台识别：优先返回 `factor_value`。
- 在因子代码里计算 `ret_5d` 或 `future_return`：这会污染分析结果，validator 会拦截常见写法。
- 使用不存在字段：先查 `docs/quant-data-guide.md` 或使用真实 parquet 字段。
- 逐股票循环查历史：小样本能跑，大区间会很慢；优先批量 SQL。
- 把因子写成交易策略：因子代码没有下单接口，交易逻辑应放在策略模块。
