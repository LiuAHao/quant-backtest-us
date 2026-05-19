# 2026-05-10 系统审查后续优化完整计划

来源状态复核：[../issues/system-review-2026-05-10.md](../issues/system-review-2026-05-10.md)

## 1. 当前基线

截至 2026-05-10，系统已经完成一批基础修复：

- qfq/hfq 复权基准修复。
- `Position.market_value` 和 `get_market_value()` 修复。
- 印花税默认值更新为 `0.0005`。
- `get_history()` 缓存读取接入。
- Settings schema、PUT/PATCH、白名单过滤。
- Validator 公共安全规则抽取。
- 技术指标库 `backtest/indicators.py`。
- SQLite WAL、busy timeout、部分索引。
- FastAPI shutdown 关闭 executor。
- 59 个单元测试通过，前端构建通过。

但仍有四类核心缺口：

1. 用户代码执行前仍未复验 validator，`exec()` 信任边界仍偏松。
2. benchmark 仍是空壳参数，没有真实超额收益、Alpha/Beta、信息比率。
3. 扩展回测指标缺少独立测试，部分指标算法偏粗。
4. API 分页、任务批量删除、前端重构、数据运维仍未系统推进。

## 2. 优化目标

本计划目标是从当前代码状态继续推进，而不是重做 2026-05-09 的完整计划。

优先顺序：

1. 先把回测结果可信度和用户代码执行边界补稳。
2. 再补后端 API 可维护性和大列表性能。
3. 然后推进前端体验和结构治理。
4. 最后收敛数据运维和因子分析模块。

## 3. 阶段总览

| 阶段 | 主题 | 优先级 | 主要解决 |
|---|---|---|---|
| Phase 0 | 安全与结果可信度地基 | P0 | Loader 复验、benchmark、engine metrics、DataLoader 剩余参数化 |
| Phase 1 | 后端 API 与任务治理 | P1 | 分页、任务批量删除、版本历史、config_center service 化 |
| Phase 2 | 前端结构与体验 | P2 | App 拆分、轮询 diff、Error Boundary、ConfirmDialog、代码编辑器 |
| Phase 3 | 数据运维与因子分析 | P3 | validate_data 升级、data_admin、factor_analysis 包 |

建议每个 Phase 独立提交，不要把前端大改和回测核心算法混在同一批改动里。

## 4. Phase 0：安全与结果可信度地基

### 4.1 Loader 执行前强制复验 Validator

当前问题：

- `StrategyService.create_strategy()` 和 `EventDefinitionService.create_definition()` 会在保存时校验代码。
- 但实际运行时，`StrategyLoader` 和 `EventAnalysisLoader` 仍直接 `exec(compile(...))`。
- 历史 DB 代码、落盘文件或未来手动导入路径可能绕过保存时校验。

涉及文件：

- `backend/services/strategy_loader.py`
- `event_analysis/loader.py`
- `backend/services/strategy_validator.py`
- `backend/services/event_analysis_validator.py`
- `tests/test_code_validator.py`
- 新增 `tests/test_loader_validation.py`

核心改动：

1. `StrategyLoader` 引入 `StrategyValidator`。
   - `_load_module_from_code()` 执行前调用 validator。
   - `_load_module()` 从文件读取源码后也调用 validator。
   - 校验失败抛 `StrategyLoadError`，错误消息保留 validator message。
2. `EventAnalysisLoader` 引入 `EventAnalysisValidator`。
   - 对 `code` 参数和 `file_path` 加载路径都做复验。
   - 校验失败抛 `EventAnalysisLoadError`。
3. 避免循环依赖。
   - Validator 只依赖 `code_validator_base.py`，loader 可安全 import。
4. 测试覆盖：
   - 合法策略可加载。
   - 含 `globals()` 的策略即使直接传给 loader 也失败。
   - 含 `().__class__.__mro__` 的事件分析文件加载失败。
   - loader 错误不会吞掉 validator 原因。

实现示意：

```python
validation = StrategyValidator().validate(code)
if not validation.ok:
    raise StrategyLoadError(validation.message)
exec(compile(code, module.__file__, "exec"), module.__dict__)
```

验收标准：

- `tests/test_loader_validation.py` 通过。
- 现有 `tests/test_backend_api.py` 通过。
- 直接调用 loader 不能绕过 validator。

### 4.2 Benchmark 真实计算与报告输出

当前问题：

- `BacktestEngine.__init__()` 已有 `benchmark: str = None` 参数。
- 前端/模板也有 benchmark 字段。
- 但引擎没有读取指数行情，也没有计算超额收益、Alpha/Beta、信息比率。

涉及文件：

- `backtest/data_loader.py`
- `backtest/engine.py`
- `backtest/reporting.py`
- `backend/services/backtest_service.py`
- `backend/schemas.py`
- `frontend/src/App.jsx`
- `tests/test_engine_metrics.py`
- `tests/test_data_loader.py`

核心改动：

1. `DataLoader` 新增 `get_index_history()`。
   - 数据源：`index_daily` 视图。
   - 入参：`index_code: str`, `start_date`, `end_date`, `fields=None`。
   - 日期参数使用 DuckDB 参数绑定。
   - `fields` 使用 `_validate_column_names()`。
   - 返回按 `trade_date` 升序 DataFrame。
2. 建立 benchmark 代码映射。
   - `hs300 -> 000300.SH`
   - `zz500 -> 000905.SH`
   - `zz1000 -> 000852.SH`
   - 允许直接传入形如 `000300.SH` 的指数代码。
3. `BacktestResult` 增加 benchmark 字段。
   - `benchmark_return`
   - `excess_return`
   - `alpha`
   - `beta`
   - `information_ratio`
   - `tracking_error`
   - `benchmark_curve`
   - `benchmark_daily_returns`
4. `BacktestEngine._generate_result()` 计算逻辑。
   - 对齐策略日收益与 benchmark 日收益。
   - benchmark 累计收益从首日 close 归一化。
   - `beta = cov(strategy, benchmark) / var(benchmark)`。
   - `alpha = annual_return - risk_free_rate - beta * (benchmark_annual_return - risk_free_rate)`。
   - `tracking_error = std(strategy_return - benchmark_return) * sqrt(252)`。
   - `information_ratio = mean(active_return) / std(active_return) * sqrt(252)`。
5. 缺 benchmark 数据时降级。
   - 不让回测失败。
   - benchmark 相关字段为 `None` 或 `0`，报告中显示 `-`。
6. `backtest/reporting.py` 输出。
   - `payload["benchmark"]` 增加指标和曲线。
   - `charts` 中增加 benchmark cumulative return。
   - HTML 可先只显示指标卡，不强求复杂图形。
7. `BacktestService` 传入 benchmark。
   - 若 `BacktestCreate` 暂无 benchmark 字段，可先从模板/默认设置后续接入。
   - 更完整方案：给 `BacktestCreate` 增加 `benchmark: str | None = None`，默认 `None` 保持兼容。

测试设计：

1. `tests/test_data_loader.py`
   - 构造 `index_daily` fixture。
   - 验证 `get_index_history()` 升序、字段过滤、非法字段拒绝。
2. `tests/test_engine_metrics.py`
   - 构造固定策略 equity_curve 和 benchmark_curve。
   - 手工计算 beta、tracking error、information ratio。
   - 验证 benchmark 缺失时不抛异常。

验收标准：

- 未传 benchmark 时现有回测测试不变。
- 传 benchmark 时报告 payload 有 `benchmark` 区块。
- 指标公式有单元测试固定。

### 4.3 修正 Sharpe 和扩展指标测试

当前问题：

- `risk_free_rate` 已经作为参数进入 `BacktestEngine`。
- 但 `sharpe_ratio` 仍用原始日收益均值计算，没有扣无风险利率。
- Sortino/Calmar/盈亏比/平均持仓周期/换手率已有初步实现，但缺测试。

涉及文件：

- `backtest/engine.py`
- `tests/test_engine_metrics.py`

核心改动：

1. Sharpe 改为使用超额收益。
   - `excess_returns = daily_returns - risk_free_rate / 252`
   - `sharpe = excess_returns.mean() / excess_returns.std() * sqrt(252)`
2. Sortino 使用同一组超额收益。
3. 指标缺样本时返回 `0.0` 或 `None` 要统一。
   - 当前系统多数字段用 `0.0`，短期保持兼容。
4. 平均持仓周期算法改进。
   - 当前简单按全部买卖顺序配对。
   - 改为按 `ts_code` 分组，FIFO 匹配买入/卖出日期。
   - 对未平仓持仓不计入已完成持仓周期。
5. 盈亏比按卖出成交的 `realized_pnl` 计算。
   - 只统计已实现 PnL。
   - 无亏损但有盈利时可返回 `inf` 或约定值；建议报告层将 `inf` 显示为 `-` 或 `∞`。
6. 新增 `tests/test_engine_metrics.py`。
   - 用手工构造 `daily_values` 和 `trade_history` 调 `_generate_result()`。
   - 不依赖真实 parquet 数据。

验收标准：

- `risk_free_rate=0` 时 Sharpe 与旧逻辑一致。
- `risk_free_rate>0` 时 Sharpe 下降。
- 平均持仓周期按股票 FIFO 计算正确。
- 无交易、无亏损、单日净值等边界不报错。

### 4.4 补齐 DataLoader 剩余 SQL 参数化

当前问题：

已参数化：

- `get_history()`
- `get_cross_section()`
- `warm_up_cache()`

仍需处理：

- `get_adj_factor()`
- `get_next_trade_date()`
- `get_prev_trade_date()`
- `get_instruments()`
- 部分财务/概念/行业查询如有用户入参，也应逐步处理。

涉及文件：

- `backtest/data_loader.py`
- `tests/test_data_loader.py`

核心改动：

1. `get_adj_factor()`
   - `WHERE ts_code = ? AND trade_date = ?`
2. `get_next_trade_date()` / `get_prev_trade_date()`
   - `WHERE trade_date = ?`
3. `get_instruments()`
   - `exchange` 和 `status` 使用条件列表 + params。
   - 不拼接用户值。
4. 增加值域白名单。
   - `exchange` 可选：`SH/SZ/BJ`。
   - `status` 可选：`L/D/P`。
   - 非法值抛 `ValueError` 或返回空；建议抛 `ValueError`，便于发现调用错误。
5. 测试覆盖 SQL 注入形态字符串。

验收标准：

- 现有 DataLoader 测试全部通过。
- 恶意 `ts_code`、`exchange`、`status` 不会拼入 SQL。

## 5. Phase 1：后端 API 与任务治理

### 5.1 列表接口分页

当前问题：

- `list_backtests()`、`list_event_analyses()`、`list_strategies()`、`list_event_definitions()` 仍全量返回。
- 前端有一些分页 UI 痕迹，但数据流不是服务端分页。

涉及文件：

- `backend/api/backtests.py`
- `backend/api/event_analyses.py`
- `backend/api/strategies.py`
- `backend/api/event_definitions.py`
- `backend/services/backtest_service.py`
- `backend/services/event_analysis_service.py`
- `backend/services/strategy_service.py`
- `backend/services/event_definition_service.py`
- `backend/schemas.py`
- `frontend/src/api.js`
- `frontend/src/App.jsx`

核心改动：

1. 新增分页响应 schema。

```python
class PageOut(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int
```

更严格的做法是为每类资源定义：

- `BacktestTaskPageOut`
- `EventAnalysisTaskPageOut`
- `StrategyPageOut`
- `EventDefinitionPageOut`

2. 保留旧接口。
   - `GET /api/backtests` 不带参数仍返回 list。
   - 可选方案 A：`GET /api/backtests?limit=50&offset=0` 返回分页结构，会改变响应类型，不推荐。
   - 推荐方案 B：新增 `GET /api/backtests/page`。
3. Service 层新增分页方法。
   - `list_tasks_page(limit, offset, status=None, keyword=None)`。
   - SQL 使用 `COUNT(*)` + `LIMIT ? OFFSET ?`。
4. 前端逐步接入。
   - 先让任务列表使用分页接口。
   - 策略/事件定义保留全量，后续再迁移。

验收标准：

- 旧接口测试不变。
- 新分页接口测试覆盖 total、limit、offset、status。
- 大列表首屏无需全量加载。

### 5.2 回测任务/事件分析任务批量删除

当前状态：

- 策略定义和事件定义已有 `batch-delete`。
- 回测任务、事件分析任务仍只有单条删除。

涉及文件：

- `backend/api/backtests.py`
- `backend/api/event_analyses.py`
- `backend/services/backtest_service.py`
- `backend/services/event_analysis_service.py`
- `frontend/src/api.js`
- `frontend/src/App.jsx`
- `tests/test_backend_api.py`

核心改动：

1. 新增请求 schema。

```python
class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1)
```

2. 新增接口。
   - `POST /api/backtests/batch-delete`
   - `POST /api/event-analyses/batch-delete`
3. 行为保持与单条删除一致。
   - running/queued 不删除，进入 failed 列表。
   - 不存在的 ID 进入 failed 列表。
   - 成功删除报告/结果文件。
4. 返回结构。

```json
{
  "ok": false,
  "deleted_ids": [1, 2],
  "failed": [{"id": 3, "reason": "请先终止运行中或排队中的回测"}]
}
```

验收标准：

- 部分成功不回滚已删除项。
- 前端可展示部分成功提示。
- 单条删除接口不变。

### 5.3 策略版本历史接口

当前问题：

- DB 有 `strategy_versions`，但 API 没有版本历史查看能力。

涉及文件：

- `backend/api/strategies.py`
- `backend/services/strategy_service.py`
- `backend/schemas.py`
- `tests/test_backend_api.py`

核心改动：

1. 新增 schema：
   - `StrategyVersionOut`
2. Service 新增：
   - `list_versions(strategy_id)`
   - `get_version(strategy_id, version_id)`
3. API 新增：
   - `GET /api/strategies/{strategy_id}/versions`
   - `GET /api/strategies/{strategy_id}/versions/{version_id}`
4. 返回字段：
   - `id`
   - `strategy_id`
   - `version`
   - `code_hash`
   - `file_path`
   - `validation_status`
   - `validation_message`
   - `dependencies`
   - `created_at`
   - 详情接口可包含 `code`

验收标准：

- 创建策略后版本列表有 v1。
- 更新代码后版本列表增加 v2。
- 不存在版本返回 404。

### 5.4 config_center Service 化

当前问题：

- `backend/api/config_center.py` 仍直接操作数据库，绕过 service 层。

涉及文件：

- `backend/api/config_center.py`
- 新增 `backend/services/config_center_service.py`
- `backend/schemas.py`
- `tests/test_backend_api.py`

核心改动：

1. 新建 `ConfigCenterService`。
2. 迁移 preset 和 agent config 的 CRUD SQL。
3. API 层只做：
   - 调 service
   - 捕获 ValueError -> HTTP 400/404
   - response_model 输出
4. 行为保持不变。

验收标准：

- 现有 config_center API 测试通过。
- API 文件中不再直接写主要 SQL。

## 6. Phase 2：前端结构与体验

### 6.1 App.jsx 渐进拆分

当前问题：

- `frontend/src/App.jsx` 仍约 2872 行。
- 所有视图、状态、工具函数混在一起。

涉及文件：

- `frontend/src/App.jsx`
- 新增 `frontend/src/utils/formatters.js`
- 新增 `frontend/src/components/MetricCard.jsx`
- 新增 `frontend/src/components/Pagination.jsx`
- 新增 `frontend/src/components/ConfirmDialog.jsx`
- 新增 `frontend/src/components/ErrorBoundary.jsx`
- 新增 `frontend/src/views/*`

拆分顺序：

1. 先抽纯函数。
   - 日期格式化。
   - 金额/百分比格式化。
   - 状态文案。
   - heatmap color。
2. 抽无状态组件。
   - `MetricCard`
   - `EmptyState`
   - `RuntimeLogPanel`
   - `Pagination`
3. 抽局部视图。
   - `DataManagementView`
   - `ReportsView`
   - `SettingsView`
4. 最后抽核心任务列表。
   - `BacktestListView`
   - `EventAnalysisListView`
   - `StrategyListView`

验收标准：

- 每一步都能 `npm run build`。
- URL 参数行为不变。
- `activeTab`、`selectedBacktestId`、`selectedEventAnalysisId` 行为不变。

### 6.2 轮询 diff 和可见性退避

当前问题：

- 每 2.5 秒刷新回测和事件分析。
- 即使数据没变也会 setState，容易触发全量重渲染。

涉及文件：

- `frontend/src/App.jsx`
- 可能新增 `frontend/src/utils/shallowEqual.js`

核心改动：

1. 增加稳定序列化或轻量比较函数。
   - 比较任务 `id/status/progress/error_message/report_path/metrics/updated fields`。
   - 不比较每个对象引用。
2. `refreshBacktests()` 和 `refreshEventAnalyses()` 只在数据变化时 setState。
3. 页面隐藏时暂停或降频。

```js
if (document.visibilityState === "hidden") return;
```

4. API offline 后退避。
   - 2.5s -> 5s -> 10s。

验收标准：

- 数据无变化时 React state 不更新。
- running 任务仍能及时刷新。

### 6.3 Error Boundary 与确认弹窗

涉及文件：

- `frontend/src/components/ErrorBoundary.jsx`
- `frontend/src/components/ConfirmDialog.jsx`
- `frontend/src/App.jsx`

核心改动：

1. App 根部包 Error Boundary。
2. 报告/图表区域使用局部 Error Boundary。
3. 替换所有 `window.confirm`。
4. 删除操作统一调用 `confirmAction({ title, message, tone })`。

验收标准：

- 搜索 `window.confirm` 返回 0。
- 人为制造组件异常时页面不白屏。

### 6.4 数据管理页真实化

当前问题：

- 数据管理页仍硬编码 `2026-04-29`。
- 按钮只是展示，不触发真实任务或读取真实校验状态。

涉及文件：

- `frontend/src/App.jsx`
- `backend/api/config_center.py` 或新增 `backend/api/data_admin.py`
- `scripts/data_utils/validate_data.py`

核心改动：

1. 先移除硬编码。
   - 最新交易日来自 `/api/settings` 的 `data.latest_trade_date`。
2. 新增只读数据状态接口。
   - `GET /api/config/system-info` 如果已有则复用。
   - 或新增 `GET /api/data/status`。
3. 页面展示：
   - 数据目录。
   - 最早/最新交易日。
   - daily_bar 文件数。
   - daily_basic 文件数。
   - calendar 是否存在。
4. “校验数据质量”按钮先只触发只读校验或展示命令，不执行长任务。

验收标准：

- 搜索 `2026-04-29` 不再出现在 `frontend/src/App.jsx`。
- 无数据目录时显示空状态。

## 7. Phase 3：数据运维与因子分析

### 7.1 validate_data 使用交易日历

当前问题：

- `validate_range()` 仍用 `weekday()` 判断工作日。
- 这会误判中国节假日和调休。

涉及文件：

- `scripts/data_utils/validate_data.py`
- `tests/test_validate_data.py`

核心改动：

1. 读取 `calendar.parquet`。
2. 只遍历 `is_open == 1` 的交易日。
3. calendar 缺失时明确报错，不回退 weekday。
4. 输出 summary 可 JSON 序列化。

验收标准：

- 调休日/节假日 fixture 测试通过。
- `failed_details` 不包含不可 JSON 序列化对象，必要时转 dict。

### 7.2 校验范围扩展

涉及文件：

- `scripts/data_utils/validate_data.py`

核心改动：

新增校验：

1. `daily_basic`
   - 主键唯一。
   - 必需字段存在。
   - `total_mv/circ_mv/turnover_rate` 非负。
2. `stk_limit`
   - `up_limit/down_limit` 存在且正数。
   - `up_limit >= down_limit`。
3. `suspend_d`
   - 日期和股票代码字段存在。
4. `instruments`
   - `ts_code/name/list_date` 基础字段存在。
5. `calendar`
   - `trade_date/is_open` 字段存在。
   - 交易日升序唯一。

验收标准：

- 任一数据集缺字段时能给出明确错误。
- 校验结果可输出 JSON。

### 7.3 统一数据运维入口

涉及文件：

- 新增 `scripts/data_utils/data_admin.py`
- `docs/quant-data-guide.md`

核心命令：

```bash
python scripts/data_utils/data_admin.py validate --start 2026-01-01 --end 2026-04-29
python scripts/data_utils/data_admin.py show-range
python scripts/data_utils/data_admin.py update-daily --start 2026-01-01 --end 2026-04-29
python scripts/data_utils/data_admin.py update-extra --start 2026-01-01 --end 2026-04-29 --tasks daily_basic stk_limit
python scripts/data_utils/data_admin.py clean-cache --dry-run
```

设计原则：

- 默认只读或 dry-run。
- 破坏性操作必须显式 `--confirm`。
- 输出包含人类可读日志和机器可读 JSON summary。

### 7.4 因子分析模块包化

当前状态：

- 有 `scripts/analysis/analyze_worldquant_factor.py` 等脚本。
- 但没有正式 `factor_analysis/` 包，也没有单元测试。

涉及文件：

- 新增 `factor_analysis/__init__.py`
- 新增 `factor_analysis/operators.py`
- 新增 `factor_analysis/metrics.py`
- 新增 `factor_analysis/engine.py`
- 新增 `tests/test_factor_analysis.py`

核心能力：

1. 算子：
   - `rank`
   - `ts_rank`
   - `delay`
   - `delta`
   - `rolling_corr`
   - `rolling_zscore`
   - `winsorize`
   - `standardize`
2. 指标：
   - IC。
   - RankIC。
   - 分组收益。
   - 多空收益。
3. Engine：
   - 输入因子 DataFrame：`ts_code/trade_date/factor`。
   - 输入未来收益 DataFrame：`ts_code/trade_date/ret_Nd`。
   - 输出 summary 和 detail。

验收标准：

- 最小 fixture 可跑通 IC 和分组收益。
- 不依赖真实 `data/`。
- 不影响现有 `backtest/` 和 `event_analysis/`。

## 8. 测试与验收矩阵

每个阶段必须运行：

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile backtest/*.py event_analysis/*.py backend/services/*.py backend/api/*.py
cd frontend && npm run build
```

新增建议测试：

| 测试文件 | 目标 |
|---|---|
| `tests/test_loader_validation.py` | loader 执行前复验 validator |
| `tests/test_engine_metrics.py` | Sharpe、Sortino、Calmar、benchmark、换手率 |
| `tests/test_data_loader.py` | index history、剩余参数化、字段白名单 |
| `tests/test_backend_api.py` | 分页、批量删除、版本历史 |
| `tests/test_validate_data.py` | 交易日历驱动的数据校验 |
| `tests/test_factor_analysis.py` | 因子算子、IC、分组收益 |

## 9. 推荐提交顺序

1. `fix(loader): validate generated code before exec`
2. `feat(backtest): compute benchmark and excess metrics`
3. `test(engine): lock down risk and trade metrics`
4. `fix(data): parameterize remaining loader queries`
5. `feat(api): add paged list endpoints and task batch delete`
6. `feat(api): expose strategy version history`
7. `refactor(api): move config center SQL into service`
8. `refactor(frontend): extract shared components and formatters`
9. `perf(frontend): diff polling results before setState`
10. `feat(data): calendar-driven validation and data admin CLI`
11. `feat(factor): introduce factor_analysis package`

## 10. 风险与注意事项

1. Benchmark 会改变报告结构。
   - 必须以新增字段方式输出，旧字段保持不变。
2. Loader 执行前复验可能拦截历史策略。
   - 需要错误信息清楚，方便用户修复历史代码。
3. Sharpe 改为扣无风险利率后，历史新跑结果会变化。
   - 默认 `risk_free_rate=0` 时保持旧结果。
4. 前端拆分容易引入状态回归。
   - 先抽纯函数和无状态组件，避免一次性改路由和全局状态。
5. 数据运维命令不能默认执行破坏性操作。
   - 清理、重置、修复必须 dry-run 或要求 `--confirm`。

## 11. 完成定义

本计划完成时，应满足：

1. `system-review-2026-05-10.md` 中 P0 项全部关闭。
2. Benchmark 指标进入报告 JSON，并有单元测试。
3. Loader 不能绕过 validator 执行危险代码。
4. 后端至少 backtests/event analyses 支持分页和批量删除。
5. 前端无硬编码 `2026-04-29`，轮询无变化时不 setState。
6. `validate_data.py` 使用交易日历而不是 weekday。
7. 所有验收命令稳定通过。
