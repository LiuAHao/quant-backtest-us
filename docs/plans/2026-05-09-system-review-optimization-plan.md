# 系统审查优化完整计划方案

来源审查报告：[../issues/system-review-2026-05-09.md](../issues/system-review-2026-05-09.md)

## 1. 目标

本计划把 2026-05-09 系统审查报告中的问题整理为可执行的优化路线，覆盖回测正确性、用户代码安全边界、数据访问性能、后端 API、前端体验、数据运维和测试体系。

核心目标：

1. 先修复会影响回测结果正确性的缺陷，保证已有策略结果可信。
2. 明确并收紧策略/事件分析代码执行的信任边界，降低误操作和暴露 API 后的安全风险。
3. 在不破坏外部调用兼容性的前提下补齐 benchmark、指标、分页、导出、批量操作等平台能力。
4. 将性能瓶颈从“每次请求重复 SQL / 重复转换”逐步改为“区间预处理 + 缓存 + 增量刷新”。
5. 补齐关键路径测试，确保后续优化不会再次引入隐性回测偏差。

## 2. 总体原则

1. 正确性优先于性能。
   - 复权、交易费用、净值统计、基准对比等会改变结果含义的内容必须先有测试再改。
2. 向后兼容优先。
   - 现有 HTTP API 和 Python import 调用默认保持可用。
   - 破坏性调整通过新增参数、新增接口、双写/双读或兼容层完成。
3. 先补基础设施，再扩功能。
   - 指标库、benchmark、分页、导出等功能应建立在更稳的数据和报告结构上。
4. 用户生成代码只视为可信代码。
   - 短期文档明确边界，中期加强校验，长期进程隔离。
5. 前端重构按功能边界逐步拆分。
   - 避免一次性大改 `App.jsx` 导致行为回归不可控。

## 3. 里程碑概览

| 阶段 | 主题 | 覆盖审查项 | 当前状态 | 剩余重点 |
|---|---|---:|---|---|
| M0 | 基线与保护网 | #1 #2 #5 #6 #11 #15 #46 | 部分完成 | 固定回测结果快照、可信代码边界文档 |
| M1 | 正确性修复 | #1 #2 #8 #11 #15 | 基本完成 | 真实大数据缓存压测、Sharpe 无风险利率仍未做 |
| M2 | 安全与配置治理 | #5 #6 #17 #39 | 部分完成 | Loader 执行前复验、文档声明、更多 SQL 参数化 |
| M3 | 回测能力增强 | #4 #8 #9 #10 #12 #13 #14 | 未完成 | benchmark、扩展指标、订单有效期、回调、指标库 |
| M4 | 后端与数据性能 | #16 #18 #19 #20 #21 #22 #23 #24 #40 | 未完成 | 分页、索引、服务层收敛、线程池关闭、批量接口 |
| M5 | 前端体验与结构 | #25-#37 | 未完成 | App 拆分、轮询优化、错误边界、编辑器、导出、数据管理 |
| M6 | 数据运维与因子分析 | #41-#45 #47 #3 | 未完成 | 数据校验升级、统一运维入口、因子分析模块 |

> #3 分红/送股/配股依赖数据源，作为 M6 的调研项，不纳入前置关键路径。

## 3.1 当前完成度快照（2026-05-09 复核）

已完成或基本完成：

1. `DataLoader.get_history()` 复权基准修复。
   - qfq/hfq 在 `_apply_adjustment()` 内统一按 `trade_date` 升序计算。
   - 新增 parquet fixture 测试覆盖 qfq、hfq、升序返回、窗口限制。
2. `Position.market_value` 设计修复。
   - property 改为成本市值。
   - 新增 `get_market_value(current_price)`。
   - 新增 Broker/Position 单元测试。
3. 默认印花税率修正。
   - `Broker(stamp_duty_rate)` 默认从 `0.001` 改为 `0.0005`。
   - 测试覆盖默认值、自定义值、只在卖出侧收取。
4. `get_history()` 缓存开始真正读取。
   - `warm_up_cache()` 后可从 `_cache` 返回。
   - 缓存返回 copy，避免策略侧污染缓存。
   - 缓存路径兼容 datetime-like `trade_date`。
5. Settings schema 和白名单治理。
   - `PUT /api/settings` 改为 Pydantic schema。
   - 新增 `PATCH /api/settings`。
   - 未知顶层 key 不再写入 settings 表。
   - 局部更新不会丢失默认字段。
6. Validator 安全规则增强。
   - 策略和事件分析 validator 拦截 `globals`、`locals`、`vars`、`getattr`、`setattr`、`delattr`、`pickle`、`marshal`、`runpy`、`multiprocessing`。
   - 拦截高风险 dunder 属性链，如 `().__class__.__mro__`。
   - 保留合法 `super().__init__()`。
7. DataLoader 部分 SQL 参数化。
   - `get_history()`、`get_cross_section()`、`warm_up_cache()` 已做参数绑定。
   - `fields` 动态 SELECT 字段增加标识符校验。

当前验证结果：

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile backtest/*.py event_analysis/*.py backend/services/*.py backend/api/*.py
cd frontend && npm run build
```

以上命令均已通过。

仍未完成的关键缺口：

1. 没有固定小型回测结果快照，尚不能自动发现净值/收益/交易条数的细微漂移。
2. Loader 执行前还没有强制重新 validator 复验，历史 DB 代码或文件加载路径仍可能绕过创建/更新时校验。
3. 用户代码执行仍在主 Python 进程内，尚未做受限 globals、超时、子进程或容器隔离。
4. Benchmark 仍停留在模板/前端字段层面，没有真实指数曲线、Alpha/Beta、信息比率、tracking error。
5. Sharpe 无风险利率、Calmar、Sortino、盈亏比、平均持仓周期、换手率等指标未实现。
6. 分页、索引、服务层收敛、线程池优雅关闭仍未做。
7. 前端 `App.jsx` 仍是大单文件，轮询 diff、Error Boundary、代码编辑器、导出、数据管理页真实化仍未做。
8. 数据校验脚本、统一数据运维入口、因子分析模块仍未系统落地。

## 4. M0 基线与保护网

### 4.1 建立回测正确性基准

涉及文件：

- `backtest/data_loader.py`
- `backtest/broker.py`
- `backtest/engine.py`
- `tests/`

任务：

1. 新增最小 parquet fixture，覆盖：
   - `daily_bar`
   - `adj_factor`
   - `calendar`
   - 可选 `daily_basic`
2. 构造一只股票 3-5 个交易日的复权因子样例。
   - 要能明确验证 qfq 使用最新日因子。
   - 要能明确验证 hfq 使用首日因子。
3. 新增 `DataLoader.get_history(adjust="qfq" / "hfq")` 单元测试。
4. 新增 `Position.market_value` 和 `get_market_value()` 行为测试。
5. 新增费用参数测试。
   - 默认印花税率。
   - 外部传入覆盖默认值。
6. 记录一个小型回测结果快照。
   - 总收益率。
   - 最大回撤。
   - 交易条数。
   - 手续费和印花税合计。

验收标准：

- `python -m unittest discover -s tests -v` 通过。
- 复权测试能在没有真实 `data/` 目录的环境中独立运行。
- 后续 M1 修改前后，非预期指标不漂移。

### 4.2 明确兼容性边界

任务：

1. 在计划实施前列出现有外部调用入口。
   - `POST /api/backtests`
   - `POST /api/backtests/quick`
   - `PUT /api/settings`
   - `POST /api/event-analyses/quick`
   - 标准脚本 `scripts/agent_entry/run_standard_backtest.py`
   - 标准脚本 `scripts/agent_entry/run_standard_event_analysis.py`
2. 为破坏性风险项制定兼容策略。
   - #5 settings 未知 key 默认忽略或进入 `custom`。
   - #38 DELETE 返回值不统一先保持现状。
   - #39 新增 PATCH，但保留 PUT。

验收标准：

- 文档中每个破坏性项都有“保留旧行为”的说明。
- 自动化测试覆盖 PUT/PATCH 双入口或明确延期。

## 5. M1 正确性修复

### 5.1 修复复权基准

覆盖审查项：#1

涉及文件：

- `backtest/data_loader.py`
- `tests/test_data_loader.py` 或新增同类测试文件

方案：

1. 在 `_apply_adjustment()` 内部先复制并按 `trade_date` 升序排序。
2. qfq 使用排序后最后一行 `adj_factor` 作为最新日基准。
3. hfq 使用排序后第一行 `adj_factor` 作为首日基准。
4. 计算完成后保持 `get_history()` 对外返回日期升序。
5. 对 `get_cross_section(adjust=...)` 单独评估。
   - 截面只有单日数据，复权基准问题不明显。
   - 但 `_apply_adjustment()` 被复用，需确认不会因排序改变单日行为。

验收标准：

- qfq/hfq fixture 测试通过。
- `get_history()` 返回仍是升序。
- 不改变函数签名。

### 5.2 修复持仓市值 API

覆盖审查项：#2

涉及文件：

- `backtest/broker.py`
- `tests/test_broker.py`

方案：

1. 保留 `Position.market_value` property。
2. 将 property 语义改为成本市值或保守命名为 `cost_value`。
   - 为兼容已有调用，推荐 `market_value` 返回 `volume * avg_cost`。
3. 新增 `get_market_value(current_price: float) -> float`。
4. `Account.get_total_value(prices)` 内部可选择调用新方法，减少重复计算。

验收标准：

- `Position(volume=100, avg_cost=10).market_value == 1000`。
- `get_market_value(12) == 1200`。
- 既有回测净值结果不因重构发生非预期变化。

### 5.3 修正交易费用默认值

覆盖审查项：#11

涉及文件：

- `backtest/broker.py`
- `backtest/engine.py`
- `backend/schemas.py`
- `backend/services/backtest_template_service.py`
- `backend/api/config_center.py`
- `frontend/src/api.js`
- `frontend/src/App.jsx`

方案：

1. 将默认印花税率从 `0.001` 改为 `0.0005`。
2. 不改变已有任务记录中的历史参数。
3. 如后端创建任务 schema 当前没有 `stamp_duty_rate` 字段，先只修 `Broker` 默认值。
4. 后续 M3 再决定是否把印花税率暴露到回测模板和 UI。

验收标准：

- 新建 `Broker()` 默认 `stamp_duty_rate == 0.0005`。
- 用户显式传入旧值 `0.001` 时仍按旧值计算。

### 5.4 启用 get_history 缓存

覆盖审查项：#15

涉及文件：

- `backtest/data_loader.py`
- `tests/test_data_loader.py`

方案：

1. 明确 `_cache` 的 key 设计。
   - 推荐 key 为 `ts_code`，value 为该股票升序全量/区间 DataFrame。
   - 对 `fields/window/end_date/adjust` 在命中后做 DataFrame 过滤和尾部截取。
2. 缓存命中时返回 `.copy()`，避免策略修改污染缓存。
3. `prepare_backtest_data()`、`clear_cache()`、数据源切换时清理缓存。
4. 对缓存缺失、字段缺失、复权方式不同做降级 SQL 查询。

验收标准：

- `warm_up_cache()` 后调用 `get_history()` 不再访问 DuckDB 查询路径。
- 返回字段、排序、复权结果和未缓存路径一致。

## 6. M2 安全与配置治理

### 6.1 Settings Schema 与白名单

覆盖审查项：#5 #39

涉及文件：

- `backend/api/settings.py`
- `backend/services/settings_service.py`
- `backend/schemas.py`
- `tests/test_backend_api.py`
- `frontend/src/api.js`

方案：

1. 新增 Pydantic schema：
   - `AiSettings`
   - `BacktestSettings`
   - `UiSettings`
   - `SettingsUpdate`
2. 允许的顶层 key：
   - `ai`
   - `backtest`
   - `ui`
   - `custom`
3. 未知顶层 key 默认忽略并记录 warning，不直接 400。
4. 已知 key 内部字段严格校验类型和范围。
5. 新增 `PATCH /api/settings`，保留 `PUT /api/settings` 调用同一实现。
6. 禁止从 settings 表直接覆盖进程环境变量。

验收标准：

- 旧 PUT 请求仍可用。
- 非法类型不会写入 settings 表。
- 未知 key 不污染 settings 表。
- PATCH 与 PUT 返回结构一致。

### 6.2 用户代码执行信任边界

覆盖审查项：#6

涉及文件：

- `backend/services/strategy_validator.py`
- `backend/services/event_analysis_validator.py`
- `backend/services/strategy_loader.py`
- `event_analysis/loader.py`
- `docs/API_GUIDE.md`
- `docs/STRATEGY_BUILD_GUIDE.md`
- `docs/EVENT_ANALYSIS_BUILD_GUIDE.md`

短期方案：

1. 文档明确声明：
   - 策略和事件分析代码会在本地 Python 进程执行。
   - 只允许运行可信代码。
   - 不建议将 quick API 暴露给不可信公网调用者。
2. Validator 增强：
   - 禁止访问 `__builtins__`、`globals`、`locals`、`vars`。
   - 禁止 dunder 属性链，例如 `().__class__.__mro__`。
   - 禁止 `getattr/setattr/delattr` 操作敏感对象。
   - 禁止 `pickle`、`marshal`、`runpy`、`multiprocessing` 等模块。
3. Loader 在执行前总是重新运行 validator。
   - 防止 DB 中历史代码或文件同步绕过创建/更新时校验。

中期方案：

1. 构建受限 globals。
2. 仅提供必要内置函数白名单。
3. 给策略/事件运行增加超时和内存保护。

长期方案：

1. 子进程或容器隔离。
2. 禁止网络访问和任意文件系统写入。
3. 通过 IPC 返回标准结果。

验收标准：

- 已知危险用法被 validator 拒绝。
- quick API、DB 中历史代码、文件加载路径都经过同一校验。
- 文档明确风险，不让用户误以为当前是安全沙箱。

### 6.3 数据 SQL 参数化

覆盖审查项：#17

涉及文件：

- `backtest/data_loader.py`

方案：

1. 对 `ts_code`、日期、状态、交易所等用户可控参数使用 DuckDB 参数绑定。
2. 表名、字段名不能参数绑定，必须来自内部白名单。
3. `fields` 参数使用白名单过滤，禁止拼接任意列表达式。

验收标准：

- 单元测试覆盖异常 `ts_code` 字符串。
- 合法字段查询结果不变。

## 7. M3 回测能力增强

### 7.1 Benchmark 对比

覆盖审查项：#4

涉及文件：

- `backtest/engine.py`
- `backtest/data_loader.py`
- `backtest/reporting.py`
- `backend/schemas.py`
- `backend/services/backtest_service.py`
- `frontend/src/App.jsx`

方案：

1. 在 `BacktestEngine` 增加可选参数：
   - `benchmark: str | None = None`
   - 默认保持 `None`，避免改变旧行为。
2. `DataLoader` 新增 `get_index_history(index_code, start_date, end_date)`。
3. 计算：
   - benchmark return
   - excess return
   - annual excess return
   - beta
   - alpha
   - information ratio
   - tracking error
4. 报告 JSON 新增 `benchmark` 区块。
5. 前端报告页新增基准对比图和指标。

验收标准：

- 未传 benchmark 时旧报告结构仍可读。
- 传 benchmark 时指标与手工计算样例一致。

### 7.2 风险收益指标扩展

覆盖审查项：#8 #9

涉及文件：

- `backtest/engine.py`
- `backtest/reporting.py`
- `backend/schemas.py`
- `frontend/src/App.jsx`

方案：

1. 新增 `risk_free_rate: float = 0.0` 参数。
2. Sharpe 使用超额日收益。
3. 新增指标：
   - Calmar
   - Sortino
   - volatility
   - downside volatility
   - profit/loss ratio
   - average holding days
   - turnover
4. 指标缺数据时返回 `None`，报告层负责显示 `-`。

验收标准：

- 默认 `risk_free_rate=0` 时 Sharpe 与旧逻辑一致或差异有明确说明。
- 新指标不会导致旧前端读取失败。

### 7.3 订单和撮合模型增强

覆盖审查项：#10 #12

涉及文件：

- `backtest/broker.py`
- `backtest/engine.py`
- `tests/test_broker.py`

方案：

1. 保留当前简单滑点作为默认模型。
2. 增加可插拔滑点模型：
   - fixed bps
   - volume participation
   - amount/liquidity aware
3. 增加订单有效期：
   - `DAY` 默认，当日未成交取消。
   - `GTC` 可跨日保留。
4. 增加成交量约束选项。

验收标准：

- 默认行为与旧逻辑一致。
- GTC 订单能跨交易日撮合。
- 滑点模型可通过参数选择。

### 7.4 策略生命周期回调

覆盖审查项：#13

涉及文件：

- `backtest/strategy.py`
- `backtest/engine.py`
- `docs/STRATEGY_BUILD_GUIDE.md`

方案：

1. `StrategyTemplate` 增加空实现回调：
   - `on_order_filled(self, context, order, trade)`
   - `on_day_end(self, context)`
   - `on_backtest_end(self, context)`
2. `get_callbacks()` 保持旧 `init/next` 可用。
3. 引擎在对应阶段检测并调用。

验收标准：

- 老策略不需要修改。
- 新回调能收到完整上下文。

### 7.5 内置技术指标库

覆盖审查项：#14

涉及文件：

- 新增 `backtest/indicators.py`
- `docs/STRATEGY_BUILD_GUIDE.md`
- `tests/test_indicators.py`

方案：

1. 提供基础指标：
   - SMA/MA
   - EMA
   - RSI
   - MACD
   - Bollinger Bands
   - ATR
2. 只依赖 pandas/numpy。
3. 明确 NaN 处理和窗口不足行为。

验收标准：

- 指标与简单手工样例一致。
- 策略可 `from backtest.indicators import sma, ema`。

## 8. M4 后端与数据性能

### 8.1 列表接口分页

覆盖审查项：#18 #29

涉及文件：

- `backend/api/*.py`
- `backend/services/*_service.py`
- `backend/schemas.py`
- `frontend/src/api.js`
- `frontend/src/App.jsx`

方案：

1. 后端新增可选查询参数：
   - `limit`
   - `offset`
   - `status`
   - `keyword`
2. 默认不传参数仍返回全量，保持兼容。
3. 新增分页响应结构可选接口：
   - `GET /api/backtests/paged`
   - 或通过 `?paged=true` 返回 `{items,total}`。
4. 前端列表分页逐步接入。

验收标准：

- 旧 API 调用不变。
- 大量任务时首屏加载显著减少。

### 8.2 StrategyService 启动优化

覆盖审查项：#19

涉及文件：

- `backend/services/strategy_service.py`

方案：

1. `_sync_current_files()` 只在应用启动时执行一次。
2. `StrategyService()` 实例化不再每次同步文件系统。
3. 如需手动同步，提供显式方法或启动 hook。

验收标准：

- 多次创建 `StrategyService()` 不重复写生成策略文件。
- 现有启动行为保持一致。

### 8.3 SQLite 连接和索引

覆盖审查项：#20 #21

涉及文件：

- `backend/db/database.py`

方案：

1. 保持 `get_conn()` 简洁模式，不急于引入复杂连接池。
2. 增加 SQLite pragmas：
   - `journal_mode=WAL`
   - `busy_timeout`
   - 合理的 `foreign_keys`
3. 增加索引：
   - `backtest_tasks(strategy_id)`
   - `backtest_tasks(status)`
   - `backtest_tasks(created_at)`
   - `event_analysis_tasks(event_definition_id)`
   - `event_analysis_tasks(status)`
   - `strategy_versions(strategy_id, version)`
4. 迁移保持幂等。

验收标准：

- 重复运行 `database.init_db()` 不报错。
- 列表和按状态查询有索引支持。

### 8.4 Validator/Service 去重

覆盖审查项：#22 #23

涉及文件：

- `backend/services/strategy_validator.py`
- `backend/services/event_analysis_validator.py`
- `backend/services/strategy_service.py`
- `backend/services/event_definition_service.py`
- `backend/api/config_center.py`

方案：

1. 提取 `BaseCodeValidator`。
2. 策略和事件分析只保留差异：
   - 模板基类名。
   - 必需方法。
   - 依赖推断关键词。
3. config_center 数据库操作逐步迁移到 service。
4. API 层只做请求/响应转换，不直接写 SQL。

验收标准：

- Validator 行为不回退。
- config_center API 响应不变。

### 8.5 批量接口和线程池关闭

覆盖审查项：#24 #40

涉及文件：

- `backend/api/backtests.py`
- `backend/api/event_analyses.py`
- `backend/api/strategies.py`
- `backend/api/event_definitions.py`
- `backend/main.py`
- `backend/services/backtest_service.py`
- `backend/services/event_analysis_service.py`

方案：

1. 批量删除：
   - 回测任务。
   - 事件分析任务。
   - 策略定义。
   - 事件定义。
2. 策略版本历史接口：
   - `GET /api/strategies/{id}/versions`
   - `GET /api/strategies/{id}/versions/{version_id}`
3. FastAPI shutdown event 中关闭全局 executor。

验收标准：

- 运行中任务不允许删除。
- 部分成功时返回明确 failed 列表。
- 应用关闭不遗留 worker。

## 9. M5 前端体验与结构

### 9.1 App.jsx 分阶段拆分

覆盖审查项：#25

涉及文件：

- `frontend/src/App.jsx`
- 新增 `frontend/src/components/*`
- 新增 `frontend/src/views/*`
- 新增 `frontend/src/hooks/*`
- 新增 `frontend/src/utils/*`

拆分顺序：

1. 纯工具函数：
   - 日期格式化。
   - 数字/百分比格式化。
   - 状态文案和颜色。
2. API 状态 hooks：
   - `useRuntimeSettings`
   - `useBacktests`
   - `useEventAnalyses`
3. 通用组件：
   - `MetricCard`
   - `ConfirmDialog`
   - `RuntimeLogPanel`
   - `Pagination`
4. 视图组件：
   - Dashboard
   - StrategyList
   - BacktestList
   - EventAnalysisList
   - Settings
   - DataManagement

验收标准：

- 每次拆分后 `npm run build` 通过。
- URL 参数行为保持不变。
- 顶部 overlay 互斥行为保持不变。

### 9.2 轮询优化

覆盖审查项：#26

涉及文件：

- `frontend/src/App.jsx`
- `frontend/src/api.js`

方案：

1. 对轮询结果做 shallow/deep light compare。
2. 只在任务状态、进度、关键指标变化时 setState。
3. 页面不可见时降低轮询频率或暂停。
4. API offline 时退避重试。

验收标准：

- 数据无变化时 React 不发生全量列表重渲染。
- 运行中任务仍能及时刷新。

### 9.3 Error Boundary 和确认弹窗

覆盖审查项：#27 #31

涉及文件：

- `frontend/src/components/ErrorBoundary.jsx`
- `frontend/src/components/ConfirmDialog.jsx`
- `frontend/src/App.jsx`

方案：

1. 全局 Error Boundary 包住主应用。
2. 视图级 Error Boundary 包住报告/图表区域。
3. 替换 `window.confirm`。
4. 对删除类操作显示对象名、影响范围和不可恢复提示。

验收标准：

- 组件异常不会白屏。
- 删除操作不再依赖浏览器原生确认框。

### 9.4 代码编辑器与导出

覆盖审查项：#28 #30 #37

涉及文件：

- `frontend/package.json`
- `frontend/src/App.jsx`
- `frontend/src/api.js`
- `frontend/src/utils/formatters.js`

方案：

1. 引入轻量代码编辑器。
   - 首选 Monaco 需评估包体。
   - 如包体过大，先用 CodeMirror。
2. 策略和事件分析代码编辑区支持：
   - Python 语法高亮。
   - 行号。
   - 基础搜索。
3. 抽出格式化函数，避免 `api.js` 与 `App.jsx` 重复。
4. 增加 CSV 导出。
5. Excel 导出可后置到后端或使用前端库。

验收标准：

- 编辑器不影响现有提交/校验。
- 回测列表、事件分析结果可导出 CSV。

### 9.5 数据管理页真实化

覆盖审查项：#32 #33

涉及文件：

- `frontend/src/App.jsx`
- `backend/api/config_center.py` 或新增数据 API
- `backend/services/settings_service.py`

方案：

1. 移除硬编码最新交易日。
2. 使用 `runtimeSettings.data.latest_trade_date`。
3. 数据管理页展示：
   - 数据目录。
   - 最早/最新交易日。
   - daily_bar 文件数。
   - daily_basic 文件数。
   - calendar 状态。
4. 按钮先接“校验数据”只读操作。
5. 下载/更新类操作作为后续后台任务，不直接在前端同步执行。

验收标准：

- 页面无硬编码 `2026-04-29`。
- 没有数据时能显示空状态。

### 9.6 前端工程化

覆盖审查项：#34 #35 #36

涉及文件：

- `frontend/vite.config.js`
- `frontend/eslint.config.js`
- `frontend/package.json`

方案：

1. 增加 `vite.config.js`。
2. 增加 ESLint。
3. 短期使用 PropTypes 或 JSDoc。
4. TypeScript 迁移作为长期目标，不与 App 拆分强绑定。

验收标准：

- `npm run build` 通过。
- `npm run lint` 可运行。

## 10. M6 数据运维与因子分析

### 10.1 数据校验升级

覆盖审查项：#41 #42 #43

涉及文件：

- `scripts/data_utils/validate_data.py`
- `scripts/data_download/download_by_date.py`
- `scripts/data_download/update_extra_data.py`

方案：

1. 校验范围扩展：
   - daily_bar
   - daily_basic
   - adj_factor
   - stk_limit
   - suspend_d
   - instruments
   - calendar
2. 日期范围使用交易日历，而不是 weekday。
3. 对 adj_factor 缺失或下载失败给出显式 warning/error。
4. 输出机器可读 JSON 报告。

验收标准：

- 缺失交易日、缺失字段、重复主键能被发现。
- 校验报告能被前端或后端读取。

### 10.2 统一数据运维入口

覆盖审查项：#44 #45

涉及文件：

- 新增 `scripts/data_utils/data_admin.py`
- `docs/quant-data-guide.md`

方案：

1. 提供统一 CLI：
   - `validate`
   - `update-daily`
   - `update-extra`
   - `repair`
   - `clean-cache`
   - `show-range`
2. 支持 dry-run。
3. 所有破坏性操作要求显式参数。

验收标准：

- 常用数据操作有一个入口。
- 文档中不再需要用户记多条脚本组合。

### 10.3 因子分析模块雏形

覆盖审查项：#47

涉及文件：

- 新增 `factor_analysis/`
- 新增 `docs/FACTOR_ANALYSIS_BUILD_GUIDE.md`
- 新增 `tests/test_factor_analysis.py`

方案：

1. 提供核心算子：
   - rank
   - ts_rank
   - delay
   - delta
   - rolling_corr
   - rolling_zscore
   - winsorize
   - standardize
2. 提供 IC/RankIC 分析。
3. 提供分组收益分析。
4. 与事件分析保持边界清晰。
   - 事件分析找样本事件。
   - 因子分析评估连续截面信号。

验收标准：

- 可用最小 fixture 跑通一个因子 IC 分析。
- 不影响现有 backtest/event_analysis 包。

### 10.4 分红送股数据调研

覆盖审查项：#3

方案：

1. 调研 Tushare 或 AkShare 可用接口。
2. 明确字段：
   - cash dividend
   - bonus share
   - rights issue
   - ex-dividend date
   - record date
3. 确定是否进入撮合/持仓层。
4. 如果已有 adj_factor 足以表达价格连续性，先不进入现金流模拟。

验收标准：

- 输出数据源可行性结论。
- 决定是否进入下一轮实现。

## 11. 测试策略

### 11.1 必跑命令

后端和引擎：

```bash
python -m unittest discover -s tests -v
python -m py_compile backtest/*.py event_analysis/*.py backend/services/*.py backend/api/*.py
```

前端：

```bash
cd frontend && npm run build
```

数据脚本：

```bash
python scripts/data_utils/validate_data.py
```

### 11.2 建议新增测试文件

| 文件 | 覆盖内容 |
|---|---|
| `tests/test_data_loader.py` | 复权、缓存、参数化查询、交易日历 |
| `tests/test_broker.py` | 持仓市值、费用、T+1、GTC |
| `tests/test_engine_metrics.py` | Sharpe、Calmar、Sortino、benchmark |
| `tests/test_settings_api.py` | settings schema、PUT/PATCH 兼容 |
| `tests/test_code_validator.py` | 策略/事件分析危险代码拦截 |
| `tests/test_indicators.py` | 技术指标库 |
| `tests/test_factor_analysis.py` | 因子算子和 IC 分析 |

### 11.3 回归样例

建议维护三个固定回归样例：

1. 空策略。
   - 验证净值不变、无交易。
2. 单票买入持有策略。
   - 验证交易费用、持仓市值、收益率。
3. 带复权历史查询策略。
   - 验证 qfq/hfq 修复不回退。

## 12. 发布顺序

推荐按以下 PR 或提交批次推进：

1. `fix(data-broker): add tests and repair adjustment/market value`
2. `fix(config-security): validate settings and document trusted code boundary`
3. `perf(data): enable get_history cache and parameterize queries`
4. `feat(backtest): add benchmark and extended metrics`
5. `feat(broker): add order validity and slippage models`
6. `perf(api): add pagination indexes and lifecycle cleanup`
7. `refactor(frontend): split app shell and shared components`
8. `feat(frontend): add polling diff error boundary editor and exports`
9. `feat(data): add unified validation and maintenance CLI`
10. `feat(factor): introduce factor analysis module`

每个批次都应满足：

- 只覆盖一个主要目标。
- 有对应测试或人工验证步骤。
- 不混入无关格式化。
- 对外接口变化必须写在 PR/提交说明中。

## 13. 风险与降级方案

| 风险 | 影响 | 降级方案 |
|---|---|---|
| 复权修复改变历史回测结果 | 用户对比旧报告出现差异 | 在 release note 明确旧结果受复权 bug 影响，保留旧报告但新任务使用修复逻辑 |
| settings schema 拒绝旧 payload | 外部自动化调用失败 | 未知 key 先忽略并告警，PATCH/PUT 双入口并存 |
| Validator 增强误杀合法策略 | 用户策略无法保存 | 提供错误详情和允许清单，先以 warning 模式观察一轮 |
| benchmark 数据缺失 | 报告生成失败 | benchmark 缺失时降级为无基准报告 |
| 前端拆分引入状态回归 | URL/弹窗/轮询异常 | 每次只拆一个视图或一组纯组件，保持构建和手测 |
| 数据维护脚本误删数据 | 本地数据损坏 | 默认 dry-run，破坏性操作要求显式 `--confirm` |

## 14. 完成定义

整体计划完成时应满足：

1. 审查报告中的高优先级项全部关闭或有明确风险接受说明。
2. 中优先级项至少完成回测核心、数据加载、后端分页/索引和前端轮询优化。
3. 低优先级项中硬编码、构建配置、ESLint、数据校验入口完成。
4. `python -m unittest discover -s tests -v` 与 `cd frontend && npm run build` 稳定通过。
5. 文档更新：
   - API 指南说明 settings、quick API 和可信代码边界。
   - 策略指南说明指标库、回调和日志建议。
   - 数据指南说明统一数据运维入口。

## 15. 下一阶段剩余工作优先级

M0/M1/M2 已完成一部分，下一阶段不再从复权和 broker 基础修复开始，而应优先补齐仍会影响正确性、安全边界和平台可用性的缺口。

### P0 必须优先完成

1. 建立固定小型回测结果快照。
   - 覆盖空策略、单票买入持有、带复权历史查询策略。
   - 记录 `total_return`、`max_drawdown`、`sharpe_ratio`、交易条数、手续费、印花税。
   - 目标是让后续 benchmark、指标、撮合模型改动都有回归锚点。
2. Loader 执行前强制重新 validator 复验。
   - `StrategyLoader.load(..., code=...)` 在 `exec` 前调用 `StrategyValidator`。
   - `EventAnalysisLoader.load(..., code=...)` 在 `exec` 前调用 `EventAnalysisValidator`。
   - 对历史 DB 代码和文件加载路径都生效。
3. 补充可信代码边界文档。
   - `docs/API_GUIDE.md` 标明 quick API 会执行本地 Python 代码，只允许可信调用者使用。
   - `docs/STRATEGY_BUILD_GUIDE.md` 和 `docs/EVENT_ANALYSIS_BUILD_GUIDE.md` 标明 validator 不是安全沙箱。
4. 继续 DataLoader SQL 参数化。
   - `get_adj_factor()`。
   - `get_next_trade_date()`。
   - `get_prev_trade_date()`。
   - `get_instruments()`。
   - 所有动态字段、状态、交易所参数必须走白名单或参数绑定。

验收命令：

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile backtest/*.py event_analysis/*.py backend/services/*.py backend/api/*.py
```

### P1 回测能力补齐

1. 实现真实 benchmark 对比。
   - `DataLoader.get_index_history()`。
   - `BacktestEngine(benchmark=None)` 可选参数。
   - 报告 JSON 输出 `benchmark` 区块。
   - 计算 benchmark return、excess return、beta、alpha、information ratio、tracking error。
2. 扩展风险收益指标。
   - `risk_free_rate=0.0` 默认参数。
   - Sharpe 使用超额日收益。
   - 新增 Calmar、Sortino、volatility、downside volatility。
3. 增加交易统计指标。
   - 盈亏比。
   - 平均持仓周期。
   - 换手率。
4. 为指标新增独立测试。
   - 新增 `tests/test_engine_metrics.py`。
   - 指标样例必须可手工计算。

验收标准：

- 未传 benchmark 时旧报告仍可读。
- benchmark 数据缺失时降级为无基准报告，不让回测失败。
- 指标缺少足够数据时返回 `None` 或显示 `-`，不抛异常。

### P2 后端性能与 API 治理

1. 列表接口分页。
   - backtests。
   - event analyses。
   - strategies。
   - event definitions。
   - 默认不传分页参数仍保持全量返回。
2. SQLite pragma 和索引。
   - WAL。
   - busy timeout。
   - 高频查询字段索引。
3. `StrategyService` 启动优化。
   - `_sync_current_files()` 不应在每次实例化时重复执行。
4. 全局 executor 优雅关闭。
   - FastAPI shutdown event 中关闭 backtest/event analysis executor。
5. 批量接口。
   - 回测任务批量删除。
   - 事件分析任务批量删除。
   - 策略定义/事件定义批量删除。
   - 返回部分成功结构。

验收标准：

- 老接口调用方式不变。
- 大列表首屏查询可以只取分页数据。
- 重复运行 `database.init_db()` 幂等。

### P3 前端体验与结构

1. 拆分 `frontend/src/App.jsx`。
   - 先抽纯工具函数和通用组件。
   - 再抽列表视图和详情视图。
2. 轮询 diff 优化。
   - 数据无变化时不 setState。
   - 页面隐藏时降低频率或暂停。
3. Error Boundary。
   - 全局应用边界。
   - 报告/图表局部边界。
4. 删除确认弹窗替代 `window.confirm`。
5. Python 代码编辑器。
   - CodeMirror 优先，Monaco 作为后续选项。
6. 数据管理页真实化。
   - 移除硬编码 `2026-04-29`。
   - 展示实际数据窗口和数据源状态。

验收命令：

```bash
cd frontend && npm run build
```

### P4 数据运维与因子分析

1. 扩展 `scripts/data_utils/validate_data.py`。
   - 覆盖 daily_bar、daily_basic、adj_factor、stk_limit、suspend_d、instruments、calendar。
   - 使用交易日历判断缺失，不再使用 weekday。
   - 输出 JSON 校验报告。
2. 新增统一数据运维入口。
   - `scripts/data_utils/data_admin.py validate`
   - `scripts/data_utils/data_admin.py update-daily`
   - `scripts/data_utils/data_admin.py update-extra`
   - `scripts/data_utils/data_admin.py show-range`
   - 破坏性操作默认 dry-run。
3. 因子分析模块从脚本收敛为包。
   - 新增 `factor_analysis/`。
   - 提供 rank、ts_rank、delay、delta、rolling_corr、rolling_zscore、winsorize、standardize。
   - 提供 IC/RankIC 和分组收益测试。

验收标准：

- 数据校验能在缺失 parquet 或字段缺失时给出明确错误。
- 因子分析有最小 fixture 测试，不依赖真实 `data/`。
