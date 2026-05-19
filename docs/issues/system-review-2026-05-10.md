# 系统审查状态复核 — 2026-05-10

本报告针对 [system-review-2026-05-09.md](system-review-2026-05-09.md) 中列出的 47 个问题，复核当前代码实现完成度。它不是替代原始审查报告，而是记录“截至 2026-05-10 当前代码状态”。

## 验证结果

本次复核已执行：

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile backtest/*.py event_analysis/*.py backend/services/*.py backend/api/*.py
cd frontend && npm run build
```

结果：

- 单元测试通过：59 个测试。
- Python 语法编译通过。
- 前端生产构建通过。

## 总体完成度

| 区域 | 完成度判断 | 说明 |
|---|---:|---|
| 高优先级正确性/安全性 | 约 65% | #1 #2 #5 #11 完成；#6 部分完成；#4 未完成；#3 阻塞 |
| 回测引擎能力 | 约 45% | 扩展指标、回调、指标库已有；benchmark、GTC、滑点模型仍缺 |
| 数据加载 | 约 65% | 复权、缓存、部分参数化完成；DuckDB 配置、剩余 SQL 参数化未完成 |
| 后端 API/架构 | 约 45% | settings、索引、shutdown、部分批量删除完成；分页、任务批量删除、版本历史、service 收敛未完成 |
| 前端 | 约 10% | 构建可用，但大多数审查项未处理 |
| 数据运维/因子分析 | 约 20% | validate_data 有基础能力，因子分析仍是脚本状态 |
| 测试体系 | 约 55% | 新增 DataLoader/Broker/Validator/Indicators 测试，但缺 engine metrics 和固定回测快照 |

整体判断：**基础正确性修复已有明显进展，但整份 2026-05-09 审查方案尚未完成，综合完成度约 40%-45%。**

## 逐项状态

| # | 问题摘要 | 当前状态 | 证据/说明 |
|---|---|---|---|
| 1 | qfq/hfq 复权基准错误 | 已完成 | `_apply_adjustment()` 内部按 `trade_date` 升序，测试覆盖 qfq/hfq |
| 2 | `Position.market_value` property 设计错误 | 已完成 | property 返回成本市值，新增 `get_market_value()` |
| 3 | 分红/送股/配股处理 | 阻塞 | 原报告已标记无数据源，当前仍未实现 |
| 4 | 无 benchmark 对比 | 未完成 | `BacktestEngine` 有 `benchmark` 参数，但未计算 Alpha/Beta/IR/tracking error |
| 5 | Settings 任意 dict 无 schema | 已完成 | 新增 `SettingsUpdate`、PUT/PATCH、白名单过滤 |
| 6 | 策略/事件分析 `exec()` 信任边界 | 部分完成 | validator 抽公共逻辑并增强；loader 执行前仍未复验，也未隔离进程 |
| 7 | 每日截面重复 `to_dict` | 未完成 | `_get_market_data()` 仍 `df.to_dict(orient='records')` |
| 8 | Sharpe 缺无风险利率 | 部分完成 | `risk_free_rate` 参数已加，但 Sharpe 仍用原始日收益 |
| 9 | 缺少 Calmar/Sortino/盈亏比等指标 | 部分完成 | 指标字段和报告展示已有；缺独立 engine metrics 测试，平均持仓计算较粗 |
| 10 | 滑点模型过简 | 未完成 | 仍为固定比例滑点 |
| 11 | 印花税默认值过时 | 已完成 | `Broker(stamp_duty_rate=0.0005)` |
| 12 | 无 GTC 订单 | 未完成 | 未成交订单仍当日取消，无订单有效期模型 |
| 13 | 策略回调过少 | 部分完成 | 已有 `on_order_filled/on_day_end/on_backtest_end`；`on_order_filled` 的 order 参数仍为 `None` |
| 14 | 缺少技术指标库 | 已完成 | 新增 `backtest/indicators.py` 和 `tests/test_indicators.py` |
| 15 | `get_history()` 缓存未使用 | 已完成 | 缓存路径已接入，测试覆盖 copy 和 datetime trade_date |
| 16 | DuckDB 配置硬编码 | 未完成 | 仍硬编码 12GB/4 线程 |
| 17 | SQL 字符串拼接 | 部分完成 | `get_history/get_cross_section/warm_up_cache` 已参数化；`get_adj_factor/get_next_trade_date/get_prev_trade_date/get_instruments` 仍拼接 |
| 18 | 列表接口无分页 | 未完成 | backtests/event analyses/strategies 等仍默认全量 |
| 19 | StrategyService 实例化同步慢 | 已完成 | `_startup_synced` 避免重复启动同步 |
| 20 | SQLite 无连接池 | 部分完成 | 加了 WAL、busy timeout、foreign_keys；仍非连接池 |
| 21 | 数据库缺少索引 | 已完成 | 增加 backtest/event/strategy version 等索引 |
| 22 | Validator/Service 重复代码 | 部分完成 | validator 已抽 `code_validator_base.py`；service 重复仍存在 |
| 23 | config_center 绕过 Service | 未完成 | 仍直接操作数据库 |
| 24 | 缺少批量删除/策略版本历史接口 | 部分完成 | 策略定义、事件定义有 batch-delete；回测/事件任务批量删除和策略版本历史未完成 |
| 25 | `App.jsx` 单文件过大 | 未完成 | 仍约 2872 行 |
| 26 | 轮询重渲染风暴 | 未完成 | 仍每 2.5s 调 `refreshBacktests()` + `refreshEventAnalyses()` |
| 27 | 无 Error Boundary | 未完成 | 未发现 ErrorBoundary 组件 |
| 28 | 无代码编辑器 | 未完成 | 仍无 CodeMirror/Monaco |
| 29 | 回测/事件列表无分页 | 未完成 | 前端有局部分页 UI 痕迹，但后端和数据流仍未分页 |
| 30 | 无 CSV/Excel 导出 | 未完成 | 仅有报告下载，无列表/结果 CSV/Excel 导出 |
| 31 | 删除用 `window.confirm` | 未完成 | 多处仍使用 `window.confirm` |
| 32 | 数据管理页空壳 | 未完成 | 仍是按钮展示，无真实任务执行/状态回读 |
| 33 | 硬编码最新交易日 | 未完成 | 前端仍硬编码 `2026-04-29` |
| 34 | 无 `vite.config.js` | 未完成 | frontend 目录未见 `vite.config.js` |
| 35 | 无 ESLint | 未完成 | 未见 ESLint 配置 |
| 36 | 无类型检查 | 未完成 | 未见 TypeScript/PropTypes/JSDoc 类型体系 |
| 37 | 格式化函数重复 | 未完成 | 未系统抽出 formatter utils |
| 38 | DELETE 返回值不一致 | 保持现状 | 这是兼容性风险项，当前未统一 |
| 39 | Settings 应支持 PATCH | 已完成 | 新增 `PATCH /api/settings`，保留 PUT |
| 40 | ThreadPoolExecutor 无优雅关闭 | 已完成 | FastAPI shutdown 关闭 backtest/event analysis executor |
| 41 | validate_data 校验范围不足 | 未完成 | 仍主要围绕 daily_bar/adj_factor，未全面覆盖 extra data |
| 42 | validate_range 用 weekday | 未完成 | `validate_range()` 仍用 `current_date.weekday() < 5` |
| 43 | AkShare 复权因子失败静默填 1.0 | 未完成 | 未见对应治理 |
| 44 | 缺少统一数据更新入口 | 未完成 | 未见 `scripts/data_utils/data_admin.py` |
| 45 | 缺少数据清理/重置/修复脚本 | 未完成 | 未见统一清理/修复入口 |
| 46 | 数据层零测试覆盖 | 部分完成 | 新增 `tests/test_data_loader.py`，但缺更多数据脚本/真实边界测试 |
| 47 | 无因子分析模块 | 部分完成 | 有分析脚本，但没有正式 `factor_analysis/` 包和测试 |

## 当前主要进展

### 正确性

- 复权计算最关键的 qfq/hfq 基准问题已修复。
- `get_history()` 现在真正读取 `_cache`，并对缓存返回 copy。
- `Position.market_value` 不再永远返回 0。
- 印花税默认值已更新为 2023-08-28 后的 0.05%。
- 回测扩展指标已有初步输出，包括 Sortino、Calmar、波动率、盈亏比、平均持仓天数、换手率。

### 安全与配置

- Settings 接口不再裸收任意 dict，已增加 schema 和白名单。
- 策略/事件分析 validator 抽出公共安全规则，新增对 `globals`、`locals`、`getattr`、`pickle`、`runpy`、高风险 dunder 属性链等拦截。
- 但用户代码仍在主进程 `exec()`，安全边界还没有真正隔离。

### 后端性能/生命周期

- SQLite 已启用 WAL、busy timeout、foreign keys。
- 高频查询字段已新增索引。
- FastAPI shutdown 会关闭两个全局 executor。
- StrategyService 避免每次实例化都做文件同步。

### 测试

新增/已有重点测试：

- `tests/test_data_loader.py`
- `tests/test_broker.py`
- `tests/test_code_validator.py`
- `tests/test_indicators.py`
- `tests/test_backend_api.py`

## 关键剩余问题

### P0：必须优先补齐

1. **Loader 执行前复验 validator**
   - 当前创建/更新时会校验代码，但 loader 执行前仍直接 `exec`。
   - 应在 `StrategyLoader` 和 `EventAnalysisLoader` 内部执行前强制校验。

2. **Benchmark 真实计算**
   - `benchmark` 参数现在基本是空壳。
   - 需要 `DataLoader.get_index_history()`、对齐收益序列、计算 Alpha/Beta/信息比率/tracking error。

3. **Engine metrics 测试**
   - 扩展指标已有实现，但缺 `tests/test_engine_metrics.py`。
   - 当前平均持仓周期和盈亏比计算都可能在复杂交易场景偏粗。

4. **剩余 DataLoader 参数化**
   - `get_adj_factor()`、`get_next_trade_date()`、`get_prev_trade_date()`、`get_instruments()` 仍需参数绑定/白名单。

### P1：后端与 API

1. 列表接口分页。
2. 回测任务、事件分析任务批量删除。
3. 策略版本历史查看接口。
4. `config_center.py` 迁移到 service 层。
5. DELETE 返回值保持兼容的前提下新增统一响应接口。

### P2：前端

1. 拆分 `App.jsx`。
2. 轮询结果 diff，避免无变化 setState。
3. Error Boundary。
4. 自定义 ConfirmDialog。
5. 代码编辑器。
6. 数据管理页接真实数据状态。
7. 移除硬编码 `2026-04-29`。

### P3：数据运维/因子分析

1. `validate_data.py` 改用交易日历，不再用 weekday。
2. 校验范围扩展到 daily_basic、stk_limit、suspend_d、instruments、calendar 等。
3. 新增统一 `scripts/data_utils/data_admin.py`。
4. 将现有因子分析脚本收敛为正式 `factor_analysis/` 包。

## 建议下一步

建议下一轮只做后端地基，不碰前端大拆：

1. Loader 执行前复验 validator。
2. Benchmark 真实计算与报告输出。
3. `tests/test_engine_metrics.py` 固定扩展指标。
4. 补齐 DataLoader 剩余 SQL 参数化。

这四项完成后，系统的“结果可信度”和“执行安全边界”会比现在扎实很多。
