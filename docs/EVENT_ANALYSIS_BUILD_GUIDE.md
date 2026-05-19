# 事件分析代码构建指南

日期: 2026-05-05

## 目标

本指南帮助外部 Agent、WebAgent 或开发者，把自然语言需求稳定转换成**可保存、可校验、可运行**的事件分析代码。

如果你的目标是：

- 让 AI 根据一句中文描述生成事件分析
- 让生成结果可以直接保存到前端“事件分析”
- 让代码通过项目校验器
- 让后续分析任务能够正常运行

就按本指南来。

---

## 标准执行入口

如果目标不只是“生成代码”，还希望后续结果能被前端稳定识别，那么事件分析运行必须走标准入口：

1. `POST /api/event-analyses/quick`
2. [run_standard_event_analysis.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_event_analysis.py)

推荐优先走标准脚本，因为它支持双模式：

- 后端在线时：自动调用标准 API
- 后端未启动时：自动本地直跑并回填标准任务结果

不要直接写数据库，也不要手工拼接结果文件。

---

## 事件分析是什么

事件分析不是交易策略。

它不负责：

- 资金管理
- 持仓
- 下单
- 净值
- 连续调仓

它只负责：

- 定义某个事件在什么日期、什么股票上发生
- 返回事件样本
- 让平台统一计算未来收益

---

## 中文命名规范（强制）

**所有外部 Agent 生成的事件分析，其名称、标签、描述必须使用中文。**

| 字段 | 要求 | 示例 |
|---|---|---|
| 事件名称 | 中文，简洁明了 | `"跌停后收益分析"` |
| Tags | 中文标签数组 | `["跌停", "反弹", "事件分析"]` |
| 描述 | 中文，说明事件定义 | `"扫描收盘接近跌停价的股票样本，用于统计后续收益"` |
| event_name | 建议中文 | `"跌停样本"`、`"放量长上影"` |

### 正确示例

```python
class LimitDownFollowup(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("跌停后收益分析")  # ✅ 中文名称
```

```json
{
  "name": "跌停后收益分析",           // ✅ 中文
  "tags": ["跌停", "反弹", "事件分析"], // ✅ 中文标签
  "description": "扫描收盘接近跌停价的股票样本" // ✅ 中文描述
}
```

### 错误示例

```python
class LimitDownFollowup(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("LimitDownFollowup")  # ❌ 英文名称
```

```json
{
  "name": "Limit Down Followup",        // ❌ 英文
  "tags": ["limit_down", "rebound"]     // ❌ 英文标签
}
```

---

## 核心接口

事件分析代码必须继承：

```python
from event_analysis.template import EventAnalysisTemplate
```

并实现：

```python
class MyEventAnalysis(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("事件名称")

    def scan(self, context):
        ...
```

### `scan(context)` 的要求

- 必须返回 `pandas.DataFrame`
- 返回结果至少包含两列：
  - `ts_code`
  - `trade_date`

可选列：

- `event_name`
- `event_value`
- `group_key`
- `note`

---

## 可用上下文

`scan(context)` 中可以使用：

- `context["start_date"]`
- `context["end_date"]`
- `context["windows"]`
- `context["entry_rule"]`
- `context["dedup_rule"]`
- `context["filters"]`
- `context["data_loader"]`
- `context["conn"]`
- `context["get_history"]`
- `context["get_cross_section"]`
- `context["trade_date_index"]`

其中最常用的是：

- `context["conn"]`
- `context["start_date"]`
- `context["end_date"]`

---

## 可查询数据表

当前事件分析生成代码时，优先使用这些真实表：

- `daily_bar`
- `daily_basic`
- `stk_limit`
- `suspend_d`
- `instruments`

### 常见字段

#### `daily_bar`

- `ts_code`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `pre_close`
- `volume`
- `amount`

#### `daily_basic`

- `turnover_rate`
- `pe_ttm`
- `pb`
- `total_mv`
- `circ_mv`

#### `stk_limit`

- `up_limit`
- `down_limit`

#### `instruments`

- `ts_code`
- `symbol`
- `exchange`
- `list_date`
- `status`

---

## AI 自然语言应该怎么写

为了让 AI 更稳定地产出可保存代码，建议用户的自然语言描述至少包含：

1. 事件本身
2. 必要过滤条件
3. 是否需要附加标签

### 好的写法

- “判断当天是否出现收盘接近跌停的事件信号”
- “判断当天是否出现放量长上影”
- “判断当天是否出现连续两天下跌后第三天反包”
- “判断当天是否出现收盘接近涨停且换手率大于 10% 的信号”
- “判断当天是否创 60 日新高，并返回 event_value 记录突破幅度”

更推荐把自然语言只写成“事件是否发生”的定义。

像下面这些内容：

- 排除 ST
- 排除次新股
- 排除北交所
- 统计未来 5/10/15 日收益

通常不必写进事件代码提示词，因为平台会在运行配置和结果统计阶段统一处理。

### 不够好的写法

- “帮我分析一下股票”
- “搞一个事件”
- “做个差不多的分析”

---

## 生成原则

AI 生成事件分析代码时，应遵守：

- 优先用 DuckDB SQL 一次性扫描
- 不要逐股票循环扫全历史
- 不要自己计算未来 5/10/15 日收益
- 不要写账户、持仓、订单逻辑
- 日期用 `YYYY-MM-DD`
- 能返回 `event_name` 时尽量返回

---

## 事件代码应该怎么写

为了让代码更稳定地被保存、校验和运行，建议按下面的顺序构建：

1. 导入 `EventAnalysisTemplate`
2. 定义一个无参初始化类
3. 在 `__init__` 中设置清晰的中文事件名
4. 在 `scan(context)` 中读取 `start_date` / `end_date`
5. 优先用 SQL 一次性返回样本表
6. 只返回事件样本，不自己算未来收益

一个稳定的写法通常长这样：

```python
from __future__ import annotations

import pandas as pd

from event_analysis.template import EventAnalysisTemplate


class DemoEvent(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("示例事件分析")

    def scan(self, context):
        start = context["start_date"].strftime("%Y-%m-%d")
        end = context["end_date"].strftime("%Y-%m-%d")
        sql = f'''
            SELECT
                ts_code,
                trade_date,
                '示例样本' AS event_name
            FROM daily_bar
            WHERE trade_date BETWEEN '{start}' AND '{end}'
        '''
        return context["conn"].execute(sql).fetchdf()
```

这类代码最容易通过：

- 本地校验
- AI 生成后的二次修正
- 标准化事件分析脚本
- 前端保存和运行链路

---

## 示例 1：最小可保存模板

这是一个可以直接保存、并通过校验的最小示例：

```python
from __future__ import annotations

import pandas as pd

from event_analysis.template import EventAnalysisTemplate


class LimitDownFollowup(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("跌停后收益分析")

    def scan(self, context):
        start = context["start_date"].strftime("%Y-%m-%d")
        end = context["end_date"].strftime("%Y-%m-%d")
        sql = f'''
            SELECT d.ts_code, d.trade_date, '跌停样本' AS event_name
            FROM daily_bar d
            JOIN stk_limit l
              ON d.ts_code = l.ts_code AND d.trade_date = l.trade_date
            WHERE d.trade_date BETWEEN '{start}' AND '{end}'
              AND d.close <= l.down_limit * 1.002
        '''
        return context["conn"].execute(sql).fetchdf()
```

---

## 示例 2：带 event_value 的模板

```python
from __future__ import annotations

import pandas as pd

from event_analysis.template import EventAnalysisTemplate


class UpperShadowVolumeEvent(EventAnalysisTemplate):
    def __init__(self):
        super().__init__("放量长上影分析")

    def scan(self, context):
        start = context["start_date"].strftime("%Y-%m-%d")
        end = context["end_date"].strftime("%Y-%m-%d")
        sql = f'''
            SELECT
                d.ts_code,
                d.trade_date,
                '放量长上影' AS event_name,
                (d.high - d.close) / NULLIF(d.close, 0) AS event_value
            FROM daily_bar d
            JOIN daily_basic b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date BETWEEN '{start}' AND '{end}'
              AND d.close > 0
              AND d.high > d.close
              AND (d.high - d.close) / d.close >= 0.04
              AND b.turnover_rate >= 8
        '''
        return context["conn"].execute(sql).fetchdf()
```

---

## AI 保存时的返回格式

AI 返回结果时，必须是一个 JSON 对象，字段固定为：

- `name`
- `key`
- `description`
- `tags`
- `code`

### 标准示例

```json
{
  "name": "跌停后收益分析",
  "key": "limit_down_followup",
  "description": "扫描收盘接近跌停价的股票样本，用于统计后续收益。",
  "tags": ["跌停", "反弹", "事件分析"],
  "code": "from __future__ import annotations\n\nimport pandas as pd\n\nfrom event_analysis.template import EventAnalysisTemplate\n\n\nclass LimitDownFollowup(EventAnalysisTemplate):\n    def __init__(self):\n        super().__init__(\"跌停后收益分析\")\n\n    def scan(self, context):\n        start = context[\"start_date\"].strftime(\"%Y-%m-%d\")\n        end = context[\"end_date\"].strftime(\"%Y-%m-%d\")\n        sql = f'''\n            SELECT d.ts_code, d.trade_date, '跌停样本' AS event_name\n            FROM daily_bar d\n            JOIN stk_limit l\n              ON d.ts_code = l.ts_code AND d.trade_date = l.trade_date\n            WHERE d.trade_date BETWEEN '{start}' AND '{end}'\n              AND d.close <= l.down_limit * 1.002\n        '''\n        return context[\"conn\"].execute(sql).fetchdf()\n"
}
```

---

## 常见错误

### 错误 1：写成交易策略

不要生成：

- `next(context)` 逻辑
- `order_target_percent`
- 仓位管理

这是错误方向。

### 错误 2：自己算未来收益

不要在代码里写：

- `ret_5d`
- `ret_10d`
- `ret_15d`

平台会统一计算。

### 错误 3：返回格式不对

`scan(context)` 不能返回：

- list
- dict
- tuple

必须返回 `DataFrame`。

### 错误 4：缺少必要列

返回的 DataFrame 必须至少有：

- `ts_code`
- `trade_date`

---

## 推荐自然语言示例

以下提示词适合直接给 AI：

### 示例 A

“请生成一个事件分析代码：扫描收盘接近跌停价的股票样本，事件名为跌停样本，返回 ts_code、trade_date 和 event_name。”

### 示例 B

“请生成一个事件分析：分析放量长上影，要求当日换手率大于 8%，上影线占收盘价比例大于 4%，返回 event_value 记录上影强度。”

### 示例 C

“请生成一个事件分析：扫描创 60 日新高且成交额大于 2 亿的股票，返回 group_key='新高样本'。”

---

## 与 AI 生成接口的关系

事件分析 AI 生成入口为：

```text
POST /api/event-definitions/ai-fill
```

它的职责是：

- 根据自然语言生成事件分析代码草稿
- 返回可直接保存的标准 JSON

如果目标是让前端稳定识别后续分析结果，再结合：

- 事件定义保存
- 事件分析任务创建
- 前端运行事件分析

一起使用。

---

## 标准运行示例

### 通过 API 运行

```bash
curl -X POST http://127.0.0.1:8000/api/event-analyses/quick \
  -H "Content-Type: application/json" \
  -d '{
    "event_code": "from event_analysis.template import EventAnalysisTemplate\n...",
    "event_key": "limit_down_followup",
    "event_name": "跌停后收益分析",
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "windows": [5, 10, 15],
    "entry_rule": "next_open",
    "dedup_rule": "per_stock_gap_5",
    "universe": "all_a",
    "filters": ["exclude_st", "exclude_new_stock"]
  }'
```

### 通过本地脚本运行

```bash
.venv/bin/python scripts/agent_entry/run_standard_event_analysis.py \
  --event-file backend/storage/event_analyses/generated/limit_down_rebound_event.py \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 5,10,15 \
  --filter exclude_st \
  --filter exclude_new_stock
```

这条脚本会自动判断：

- 后端在线：走 API
- 后端离线：本地直跑

最终都会产出前端可识别的标准结果。
