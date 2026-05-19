# 系统审查报告 — 2026-05-09

全面扫描策略构建和回测系统，涵盖回测引擎、后端 API、前端实现、数据层。

> **兼容性约定**: 项目需支持外部调用（Python import + HTTP API），以下标记含义：
> - 🟢 **安全** — 内部优化/新增功能，不影响外部接口
> - 🟡 **向后兼容** — 可通过默认参数/向后兼容方式实现
> - 🔴 **破坏性** — 会改变现有接口行为，需谨慎评估

---

## 🔴 高优先级（影响正确性/安全性）

| # | 模块 | 问题 | 位置 | 兼容性 |
|---|------|------|------|--------|
| 1 | 数据加载 | **前复权/后复权基准都依赖错误行序** — `get_history()` 复权前返回倒序数据，qfq/hfq 基准索引与注释语义相反 | `data_loader.py:675-693` | 🟢 修复内部实现，接口不变 |
| 2 | 券商模拟 | **`Position.market_value` property 设计错误** — `@property` 不能传入现价，直接访问永远按默认 0 计算；当前主估值路径未必受影响 | `broker.py:60-63` | 🟡 保留 property 同时新增 `get_market_value()` 方法 |
| 3 | ~~券商模拟~~ | ~~**缺少分红/送股/配股处理**~~ — 无数据源，暂不处理 | `broker.py` | ⏸️ 阻塞 |
| 4 | 回测引擎 | **无 benchmark 对比** — 无法输出超额收益、信息比率、Beta、Alpha | `engine.py` | 🟢 新增功能，不影响现有接口 |
| 5 | 安全 | **Settings 接口接受任意字典，无 Schema 校验** — 可写入任意配置命名空间，污染 settings 表并影响后续读取 | `backend/api/settings.py:16` | 🔴 加校验可能拒绝之前能通过的参数 |
| 6 | 安全 | **策略/事件分析代码通过 `exec()` 执行，信任边界不清** — AST 校验只能减少误用，不是安全沙箱 | `strategy_loader.py:47` / `event_analysis/loader.py:47` | 🟡 加强校验/隔离，不改接口 |

---

## 🟠 中优先级（性能/架构/功能缺失）

### 回测引擎

| # | 问题 | 位置 | 兼容性 |
|---|------|------|--------|
| 7 | 每日截面数据重复 `to_dict` 转换，5000+ 只股票 GC 压力大 | `engine.py:323-329` | 🟢 内部优化 |
| 8 | Sharpe 比率缺少无风险利率参数（隐含为 0） | `engine.py:367-370` | 🟡 新增参数用默认值 0 |
| 9 | 缺少 Calmar、Sortino、盈亏比、平均持仓周期等关键指标 | `reporting.py` | 🟢 新增字段，不影响现有输出 |
| 10 | 滑点模型过于简化 — 不区分流动性、不考虑成交量 | `broker.py:317-320` | 🟡 可保留默认行为 |
| 11 | 印花税率过时（默认 0.1%，2023-08-28 起已减半至 0.05%） | `broker.py:324` | 🟡 改默认值，外部可覆盖 |
| 12 | 未成交订单当日自动取消，无 GTC 支持 | `broker.py:348-350` | 🟢 新增功能 |
| 13 | 策略基类接口过简 — 无 `on_order_filled`、`on_day_end` 等回调 | `strategy.py` | 🟡 新增方法，不改现有接口 |
| 14 | 缺少内置技术指标库（MA/EMA/RSI/MACD/布林带） | `strategy.py` | 🟢 新增模块 |

### 数据加载

| # | 问题 | 位置 | 兼容性 |
|---|------|------|--------|
| 15 | `get_history()` 每次都执行 SQL，`_cache` 存在但从未读取 | `data_loader.py:38/322` | 🟢 内部优化 |
| 16 | DuckDB 连接配置硬编码（12GB/4线程） | `data_loader.py:45` | 🟡 改为从 settings 读取，保留默认值 |
| 17 | SQL 字符串拼接，非参数化查询 | 多处 | 🟢 内部优化 |

### 后端

| # | 问题 | 位置 | 兼容性 |
|---|------|------|--------|
| 18 | 所有列表接口无分页，全量加载 | 所有 `list_*` 端点 | 🟡 默认返回全量，分页为可选参数 |
| 19 | StrategyService 每次实例化触发文件同步，启动慢 | `strategy_service.py:27-30` | 🟢 内部优化 |
| 20 | SQLite 无连接池，每次操作创建新连接 | `database.py:24-33` | 🟢 内部优化 |
| 21 | 数据库缺少索引（strategy_id、status 等高频查询字段） | `database.py` | 🟢 内部优化 |
| 22 | 两个 Validator 和两个 Service 大量重复代码 | `strategy_validator.py` / `event_analysis_validator.py` | 🟢 内部重构 |
| 23 | config_center.py 绕过 Service 层直接操作数据库 | `backend/api/config_center.py` | 🟢 内部重构，API 行为不变 |
| 24 | 缺少回测任务批量删除、策略版本历史查看接口 | API 层 | 🟢 新增接口 |

### 前端

| # | 问题 | 位置 | 兼容性 |
|---|------|------|--------|
| 25 | **单文件 2872 行** — 20+ 组件全在 `App.jsx` | `App.jsx` | 🟢 前端重构 |
| 26 | **轮询每 2.5s 触发全量重渲染风暴** — 数据未变化也会 setState | `App.jsx:2387-2393` | 🟢 前端优化 |
| 27 | 无 Error Boundary — 异常即白屏 | `App.jsx` | 🟢 前端新增 |
| 28 | 无代码编辑器 — 策略代码用纯 textarea | `App.jsx` | 🟢 前端新增 |
| 29 | 回测结果/事件分析列表无分页 | `App.jsx` | 🟢 前端新增 |
| 30 | 无数据导出（CSV/Excel） | `App.jsx` | 🟢 前端新增 |
| 31 | 删除操作用 `window.confirm` 而非自定义确认弹窗 | 多处 | 🟢 前端优化 |
| 32 | "数据管理"页面是空壳，按钮无实际功能 | `App.jsx:1925-1933` | 🟢 前端功能 |

---

## 🟡 低优先级（体验/规范）

| # | 模块 | 问题 | 兼容性 |
|---|------|------|--------|
| 33 | 前端 | 硬编码"最新交易日"为 `2026-04-29` | 🟢 |
| 34 | 前端 | 无 vite.config.js，构建不可控 | 🟢 |
| 35 | 前端 | 无 ESLint 配置 | 🟢 |
| 36 | 前端 | 无 TypeScript/PropTypes 类型检查 | 🟢 |
| 37 | 前端 | 格式化函数重复（api.js 和 App.jsx 各一套） | 🟢 |
| 38 | 后端 | DELETE 接口返回值不一致（204 vs `{ok: true}`） | 🔴 改返回格式会破坏外部调用 |
| 39 | 后端 | `PUT /api/settings` 应为 `PATCH` | 🔴 改 HTTP 方法会破坏外部调用 |
| 40 | 后端 | 全局 ThreadPoolExecutor 无优雅关闭 | 🟢 |
| 41 | 数据 | validate_data 校验范围不足（只校验 daily_bar） | 🟢 |
| 42 | 数据 | validate_range 用 weekday 而非交易日历判断交易日 | 🟢 |
| 43 | 数据 | AkShare 复权因子失败时静默填 1.0 | 🟢 |
| 44 | 数据 | 缺少统一数据更新入口脚本 | 🟢 |
| 45 | 数据 | 缺少数据清理/重置/完整性修复脚本 | 🟢 |
| 46 | 测试 | 整个数据层零测试覆盖（仅 12 个 API 测试用例） | 🟢 |
| 47 | 因子分析 | **无因子分析模块** — ts_rank 等核心算子未支持 | 🟢 |

---

## 统计

| 类别 | 高 | 中 | 低 | 合计 |
|------|---|---|---|------|
| 回测引擎 | 2 | 8 | 0 | 10 |
| 数据加载 | 1 | 3 | 0 | 4 |
| 后端 | 2 | 7 | 4 | 13 |
| 前端 | 0 | 8 | 5 | 13 |
| 数据/配置 | 0 | 2 | 7 | 9 |
| 因子分析 | 0 | 1 | 0 | 1 |
| **合计** | **5** | **29** | **16** | **50** |

> 注: #3（分红送股）因数据依赖已标记为阻塞，不计入统计。

---

## 详细说明

### #1 前复权/后复权基准依赖错误行序

`get_history()` 的 SQL 使用 `ORDER BY trade_date DESC LIMIT {window}`，进入 `_apply_adjustment()` 时 DataFrame 仍是倒序：`iloc[0]` 是最新日期，`iloc[-1]` 是最早日期。当前 qfq 使用 `iloc[-1]` 作为“最新价格基准”，hfq 使用 `iloc[0]` 作为“首日价格基准”，两者都和代码注释/复权语义相反。

**影响**: 所有使用 `adjust='qfq'` 或 `adjust='hfq'` 的策略回测结果都是错的。

**修复**: 优先在复权计算前统一 `sort_values('trade_date')`，让 `_apply_adjustment()` 只面对升序数据；或者分别将 qfq 基准改为当前倒序下的 `iloc[0]`、hfq 基准改为 `iloc[-1]`。第一种更不容易被未来改动再次打乱。

### #2 Position.market_value property bug

```python
@property
def market_value(self, current_price: float = 0):
    return self.volume * current_price  # current_price 默认 0
```

`@property` 不能接受参数，`pos.market_value` 直接访问时永远返回 0。不过当前账户估值主流程使用 `Account.get_total_value(prices)`，按外部价格字典计算持仓市值，因此这个问题更准确地说是“暴露了错误 API / 潜在误用”，不一定已经污染当前回测净值。

**修复**: 保留 `@property` 返回 `self.volume * self.avg_cost`（持仓成本），同时新增 `get_market_value(self, current_price)` 方法。

### #26 轮询重渲染风暴

每 2.5 秒调用 `refreshBacktests()` + `refreshEventAnalyses()`，内部多次 `setState`。即使数据完全相同，引用也会变化，触发 App 及所有子组件重渲染。

**修复**: 对轮询结果做 shallow compare，仅在数据真正变化时 setState。

### #15 get_history 缓存未使用

`_cache` dict 在 `__init__` 中定义，`warm_up_cache()` 会写入，但 `get_history()` **完全不检查 `_cache`**，每次都走 SQL。缓存形同虚设。

**修复**: `get_history()` 开头先检查 `_cache`，命中则直接返回。

### #3 分红送股（阻塞）

需要数据源（Tushare `dividend` 接口或其他），当前无此数据。待数据就绪后再实现。

### #5 Settings Schema 校验（破坏性）

当前 `PUT /api/settings` 接受任意 dict，并将 payload 的顶层 key 直接写入 settings 表。它不会直接覆盖 `.env` 或进程环境变量中的 `AI_API_KEY`，但可以写入任意配置命名空间，造成配置污染、前端展示异常，或影响未来从 settings 表读取配置的服务逻辑。

**建议**: 白名单方式只允许已知 key，未知 key 默认忽略并记录告警；对已知 key 内部再做 Pydantic 校验。若要保留扩展能力，可单独提供 `custom` 命名空间。

### #6 用户代码执行信任边界

策略加载器和事件分析加载器都会对用户提交的代码执行 `exec(compile(...))`。现有 AST Validator 能拦截常见危险 import/call，但它自己也说明这不是安全沙箱，只适合运行可信代码。

**影响**: 如果 HTTP API 暴露给不可信调用者，策略/事件分析代码执行应被视为远程代码执行风险；如果系统只在本机或可信内网使用，风险主要是误操作和数据/文件破坏。

**建议**: 文档/API 明确“只运行可信代码”；中期加强 AST 和运行时内置函数白名单；长期将策略和事件分析放入隔离进程/容器执行，限制文件系统、网络和超时资源。

### #38 DELETE 返回值（破坏性）

当前 strategies 和 event_definitions 返回 `{"ok": true, "message": "..."}`，backtests 和 event_analyses 返回 204 无 body。统一后外部调用者需要适配。

**建议**: 保持现状，或新增统一接口并保留旧接口。

### #39 PUT 改 PATCH（破坏性）

改 HTTP 方法后，所有调用 `PUT /api/settings` 的外部程序都需要改代码。

**建议**: 同时支持 PUT 和 PATCH，逐步迁移。
