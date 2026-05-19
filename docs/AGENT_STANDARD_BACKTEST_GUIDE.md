# Agent 标准化回测指南

日期: 2026-05-05

## 目标

本指南用于约束外部 Agent / WebAgent 如何在本项目中生成**前端可识别**的标准化回测结果。

满足本指南后，生成的结果会稳定出现在：

- 回测结果
- 报告中心

不会再出现：

- 后端有文件但前端详情空白
- 策略已跑完但没有标准任务记录
- 报告文件存在但前端无法关联

---

## 结论

Agent 发起回测时，**只能使用以下两种标准入口**：

1. `POST /api/backtests/quick`
2. [scripts/agent_entry/run_standard_backtest.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_backtest.py)

其中：

- 后端已经启动时，优先用 `POST /api/backtests/quick`
- 如果 Agent 不确定后端是否在线，或希望"一条命令自适应"，优先用 `scripts/agent_entry/run_standard_backtest.py`

---

## 中文命名规范（强制）

**所有 Agent 生成的策略，其名称、标签、描述必须使用中文。** 详见 [STRATEGY_BUILD_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/STRATEGY_BUILD_GUIDE.md)。

| 字段 | 要求 | 示例 |
|---|---|---|
| 策略名称 | 中文，且必须与 `super().__init__(...)` 一致 | `"小市值轮动策略"` |
| Tags | 中文标签，体现筛选特征 | `["小市值", "轮动"]` |
| 描述 | 中文，直接描述选股逻辑 | `"选取市值最小的10只股票"` |

强制补充规则：

- `super().__init__("...")` 必须写中文名称，前端最终展示名以这里为准。
- 不允许把类名、CamelCase 英文名、拼音 key、随机后缀当作前端展示名称。
- `description` 不能写成“AI生成的XXX策略”“根据提示生成的策略”“策略草稿”这类空泛句子，必须直接描述筛选条件、过滤条件和调仓方式。
- `tags` 不能只写 `AI生成`、`量化策略`、`AI`、`agent` 这类泛标签，至少要包含像 `小市值`、`盈利`、`低PE`、`月调仓` 这种策略特征标签。

---

## 推荐规则

### 规则 1

除前端人工点击外，**所有 Agent 自动回测一律优先走**：

```bash
.venv/bin/python scripts/agent_entry/run_standard_backtest.py ...
```

原因：

- 后端在线时，它会自动走标准 API
- 后端不在线时，它会自动走本地直跑模式
- 两种模式最终都会生成相同格式的标准回测结果

### 规则 2

不要直接做以下事情：

- 不要直接写 SQLite 的 `backtest_tasks`
- 不要手工写 JSON 报告文件
- 不要手工写 HTML 报告文件
- 不要只保存策略文件却不创建标准回测任务
- 不要自己发明另一套任务状态或报告目录

---

## 标准入口 A：API

### 接口

```text
POST /api/backtests/quick
```

### 最小请求体

```json
{
  "strategy_code": "from backtest.strategy import StrategyTemplate\nclass MyStrategy(StrategyTemplate):\n    def __init__(self):\n        super().__init__(\"我的策略\")\n    def init(self, context):\n        pass\n    def next(self, context):\n        pass",
  "start_date": "2026-04-01",
  "end_date": "2026-04-29"
}
```

### 标准调用顺序

1. `POST /api/backtests/quick`
2. 轮询 `GET /api/backtests/{task_id}`
3. 等待 `status=success`
4. 再读取 `GET /api/reports/{task_id}`

### 成功标志

满足以下条件才算真正成功：

- `backtest_tasks.status = success`
- `report_json_path` 不为空
- `report_html_path` 不为空
- `/api/reports/{task_id}` 能返回 `payload`

---

## 标准入口 B：脚本

### 脚本

[scripts/agent_entry/run_standard_backtest.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_backtest.py)

### 典型调用

```bash
.venv/bin/python scripts/agent_entry/run_standard_backtest.py \
  --strategy-file backend/storage/strategies/test_buy_and_hold.py \
  --start 2026-04-01 \
  --end 2026-04-29
```

标准脚本当前使用默认成交时序 `next_open`：策略 `next()` 在收盘后运行，生成的订单在下一交易日开盘成交。需要当日尾盘下单并按当日收盘成交时，使用 Python 直接创建 `BacktestEngine(..., execution_mode="same_close")`，或先扩展标准入口参数后再接入前端任务体系。

### 脚本双模式行为

#### 模式 1：后端在线

脚本会：

1. 检查 `/api/health`
2. 调用 `POST /api/backtests/quick`
3. 轮询回测任务
4. 输出标准报告路径和核心指标

#### 模式 2：后端不在线

脚本会：

1. 本地保存或更新策略
2. 本地创建标准 `backtest_tasks`
3. 直接运行 `BacktestEngine`
4. 生成标准 JSON / HTML 报告
5. 回填任务表中的：
   - `status`
   - `progress`
   - `report_json_path`
   - `report_html_path`
   - `total_return`
   - `max_drawdown`
   - `sharpe_ratio`

所以即使后端没启动，前端后续启动后也能识别这些结果。

---

## 前端识别依赖

前端“回测结果”和“报告中心”识别一条回测记录，依赖的是：

- SQLite 中存在标准 `backtest_tasks` 记录
- 任务状态为 `success`
- `report_json_path` 指向存在的标准 JSON 报告

因此，**是否被前端识别，不取决于你有没有跑过策略，而取决于你有没有产出标准任务记录和标准报告文件。**

---

## Agent 输出建议

Agent 执行完成后，建议至少输出这些字段：

```json
{
  "task_id": 123,
  "status": "success",
  "report_json_path": "...",
  "report_html_path": "...",
  "return_pct": 0.12,
  "max_drawdown": -0.08,
  "sharpe_ratio": 1.35
}
```

这样调用方更容易判断结果是否可用。

---

## 失败处理建议

如果回测失败，Agent 应优先返回：

- `task_id`
- `status`
- `error_message`

而不是只说“运行失败”。

推荐格式：

```json
{
  "task_id": 123,
  "status": "failed",
  "error_message": "策略类未定义 StrategyTemplate"
}
```

---

## 最佳实践

### 对 WebAgent

最推荐直接调用：

```bash
.venv/bin/python scripts/agent_entry/run_standard_backtest.py \
  --strategy-file <策略文件> \
  --start <开始日期> \
  --end <结束日期>
```

### 对本地应用或集成器

如果已知后端在线，最推荐直接调：

```text
POST /api/backtests/quick
```

---

## 一句话标准

**凡是希望前端稳定展示的 Agent 自动回测，必须走 `POST /api/backtests/quick` 或 `scripts/agent_entry/run_standard_backtest.py`，不得自行拼装报告和任务记录。**

---

## 文件存放规范

Agent 在项目中产生的文件必须按类型放到正确位置：

| 文件类型 | 存放路径 | 说明 |
|---|---|---|
| 策略代码 | `backend/storage/strategies/` | 通过 `POST /api/strategies` 或 `StrategyService` 写入，**可被后端导入和前端展示** |
| 自定义运行脚本 | `scripts/agent_simulation/` | 批量测试、数据处理、自定义分析等**非规范脚本**，不会上传到 GitHub |

**关键区分：**

- **策略代码**（`.py` 文件，继承 `StrategyTemplate`，实现 `init`/`next`）→ 写入后端，通过标准入口运行
- **运行脚本**（批量回测、数据清洗、因子筛选等辅助脚本）→ 写入 `scripts/agent_simulation/`

不要把策略代码写到 `scripts/agent_simulation/`，也不要在那里存放需要后端导入的规范文件。
