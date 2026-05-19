# Agent ML 研究模块指南

日期: 2026-05-11

## 概述

`ml_research/` 是本地 ML 研究模块，用于训练截面选股模型并将预测结果接入回测引擎。**不上前端，不走 API**，纯本地研究用途。

核心流程：**特征工程 → 标签生成 → Walk-Forward 训练 → 预测 → 评估 → 回测验证**

---

## 快速开始

### 方式 1：CLI 入口（推荐）

```bash
python scripts/agent_entry/run_ml_training.py \
    --start 2016-01-01 --end 2026-04-29 \
    --experiment-name lgb_v1 \
    --forward-days 5 --top-n 20
```

训练完成后自动保存实验到 `ml_research/experiments/lgb_v1/`。

### 方式 2：Python API

```python
from ml_research.pipeline import run_pipeline
from ml_research.config import MLConfig

cfg = MLConfig(
    experiment_name="lgb_v1",
    forward_days=5,
    top_n=20,
)
result = run_pipeline(
    start_date="2016-01-01",
    end_date="2026-04-29",
    config=cfg,
    cache_dir=Path("ml_research/experiments/lgb_v1/cache"),
)
```

---

## CLI 参数速查

```bash
python scripts/agent_entry/run_ml_training.py --help
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--start` | `2016-01-01` | 训练数据起始日期 |
| `--end` | `2026-04-29` | 训练数据结束日期 |
| `--experiment-name` | `default` | 实验名称（保存目录名） |
| `--forward-days` | `5` | 前瞻收益天数 |
| `--top-n` | `20` | 选股数量 |
| `--train-days` | `504` | 训练窗口（~2年） |
| `--test-days` | `63` | 测试窗口（~3月） |
| `--step-days` | `63` | 步进 |
| `--n-estimators` | `500` | LightGBM 树数量 |
| `--learning-rate` | `0.05` | 学习率 |
| `--momentum-windows` | `5,10,20,60` | 动量窗口 |
| `--use-cache` | off | 使用特征/标签缓存 |
| `--run-backtest` | off | 训练后自动跑回测 |

---

## 模块结构

```
ml_research/
├── config.py             # MLConfig 数据类
├── features.py           # 特征工程
├── labels.py             # 标签生成
├── splitter.py           # Walk-Forward 切分
├── models/
│   ├── base.py           # 模型基类
│   └── lightgbm_model.py # LightGBM 封装
├── evaluate.py           # 评估（IC/ICIR/分组收益）
├── pipeline.py           # 训练 Pipeline
├── signal.py             # MLStrategy（接入回测）
└── experiments/          # 实验输出（gitignore）
```

---

## 核心概念

### 特征（features.py）

每个交易日构建截面特征矩阵，每行一只股票：

| 特征 | 说明 |
|---|---|
| `mom_5d`, `mom_10d`, `mom_20d`, `mom_60d` | N 日动量收益 |
| `vol_20d` | 20 日收益波动率 |
| `vol_ratio_20d` | 当日成交量 / 20 日均量 |
| `log_circ_mv` | log(流通市值) |
| `log_pe_ttm` | log(|PE_TTM|) |
| `log_pb` | log(|PB|) |
| `turnover_rate` | 换手率 |

所有特征经过截面排名归一化（`rank_normalize`），转为 [0, 1] 百分位。

### 标签（labels.py）

`ret_Nd = close(t+N) / close(t) - 1`，即 N 日前瞻收益率。

**无前瞻偏差**：标签只使用已实现的历史价格，通过交易日历确定 t+N 对应的准确日期。

### Walk-Forward（splitter.py）

```
Split 1: [--------train--------] [test]
Split 2:      [--------train--------] [test]
Split 3:           [--------train--------] [test]
```

- **rolling**：固定窗口滑动（默认 2 年训练 / 3 月测试）
- **expanding**：窗口递增

### 模型（models/）

统一接口 `BaseModel`：
- `fit(X, y)` → 训练
- `predict(X)` → 预测
- `save(path)` / `load(path)` → 序列化
- `feature_importance()` → 特征重要性

当前实现：`LightGBMModel`（LightGBM 回归）

### 评估（evaluate.py）

复用 `factor_analysis.engine` 计算：
- **IC**：预测值与真实收益的 Spearman 秩相关
- **ICIR**：IC 均值 / IC 标准差（越高越稳定）
- **分组收益**：按预测值分 5 组，比较各组平均收益
- **特征重要性**：LightGBM gain-based importance

### 信号（signal.py）

`MLStrategy` 继承 `StrategyTemplate`：
- 从 `predictions.parquet` 加载预测分数
- 每个调仓日选 top_n 等权配置
- 可直接接入 `run_strategy()` 跑回测

---

## 输出文件

实验结果保存在 `ml_research/experiments/{experiment_name}/`：

| 文件 | 说明 |
|---|---|
| `predictions.parquet` | 全部预测结果 [ts_code, trade_date, pred] |
| `model.lgb` | 最后一个 split 的 LightGBM 模型 |
| `feature_importance.csv` | 特征重要性排名 |
| `config.json` | 本次实验的完整配置 |

---

## 典型 Agent 工作流

### 1. 训练基础模型

```bash
python scripts/agent_entry/run_ml_training.py \
    --experiment-name baseline \
    --start 2016-01-01 --end 2026-04-29
```

查看输出的 IC/ICIR，判断模型是否有预测能力。

### 2. 调参实验

```bash
# 更多树、更深
python scripts/agent_entry/run_ml_training.py \
    --experiment-name lgb_deep \
    --n-estimators 1000 --max-depth 10 --num-leaves 127

# 更短前瞻
python scripts/agent_entry/run_ml_training.py \
    --experiment-name lgb_3d \
    --forward-days 3 --top-n 15
```

### 3. 回测验证

```bash
python scripts/agent_entry/run_ml_training.py \
    --experiment-name lgb_v1 \
    --run-backtest --backtest-start 2023-01-01 --backtest-end 2026-04-29
```

### 4. 用预测结果自定义回测

```python
from ml_research.signal import MLStrategy
from backtest.strategy import run_strategy

strategy = MLStrategy(
    predictions_path="ml_research/experiments/lgb_v1/predictions.parquet",
    top_n=30,
    rebalance_freq=10,
)
run_strategy(strategy, start_date="20230101", end_date="20260429")
```

### 5. 缓存加速重复实验

首次训练加 `--use-cache`，后续修改模型参数时特征和标签会直接从 parquet 加载：

```bash
# 首次（构建特征+标签，耗时较长）
python scripts/agent_entry/run_ml_training.py --experiment-name exp1 --use-cache

# 后续（特征+标签从缓存加载，只重跑训练）
python scripts/agent_entry/run_ml_training.py --experiment-name exp2 --use-cache
```

---

## 扩展模型

如需添加新模型，继承 `ml_research.models.base.BaseModel`：

```python
from ml_research.models.base import BaseModel

class XGBoostModel(BaseModel):
    def fit(self, X, y): ...
    def predict(self, X): ...
    def save(self, path): ...
    def load(self, path): ...
```

然后在 `pipeline.py` 中替换 `LightGBMModel` 为你的模型。

---

## 依赖

```
lightgbm>=4.0.0
scikit-learn>=1.3.0
optuna>=3.4.0
matplotlib>=3.7.0
```

已包含在 `requirements.txt` 中。

---

## 注意事项

1. **数据要求**：需要 `data/` 目录下有完整的 parquet 数据（日线、复权因子、daily_basic、交易日历）
2. **内存**：全市场特征构建需要较大内存（~8GB+），可通过缩短日期范围缓解
3. **时间**：全量训练（2016-2026）首次约需 30-60 分钟，使用缓存后约 5-10 分钟
4. **不走前端**：ML 模块的输出不进入 `backtest_tasks` 表，不被前端展示
5. **实验隔离**：每次实验用不同的 `experiment_name`，避免覆盖
