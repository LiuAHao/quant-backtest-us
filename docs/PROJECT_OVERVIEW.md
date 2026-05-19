# Project Overview

这份文档给开发者和外部 agent 快速补齐项目细节。README 只保留项目展示和最短启动路径，具体约束放在这里。

## 项目定位

Quant Backtest 是面向本地部署的 A 股量化研究工具，适合：

- 想把量化研究环境完全放在本地的人。
- 想快速验证策略想法、生成回测报告的人。
- 想把策略研究、事件研究、因子研究、报告查看和前端面板放在同一个项目里的人。
- 需要让外部 agent 自动创建策略、运行回测、生成标准结果的人。

默认场景是“单机、本地、自用”，不是多租户 SaaS。

## Architecture

```text
quant-backtest/
├── backend/        # FastAPI API、服务层、SQLite 元数据
├── backtest/       # 回测核心引擎
├── event_analysis/ # 事件分析引擎
├── factor_analysis/# 因子分析基础函数
├── frontend/       # React + Vite 前端
├── scripts/        # 数据下载、校验、标准运行脚本
├── tests/          # 单元测试
├── docs/           # API、策略、事件分析、agent 文档
├── data/           # 本地市场数据，不进 git
└── config.py       # 全局配置
```

关键数据系统：

- **SQLite metadata**：`backend/storage/quant_backtest.db`，保存策略、版本、任务、设置和模板。
- **DuckDB + parquet**：读取 `data/` 下的本地行情数据。
- **Generated code**：策略、事件分析和因子分析代码由服务层生成并同步，不应手工编辑生成目录。

## Core Features

- 策略管理：创建、校验、版本化保存 Python 策略。
- 本地回测：基于本地行情数据运行异步回测任务。
- 事件分析：定义事件信号，批量统计后续窗口收益。
- 因子分析：定义单因子截面取值，统一计算 IC、RankIC、分组收益、多空收益和覆盖率。
- 报告查看：生成 JSON / HTML 报告并在前端统一查看。
- 配置中心：管理回测预设、Agent 配置和系统信息。
- 数据校验：基于交易日历校验本地 parquet 数据完整性。
- AI 辅助：可选使用兼容 OpenAI 的接口辅助生成策略、事件分析或因子分析草稿。

## Environment

建议环境：

- Python 3.10+
- Node.js 18+

初始化：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
cp .env.example .env
```

常用环境变量：

- `TUSHARE_TOKEN`：下载数据时需要。
- `TUSHARE_BASE_URL`：可选，自建 Tushare 代理时填写。
- `AI_API_KEY` / `OPENAI_API_KEY`：使用 AI 生成功能时需要。
- `AI_BASE_URL`、`AI_MODEL`：切换模型服务时使用。

## Common Commands

启动后端：

```bash
python3 -m uvicorn backend.main:app --reload \
  --reload-exclude 'backend/storage/strategies/*' \
  --reload-exclude 'backend/storage/event_analyses/generated/*' \
  --reload-exclude 'backend/storage/factor_analyses/generated/*' \
  --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

启动前端：

```bash
cd frontend
npm run dev
```

测试与构建：

```bash
python3 -m unittest discover -s tests -v
cd frontend && npm run build
```

数据下载与校验：

```bash
python3 scripts/data_download/download_by_date.py --start 20140102 --end 20260429
python3 scripts/data_download/update_extra_data.py --start 20140102 --end 20260429 --tasks daily_basic stk_limit suspend_d
python3 scripts/data_utils/validate_data.py
python3 scripts/data_utils/data_admin.py status
python3 scripts/data_utils/data_admin.py validate --days 10 --json
```

## Agent Entry Points

外部 agent 生成结果时必须走标准入口，否则前端可能无法识别任务和报告。

标准回测：

```bash
python3 scripts/agent_entry/run_standard_backtest.py \
  --strategy-file <path> \
  --start 2026-01-01 \
  --end 2026-04-29
```

标准事件分析：

```bash
python3 scripts/agent_entry/run_standard_event_analysis.py \
  --event-file <path> \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 5,10,15
```

标准因子分析：

```bash
python3 scripts/agent_entry/run_standard_factor_analysis.py \
  --factor-file <path> \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --windows 1,5,10,20
```

也可以使用 API：

- `POST /api/backtests/quick`
- `POST /api/event-analyses/quick`
- `POST /api/factor-analyses/quick`

标准链路会：

1. 创建或复用合法定义。
2. 创建标准任务记录。
3. 执行引擎。
4. 生成标准 JSON / HTML、事件分析结果 JSON 或因子分析结果 JSON。
5. 回填任务表。
6. 让前端通过 API 正常展示。

## Strategy Rules

策略代码必须：

- 继承 `StrategyTemplate` from `backtest.strategy`。
- 实现 `init(self, context)` 和 `next(self, context)`。
- 不直接写文件、不联网、不执行系统命令。

禁止导入：

```text
os, subprocess, socket, shutil, requests, httpx, urllib, ftplib, pathlib
```

禁止调用：

```text
eval, exec, compile, open, __import__
```

策略上下文常用字段：

- `context["market_data"]`：当前交易日横截面数据，已包含行情和 `daily_basic` 常用字段。
- `context["data_loader"]`：数据加载器。
- `context["get_history"](ts_code, end_date, window, adjust)`：个股历史行情。
- `context["order"]` / `context["order_target_percent"]`：下单接口。
- `context["get_price_limit_status"](bar)`、`context["is_limit_up"](bar)`、`context["is_limit_down"](bar)`：涨跌停快速判断接口。若截面数据中包含 `up_limit/down_limit`，会优先使用精确涨跌停价；否则按板块规则和 `pre_close` 回退估算。

默认成交时序是 `execution_mode="next_open"`：`next()` 收盘后生成订单，下一交易日开盘撮合。如需模拟当日尾盘下单、当日收盘成交，直接使用 `BacktestEngine(..., execution_mode="same_close")`。

完整说明见 [STRATEGY_BUILD_GUIDE.md](STRATEGY_BUILD_GUIDE.md)。

## Event Analysis Rules

事件分析代码必须：

- 继承 `EventAnalysisTemplate` from `event_analysis.template`。
- 实现 `scan(self, context)`。
- 返回 DataFrame，至少包含 `ts_code` 和 `trade_date`。
- 只负责扫描事件，不计算未来收益，不写交易或组合逻辑。

平台会统一计算窗口收益。完整说明见 [EVENT_ANALYSIS_BUILD_GUIDE.md](EVENT_ANALYSIS_BUILD_GUIDE.md)。

## Factor Analysis Rules

因子分析代码必须：

- 继承 `FactorAnalysisTemplate` from `factor_analysis.template`。
- 实现 `compute(self, context)`。
- 返回 DataFrame，至少包含 `ts_code`、`trade_date`、`factor_value`。
- 只负责计算当日截面因子值，不计算未来收益，不写交易、组合或调仓逻辑。

平台会统一处理股票池过滤、未来收益、IC、RankIC、分组收益、多空收益和覆盖率。完整说明见 [FACTOR_ANALYSIS_BUILD_GUIDE.md](FACTOR_ANALYSIS_BUILD_GUIDE.md)。

## Data Access Pattern

策略中的常见数据访问：

- `context["market_data"]`：当前交易日横截面。
- `context["data_loader"].conn`：DuckDB connection。
- `context["get_history"](...)`：个股历史窗口。

DuckDB 查询日期统一使用 `YYYY-MM-DD` 字符串。

本地数据目录 `data/` 不进 git。公开仓库只保留目录结构和文档，不提交真实行情数据。

## Safety Boundary

- 本项目默认运行在本机，不应直接暴露到公网。
- 策略、事件分析和因子分析代码最终会在本地 Python 进程内执行，只运行你信任的代码。
- 静态 validator 是基础防线，不是完整沙箱。
- `.env`、`data/`、本地 SQLite 数据库、运行报告和日志不应提交到公开仓库。

## Documentation Map

- [API_GUIDE.md](API_GUIDE.md)：完整 API、数据模型和 Agent 集成说明。
- [STRATEGY_BUILD_GUIDE.md](STRATEGY_BUILD_GUIDE.md)：策略开发约束和 context 说明。
- [EVENT_ANALYSIS_BUILD_GUIDE.md](EVENT_ANALYSIS_BUILD_GUIDE.md)：事件分析开发约束。
- [FACTOR_ANALYSIS_BUILD_GUIDE.md](FACTOR_ANALYSIS_BUILD_GUIDE.md)：因子分析开发约束。
- [AGENT_STANDARD_BACKTEST_GUIDE.md](AGENT_STANDARD_BACKTEST_GUIDE.md)：Agent 标准回测入口。
- [AGENT_STANDARD_EVENT_ANALYSIS_GUIDE.md](AGENT_STANDARD_EVENT_ANALYSIS_GUIDE.md)：Agent 标准事件分析入口。
- [AGENT_STANDARD_FACTOR_ANALYSIS_GUIDE.md](AGENT_STANDARD_FACTOR_ANALYSIS_GUIDE.md)：Agent 标准因子分析入口。
- [quant-data-guide.md](quant-data-guide.md)：本地数据结构和数据源说明。
