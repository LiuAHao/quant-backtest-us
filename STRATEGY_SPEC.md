# 策略文件规范

## 必须遵守的规则

1. **继承 StrategyTemplate**：`from backtest.strategy import StrategyTemplate`
2. **实现 `init(self, context)` 和 `next(self, context)` 方法**
3. **禁止导入**：`os`, `subpathlib`, `subprocess`, `requests`, `httpx`, `urllib`, `socket`, `shutil`, `ftplib`
4. **禁止调用**：`eval`, `exec`, `compile`, `open`, `__import__`

## 使用方法

1. 生成符合规范的策略文件
2. 保存到 `backend/storage/strategies/` 目录
3. 前端自动识别，无需手动导入

## 最小模板

```python
from backtest.strategy import StrategyTemplate


class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("策略名称")
        self.buy_count = 5

    def init(self, context):
        pass

    def next(self, context):
        market = context["market_data"]
        if market is None or market.empty:
            return

        selected = market.nsmallest(self.buy_count, "circ_mv")["ts_code"].tolist()
        if not selected:
            return

        broker = context["broker"]
        target_set = set(selected)
        for ts_code in list(broker.account.positions.keys()):
            pos = broker.account.get_position(ts_code)
            if pos.volume > 0 and ts_code not in target_set:
                context["order_target_percent"](ts_code, 0)

        weight = 0.95 / len(selected)
        for stock in selected:
            context["order_target_percent"](stock, weight)
```

## 回测成交时序

默认回测模式是 `execution_mode="next_open"`：`next()` 在每个交易日收盘后运行，生成的订单在下一交易日开盘撮合。

如果需要模拟当日尾盘下单并按当日收盘价成交，可直接创建引擎时显式传入：

```python
engine = BacktestEngine(
    start_date="20260101",
    end_date="20260429",
    execution_mode="same_close",
)
```

同一次回测应只使用一种成交时序，不要在策略代码里混用两种假设。

## 涨跌停判断

策略里优先使用上下文提供的接口判断涨跌停：

```python
for _, row in context["market_data"].iterrows():
    if context["is_limit_up"](row):
        continue
    if context["is_limit_down"](row):
        continue
```

`get_price_limit_status(row)` 会优先使用 `up_limit/down_limit` 字段；若本地没有 `stk_limit` 数据，则按代码板块和 `pre_close` 回退估算。

## context 对象

| 字段 | 类型 | 说明 |
|---|---|---|
| `current_date` | datetime | 当前交易日 |
| `market_data` | DataFrame | 当日全市场截面（已含基本面字段，见下表） |
| `order_target_percent` | callable | `(ts_code, target_percent)` 调仓，0~1 |
| `get_history` | callable | `(ts_code, end_date, fields, window, adjust)` 个股历史 |
| `trade_date_index` | callable | `(date)` 交易日序号，可用于调仓间隔 |
| `get_hold_days` | callable | `(entry_date, current_date)` 持仓天数 |
| `get_price_limit_status` | callable | `(bar, price=None)` 判断涨停/跌停并返回涨跌停价 |
| `is_limit_up` / `is_limit_down` | callable | `(bar, price=None)` 快速判断涨停/跌停 |
| `data_loader` | DataLoader | 数据加载器，`.conn` 为 DuckDB 连接 |
| `broker` | Broker | 交易经纪商 |

## market_data 字段

`market_data` 由 `get_cross_section()` 返回，已自动 LEFT JOIN `daily_basic`，**无需再次查询**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | str | 股票代码 |
| `trade_date` | str | 交易日期 |
| `open` / `high` / `low` / `close` | float | OHLC 价格 |
| `pre_close` | float | 前收盘价 |
| `up_limit` / `down_limit` | float | 当日涨跌停价（本地存在 `stk_limit` 数据时自动带出） |
| `volume` | float | 成交量 |
| `amount` | float | 成交额 |
| `circ_mv` | float | 流通市值（万元） |
| `total_mv` | float | 总市值（万元） |
| `total_share` / `float_share` / `free_share` | float | 总股本/流通股本/自由流通股本 |
| `turnover_rate` | float | 换手率 |
| `pe_ttm` | float | 市盈率（TTM） |
| `pb` | float | 市净率 |

## get_history 返回字段

`get_history()` 使用 `adjust="qfq"` 时，返回的复权价字段为：

| 原始字段 | 复权字段 |
|---|---|
| `close` | `close_fq` |
| `open` | `open_fq` |
| `high` | `high_fq` |
| `low` | `low_fq` |
| `pre_close` | `pre_close_fq` |

用法示例：
```python
hist = context["get_history"](ts_code, current_date, fields=["close"], window=20, adjust="qfq")
# hist 包含: ts_code, trade_date, close, adj_factor, close_fq
```

## 完整指南

详见 `docs/STRATEGY_BUILD_GUIDE.md`
