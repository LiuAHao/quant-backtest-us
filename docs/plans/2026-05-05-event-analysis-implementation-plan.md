# 事件分析模块实施方案

日期: 2026-05-05

## 目标

在现有本地量化回测系统中新增一个独立的“事件分析”模块，用于对全市场历史数据进行大范围条件扫描，并统计事件发生后的未来收益表现。

该模块不模拟账户资金、不维护连续持仓、不生成净值曲线，而是专注于：

- 定义某个事件何时发生
- 在全市场扫描事件样本
- 统一计算未来多个观察窗口的收益
- 输出样本明细与聚合统计结果

---

## 命名与定位

### 中文名称

`事件分析`

### 英文内部名

`event_analysis`

### 与现有模块的边界

- `回测 Backtest`：模拟账户、订单、持仓、净值、回撤
- `事件分析 Event Analysis`：扫描样本事件，统计未来收益，不做交易模拟
- `因子分析 Factor Analysis`：先不纳入本期范围，后续如需做 IC、分层收益、因子检验时再独立设计

### 本期明确不做

- 资金管理
- 连续调仓
- 仓位模拟
- 订单撮合
- 净值曲线
- 组合级收益回测
- 参数寻优
- 图形化 DSL 编排

---

## 产品形态

事件分析模块建议在前端作为一个独立菜单，与“策略”“回测”并列。

页面建议分为四个区域：

1. 事件定义
2. 分析配置
3. 结果展示
4. 样本明细

其中“事件定义”应以自定义代码为主入口，参数面板只作为快捷辅助，不应成为唯一入口。

### 核心设计原则

- 面板是快捷方式，自定义代码才是完整能力
- AI 生成用于提升起步效率，但最终产物仍然是用户可编辑、可保存、可复用的代码
- 事件定义与收益统计分离：用户负责定义样本，平台负责统一计算未来收益

---

## 核心功能范围

### 第一版建议支持

- 自定义事件代码
- AI 生成事件代码
- 代码校验与安全约束
- 异步事件分析任务
- 未来收益窗口统计：`1/3/5/10/15/20`
- 样本明细表
- 聚合统计摘要
- 基础过滤：时间范围、股票范围、去重规则
- 结果导出

### 第一版建议暂缓

- 多事件对比分析
- 参数批量遍历
- 自动寻优
- 事件链分析
- 因子 IC / RankIC
- 组合化事件回测
- 分钟级 / Tick 级事件分析

---

## 技术架构

建议复用当前系统“代码管理 + AI 生成 + 校验 + 异步任务”的产品模式，但为事件分析建立独立链路。

### 模块层级

- 事件定义管理
- AI 生成事件代码
- 事件代码校验
- 事件分析任务创建
- 异步扫描执行
- 结果查询与展示

### 推荐目录结构

```text
backend/api/event_analyses.py
backend/api/event_definitions.py

backend/services/event_analysis_service.py
backend/services/event_definition_service.py
backend/services/event_analysis_validator.py
backend/services/ai_event_analysis_prompt.py

event_analysis/__init__.py
event_analysis/template.py
event_analysis/engine.py
event_analysis/result_builder.py
event_analysis/loader.py

backend/storage/event_analyses/README.md
backend/storage/event_analyses/generated/
```

### 设计原则

- 与 `backtest/engine.py` 分离，不复用交易模拟语义
- 与 `StrategyTemplate` 分离，避免误导用户写成“伪回测策略”
- 尽量复用 `DataLoader`、DuckDB 查询能力和现有异步任务模式

---

## 数据库设计建议

建议新增三张核心表，与当前策略/回测结构平行：

### 1. `event_definitions`

保存事件定义元信息：

- `id`
- `key`
- `name`
- `description`
- `source`
- `tags_json`
- `status`
- `current_version_id`
- `created_at`
- `updated_at`

### 2. `event_definition_versions`

保存事件代码版本：

- `id`
- `event_definition_id`
- `version`
- `code`
- `code_hash`
- `file_path`
- `validation_status`
- `validation_message`
- `dependencies_json`
- `created_at`

### 3. `event_analysis_tasks`

保存事件分析任务：

- `id`
- `event_definition_id`
- `event_definition_version_id`
- `status`
- `start_date`
- `end_date`
- `windows_json`
- `entry_rule`
- `dedup_rule`
- `universe`
- `progress`
- `sample_count`
- `result_json_path`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

可选：

- `summary_json`

如果后续前端列表页需要更快展示摘要数据，可再考虑单独落库存储。

---

## 事件定义代码接口

建议新增独立模板类：

```python
from event_analysis.template import EventAnalysisTemplate


class MyEventAnalysis(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("跌停后收益分析")

    def scan(self, context):
        """
        返回事件样本 DataFrame
        必填列：
        - ts_code
        - trade_date

        可选列：
        - event_name
        - event_value
        - group_key
        - note
        """
        pass
```

### 设计说明

- 用户只负责定义“哪些股票、在哪天触发了事件”
- 平台统一补充未来收益列
- 平台统一生成统计结果
- 用户无需重复实现收益计算逻辑

### `scan(context)` 返回值约束

必填列：

- `ts_code`
- `trade_date`

可选列：

- `event_name`
- `event_value`
- `group_key`
- `note`

### 推荐上下文字段

- `context["data_loader"]`
- `context["conn"]`
- `context["start_date"]`
- `context["end_date"]`
- `context["windows"]`
- `context["get_history"]`
- `context["get_cross_section"]`
- `context["trade_date_index"]`
- `context["get_trade_dates"]`

---

## 执行引擎设计

建议新增独立引擎：

- [event_analysis/engine.py](/Users/a0000/Desktop/项目文件/quant-backtest/event_analysis/engine.py)

### 引擎职责

1. 加载事件定义代码
2. 执行 `scan(context)` 获取事件样本
3. 对样本统一计算未来收益
4. 构建摘要统计与明细结果
5. 写出结果 JSON

### 引擎明确不负责

- 订单撮合
- 账户现金
- 持仓状态
- 连续调仓
- 净值生成

---

## 收益计算标准

第一版建议平台统一提供固定收益口径，避免不同事件脚本各自定义，导致结果不可横向比较。

### 建议支持的观察窗口

- `1`
- `3`
- `5`
- `10`
- `15`
- `20`

### 建议支持的买入口径

- `event_close`
- `next_open`
- `next_close`

### 建议支持的卖出口径

- `window_close`

### 默认口径建议

- 买入口径：`next_open`
- 价格口径：前复权价
- 收益公式：`future_price / entry_price - 1`

---

## 去重与样本范围

第一版建议将这部分作为标准配置，而不是让每份代码重复处理。

### `dedup_rule`

- `none`
- `per_stock_per_day`
- `per_stock_gap_5`
- `per_stock_gap_10`

### `universe`

- `all_a`
- `exclude_beijing`
- `main_board_only`

后续可扩展：

- `exclude_st`
- `exclude_kcb_cyb`
- `hs300_only`

---

## 结果结构设计

建议统一输出三层结构。

### 1. 任务层

适合任务列表页：

- 状态
- 创建时间
- 运行进度
- 错误信息
- 样本数量

### 2. 摘要层

适合结果卡片和概览页：

- 样本数
- 覆盖股票数
- 覆盖交易日数
- 每个窗口的平均收益
- 每个窗口的中位数收益
- 每个窗口的胜率
- 每个窗口的 P10 / P25 / P75 / P90
- 最大收益 / 最大亏损

### 3. 明细层

适合表格展示和导出：

- `ts_code`
- `trade_date`
- `event_name`
- `group_key`
- `event_value`
- `entry_date`
- `entry_price`
- `ret_1d`
- `ret_3d`
- `ret_5d`
- `ret_10d`
- `ret_15d`
- `ret_20d`

---

## 后端 API 设计

建议保持与现有 `strategies` 和 `backtests` 相同的风格。

### 事件定义管理

- `GET /api/event-definitions`
- `POST /api/event-definitions`
- `GET /api/event-definitions/{id}`
- `PUT /api/event-definitions/{id}`
- `POST /api/event-definitions/{id}/enable`
- `POST /api/event-definitions/{id}/disable`
- `POST /api/event-definitions/validate`
- `POST /api/event-definitions/ai-fill`

### 事件分析任务

- `GET /api/event-analyses`
- `POST /api/event-analyses`
- `GET /api/event-analyses/{task_id}`
- `POST /api/event-analyses/{task_id}/cancel`
- `DELETE /api/event-analyses/{task_id}`

### 一键运行接口

- `POST /api/event-analyses/quick`

请求体示例：

```json
{
  "event_code": "...",
  "event_key": "limit_down_rebound",
  "event_name": "跌停后反弹分析",
  "start_date": "2020-01-01",
  "end_date": "2025-05-01",
  "windows": [5, 10, 15],
  "entry_rule": "next_open",
  "dedup_rule": "per_stock_gap_5",
  "universe": "all_a"
}
```

---

## Pydantic Schema 设计建议

建议在 [backend/schemas.py](/Users/a0000/Desktop/项目文件/quant-backtest/backend/schemas.py) 中增加事件分析相关模型。

### 事件定义

```python
EventSource = Literal["manual", "ai", "builtin", "手动导入", "AI生成", "内置"]
EventStatus = Literal["enabled", "disabled", "draft", "archived"]


class EventDefinitionCreate(BaseModel):
    key: str
    name: str
    description: str = ""
    source: EventSource = "manual"
    tags: list[str] = Field(default_factory=list)
    code: str
    status: EventStatus = "enabled"
```

### 事件任务

```python
class EventAnalysisCreate(BaseModel):
    event_definition_id: int
    start_date: str
    end_date: str
    windows: list[int] = Field(default_factory=lambda: [5, 10, 15])
    entry_rule: str = "next_open"
    dedup_rule: str = "none"
    universe: str = "all_a"
```

---

## 校验器设计

建议新增：

- [backend/services/event_analysis_validator.py](/Users/a0000/Desktop/项目文件/quant-backtest/backend/services/event_analysis_validator.py)

### 校验职责

- 校验是否继承 `EventAnalysisTemplate`
- 校验是否只定义一个事件分析类
- 校验是否实现 `scan(self, context)`
- 校验返回样本格式的基本约束
- 禁止危险导入
- 禁止文件读写
- 禁止网络请求
- 限制代码依赖范围

### 重点说明

由于本模块明确支持“自定义代码 + AI 生成”，因此 validator 是安全边界和运行稳定性的核心组成部分，优先级很高。

---

## AI 生成方案

建议复用当前策略系统 `ai-fill` 的产品形式，但使用单独的事件分析提示词和校验器。

新增：

- [backend/services/ai_event_analysis_prompt.py](/Users/a0000/Desktop/项目文件/quant-backtest/backend/services/ai_event_analysis_prompt.py)

### AI 生成目标

将自然语言描述转换为事件定义代码，而不是交易策略代码。

### 提示词应强调

- 必须继承 `EventAnalysisTemplate`
- 只实现 `scan(context)`
- 返回 DataFrame，且必须包含 `ts_code` 和 `trade_date`
- 优先使用 DuckDB SQL 和横截面查询
- 不要自己计算未来收益
- 不要写账户、订单、仓位逻辑
- 日期必须使用 `YYYY-MM-DD`
- 允许查询 `daily_bar`、`daily_basic`、`stk_limit`、`suspend_d`、`instruments`

### 典型用户输入示例

- “分析跌停后未来 5/10/15 天收益”
- “分析放量长上影后表现，排除 ST 和北交所”
- “分析连续两天缩量下跌后第三天的收益”

---

## 前端页面建议

建议将“事件分析”做成独立导航项。

### 页面结构

1. 事件定义区
2. 分析配置区
3. 结果区
4. 样本明细区

### 事件定义区

- 代码编辑器
- AI 生成按钮
- 代码校验按钮
- 保存按钮

### 分析配置区

- 时间范围
- 收益窗口
- 买入规则
- 去重规则
- 股票范围

### 结果区

- 摘要卡片
- 收益统计表
- 收益分布图
- 年度分布图

### 样本明细区

- 表格查看
- 简单筛选
- 导出 CSV

---

## 执行流程

建议整体链路如下：

1. 用户新建事件定义
2. 用户手写代码或通过 AI 生成代码草稿
3. 后端执行代码校验
4. 保存至 `event_definitions` 和 `event_definition_versions`
5. 创建 `event_analysis_tasks`
6. 后台线程执行 `event_analysis.engine`
7. 写出结果 JSON
8. 前端读取任务结果并展示摘要和明细

---

## 分阶段开发顺序

为降低复杂度，建议按以下顺序实施。

### 阶段 1：执行内核打通

- 新建 `EventAnalysisTemplate`
- 实现 `event_analysis/engine.py`
- 实现基础收益统计逻辑
- 实现 `quick` 接口

### 阶段 2：代码管理与校验

- 新建 `event_definitions`
- 新建 `event_definition_versions`
- 实现 `EventDefinitionService`
- 实现 `EventAnalysisValidator`

### 阶段 3：异步任务与结果文件

- 新建 `event_analysis_tasks`
- 实现异步任务执行
- 输出结果 JSON
- 接入任务状态查询

### 阶段 4：前端接入

- 事件分析页面
- 代码编辑器
- 配置面板
- 结果展示

### 阶段 5：AI 生成接入

- 新建 AI prompt
- 接入 `ai-fill`
- 增加报错反馈后的自动修正能力

---

## 第一版推荐内置示例

建议把“跌停后收益分析”作为第一个内置样例。

### 示例逻辑

- 当日收盘接近跌停价
- 排除 ST
- 排除北交所
- 排除停牌
- 统计未来 `5/10/15` 日收益

### 选择原因

- 贴近当前最明确的业务需求
- 容易验证样本逻辑是否正确
- 便于测试整条链路：事件定义、扫描、收益统计、结果展示

---

## 结论

事件分析模块应当被设计为一个独立于传统回测的分析系统，而不是回测引擎的附属模式。

本期实施重点应放在：

- 独立模板接口
- 自定义代码能力
- 安全校验
- 异步分析任务
- 标准化收益统计

在此基础上，再逐步接入前端编辑体验和 AI 生成能力，能够兼顾灵活性、可维护性和后续扩展空间。
