# 量化数据使用说明

本文档说明当前本地数据仓库已补充的数据表、时间范围、字段含义和策略中的使用方式。策略默认通过 `backtest.data_loader.DataLoader` 访问数据，不建议直接读写 Parquet 文件。

## 数据范围

截至 2026-05-05，已完成以下数据补充：

### 核心行情数据

| 数据表 | 本地视图名 | 时间范围 | 行数 | 用途 |
| --- | --- | --- | ---: | --- |
| 日线行情 | `daily_bar` | 2014-01-02 ~ 2026-04-29 | 11,783,483 | OHLCV、成交额、基础行情 |
| 复权因子 | `adj_factor` | 2014-01-02 ~ 2026-04-30 | 12,352,375 | 前复权、后复权价格计算 |
| 每日基础指标 | `daily_basic` | 2014-01-02 ~ 2026-04-29 | 11,692,430 | 估值、市值、换手率、股本 |
| 涨跌停价格 | `stk_limit` | 2014-01-02 ~ 2026-04-29 | 14,131,498 | 涨停、跌停过滤和打板研究 |
| 停复牌明细 | `suspend_d` | 2014-01-02 ~ 2026-04-29 | 384,762 | 停牌、复牌过滤 |
| 交易日历 | `calendar` | 2014-01-01 ~ 2026-04-29 | 4,502 | 交易日判断、持仓天数计算 |

### 股票基础数据

| 数据表 | 本地视图名 | 时间范围 | 行数 | 用途 |
| --- | --- | --- | ---: | --- |
| 股票列表 | `instruments` | 全状态快照（含退市） | 5,837 | 上市/退市/暂停股票基础信息 |
| 历史名称变更 | `namechange` | 2020-12-04 ~ 2026-05-07 | 10,000 | ST、*ST、摘帽、改名历史 |

### 指数与板块数据

| 数据表 | 本地路径 | 行数 | 数据来源 | 用途 |
| --- | --- | ---: | --- | --- |
| 指数日线 | `data/index_daily/` | 24,321 | Tushare | 12个关键指数行情（基准对比） |
| 指数成分股 | `index_member` | 328,685 | Tushare + Baostock + AkShare | 宽基指数+行业指数成分股 |
| 概念板块列表 | `concept` | 879 | Tushare | 概念板块目录 |
| 概念板块成分 | `concept_member` | 23,042 | Tushare | 概念板块成分股 |

**宽基指数成分股覆盖（数据来源说明）：**

| 指数 | 代码 | 数据来源 | 历史数据 | 当前成分 |
|---|---|---|---|---|
| 沪深300 | `000300.CSI` | Baostock | ✅ 2014-01 ~ 2026-05（149月） | ✅ 300只 |
| 中证500 | `000905.CSI` | Baostock | ✅ 2014-01 ~ 2026-05（149月） | ✅ 500只 |
| 上证50 | `000016.CSI` | Baostock | ✅ 2014-01 ~ 2026-05（149月） | ✅ 50只 |
| 中证1000 | `000852.CSI` | AkShare | ❌ 仅当前 | ✅ 765只 |
| 中证2000 | `932000.CSI` | AkShare | ❌ 仅当前 | ✅ 693只 |
| 国证2000 | `399303.SZ` | AkShare | ❌ 仅当前 | ✅ 1159只 |
| 中证A500 | `000510.CSI` | AkShare | ❌ 仅当前 | ✅ 375只 |

> **注意：** 宽基指数成分股数据来自 Baostock 和 AkShare（非 Tushare），代码格式已统一为 `600000.SH`。Baostock 支持按月查询历史成分股，AkShare 仅支持当前快照。Tushare 代理不支持 `index_member(index_code=...)` 查询宽基指数成分股。

### 行业分类数据

| 数据表 | 本地路径 | 行数 | 用途 |
| --- | --- | ---: | --- |
| 股票行业归属 | `stock_industry` | 5,837 | 每只股票的行业分类（110个行业） |
| 申万一级行业 | `sw_index_l1` | 31 | 申万2021版一级行业列表 |
| 申万行业成分 | `sw_index_member` | 7,654 | 申万一级行业成分股 |

### 财务报表数据

| 数据表 | 本地路径 | 行数 | 覆盖股票 | 来源 | 用途 |
| --- | --- | ---: | ---: | --- | --- |
| 利润表 | `income` | 139,049 | 5,513 | Tushare | 营收、净利润、EPS |
| 资产负债表 | `balancesheet` | 137,102 | 5,513 | Tushare | 总资产、总负债、净资产 |
| 现金流量表 | `cashflow` | 138,523 | 5,513 | Tushare | 经营/投资/筹资现金流 |
| 财务指标 | `fina_indicator` | 136,136 | 5,513 | Tushare | ROE、ROA、资产负债率等 |
| 业绩快报 | `performance_express` | - | - | Baostock | 营收/净利/EPS/ROE（比财报早1-2月） |
| 业绩预告 | `forecast` | - | - | Baostock | 预增/预减/扭亏/续亏等类型+幅度 |
| 分红送转 | `dividend` | - | - | Baostock | 每股派息/送股/转增+除权登记日等 |
| 股东人数 | `holder_number` | - | - | Tushare | 筹码集中度（股东人数变化） |

> **注意：** 业绩快报和业绩预告比正式财报更早披露，可用于事件驱动策略。分红送转包含除权登记日、除权日、派息日等关键日期。股东人数骤减表示筹码集中，常伴随主力建仓。Tushare token 过期后需续费才能更新 `holder_number`。

### ETF/基金数据

| 数据表 | 本地路径 | 行数 | 用途 |
| --- | --- | ---: | --- |
| ETF日线行情 | `data/etf_daily/` | 2,120,187 | 1,941只ETF日线行情 |
| 基金基本资料 | `fund_basic` | 2,560 | ETF/基金基础信息 |

### 元数据

| 数据表 | 本地路径 | 用途 |
| --- | --- | --- |
| 复权类型标记 | `meta.duckdb` → `daily_bar_meta` | 标记 daily_bar 存储的复权类型（当前: `raw`） |

说明：

- `daily_bar` 存储**未复权原始价格**，复权通过 `adj_factor` 在 DataLoader 中动态计算（前复权/后复权）。
- `adj_factor` 已过滤非交易日，仅保留交易日分区。
- `instruments` 包含退市股票（status=D），消除回测生存偏差。
- 财务报表数据起始日期为 2020-01-01，可通过 `--start` 参数调整。

## 指数日线覆盖

12个关键指数：

| 代码 | 名称 | 用途 |
| --- | --- | --- |
| `000001.SH` | 上证综指 | 大盘基准 |
| `399001.SZ` | 深证成指 | 大盘基准 |
| `000016.SH` | 上证50 | 大盘蓝筹 |
| `000300.CSI` | 沪深300 | 权重基准 |
| `000905.CSI` | 中证500 | 中盘基准 |
| `000852.CSI` | 中证1000 | 小盘基准 |
| `000985.CSI` | 中证全指 | 全市场基准 |
| `399006.SZ` | 创业板指 | 成长基准 |
| `399316.SZ` | 创业板综 | 创业板全市场 |
| `399673.SZ` | 创业板50 | 创业板龙头 |
| `399101.SZ` | 中小板综 | 中小板全市场 |
| `000688.CSI` | 科创50 | 科创基准 |

## 主要字段

### `daily_bar`

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码，例如 `600000.SH` |
| `trade_date` | 交易日期 |
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `close` | 收盘价 |
| `pre_close` | 前收盘价 |
| `volume` | 成交量 |
| `amount` | 成交额 |
| `is_trading` | 是否交易，当前日线记录默认为 `1` |

### `daily_basic`

| 字段 | 含义 |
| --- | --- |
| `turnover_rate` | 换手率 |
| `turnover_rate_f` | 自由流通股换手率 |
| `volume_ratio` | 量比 |
| `pe` / `pe_ttm` | 市盈率、滚动市盈率 |
| `pb` | 市净率 |
| `ps` / `ps_ttm` | 市销率、滚动市销率 |
| `dv_ratio` / `dv_ttm` | 股息率 |
| `total_share` | 总股本 |
| `float_share` | 流通股本 |
| `free_share` | 自由流通股本 |
| `total_mv` | 总市值 |
| `circ_mv` | 流通市值 |

### `stk_limit`

| 字段 | 含义 |
| --- | --- |
| `pre_close` | 前收盘价 |
| `up_limit` | 涨停价（精确值） |
| `down_limit` | 跌停价（精确值） |

### `suspend_d`

| 字段 | 含义 |
| --- | --- |
| `suspend_timing` | 停复牌时段 |
| `suspend_type` | 停复牌类型，`S`=停牌，`R`=复牌 |

### `instruments`

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码 |
| `symbol` | 股票简称 |
| `exchange` | 交易所：`SH`/`SZ`/`BJ` |
| `list_date` | 上市日期 |
| `delist_date` | 退市日期（退市股才有） |
| `status` | 状态：`L`=上市，`D`=退市，`P`=暂停 |

### `stock_industry`

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码 |
| `name` | 股票简称 |
| `industry` | 所属行业（110个行业） |
| `market` | 市场板块 |

### 财务报表通用字段

利润表 (`income`)：

| 字段 | 含义 |
| --- | --- |
| `basic_eps` | 基本每股收益 |
| `total_revenue` | 营业总收入 |
| `revenue` | 营业收入 |
| `operate_profit` | 营业利润 |
| `n_income` | 净利润 |

资产负债表 (`balancesheet`)：

| 字段 | 含义 |
| --- | --- |
| `total_assets` | 总资产 |
| `total_liab` | 总负债 |
| `total_hldr_eqy_exc_min_int` | 归属母公司股东权益 |

现金流量表 (`cashflow`)：

| 字段 | 含义 |
| --- | --- |
| `n_cashflow_act` | 经营活动现金流净额 |
| `n_cashflow_inv_act` | 投资活动现金流净额 |
| `n_cash_flows_fnc_act` | 筹资活动现金流净额 |

财务指标 (`fina_indicator`)：

| 字段 | 含义 |
| --- | --- |
| `eps` | 每股收益 |
| `roe` | 净资产收益率 |
| `roa` | 总资产收益率 |
| `debt_to_assets` | 资产负债率 |
| `gross_margin` | 毛利率 |
| `current_ratio` | 流动比率 |
| `quick_ratio` | 速动比率 |

业绩快报 (`performance_express`)：

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码（Tushare格式） |
| `code` | 原始代码（Baostock格式） |
| `performanceExpPubDate` | 公告日期（避免前瞻偏差的关键字段） |
| `performanceExpStatDate` | 报告期 |
| `performanceExpressGRYOY` | 营收同比增长率 |
| `performanceExpressOPYOY` | 利润同比增长率 |
| `performanceExpressROEWa` | 加权ROE |
| `performanceExpressEPSDiluted` | 稀释EPS |
| `performanceExpressTotalAsset` | 总资产 |
| `performanceExpressNetAsset` | 净资产 |

业绩预告 (`forecast`)：

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码 |
| `profitForcastExpPubDate` | 公告日期 |
| `profitForcastExpStatDate` | 报告期 |
| `profitForcastType` | 预告类型：预增/预减/扭亏/续亏/略增/略减/续盈/首亏 |
| `profitForcastChgPctUp` | 变动幅度上限(%) |
| `profitForcastChgPctDwn` | 变动幅度下限(%) |
| `profitForcastAbstract` | 预告摘要 |

分红送转 (`dividend`)：

| 字段 | 含义 |
| --- | --- |
| `code` | 股票代码（Baostock格式） |
| `query_year` | 查询年份 |
| `dividCashPsBeforeTax` | 每股派息(税前) |
| `dividCashPsAfterTax` | 每股派息(税后) |
| `dividStocksPs` | 每股送股 |
| `dividReserveToStockPs` | 每股转增 |
| `dividRegistDate` | 股权登记日 |
| `dividOperateDate` | 除权日 |
| `dividPayDate` | 派息日 |
| `dividPlanAnnounceDate` | 分红预案公告日 |

股东人数 (`holder_number`)：

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码 |
| `end_date` | 截止日期 |
| `ann_date` | 公告日期 |
| `holder_num` | 股东人数 |
| `holder_num_chg` | 股东人数变化 |
| `hold_num_per` | 人均持股数 |

## 涨跌停规则

专业判断涨跌停时，优先使用数据源给出的当日精确涨跌停价，即 `stk_limit.up_limit` / `stk_limit.down_limit`。回测引擎和策略上下文中的 `get_price_limit_status()`、`is_limit_up()`、`is_limit_down()` 会优先读取这些字段；只有本地缺少 `stk_limit` 数据时，才按板块规则和 `pre_close` 回退估算。

回退估算使用以下常见 A 股比例：

| 板块 | 代码特征 | 涨跌停幅度 |
| --- | --- | ---: |
| 主板 | `6xxxxx.SH`、`0xxxxx.SZ` | ±10% |
| 创业板 | `3xxxxx.SZ` | ±20% |
| 科创板 | `688xxx.SH` | ±20% |
| 北交所 | `8xxxxx.BJ`、`4xxxxx.BJ` | ±30% |

ST/风险警示、上市初期、退市整理、复牌首日等特殊情形应以 `stk_limit` 的精确字段为准；策略代码不要自行写死这些例外。

## 策略中如何使用

### 使用当日行情截面

回测引擎会在 `context` 中提供当日行情：

```python
market_data = context.get("market_data", [])
market_data_map = context.get("market_data_map", {})

row = market_data_map.get("600000.SH")
if row:
    close = row["close"]
    limit_status = context["get_price_limit_status"](row)
    if limit_status["is_limit_up"]:
        pass
```

### 查询补充数据表

策略可通过 `data_loader.conn` 查询所有 DuckDB 视图。

获取某天的估值和涨跌停价格：

```python
trade_date = context["current_date"].strftime("%Y-%m-%d")
loader = context["data_loader"]

df = loader.conn.execute(
    """
    SELECT
        b.ts_code,
        b.turnover_rate,
        b.pe_ttm,
        b.pb,
        b.total_mv,
        l.up_limit,
        l.down_limit
    FROM daily_basic b
    LEFT JOIN stk_limit l
        ON b.ts_code = l.ts_code
       AND b.trade_date = l.trade_date
    WHERE b.trade_date = ?
    """,
    [trade_date],
).fetchdf()
```

### 查询行业分类

```python
loader = context["data_loader"]

df = loader.conn.execute(
    """
    SELECT ts_code, industry
    FROM stock_industry
    WHERE industry = '银行'
    """
).fetchdf()
```

### 查询财务指标

```python
loader = context["data_loader"]

df = loader.conn.execute(
    """
    SELECT ts_code, end_date, eps, roe, debt_to_assets
    FROM fina_indicator
    WHERE ts_code = '600000.SH'
    ORDER BY end_date DESC
    LIMIT 4
    """
).fetchdf()
```

### 查询业绩快报（事件驱动）

```python
loader = context["data_loader"]
trade_date = context["current_date"].strftime("%Y-%m-%d")

# 获取当日已公告的业绩快报
df = loader.conn.execute(
    """
    SELECT ts_code, performanceExpPubDate, performanceExpStatDate,
           performanceExpressGRYOY, performanceExpressOPYOY, performanceExpressROEWa
    FROM performance_express
    WHERE performanceExpPubDate = ?
    """,
    [trade_date],
).fetchdf()
```

### 查询业绩预告（事件驱动）

```python
loader = context["data_loader"]
trade_date = context["current_date"].strftime("%Y-%m-%d")

# 获取当日已公告的业绩预告
df = loader.conn.execute(
    """
    SELECT ts_code, profitForcastType, profitForcastChgPctUp, profitForcastAbstract
    FROM forecast
    WHERE profitForcastExpPubDate = ?
    """,
    [trade_date],
).fetchdf()
```

### 查询分红送转（高股息策略）

```python
loader = context["data_loader"]

# 获取某年的高股息股票
df = loader.conn.execute(
    """
    SELECT code, dividCashPsBeforeTax, dividRegistDate, dividOperateDate
    FROM dividend
    WHERE query_year = 2024
      AND CAST(dividCashPsBeforeTax AS DOUBLE) > 1.0
    ORDER BY CAST(dividCashPsBeforeTax AS DOUBLE) DESC
    """
).fetchdf()
```

### 查询股东人数变化（筹码集中度）

```python
loader = context["data_loader"]

# 获取股东人数连续减少的股票
df = loader.conn.execute(
    """
    SELECT ts_code, end_date, holder_num, holder_num_chg
    FROM holder_number
    WHERE ts_code = '600519.SH'
    ORDER BY end_date DESC
    LIMIT 10
    """
).fetchdf()
```

### 查询指数成分股

```python
loader = context["data_loader"]

df = loader.conn.execute(
    """
    SELECT con_code
    FROM index_member
    WHERE index_code = '000300.CSI'
      AND is_new = 'Y'
    """
).fetchdf()
```

### 查询ETF行情

```python
loader = context["data_loader"]

df = loader.conn.execute(
    """
    SELECT trade_date, close, volume
    FROM etf_daily
    WHERE ts_code = '510300.SH'
    ORDER BY trade_date DESC
    LIMIT 20
    """
).fetchdf()
```

### 过滤停牌股票

```python
trade_date = context["current_date"].strftime("%Y-%m-%d")
loader = context["data_loader"]

suspend_codes = set(
    loader.conn.execute(
        "SELECT DISTINCT ts_code FROM suspend_d WHERE trade_date = ?",
        [trade_date],
    ).fetchdf()["ts_code"]
)
```

### 使用交易日持仓天数

```python
get_hold_days = context.get("get_hold_days")
hold_days = get_hold_days(entry_date, context["current_date"])
```

## 常见策略用法

### 小市值或估值过滤

```sql
SELECT ts_code, total_mv, circ_mv
FROM daily_basic
WHERE trade_date = DATE '2026-04-29'
  AND total_mv IS NOT NULL
ORDER BY total_mv ASC
LIMIT 100
```

### 涨停过滤（使用精确涨跌停价）

策略代码中推荐直接用 `context["is_limit_up"](row)`。如果需要写 DuckDB 查询，可直接连接 `stk_limit`：

```sql
SELECT d.ts_code, d.close, l.up_limit
FROM daily_bar d
JOIN stk_limit l
  ON d.ts_code = l.ts_code
 AND d.trade_date = l.trade_date
WHERE d.trade_date = DATE '2026-04-29'
  AND d.close >= l.up_limit
```

### ST 或名称变更过滤

```sql
SELECT ts_code, name, start_date, end_date, change_reason
FROM namechange
WHERE name LIKE '%ST%'
```

### 行业轮动选股

```sql
SELECT s.ts_code, s.industry, b.pe_ttm, b.circ_mv
FROM stock_industry s
JOIN daily_basic b ON s.ts_code = b.ts_code
WHERE b.trade_date = DATE '2026-04-29'
  AND s.industry = '半导体'
ORDER BY b.circ_mv ASC
```

### 财务质量筛选

```sql
SELECT f.ts_code, f.roe, f.debt_to_assets, f.eps
FROM fina_indicator f
WHERE f.end_date = DATE '2025-12-31'
  AND f.roe > 15
  AND f.debt_to_assets < 60
ORDER BY f.roe DESC
```

## 数据更新命令

### 日线和复权因子

```bash
python scripts/data_download/download_by_date.py --start 20140102 --end 20260429
```

### 补充数据（daily_basic、stk_limit、suspend_d）

```bash
python scripts/data_download/update_extra_data.py --start 20140102 --end 20260429 --tasks daily_basic stk_limit suspend_d
```

### 补充数据（指数/行业/财务/ETF/事件）

```bash
# 全部任务
python scripts/data_download/update_supplement_data.py --tasks all

# 按需选择
python scripts/data_download/update_supplement_data.py --tasks instruments,namechange,index_daily
python scripts/data_download/update_supplement_data.py --tasks industry,fina --start 20200101
python scripts/data_download/update_supplement_data.py --tasks etf_daily
python scripts/data_download/update_supplement_data.py --tasks adj_factor_dl

# 事件驱动数据（业绩快报/预告/分红/股东人数）
python scripts/data_download/update_supplement_data.py --tasks bs_express,bs_forecast,bs_dividend
python scripts/data_download/update_supplement_data.py --tasks holder_number
```

### 标记复权类型

```bash
python scripts/data_utils/mark_adj_type.py --adj_type raw
```

如需强制重拉已存在分区，使用脚本中的 `--force` 参数。
