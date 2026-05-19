# 测试模块 Review 与优化实施方案

## 1. 背景与目标

当前项目测试已经覆盖了回测核心、DataLoader、SQL 安全、策略/事件/因子校验、后端 API、数据校验、指标计算和 ML 研究模块。全量测试目前可通过，但测试结构开始出现维护压力：

- `tests/test_backend_api.py` 已接近 1000 行，承担过多 API 模块职责。
- 多个测试文件重复创建 parquet 夹具、临时 SQLite、patch 配置目录。
- 因子分析模块刚扩展完成，需要把真实失败场景沉淀成稳定回归测试。
- ML 测试存在未固定随机数。
- 测试分层命令和覆盖矩阵尚未文档化，外部 agent 不容易判断应该跑哪组测试。

本方案目标是把测试体系优化为：

1. 夹具复用，减少复制粘贴。
2. API 测试按模块拆分，失败定位更清晰。
3. 因子分析关键路径有稳定回归覆盖。
4. 测试结果确定、可重复、适合 agent 执行。
5. 建立测试分层命令和覆盖矩阵，方便后续开发按风险选择测试范围。

## 2. 当前测试模块现状

### 2.1 测试文件分布

当前 `tests/` 下主要文件：

| 文件 | 当前职责 | 行数级别 | 主要问题 |
| --- | --- | ---: | --- |
| `test_backend_api.py` | 策略、回测、配置、报告、事件分析 API | 约 989 | 职责过多，继续扩展会难维护 |
| `test_data_loader.py` | DataLoader 数据读取、复权、缓存 | 约 255 | 夹具与 security/engine_metrics 重复 |
| `test_data_loader_security.py` | DataLoader SQL 注入与参数校验 | 约 407 | patch 配置样板较多 |
| `test_engine_metrics.py` | 回测指标、基准、执行模式、指数读取 | 约 451 | DataLoader 夹具重复 |
| `test_factor_analysis.py` | 因子指标纯函数 | 约 220 | 已补混合日期类型回归 |
| `test_factor_analysis_platform.py` | 因子定义/API/任务/结果链路 | 约 367 | 与 backend API 测试样板相似 |
| `test_factor_analysis_prompt.py` | AI 因子提示词和 JSON 解析 | 约 35 | 覆盖合理，可保留轻量 |
| `test_broker.py` | broker 手续费、T+1、涨跌停、账户市值 | 约 162 | 状态独立，问题较少 |
| `test_code_validator.py` | 策略/事件 validator 安全规则 | 约 63 | 可后续扩展 factor validator 专项 |
| `test_loader_validation.py` | 策略/事件 loader 安全加载 | 约 218 | 可后续补 factor loader |
| `test_data_validation.py` | 数据质量校验 | 约 228 | 独立性较好 |
| `test_indicators.py` | 技术指标 | 约 130 | 独立性较好 |
| `test_ml_*.py` | ML 特征、标签、pipeline、splitter | 约 180 | `test_ml_features.py` 有未固定随机数 |

### 2.2 已有优点

- 核心数据层和安全层有较多测试，尤其是 DataLoader SQL 注入防护。
- 回测指标和 broker 规则有明确的边界测试。
- 事件/因子平台链路已经能覆盖定义创建、任务创建、失败态和结果读取。
- 因子指标纯函数有 IC、RankIC、分组收益、覆盖率、摘要序列测试。
- 全量测试可通过，当前具备重构测试结构的基础。

### 2.3 主要风险

#### 风险 1：夹具重复导致未来修一处漏多处

重复模式集中在：

- 创建 `.test-tmp/<test_name>`。
- `shutil.rmtree()` 清理。
- 写 `calendar/daily_bar/adj_factor/daily_basic/instruments/index_daily` parquet。
- patch `config.settings.*_DIR`。
- 初始化 `DataLoader` 或 SQLite。

涉及文件：

- `tests/test_data_loader.py`
- `tests/test_data_loader_security.py`
- `tests/test_engine_metrics.py`
- `tests/test_backend_api.py`
- `tests/test_factor_analysis_platform.py`

#### 风险 2：API 测试文件过大

`test_backend_api.py` 已混合：

- 策略校验与创建。
- AI fill mock。
- 回测任务创建/分页/批删/取消。
- 报告下载和日志注入。
- 回测模板。
- 配置中心。
- 事件分析分页/批删。

继续把因子 API、报告中心、更多生命周期测试放进去，会造成：

- 单个文件加载和定位成本高。
- helper 只能写在大文件内部，其他模块无法复用。
- 外部 agent 难以只运行相关 API 测试。

#### 风险 3：部分测试不够确定

`tests/test_ml_features.py` 使用：

```python
np.random.randn(window)
np.random.randint(1e5, 1e7, window)
```

当前只断言 shape 和列存在，因此短期不一定失败，但它仍然会让测试数据不可复现，不利于后续添加数值断言。

#### 风险 4：因子模块真实场景仍需增强

刚发生过真实任务失败：

```text
You are trying to merge on str and datetime64[us] columns for key 'trade_date'
```

这类问题属于真实数据类型和平台规范之间的缝隙，需要沉淀为：

- 指标纯函数回归。
- 平台任务链路回归。
- 报告下载和失败态回归。

#### 风险 5：缺少测试分层和覆盖矩阵

目前只有“全量测试”命令。外部 agent 或开发者在小改动后不知道应该跑：

- smoke 测试？
- 数据层测试？
- API 测试？
- 因子模块测试？
- 全量测试？

这会导致两种坏结果：

- 小改动每次跑全量，效率低。
- 或者只跑单测，漏掉相邻模块回归。

## 3. 总体优化方向

### 3.1 测试分层

建议将测试分成 6 层：

| 层级 | 目标 | 文件/命令 |
| --- | --- | --- |
| smoke | 快速验证核心安全和纯函数 | validator、factor metrics、broker 部分 |
| data | 数据加载、复权、SQL 安全、数据校验 | data_loader、data_loader_security、data_validation |
| engine | 回测引擎、broker、指标 | broker、engine_metrics、indicators |
| api | FastAPI 路由和服务集成 | strategy/backtest/report/config/event/factor API |
| research | ML research | ml_features、ml_labels、ml_pipeline、ml_splitter |
| all | 合并验证 | `unittest discover` |

### 3.2 公共测试 helper

新增 `tests/helpers/`，把重复夹具与环境 patch 收敛到公共工具。

建议结构：

```text
tests/helpers/
├── __init__.py
├── temp_env.py
├── market_data.py
└── api.py
```

职责：

- `temp_env.py`：创建临时测试目录，统一 storage/data/db 路径。
- `market_data.py`：写 parquet 数据夹具。
- `api.py`：FastAPI 测试基类、NoopExecutor、SQLite 初始化、服务 patch。

### 3.3 API 测试拆分

拆分 `test_backend_api.py` 为模块化文件：

```text
tests/test_strategy_api.py
tests/test_backtest_api.py
tests/test_report_api.py
tests/test_config_api.py
tests/test_event_analysis_api.py
tests/test_factor_analysis_api.py
```

`test_factor_analysis_platform.py` 可保留端到端平台链路测试，或拆成：

```text
tests/test_factor_analysis_api.py
tests/test_factor_analysis_engine_integration.py
tests/test_factor_analysis_prompt.py
```

第一阶段不必强行重命名全部文件，先把最大文件拆开即可。

## 4. 详细实施计划

## Phase 1：建立公共测试 helper

### 目标

降低夹具重复，不改变业务逻辑和测试意图。

### 新增文件

#### `tests/helpers/__init__.py`

内容：

```python
from __future__ import annotations
```

#### `tests/helpers/temp_env.py`

实现建议：

```python
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import config
import backend.db.database as database


class TempProjectEnv:
    def __init__(self, root: Path):
        self.root = root
        self.storage = root / "storage"
        self.db_path = self.storage / "quant_backtest.db"
        self.data_dir = root / "data"
        self.patchers = []

    @classmethod
    def under_cwd(cls, test_name: str) -> "TempProjectEnv":
        root = Path.cwd() / ".test-tmp" / test_name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        return cls(root)

    def patch_data_dirs(self):
        self.patchers.extend(
            [
                patch.object(config.settings, "DATA_DIR", self.data_dir),
                patch.object(config.settings, "DAILY_BAR_DIR", self.data_dir / "daily_bar"),
                patch.object(config.settings, "ADJ_FACTOR_DIR", self.data_dir / "adj_factor"),
                patch.object(config.settings, "CALENDAR_DIR", self.data_dir / "calendar"),
                patch.object(config.settings, "DAILY_BASIC_DIR", self.data_dir / "daily_basic"),
                patch.object(config.settings, "STK_LIMIT_DIR", self.data_dir / "stk_limit"),
                patch.object(config.settings, "SUSPEND_D_DIR", self.data_dir / "suspend_d"),
                patch.object(config.settings, "NAMECHANGE_DIR", self.data_dir / "namechange"),
                patch.object(config.settings, "INSTRUMENTS_DIR", self.data_dir / "instruments"),
                patch.object(config.settings, "INDEX_MEMBER_DIR", self.data_dir / "index_member"),
                patch.object(config.settings, "CONCEPT_DIR", self.data_dir / "concept"),
                patch.object(config.settings, "INDEX_DAILY_DIR", self.data_dir / "index_daily"),
                patch.object(config.settings, "FUND_BASIC_DIR", self.data_dir / "fund_basic"),
                patch.object(config.settings, "INDUSTRY_DIR", self.data_dir / "industry"),
                patch.object(config.settings, "FINANCIAL_DIR", self.data_dir / "financial"),
                patch.object(config.settings, "ETF_DAILY_DIR", self.data_dir / "etf_daily"),
                patch.object(config.settings, "HOLDER_NUMBER_DIR", self.data_dir / "holder_number"),
            ]
        )
        return self

    def patch_database(self):
        self.patchers.extend(
            [
                patch.object(database, "STORAGE_DIR", self.storage),
                patch.object(database, "DB_PATH", self.db_path),
            ]
        )
        return self

    def start(self):
        for patcher in self.patchers:
            patcher.start()
        return self

    def stop(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)
```

#### `tests/helpers/market_data.py`

实现建议：

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_calendar(root: Path, dates: list[str], *, open_all: bool = True) -> None:
    calendar_dir = root / "calendar"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, date in enumerate(dates):
        rows.append(
            {
                "trade_date": date,
                "is_open": 1 if open_all else 0,
                "pretrade_date": dates[idx - 1] if idx else None,
                "next_trade_date": dates[idx + 1] if idx + 1 < len(dates) else None,
                "prev_trade_date": dates[idx - 1] if idx else None,
            }
        )
    pd.DataFrame(rows).to_parquet(calendar_dir / "calendar.parquet", index=False)


def write_daily_bar(root: Path, dates: list[str], codes: list[str], *, year: str = "2025") -> None:
    daily_dir = root / "daily_bar" / year
    daily_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, date in enumerate(dates):
        for rank, code in enumerate(codes, start=1):
            close = 10.0 + rank + idx * rank
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": date,
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "pre_close": close - rank if idx else close,
                    "volume": 100000 * rank,
                    "amount": 1000000.0 * rank,
                }
            )
    pd.DataFrame(rows).to_parquet(daily_dir / "daily_bar.parquet", index=False)


def write_daily_basic(root: Path, dates: list[str], codes: list[str], *, year: str = "2025") -> None:
    basic_dir = root / "daily_basic" / year
    basic_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for date in dates:
        for rank, code in enumerate(codes, start=1):
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": date,
                    "circ_mv": 100000.0 * rank,
                    "total_mv": 120000.0 * rank,
                    "total_share": 1000.0,
                    "float_share": 800.0,
                    "free_share": 700.0,
                    "turnover_rate": 1.0,
                    "pe_ttm": 10.0,
                    "pb": 1.0,
                }
            )
    pd.DataFrame(rows).to_parquet(basic_dir / "daily_basic.parquet", index=False)


def write_instruments(root: Path, rows: list[dict]) -> None:
    instruments_dir = root / "instruments"
    instruments_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(instruments_dir / "instruments.parquet", index=False)
```

#### `tests/helpers/api.py`

实现建议：

```python
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.db.database as database
from backend.main import app


class NoopExecutor:
    def submit(self, func, *args, **kwargs):
        return None


class ApiTestCase(unittest.TestCase):
    client: TestClient

    def init_client(self):
        database.init_db()
        self.client = TestClient(app)
        return self.client
```

### 迁移范围

第一批只迁移这些文件：

- `tests/test_data_loader.py`
- `tests/test_data_loader_security.py`
- `tests/test_engine_metrics.py`
- `tests/test_factor_analysis_platform.py`

不要一次迁移 `test_backend_api.py`，避免同时改太多。

### 验收命令

```bash
./.venv/bin/python -m unittest \
  tests.test_data_loader \
  tests.test_data_loader_security \
  tests.test_engine_metrics \
  tests.test_factor_analysis_platform \
  -v
```

成功标准：

- 以上测试全部通过。
- 单个文件中 patch 配置目录的重复列表明显减少。
- 业务代码零改动。

## Phase 2：拆分后端 API 测试

### 目标

将 `tests/test_backend_api.py` 按 API 领域拆分，便于定位和并行执行。

### 新增/拆分文件

```text
tests/test_strategy_api.py
tests/test_backtest_api.py
tests/test_report_api.py
tests/test_config_api.py
tests/test_event_analysis_api.py
```

### 拆分映射

| 来源测试 | 迁移到 |
| --- | --- |
| strategy validate/create/list/version | `test_strategy_api.py` |
| strategy ai-fill | `test_strategy_api.py` |
| backtest create/page/batch/cancel/delete | `test_backtest_api.py` |
| backtest templates | `test_backtest_api.py` |
| report download/log/html escape | `test_report_api.py` |
| settings/config/presets/agents/system-info | `test_config_api.py` |
| event analysis page/batch/delete guards | `test_event_analysis_api.py` |

### 公共基类

使用 Phase 1 的 `ApiTestCase`，并在 `tests/helpers/api.py` 增加：

```python
VALID_STRATEGY_CODE = """
from backtest.strategy import StrategyTemplate


class DemoStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("Demo")

    def init(self, context):
        self.count = 0

    def next(self, context):
        self.count += 1
""".strip()
```

以及：

```python
def create_strategy(client, key="demo_strategy", name="Demo Strategy", code=VALID_STRATEGY_CODE):
    response = client.post(
        "/api/strategies",
        json={
            "key": key,
            "name": name,
            "description": "测试策略",
            "source": "manual",
            "tags": ["测试"],
            "code": code,
            "status": "enabled",
        },
    )
    assert response.status_code == 200
    return response.json()
```

### 执行步骤

1. 新建目标文件，先复制测试，不删除源测试。
2. 跑目标文件，确认通过。
3. 从 `test_backend_api.py` 删除对应测试。
4. 跑全量。

### 验收命令

```bash
./.venv/bin/python -m unittest \
  tests.test_strategy_api \
  tests.test_backtest_api \
  tests.test_report_api \
  tests.test_config_api \
  tests.test_event_analysis_api \
  -v

./.venv/bin/python -m unittest discover -s tests -v
```

成功标准：

- `test_backend_api.py` 不再超过 250 行，或完全删除。
- 所有 API 测试通过。
- 没有重复的 `VALID_STRATEGY_CODE` 和 `NoopExecutor`。

## Phase 3：测试确定性与工作区卫生

### 目标

消除随机性和缓存文件污染。

### 改动 1：固定 ML feature 测试随机数

修改 `tests/test_ml_features.py`：

```python
rng = np.random.default_rng(42)
```

将：

```python
close = base * (1 + np.random.randn(window) * 0.02)
volume = np.random.randint(1e5, 1e7, window)
```

改为：

```python
close = base * (1 + rng.normal(0, 0.02, window))
volume = rng.integers(100_000, 10_000_000, window)
```

### 改动 2：清理 pycache

执行：

```bash
find tests -type d -name '__pycache__' -prune -exec rm -rf {} +
```

确认 `.gitignore` 包含：

```text
__pycache__/
*.py[cod]
.test-tmp/
.test-tmp-validation/
```

### 验收命令

```bash
./.venv/bin/python -m unittest tests.test_ml_features -v
./.venv/bin/python -m unittest discover -s tests -v
git status --short tests
```

成功标准：

- ML feature 测试稳定通过。
- `git status --short tests` 不出现 `__pycache__`。

## Phase 4：补强因子分析回归测试

### 目标

把新因子模块的真实故障和核心链路沉淀为测试。

### 4.1 指标层日期类型兼容

文件：`tests/test_factor_analysis.py`

已有：

- `test_coverage_accepts_mixed_trade_date_types`

建议新增：

```python
def test_ic_accepts_mixed_trade_date_types(self):
    fdf = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "2025-01-02", "factor": 1.0},
            {"ts_code": "000002.SZ", "trade_date": "2025-01-02", "factor": 2.0},
            {"ts_code": "000003.SZ", "trade_date": "2025-01-02", "factor": 3.0},
        ]
    )
    rdf = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": pd.Timestamp("2025-01-02"), "ret": 0.01},
            {"ts_code": "000002.SZ", "trade_date": pd.Timestamp("2025-01-02"), "ret": 0.02},
            {"ts_code": "000003.SZ", "trade_date": pd.Timestamp("2025-01-02"), "ret": 0.03},
        ]
    )
    ic = compute_ic(fdf, rdf)
    self.assertEqual(ic.iloc[0]["trade_date"], "2025-01-02")
    self.assertEqual(ic.iloc[0]["n"], 3)
```

### 4.2 真实 20 日动量 SQL 因子 quick API

文件：`tests/test_factor_analysis_platform.py`

新增常量：

```python
MOMENTUM_20_SQL_FACTOR_CODE = """
from __future__ import annotations

from factor_analysis.template import FactorAnalysisTemplate


class Momentum20dFactor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("20日动量因子")

    def compute(self, context):
        current_date = context["current_date"].strftime("%Y-%m-%d")
        sql = f'''
            WITH recent AS (
                SELECT ts_code, trade_date, close,
                       ROW_NUMBER() OVER (
                           PARTITION BY ts_code
                           ORDER BY trade_date DESC
                       ) AS rn
                FROM daily_bar
                WHERE trade_date <= '{current_date}'
            ),
            pivoted AS (
                SELECT ts_code,
                       MAX(CASE WHEN rn = 1 THEN close END) AS close_now,
                       MAX(CASE WHEN rn = 21 THEN close END) AS close_then
                FROM recent
                WHERE rn <= 21
                GROUP BY ts_code
            )
            SELECT
                ts_code,
                '{current_date}' AS trade_date,
                close_now / NULLIF(close_then, 0) - 1 AS factor_value
            FROM pivoted
            WHERE close_now IS NOT NULL
              AND close_then IS NOT NULL
        '''
        return context["conn"].execute(sql).fetchdf()
""".strip()
```

新增测试：

```python
def test_quick_momentum_20_factor_runs_successfully(self):
    response = self.client.post(
        "/api/factor-analyses/quick",
        json={
            "factor_code": MOMENTUM_20_SQL_FACTOR_CODE,
            "factor_key": "momentum_20d_test",
            "factor_name": "20日动量因子",
            "start_date": "2026-02-02",
            "end_date": "2026-02-20",
            "windows": [1],
            "quantiles": 2,
            "filters": ["exclude_st", "exclude_new_stock"],
            "preprocessing": {"winsorize": "mad", "standardize": "zscore"},
        },
    )
    self.assertEqual(response.status_code, 200)
    task = response.json()

    import backend.services.factor_analysis_service as factor_analysis_service

    factor_analysis_service.FactorAnalysisService()._run_task(task["id"])
    result = self.client.get(f"/api/factor-analyses/{task['id']}/result")
    self.assertEqual(result.status_code, 200)
    payload = result.json()
    self.assertEqual(payload["task"]["status"], "success")
    self.assertGreater(payload["payload"]["summary"]["sample_count"], 0)
    self.assertIn("ic_series", payload["payload"]["charts"])
```

### 4.3 因子报告下载

新增文件：`tests/test_factor_report_api.py`

目标：

- 成功任务可通过 `/api/reports/{task_id}/download?kind=factor_analysis&format=json` 下载。
- 失败任务 runtime logs 可被读取。
- `format=html` 对因子分析应返回明确错误或不支持状态。

建议测试：

```python
def test_factor_report_download_json(self):
    # 使用 factor platform helper 创建并运行一个成功任务
    # 调用 /api/reports/{task_id}/download?kind=factor_analysis&format=json
    # 断言返回 JSON 包含 summary/charts/tables/runtime
```

### 验收命令

```bash
./.venv/bin/python -m unittest \
  tests.test_factor_analysis \
  tests.test_factor_analysis_platform \
  tests.test_factor_report_api \
  -v
```

## Phase 5：建立测试分层命令文档

### 新增文件

`docs/TESTING.md`

建议内容：

```markdown
# Testing Guide

## 快速测试

```bash
./.venv/bin/python -m unittest tests.test_code_validator tests.test_factor_analysis -v
```

## 数据层测试

```bash
./.venv/bin/python -m unittest \
  tests.test_data_loader \
  tests.test_data_loader_security \
  tests.test_data_validation \
  -v
```

## 引擎层测试

```bash
./.venv/bin/python -m unittest \
  tests.test_broker \
  tests.test_engine_metrics \
  tests.test_indicators \
  -v
```

## API 测试

```bash
./.venv/bin/python -m unittest \
  tests.test_strategy_api \
  tests.test_backtest_api \
  tests.test_report_api \
  tests.test_config_api \
  tests.test_event_analysis_api \
  tests.test_factor_analysis_platform \
  -v
```

## ML 测试

```bash
./.venv/bin/python -m unittest \
  tests.test_ml_features \
  tests.test_ml_labels \
  tests.test_ml_pipeline \
  tests.test_ml_splitter \
  -v
```

## 全量测试

```bash
./.venv/bin/python -m unittest discover -s tests -v
```
```

### 可选脚本

新增 `scripts/run_tests.py`：

```python
from __future__ import annotations

import subprocess
import sys


GROUPS = {
    "smoke": ["tests.test_code_validator", "tests.test_factor_analysis"],
    "data": ["tests.test_data_loader", "tests.test_data_loader_security", "tests.test_data_validation"],
    "engine": ["tests.test_broker", "tests.test_engine_metrics", "tests.test_indicators"],
    "factor": ["tests.test_factor_analysis", "tests.test_factor_analysis_platform", "tests.test_factor_analysis_prompt"],
    "ml": ["tests.test_ml_features", "tests.test_ml_labels", "tests.test_ml_pipeline", "tests.test_ml_splitter"],
}


def main() -> int:
    group = sys.argv[1] if len(sys.argv) > 1 else "all"
    if group == "all":
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    elif group in GROUPS:
        cmd = [sys.executable, "-m", "unittest", *GROUPS[group], "-v"]
    else:
        print(f"Unknown test group: {group}")
        print("Available:", ", ".join(["all", *GROUPS.keys()]))
        return 2
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
```

验收：

```bash
./.venv/bin/python scripts/run_tests.py smoke
./.venv/bin/python scripts/run_tests.py factor
./.venv/bin/python scripts/run_tests.py all
```

## Phase 6：建立覆盖矩阵

### 新增文件

`docs/TEST_COVERAGE_MATRIX.md`

建议表格：

```markdown
# Test Coverage Matrix

| 模块 | 已覆盖 | 缺口 | 推荐测试文件 | 优先级 |
| --- | --- | --- | --- | --- |
| Broker | 手续费、T+1、涨跌停、市值 | 极端订单生命周期 | `tests/test_broker.py` | P2 |
| DataLoader | 复权、缓存、截面、SQL 安全 | 更多真实字段组合 | `tests/test_data_loader*.py` | P1 |
| Strategy API | 创建、校验、版本、AI fill | 批量导入/禁用组合 | `tests/test_strategy_api.py` | P2 |
| Backtest API | 创建、分页、删除、取消 | 运行中状态转换 | `tests/test_backtest_api.py` | P1 |
| Reports | JSON/HTML 下载、日志 escape | factor/event 统一报告 | `tests/test_report_api.py` | P1 |
| Event Analysis | 分页、批删、任务生命周期 | 标准脚本离线模式 | `tests/test_event_analysis_api.py` | P2 |
| Factor Analysis | 指标、API、prompt、过滤器 | 报告下载、真实动量因子 | `tests/test_factor_analysis*.py` | P0 |
| ML Research | features/labels/pipeline/splitter | 数据泄漏边界、训练 artifact | `tests/test_ml_*.py` | P2 |
| Frontend | build | 关键交互缺自动化 | 后续 Playwright | P3 |
```

## 5. Agent 分工建议

### Agent A：测试 helper 与 DataLoader 夹具收敛

提示词：

```text
你负责优化 quant-backtest 的测试夹具复用。请只修改 tests/helpers/*、tests/test_data_loader.py、tests/test_data_loader_security.py、tests/test_engine_metrics.py。新增 tests/helpers/temp_env.py 和 tests/helpers/market_data.py，把重复的临时目录、config.settings patch、parquet fixture 写入逻辑抽出来。不要改业务代码。完成后运行：
./.venv/bin/python -m unittest tests.test_data_loader tests.test_data_loader_security tests.test_engine_metrics -v
并汇报修改文件和结果。
```

### Agent B：API 测试拆分

提示词：

```text
你负责拆分 tests/test_backend_api.py。请新增 tests/test_strategy_api.py、tests/test_backtest_api.py、tests/test_report_api.py、tests/test_config_api.py、tests/test_event_analysis_api.py，并把对应测试从 test_backend_api.py 迁移过去。优先复用 tests/helpers/api.py，如 helper 不足可补充。不要改业务代码。完成后运行：
./.venv/bin/python -m unittest tests.test_strategy_api tests.test_backtest_api tests.test_report_api tests.test_config_api tests.test_event_analysis_api -v
以及全量 unittest。
```

### Agent C：因子分析回归补测

提示词：

```text
你负责补强因子分析测试。请修改 tests/test_factor_analysis.py、tests/test_factor_analysis_platform.py，并新增 tests/test_factor_report_api.py。目标是覆盖混合 trade_date 类型的 IC/coverage、真实 20 日动量 SQL 因子 quick API 成功运行、factor_analysis 报告 JSON 下载和失败 runtime logs。不要改业务逻辑，除非测试暴露真实 bug；如需改业务逻辑，先写 failing test。完成后运行：
./.venv/bin/python -m unittest tests.test_factor_analysis tests.test_factor_analysis_platform tests.test_factor_report_api -v
```

### Agent D：测试文档与命令

提示词：

```text
你负责补充测试文档和测试分组命令。请新增 docs/TESTING.md、docs/TEST_COVERAGE_MATRIX.md，可选新增 scripts/run_tests.py。不要改业务代码。文档要列出 smoke/data/engine/api/factor/ml/all 的命令和适用场景。完成后运行：
./.venv/bin/python scripts/run_tests.py smoke
./.venv/bin/python scripts/run_tests.py factor
```

## 6. 推荐执行顺序

1. Phase 3：先做确定性和 pycache 清理，风险最低。
2. Phase 4：补因子回归，直接覆盖近期真实故障。
3. Phase 1：抽 helper，降低后续拆分成本。
4. Phase 2：拆 API 测试大文件。
5. Phase 5/6：补测试文档和覆盖矩阵。

如果多人并行：

- Agent C 可以先做 Phase 4。
- Agent D 可以独立做 Phase 5/6。
- Agent A 先做 Phase 1。
- Agent B 等 Agent A 完成后再做 Phase 2，减少冲突。

## 7. 最终验收标准

全部优化完成后必须满足：

```bash
./.venv/bin/python -m unittest discover -s tests -v
cd frontend && npm run build
```

并满足：

- 全量后端测试通过。
- 前端构建通过。
- `tests/test_backend_api.py` 不再承担所有 API 测试。
- 公共夹具 helper 被至少 3 个测试文件复用。
- 因子分析真实 20 日动量任务有回归测试。
- `docs/TESTING.md` 能指导 agent 选择测试范围。
- `docs/TEST_COVERAGE_MATRIX.md` 能反映模块覆盖缺口。
