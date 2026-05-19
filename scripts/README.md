# Scripts

## 脚本分类

```
scripts/
├── data_download/          # 数据下载
│   ├── download_by_date.py       # 按日期下载日线+复权因子（推荐）
│   ├── update_daily.py           # 底层数据更新引擎（DataUpdater类）
│   ├── update_extra_data.py      # 补充基础数据（daily_basic/stk_limit等）
│   ├── update_index_data.py      # 指数相关数据（概念板块/成分股/指数日线）
│   └── update_supplement_data.py # 综合补充数据（财务/行业/ETF等14类）
├── data_utils/             # 数据工具
│   ├── data_admin.py             # 数据状态查看和校验CLI
│   ├── mark_adj_type.py          # 标记复权类型元数据
│   └── validate_data.py          # 数据质量校验
├── data_source/            # 数据源适配器（被下载脚本调用）
│   ├── data_source_tushare.py    # Tushare API适配器
│   └── data_source_akshare.py    # AkShare API适配器
├── agent_entry/            # 外部Agent标准入口
│   ├── run_standard_backtest.py        # 标准回测入口
│   ├── run_standard_event_analysis.py  # 标准事件分析入口
│   ├── run_standard_factor_analysis.py # 标准因子分析入口
│   └── run_ml_training.py             # ML模型训练入口
├── agent_simulation/       # Agent模拟/实验脚本（.gitignore，不上传GitHub）
│   ├── gen_factor_strategies.py
│   ├── import_strategies.py
│   ├── run_momentum_backtests.py
│   ├── run_sharpe_benchmark.py
│   ├── test_ai_strategy_generation.py
│   └── analysis/analyze_worldquant_factor.py
├── __init__.py
├── README.md
└── AKShareAPI概括-A股.md
```

> **说明**: `agent_simulation/` 已加入 `.gitignore`，不会上传到 GitHub。该目录存放开发/实验用途的脚本。

## 数据更新脚本速查

Tushare token 不再写在脚本里，请在项目根目录 `.env` 中配置：

```text
TUSHARE_TOKEN=你的TushareToken
TUSHARE_BASE_URL=可选，自建代理时再填写
```

## 详细用法

### 日线和复权因子

已有日期分区会自动跳过，适合反复执行或中断后续跑：

```bash
python scripts/data_download/download_by_date.py --start 20140102 --end 20260429
```

### 补充基础数据

补充表包括 `daily_basic`、`stk_limit`、`suspend_d`、`namechange` 和全状态股票列表。日度分区表会自动跳过已存在分区：

```bash
python scripts/data_download/update_extra_data.py --start 20140102 --end 20260429 --tasks daily_basic stk_limit suspend_d
```

### 补充高级数据

涵盖指数日线、行业分类、财务报表、ETF日线、复权因子等：

```bash
# 全部任务
python scripts/data_download/update_supplement_data.py --tasks all

# 按需选择
python scripts/data_download/update_supplement_data.py --tasks instruments,namechange,index_daily
python scripts/data_download/update_supplement_data.py --tasks industry --start 20200101
python scripts/data_download/update_supplement_data.py --tasks fina --start 20200101
python scripts/data_download/update_supplement_data.py --tasks etf_daily
python scripts/data_download/update_supplement_data.py --tasks adj_factor_dl
python scripts/data_download/update_supplement_data.py --tasks adj_factor_fix

# 事件驱动数据
python scripts/data_download/update_supplement_data.py --tasks bs_express,bs_forecast,bs_dividend
python scripts/data_download/update_supplement_data.py --tasks holder_number
```

任务说明：

| 任务名 | 说明 | 数据来源 |
| --- | --- | --- |
| `instruments` | 历史化股票列表（含退市/暂停，消除生存偏差） | Tushare |
| `namechange` | 股票历史名称变更（ST摘帽/戴帽） | Tushare |
| `index_daily` | 12个关键指数日线行情 | Tushare |
| `industry` | 行业分类（stock_basic行业字段 + 申万一级） | Tushare |
| `fina` | 财务报表（利润表/资产负债表/现金流量表/财务指标） | Tushare |
| `etf_daily` | ETF/基金日线行情 | Tushare |
| `adj_factor_dl` | 按交易日下载全市场复权因子 | Tushare |
| `adj_factor_fix` | 清理复权因子中的非交易日分区 | - |
| `index_member_bs` | 宽基指数历史成分股（CSI300/CSI500/SSE50，按月） | Baostock |
| `index_member_ak` | 宽基指数当前成分股（CSI1000/CSI2000等） | AkShare |
| `bs_express` | 业绩快报（营收/净利/EPS/ROE，比财报早1-2月） | Baostock |
| `bs_forecast` | 业绩预告（预增/预减/扭亏/续亏等类型+幅度） | Baostock |
| `bs_dividend` | 分红送转（每股派息/送股/转增+除权日等关键日期） | Baostock |
| `holder_number` | 股东人数变化（筹码集中度指标） | Tushare |

### 标记复权类型

在 `meta.duckdb` 中记录 `daily_bar` 存储的价格类型：

```bash
python scripts/data_utils/mark_adj_type.py --adj_type raw
```

可选值：`raw`（未复权）、`qfq`（前复权）、`hfq`（后复权）。

完整数据字段和策略使用方式见 `docs/quant-data-guide.md`。

## Agent 标准入口

外部 Agent 需要产出前端可识别的任务和结果时，应使用 `scripts/agent_entry/` 下的标准入口，不要直接写 SQLite 或手工拼结果文件。

### 标准回测

```bash
python scripts/agent_entry/run_standard_backtest.py \
  --strategy-file <path> \
  --start 2026-01-01 \
  --end 2026-04-29
```

### 标准事件分析

```bash
python scripts/agent_entry/run_standard_event_analysis.py \
  --event-file <path> \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 5,10,15
```

### 标准因子分析

```bash
python scripts/agent_entry/run_standard_factor_analysis.py \
  --factor-file <path> \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 1,5,10,20 \
  --filter exclude_st \
  --filter exclude_new_stock
```

标准因子脚本会优先调用后端 `POST /api/factor-analyses/quick`；后端不可用时，本地运行 `FactorAnalysisEngine` 并写入标准任务和结果 JSON。
