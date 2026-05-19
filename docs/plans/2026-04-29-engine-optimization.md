# Engine Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 提升日线 A 股回测引擎的运行速度，同时保持现有交易时序和策略接口兼容。

**Architecture:** 优化先集中在公共层：`DataLoader` 增加回测区间预处理与截面缓存，`BacktestEngine` 复用当天截面和交易日索引，策略只做轻量适配。所有优化都不能改变“开盘先撮合上一交易日订单，收盘后生成下一交易日订单”的执行顺序。

**Tech Stack:** Python, pandas, DuckDB, Parquet, loguru.

---

### Task 1: 建立性能基准

**Files:**
- Read: `backtest/engine.py`
- Read: `backtest/data_loader.py`
- Read: `strategies/small_cap_strategy.py`

**Step 1: 跑空策略基准**

Run: `python - <<'PY' ... BacktestEngine(... noop strategy) ... PY`

Expected: 记录 20250101~20250131 的耗时、交易日数量、交易数。

**Step 2: 跑代表性策略基准**

Run: `SmallCapStrategy` 同区间回测。

Expected: 记录耗时和交易数，后续优化必须保持交易数一致。

### Task 2: DataLoader 区间预处理

**Files:**
- Modify: `backtest/data_loader.py`

**Step 1: 增加预处理状态**

新增 `_daily_bar_source`、`_cross_section_cache`、`_trade_date_index` 等状态。

**Step 2: 增加 `prepare_backtest_data`**

创建 DuckDB 临时表 `prepared_daily_bar`，只包含当前回测区间数据，并清理截面缓存。

**Step 3: 让 `get_cross_section` 和 `get_history` 读当前数据源**

默认仍读 `daily_bar`，预处理后读 `prepared_daily_bar`。

**Step 4: 增加 `get_trade_date_index` / `get_hold_days`**

用交易日索引差替代重复 SQL 区间计数。

### Task 3: BacktestEngine 使用预处理和缓存

**Files:**
- Modify: `backtest/engine.py`

**Step 1: 增加构造参数**

新增 `prepare_data=True`、`enable_reports=True`，保持默认易用。

**Step 2: run 开始前调用数据预处理**

在交易日历读取后，准备回测区间数据。

**Step 3: context 增加公共字段**

提供 `market_data`、`market_data_map`、`trade_date_index`、`get_hold_days`。

**Step 4: 报告导出可关闭**

参数测试时可用 `enable_reports=False` 避免 JSON/HTML I/O。

### Task 4: 策略适配公共缓存

**Files:**
- Modify: `strategies/small_cap_strategy.py`
- Modify: `strategies/factor_base.py`
- Modify: `strategies/stronger_keep_stronger_strategy.py`

**Step 1: 复用 `context["market_data"]`**

避免策略同一天重复调用 `get_cross_section`。

**Step 2: 用列向量替代 `iterrows` 热点**

小市值策略选股改为 DataFrame 筛选、排序和 `itertuples` 输出少量日志。

### Task 5: 验证和复测

**Files:**
- Test: `backtest/engine.py`
- Test: `backtest/data_loader.py`
- Test: `strategies/small_cap_strategy.py`

**Step 1: 语法检查**

Run: `python -m py_compile backtest/engine.py backtest/data_loader.py strategies/small_cap_strategy.py strategies/factor_base.py strategies/stronger_keep_stronger_strategy.py`

Expected: PASS.

**Step 2: 性能基准复测**

Run: 空策略和 `SmallCapStrategy` 20250101~20250131。

Expected: 耗时明显下降，`SmallCapStrategy` 交易数保持 80。

**Step 3: 清理临时报告**

删除本轮性能测试生成的未跟踪报告文件。
