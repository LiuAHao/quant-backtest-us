# Strategies

## 策略可用数据

本系统已补充完整的量化数据，策略可以通过 `context["data_loader"].conn` 查询以下 DuckDB 视图：

| 视图名 | 内容 | 用途 |
| --- | --- | --- |
| `daily_bar` | 日线行情 OHLCV | 基础行情 |
| `daily_basic` | 估值/市值/换手率 | 因子选股 |
| `stk_limit` | 涨跌停价格 | 涨停过滤 |
| `suspend_d` | 停复牌明细 | 停牌过滤 |
| `instruments` | 股票列表（含退市） | 股票池过滤 |
| `namechange` | 名称变更历史 | ST过滤 |
| `stock_industry` | 行业分类（110个行业） | 行业轮动 |
| `fina_indicator` | 财务指标（ROE/ROA等） | 质量因子 |
| `income_stmt` | 利润表 | 盈利分析 |
| `balancesheet` | 资产负债表 | 资产分析 |
| `cashflow` | 现金流量表 | 现金流分析 |
| `performance_express` | 业绩快报（比财报早1-2月） | 事件驱动 |
| `forecast` | 业绩预告（预增/预减/扭亏等） | 事件驱动 |
| `dividend` | 分红送转（含除权日等关键日期） | 高股息策略 |
| `holder_number` | 股东人数变化 | 筹码集中度 |
| `index_member` | 指数成分股 | 指数选股 |
| `concept` / `concept_member` | 概念板块 | 题材选股 |
| `etf_daily` | ETF日线行情 | ETF轮动 |

也可以继续使用引擎注入的 `context["market_data"]` 和 `context["market_data_map"]` 读取当日行情截面。

详细字段、时间范围和示例 SQL 见 [量化数据使用说明](../docs/quant-data-guide.md)。

本目录存放可直接运行的日线策略文件，统一继承 `strategies.template.StrategyTemplate`，由 `backtest.engine.BacktestEngine` 调度。

## 开源仓库建议保留

如果仓库准备公开，建议把本目录中的策略分成“公开模板”和“个人研究产物”两类。

建议保留：

- `strategies/templates.py`
  - 通用模板集合，适合作为新用户起步示例
- `strategies/pure_small_cap_strategy.py`
  - 代表性的全市场小市值轮动样例，能体现项目的数据接入和调仓能力
- `strategies/pure_small_cap_sme.py`
  - 带指数成分股约束的变体，能体现指数成分、停牌、涨停锁仓等更完整的实盘约束

建议不要把以下内容长期提交到公开仓库：

- `strategies/reports/` 下的 HTML / JSON 报告
- 临时测试策略、AI 生成草稿、针对个人研究不断迭代的私有策略版本
- 直接放在 `backend/storage/strategies/` 下的运行时落盘策略文件

更推荐的做法：

- 公开模板和示例放在 `strategies/`
- 运行时生成与用户自定义策略保留在 `backend/storage/strategies/`
- 回测输出统一只保存在 `strategies/reports/` 或 `backend/storage/.../reports/`，并加入 `.gitignore`

## 新增策略

### `chip_trend_pullback_strategy.py`

这是基于截图公式复现的“筹码趋势回撤”策略，分为两部分：

1. 精确映射的条件
   - `跌幅条件`：`(CLOSE - REF(CLOSE, 1)) / REF(CLOSE, 1) * 100 < -4.5`
   - `涨停存在`：近 9 个交易日内至少有 1 次收盘涨幅大于等于 9.9%
   - `多头排列`：`MA5 > MA10 > MA20 > MA60`

2. 近似映射的条件
   - `WINNER(CLOSE)`：仓库没有原生筹码分布数据，因此用“近 120 日成交额衰减加权价格分布”估算获利盘比例
   - `COST(50)`：同样基于上述价格分布估算 50% 成本分位价

## 回测假设

截图只给了选股公式，没有给出交易规则。为了可回测，策略采用以下固定假设：

- 当日收盘满足条件，次日开盘买入
- 条件失效时，次日开盘卖出
- 若持续满足条件，也最多持有 `10` 个交易日
- 默认最多持有 `5` 只股票，总仓位 `95%`

## 运行方式

```bash
python strategies/chip_trend_pullback_strategy.py --start 20250401 --end 20260319
```

可调参数示例：

```bash
python strategies/chip_trend_pullback_strategy.py --start 20250401 --end 20260319 --max-positions 5 --max-hold-days 10 --chip-window 120 --chip-decay 0.97
```

### `five_small_yang_strategy.py`

这是一个事件统计型策略脚本，用来回答“连续 5 天小阳后，第 6 天开盘买入，持有固定天数后的收益表现如何”。

默认规则：

1. 前 5 个交易日连续满足“小阳”：
   - `close > open`
   - `close > pre_close`
   - 单日涨幅 `> 0`
   - 单日涨幅 `<= 3%`
2. 第 6 个交易日开盘价买入
3. 买入当日记为第 1 天，分别统计持有 `5/10/15/20` 个交易日后按收盘价卖出的收益率

运行方式：

```bash
python strategies/five_small_yang_strategy.py --start 20140102 --end 20260319
```

可调参数示例：

```bash
python strategies/five_small_yang_strategy.py --start 20240101 --end 20260319 --min-up-pct 0.002 --max-up-pct 0.025 --min-price 3
```

输出文件会写入 `strategies/reports/`，包括：

- 逐笔信号明细 CSV
- 分持有天数汇总 CSV
- 汇总 JSON
