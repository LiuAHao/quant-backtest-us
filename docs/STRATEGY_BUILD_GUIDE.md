# 策略文件构建指南

本指南帮助外部 Agent 或开发者生成符合后端要求的策略文件，确保策略能被正确导入和回测。

## 核心要求

### 0. 中文命名规范（强制）

**所有外部 Agent 生成的策略，其名称、标签、描述必须使用中文。**

| 字段 | 要求 | 示例 |
|---|---|---|
| 策略名称 | 中文，简洁明了 | `"小市值轮动策略"` |
| Tags | 中文标签数组 | `["小市值", "轮动", "每日调仓"]` |
| 描述 | 中文，说明选股逻辑 | `"选取市值最小的10只股票，每5天调仓一次"` |

#### 正确示例

```python
class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("小市值轮动策略")  # ✅ 中文名称
```

```python
"""
小市值轮动策略 v1

选股逻辑：
1. 股票池：沪深主板
2. 选取市值最小的10只股票
3. 每5天调仓一次

Tags: ["小市值", "轮动", "每日调仓"]  # ✅ 中文标签
"""
```

#### 错误示例

```python
class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("SmallCapRotation")  # ❌ 英文名称
```

```python
"""
Tags: ["small_cap", "rotation"]  # ❌ 英文标签
"""
```

---

### 1. 必须继承 StrategyTemplate

```python
from backtest.strategy import StrategyTemplate

class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("策略名称")
```

### 2. 必须实现 init 和 next 方法

```python
def init(self, context: dict):
    """初始化，回测开始前调用一次"""
    pass

def next(self, context: dict):
    """每个交易日收盘后执行，产生下一交易日开盘成交的订单"""
    pass
```

默认回测撮合模式是 `execution_mode="next_open"`。如需模拟当日尾盘下单并按当日收盘价成交，可在创建 `BacktestEngine` 时显式传入 `execution_mode="same_close"`。

### 3. 禁止使用的模块

```python
# ❌ 禁止导入
import os, subprocess, pathlib, requests, httpx, urllib, socket, shutil, ftplib

# ❌ 禁止调用
eval(...), exec(...), open(...), __import__(...)
```

## context 对象

`init` 和 `next` 方法接收的 `context` 字典：

| 字段 | 类型 | 说明 |
|---|---|---|
| `current_date` | datetime | 当前交易日 |
| `market_data` | DataFrame | 当日全市场截面（已含基本面，见下表） |
| `order_target_percent` | callable | `(ts_code, target_percent)` 调仓，target_percent 0~1 |
| `get_history` | callable | `(ts_code, end_date, fields, window, adjust)` 个股历史 |
| `trade_date_index` | callable | `(date)` 交易日序号，可用于调仓间隔判断 |
| `get_hold_days` | callable | `(entry_date, current_date)` 计算持仓天数 |
| `get_price_limit_status` | callable | `(bar, price=None)` 快速判断单行行情是否涨停/跌停 |
| `is_limit_up` / `is_limit_down` | callable | `(bar, price=None)` 快速判断单行行情是否涨停/跌停 |
| `get_cross_section` | callable | `(trade_date)` 获取指定日期截面数据 |
| `data_loader` | DataLoader | 数据加载器，`.conn` 为 DuckDB 连接 |
| `broker` | Broker | 交易经纪商 |
| `start_date` / `end_date` | datetime | 回测起止日期 |

## market_data 字段

`market_data` 由 `get_cross_section()` 返回，已自动 LEFT JOIN `daily_basic`，**策略中无需再次查询 daily_basic 获取市值/估值**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | str | 股票代码，如 `600000.SH` |
| `trade_date` | str | 交易日期 `YYYY-MM-DD` |
| `open` / `high` / `low` / `close` | float | OHLC 价格 |
| `pre_close` | float | 前收盘价 |
| `up_limit` / `down_limit` | float | 当日涨跌停价（本地存在 `stk_limit` 数据时自动带出） |
| `volume` | float | 成交量 |
| `amount` | float | 成交额 |
| `circ_mv` | float | 流通市值（万元），小市值策略优先用此字段 |
| `total_mv` | float | 总市值（万元），`circ_mv` 缺失时用此兜底 |
| `total_share` / `float_share` / `free_share` | float | 股本信息 |
| `turnover_rate` | float | 换手率 |
| `pe_ttm` | float | 市盈率（TTM），盈利判断用 `pe_ttm > 0` |
| `pb` | float | 市净率 |

## get_history 返回字段

```python
hist = context["get_history"](ts_code, end_date, fields=["close"], window=20, adjust="qfq")
```

使用 `adjust="qfq"`（前复权）时，返回的复权价字段：

| 原始字段 | 复权字段 | 说明 |
|---|---|---|
| `close` | `close_fq` | 前复权收盘价 |
| `open` | `open_fq` | 前复权开盘价 |
| `high` | `high_fq` | 前复权最高价 |
| `low` | `low_fq` | 前复权最低价 |
| `pre_close` | `pre_close_fq` | 前复权前收盘价 |

## 完整模板

```python
"""
策略名称 v1

选股逻辑：
1. 股票池：沪深主板（排除科创板、创业板、北交所）
2. 剔除 ST 股票、停牌股票
3. 选股条件
4. 等权重调仓

Tags: ["标签1", "标签2"]
"""
from __future__ import annotations

from datetime import datetime
from loguru import logger
from backtest.strategy import StrategyTemplate


def _is_main_board(ts_code: str) -> bool:
    """沪深主板判定（排除科创板、创业板、北交所）"""
    code = str(ts_code).split(".")[0]
    if code.startswith("688"):      # 科创板
        return False
    if code.startswith(("300", "301")):  # 创业板
        return False
    if code.startswith(("4", "8")) and len(code) == 6:  # 北交所
        return False
    return True


class MyStrategy(StrategyTemplate):
    """策略描述"""

    def __init__(self):
        super().__init__("策略名称")
        self.buy_count = 5
        self.min_amount = 50000
        self.current_targets: set[str] = set()

    def init(self, context):
        self.current_targets = set()
        loader = context["data_loader"]
        # 获取 ST 股票列表
        try:
            st_df = loader.conn.execute(
                "SELECT ts_code FROM instruments WHERE symbol LIKE '%ST%'"
            ).fetchdf()
            self.st_codes = set(st_df["ts_code"].tolist())
        except Exception:
            self.st_codes = set()
        logger.info(f"[{self.name}] init 完成, ST={len(self.st_codes)}")

    def next(self, context):
        date = context["current_date"]
        broker = context["broker"]
        market = context["market_data"]
        if market is None or market.empty:
            return

        df = market.copy()

        # 1. 基础过滤
        df = df[(df["close"] > 0) & (df["amount"] >= self.min_amount)].copy()
        if df.empty:
            return

        # 2. 板块过滤
        df = df[df["ts_code"].apply(_is_main_board)].copy()
        if df.empty:
            return

        # 3. 排除 ST
        df = df[~df["ts_code"].isin(self.st_codes)].copy()
        if df.empty:
            return

        # 4. 选股（示例：小市值）
        df["market_cap"] = df["circ_mv"].fillna(df["total_mv"])
        df = df[df["market_cap"] > 0].sort_values("market_cap").head(self.buy_count)
        selected = df["ts_code"].astype(str).tolist()
        if not selected:
            return

        # 5. 去重判断
        target_set = set(selected)
        if target_set == self.current_targets:
            return
        self.current_targets = target_set

        # 6. 调仓
        for ts_code in list(broker.account.positions.keys()):
            pos = broker.account.get_position(ts_code)
            if pos.volume > 0 and ts_code not in target_set:
                context["order_target_percent"](ts_code, 0)

        weight = min(0.95 / len(selected), 0.95)
        for stock in selected:
            context["order_target_percent"](stock, weight)
        logger.info(f"[{self.name}] {date.date()} 调仓 -> {', '.join(selected[:3])}...")
```

## 数据库直接查询

当 `market_data` 字段不够用时，可通过 `context["data_loader"].conn` 直接查询 DuckDB。

### 可用表

| 表名 | 说明 | 常用字段 |
|---|---|---|
| `daily_basic` | 每日基本面 | `ts_code`, `trade_date`, `pe`, `pe_ttm`, `pb`, `volume_ratio`, `circ_mv`, `total_mv` |
| `instruments` | 股票列表 | `ts_code`, `symbol`, `exchange`, `list_date`, `status` |
| `suspend_d` | 停牌信息 | `ts_code`, `trade_date` |
| `stk_limit` | 涨跌停 | `ts_code`, `trade_date`, `up_limit`, `down_limit` |
| `fina_indicator` | 财务指标 | `ts_code`, `ann_date`, `end_date`, `roe`, `roa` |
| `adj_factor` | 复权因子 | `ts_code`, `trade_date`, `adj_factor` |

### 查询示例

```python
loader = context["data_loader"]
date_str = context["current_date"].strftime("%Y-%m-%d")

# 查询停牌股票
suspend = set(loader.conn.execute(
    f"SELECT DISTINCT ts_code FROM suspend_d WHERE trade_date='{date_str}'"
).fetchdf()["ts_code"].tolist())

# 查询财务指标（全市场截面）
fin = loader.get_financial_cross_section(
    date_str, table="fina_indicator", fields=["ts_code", "roe"]
)

# 查询个股最新财报
latest = loader.get_latest_financial("600000.SH", date_str, table="fina_indicator")
```

### 注意事项

- DuckDB 日期格式必须为 `YYYY-MM-DD`
- `instruments` 表没有 `type` 字段，上市股票用 `status = 'L'`
- 板块过滤：创业板 `300*/301*`，科创板 `688*`，北交所 `exchange='BJ'` 或 `4*/8*` 开头

## 导入策略

**无需手动导入！** 后端自动扫描 `backend/storage/strategies/` 目录，发现新文件后自动导入。

Agent 只需要：
1. 生成符合规范的策略文件
2. 保存到 `backend/storage/strategies/` 目录
3. 前端刷新即可看到新策略

## 常见错误

### 1. 用 `pe` 而非 `pe_ttm`

```python
# ❌ 错误：market_data 没有 pe 字段
valid = market[market["pe"] > 0]

# ✅ 正确：使用 pe_ttm
valid = market[market["pe_ttm"] > 0]
```

### 2. 重复查询 daily_basic

```python
# ❌ 错误：market_data 已包含这些字段
basic = loader.conn.execute("SELECT circ_mv, pe_ttm FROM daily_basic WHERE ...").fetchdf()
work = work.merge(basic, on="ts_code")

# ✅ 正确：直接使用 market_data
work["market_cap"] = work["circ_mv"].fillna(work["total_mv"])
```

### 3. 板块过滤不完整

```python
# ❌ 错误：只排除了 300
df = df[~df["ts_code"].str.startswith("300")]

# ✅ 正确：排除 300、301、688
df = df[~df["ts_code"].astype(str).str.startswith(("300", "301", "688"))]
```

### 4. 未继承 StrategyTemplate

```python
# ❌ 错误
class MyStrategy:
    pass

# ✅ 正确
class MyStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("策略名称")
```

## 验证策略

```python
from backend.services.strategy_validator import StrategyValidator

validator = StrategyValidator()
result = validator.validate(code)
if result.ok:
    print("验证通过")
else:
    print(f"验证失败: {result.message}")
```
