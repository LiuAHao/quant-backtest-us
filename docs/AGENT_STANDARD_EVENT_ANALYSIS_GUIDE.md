# Agent 标准化事件分析指南

日期: 2026-05-05

## 目标

本指南用于约束外部 Agent、WebAgent 或本地脚本，如何生成**前端可识别**的标准化事件分析结果。

如果希望事件分析结果能被前端“事件分析”页面稳定展示，就按本指南执行。

---

## 标准入口

Agent 自动运行事件分析时，只允许使用两种标准入口：

1. `POST /api/event-analyses/quick`
2. [run_standard_event_analysis.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_event_analysis.py)

推荐默认走脚本：

- 后端在线时：脚本自动调用 `POST /api/event-analyses/quick`
- 后端未启动时：脚本自动本地直跑，并回填标准任务结果

---

## 中文命名规范（强制）

**所有 Agent 生成的事件分析，其名称、标签、描述必须使用中文。** 详见 [EVENT_ANALYSIS_BUILD_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/EVENT_ANALYSIS_BUILD_GUIDE.md)。

| 字段 | 要求 | 示例 |
|---|---|---|
| 事件名称 | 中文 | `"跌停后收益分析"` |
| Tags | 中文标签 | `["跌停", "反弹"]` |
| 描述 | 中文 | `"扫描收盘接近跌停价的股票样本"` |
| event_name | 建议中文 | `"跌停样本"` |

---

## 严禁绕过标准链路

不要这样做：

- 直接写 `event_analysis_tasks`
- 手工拼接结果 JSON 文件
- 只生成事件定义文件但不创建标准任务
- 只在终端打印统计结果，不回填任务记录

这些做法会导致：

- 前端列表为空
- 前端有任务但详情空白
- 本地算出了结果，但页面无法加载

---

## 前端识别成功的条件

一份事件分析结果要被前端正常识别，至少要满足：

- 存在标准 `event_analysis_tasks` 记录
- `status = success`
- `result_json_path` 指向有效结果文件
- `summary_json` 已写入
- `GET /api/event-analyses/{task_id}/result` 能返回 `payload`

---

## 推荐执行方式

### 方式 A：直接走 API

适用于后端已启动的场景。

步骤：

1. 调 `POST /api/event-analyses/quick`
2. 轮询 `GET /api/event-analyses/{task_id}`
3. 成功后再读 `GET /api/event-analyses/{task_id}/result`

### 方式 B：走标准脚本

适用于外部 Agent、本地自动化任务、后端不一定在线的场景。

```bash
.venv/bin/python scripts/agent_entry/run_standard_event_analysis.py \
  --event-file backend/storage/event_analyses/generated/limit_down_rebound_event.py \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 5,10,15 \
  --filter exclude_st \
  --filter exclude_new_stock
```

脚本行为：

- 后端在线时：走标准 API
- 后端离线时：本地运行 `EventAnalysisEngine`
- 两种模式都会写入标准任务结果
- 成功后输出 `task_id`、`result_json_path`、`sample_count` 和 `summary`

---

## 标准请求示例

### `POST /api/event-analyses/quick`

```json
{
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
}
```

---

## 输出约定

Agent 在执行标准化事件分析后，推荐至少输出这些字段：

- `mode`
- `task_id`
- `status`
- `result_json_path`
- `sample_count`
- `summary`

其中 `summary` 由平台统一构建，便于前端和脚本共享。

---

## 推荐工作流

1. 先根据自然语言生成事件分析代码
2. 保存为单文件事件定义
3. 通过标准入口创建分析任务
4. 等待任务成功
5. 再从标准结果接口或结果文件中读取摘要

---

## 相关文档

- [API_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/API_GUIDE.md)
- [EVENT_ANALYSIS_BUILD_GUIDE.md](/Users/a0000/Desktop/项目文件/quant-backtest/docs/EVENT_ANALYSIS_BUILD_GUIDE.md)
- [run_standard_event_analysis.py](/Users/a0000/Desktop/项目文件/quant-backtest/scripts/agent_entry/run_standard_event_analysis.py)

---

## 文件存放规范

Agent 在项目中产生的文件必须按类型放到正确位置：

| 文件类型 | 存放路径 | 说明 |
|---|---|---|
| 事件分析代码 | `backend/storage/event_analyses/generated/` | 通过 `POST /api/event-analyses` 或 `EventDefinitionService` 写入，**可被后端导入和前端展示** |
| 自定义运行脚本 | `scripts/agent_simulation/` | 批量扫描、数据处理、自定义分析等**非规范脚本**，不会上传到 GitHub |

**关键区分：**

- **事件分析代码**（`.py` 文件，继承 `EventAnalysisTemplate`，实现 `scan`）→ 写入后端，通过标准入口运行
- **运行脚本**（批量事件扫描、数据清洗、自定义统计等辅助脚本）→ 写入 `scripts/agent_simulation/`

不要把事件分析代码写到 `scripts/agent_simulation/`，也不要在那里存放需要后端导入的规范文件。
