# ML Research Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone ML research module (`ml_research/`) for local model training, producing stock selection signals that integrate with the existing backtest engine — no frontend, no backend API.

**Architecture:** Cross-sectional prediction approach: for each trade date, predict N-day forward return for all stocks using historical features. LightGBM as the first model. Walk-forward validation to avoid look-ahead bias. Model predictions are converted to portfolio weights via a `StrategyTemplate` subclass and fed into the existing backtest engine for evaluation.

**Tech Stack:** lightgbm, scikit-learn (for metrics/utilities only), optuna (hyperparameter tuning), matplotlib/plotly (visualization). Reuse existing: `backtest.data_loader.DataLoader`, `backtest.strategy.StrategyTemplate`, `factor_analysis.engine`.

---

## File Map

| File | Responsibility |
|---|---|
| `ml_research/__init__.py` | Package marker |
| `ml_research/config.py` | ML-specific settings (train window, forward days, feature list, etc.) |
| `ml_research/features.py` | Build cross-sectional feature matrix from DataLoader |
| `ml_research/labels.py` | Generate forward return labels |
| `ml_research/splitter.py` | Walk-forward train/test splitting |
| `ml_research/models/__init__.py` | Package marker |
| `ml_research/models/base.py` | Abstract model interface: fit/predict/save/load |
| `ml_research/models/lightgbm_model.py` | LightGBM wrapper |
| `ml_research/pipeline.py` | Orchestrate: features → labels → split → train → predict → save |
| `ml_research/signal.py` | Convert model predictions to StrategyTemplate for backtest |
| `ml_research/evaluate.py` | IC, ICIR, feature importance, group returns, backtest comparison |
| `ml_research/experiments/.gitignore` | Ignore model artifacts and experiment outputs |
| `tests/test_ml_features.py` | Unit tests for features.py |
| `tests/test_ml_labels.py` | Unit tests for labels.py |
| `tests/test_ml_splitter.py` | Unit tests for splitter.py |
| `tests/test_ml_pipeline.py` | Integration test for pipeline |

---

## Task 1: Config and Package Structure

**Files:**
- Create: `ml_research/__init__.py`
- Create: `ml_research/config.py`
- Create: `ml_research/models/__init__.py`
- Create: `ml_research/experiments/.gitignore`

- [ ] **Step 1: Create `ml_research/config.py`**

```python
"""
ML Research 配置
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class MLConfig:
    # === 特征工程 ===
    # 动量窗口（交易日）
    momentum_windows: List[int] = field(default_factory=lambda: [5, 10, 20, 60])
    # 波动率窗口
    volatility_window: int = 20
    # 换手率窗口
    turnover_window: int = 20

    # === 标签 ===
    # 前瞻收益天数
    forward_days: int = 5

    # === Walk-Forward ===
    # 训练窗口（交易日）
    train_days: int = 504  # ~2 years
    # 测试窗口（交易日）
    test_days: int = 63  # ~3 months
    # 步进（交易日）
    step_days: int = 63

    # === 模型 ===
    lgb_params: dict = field(default_factory=lambda: {
        "objective": "regression",
        "metric": "mse",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "max_depth": 7,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "n_estimators": 500,
        "verbose": -1,
        "n_jobs": -1,
    })

    # === 信号生成 ===
    top_n: int = 20
    rebalance_freq: int = 5

    # === 路径 ===
    experiment_name: str = "default"


# 默认配置实例
default_config = MLConfig()
```

- [ ] **Step 2: Create `ml_research/__init__.py`**

```python
"""ML Research 模块 — 本地量化模型训练与回测"""
```

- [ ] **Step 3: Create `ml_research/models/__init__.py`**

```python
```

- [ ] **Step 4: Create `ml_research/experiments/.gitignore`**

```
*
!.gitignore
!README.md
```

- [ ] **Step 5: Commit**

```bash
git add ml_research/
git commit -m "feat(ml): add ml_research package skeleton with config"
```

---

## Task 2: Feature Engineering

**Files:**
- Create: `ml_research/features.py`
- Create: `tests/test_ml_features.py`

**Design:** `build_features(data_loader, trade_dates)` iterates over trade dates, calls `get_cross_section()` for each, computes cross-sectional features, returns a DataFrame with `[ts_code, trade_date, feature_1, feature_2, ...]`.

Features to compute (all cross-sectional rank-normalized):
- **Momentum:** N-day return (5, 10, 20, 60)
- **Volatility:** 20-day daily return std
- **Turnover:** mean turnover_rate over 5d, 20d
- **Size:** log(circ_mv)
- **Valuation:** pe_ttm, pb (log-transformed)
- **Volume change:** volume / volume_20d_mean - 1

- [ ] **Step 1: Write failing test for `features.build_single_day_features`**

```python
# tests/test_ml_features.py
import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock


def test_build_single_day_features_basic():
    """build_single_day_features returns correct columns and shape."""
    from ml_research.features import build_single_day_features

    # Mock cross-section data (what DataLoader.get_cross_section returns)
    cs = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
        "trade_date": ["2025-01-10"] * 3,
        "close": [10.0, 20.0, 15.0],
        "volume": [1e6, 2e6, 1.5e6],
        "amount": [1e7, 4e7, 2.25e7],
        "circ_mv": [100e8, 200e8, 150e8],
        "pe_ttm": [10.0, 20.0, 15.0],
        "pb": [1.5, 2.0, 1.0],
        "turnover_rate": [3.0, 2.0, 4.0],
    })

    # Mock history data for momentum/volatility (get_history returns)
    def mock_get_history(ts_code, end_date, window, adjust="qfq"):
        dates = pd.date_range("2024-12-01", periods=window, freq="B")
        base = {"000001.SZ": 10.0, "000002.SZ": 20.0, "600000.SH": 15.0}[ts_code]
        close = base * (1 + np.random.randn(window) * 0.02)
        return pd.DataFrame({
            "ts_code": ts_code,
            "trade_date": dates.strftime("%Y-%m-%d"),
            "close": close,
            "volume": np.random.randint(1e5, 1e7, window),
        })

    dl = MagicMock()
    dl.get_cross_section.return_value = cs
    dl.get_history.side_effect = mock_get_history

    result = build_single_day_features(dl, "2025-01-10")

    assert isinstance(result, pd.DataFrame)
    assert "ts_code" in result.columns
    assert "trade_date" in result.columns
    assert len(result) == 3
    # Should have feature columns
    feature_cols = [c for c in result.columns if c not in ("ts_code", "trade_date")]
    assert len(feature_cols) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ml_features.py -v`
Expected: FAIL (module `ml_research.features` not found)

- [ ] **Step 3: Implement `ml_research/features.py`**

```python
"""
特征工程：从 DataLoader 构建截面特征矩阵
"""
from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from backtest.data_loader import DataLoader


def _safe_log(s: pd.Series) -> pd.Series:
    return np.log(s.clip(lower=1e-8))


def build_single_day_features(
    dl: DataLoader,
    trade_date: str,
    momentum_windows: List[int] = (5, 10, 20, 60),
    volatility_window: int = 20,
) -> pd.DataFrame:
    """
    为单个交易日构建截面特征。

    Returns:
        DataFrame with [ts_code, trade_date, feat_1, feat_2, ...]
    """
    cs = dl.get_cross_section(trade_date)
    if cs.empty:
        return pd.DataFrame()

    cs = cs.copy()
    cs["trade_date"] = pd.to_datetime(cs["trade_date"]).dt.strftime("%Y-%m-%d")

    # --- 基础截面特征（直接从截面数据计算） ---
    cs["log_circ_mv"] = _safe_log(cs.get("circ_mv", pd.Series(dtype=float)))
    cs["log_pe_ttm"] = _safe_log(cs.get("pe_ttm", pd.Series(dtype=float)).abs())
    cs["log_pb"] = _safe_log(cs.get("pb", pd.Series(dtype=float)).abs())
    cs["turnover_rate"] = cs.get("turnover_rate", pd.Series(dtype=float))

    # --- 需要历史数据的特征 ---
    hist_features = []
    max_window = max(momentum_windows + [volatility_window])

    for _, row in cs.iterrows():
        ts_code = row["ts_code"]
        try:
            hist = dl.get_history(
                ts_code=ts_code,
                end_date=trade_date,
                window=max_window + 5,
                adjust="qfq",
            )
        except Exception:
            hist = pd.DataFrame()

        rec = {"ts_code": ts_code, "trade_date": row["trade_date"]}

        if hist is not None and len(hist) >= 2:
            close = hist["close"].values
            vol = hist["volume"].values if "volume" in hist.columns else None

            # Momentum
            for w in momentum_windows:
                if len(close) >= w:
                    rec[f"mom_{w}d"] = close[-1] / close[-w] - 1
                else:
                    rec[f"mom_{w}d"] = np.nan

            # Volatility
            if len(close) >= volatility_window + 1:
                rets = np.diff(np.log(close[-volatility_window - 1:]))
                rec[f"vol_{volatility_window}d"] = np.std(rets)
            else:
                rec[f"vol_{volatility_window}d"] = np.nan

            # Volume ratio (current / 20d mean)
            if vol is not None and len(vol) >= 20:
                rec["vol_ratio_20d"] = vol[-1] / (np.mean(vol[-20:]) + 1e-8)
            else:
                rec["vol_ratio_20d"] = np.nan
        else:
            for w in momentum_windows:
                rec[f"mom_{w}d"] = np.nan
            rec[f"vol_{volatility_window}d"] = np.nan
            rec["vol_ratio_20d"] = np.nan

        hist_features.append(rec)

    if not hist_features:
        return pd.DataFrame()

    hist_df = pd.DataFrame(hist_features)

    # Merge cross-sectional base features with history-derived features
    base_cols = ["ts_code", "trade_date", "log_circ_mv", "log_pe_ttm", "log_pb", "turnover_rate"]
    base_cols = [c for c in base_cols if c in cs.columns]
    result = cs[base_cols].merge(hist_df, on=["ts_code", "trade_date"], how="outer")

    return result


def build_feature_matrix(
    dl: DataLoader,
    trade_dates: List[str],
    momentum_windows: List[int] = (5, 10, 20, 60),
    volatility_window: int = 20,
) -> pd.DataFrame:
    """
    为多个交易日构建特征矩阵。

    Returns:
        DataFrame: [ts_code, trade_date, feat_1, ...]
    """
    parts = []
    for i, td in enumerate(trade_dates):
        if i % 50 == 0:
            logger.info(f"Building features: {i}/{len(trade_dates)}")
        part = build_single_day_features(dl, td, momentum_windows, volatility_window)
        if not part.empty:
            parts.append(part)

    if not parts:
        return pd.DataFrame()

    return pd.concat(parts, ignore_index=True)


def rank_normalize(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """
    截面排名归一化：每个 trade_date 内，将特征值转为 [0, 1] 排名百分位。
    """
    df = df.copy()
    for col in feature_cols:
        if col in df.columns:
            df[col] = df.groupby("trade_date")[col].rank(pct=True)
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ml_features.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml_research/features.py tests/test_ml_features.py
git commit -m "feat(ml): add cross-sectional feature engineering"
```

---

## Task 3: Label Generation

**Files:**
- Create: `ml_research/labels.py`
- Create: `tests/test_ml_labels.py`

**Design:** `build_labels(dl, trade_dates, forward_days)` computes `ret_Nd = close(t+N) / close(t) - 1` using `get_cross_section()` on both dates. No look-ahead: the label for date t requires data from date t+N, so we only compute labels for dates where t+N exists in the data.

- [ ] **Step 1: Write failing test**

```python
# tests/test_ml_labels.py
import pandas as pd
import pytest
from unittest.mock import MagicMock


def test_build_labels_basic():
    """build_labels computes forward return correctly."""
    from ml_research.labels import build_labels

    cs_t0 = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": ["2025-01-10", "2025-01-10"],
        "close": [10.0, 20.0],
    })
    cs_t5 = pd.DataFrame({
        "ts_code": ["000001.SZ", "000002.SZ"],
        "trade_date": ["2025-01-17", "2025-01-17"],
        "close": [11.0, 18.0],
    })

    call_count = [0]
    def mock_cs(trade_date, fields=None, adjust=None):
        call_count[0] += 1
        if str(trade_date) in ("2025-01-10", "20250110"):
            return cs_t0
        return cs_t5

    dl = MagicMock()
    dl.get_cross_section.side_effect = mock_cs
    dl.get_trade_calendar.return_value = pd.DataFrame({
        "trade_date": ["2025-01-10", "2025-01-13", "2025-01-14", "2025-01-15", "2025-01-16", "2025-01-17"],
    })

    result = build_labels(dl, ["2025-01-10"], forward_days=5)

    assert len(result) == 2
    assert set(result.columns) >= {"ts_code", "trade_date", "ret_5d"}

    row_a = result[result["ts_code"] == "000001.SZ"].iloc[0]
    assert abs(row_a["ret_5d"] - 0.1) < 1e-6  # 11/10 - 1 = 0.1

    row_b = result[result["ts_code"] == "000002.SZ"].iloc[0]
    assert abs(row_b["ret_5d"] - (-0.1)) < 1e-6  # 18/20 - 1 = -0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ml_labels.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `ml_research/labels.py`**

```python
"""
标签生成：计算未来 N 日收益率
"""
from typing import List

import pandas as pd
from loguru import logger

from backtest.data_loader import DataLoader


def build_labels(
    dl: DataLoader,
    trade_dates: List[str],
    forward_days: int = 5,
) -> pd.DataFrame:
    """
    为 trade_dates 中的每个日期计算 forward_days 日后的收益率。

    对于每个 date t:
      1. 获取 t 日截面的 close_t
      2. 获取 t+forward_days 交易日截面的 close_tn
      3. ret = close_tn / close_t - 1

    Returns:
        DataFrame: [ts_code, trade_date, ret_{forward_days}d]
    """
    # 预取交易日历，用于确定 t+N 对应的交易日
    all_dates_set = set()
    for td in trade_dates:
        all_dates_set.add(td)

    calendar = dl.get_trade_calendar(
        start_date=min(trade_dates),
        end_date=None,
        only_open=True,
    )
    cal_dates = sorted(calendar["trade_date"].tolist())

    # 建立日期到索引的映射
    date_to_idx = {d: i for i, d in enumerate(cal_dates)}

    parts = []
    for i, td in enumerate(trade_dates):
        if i % 100 == 0:
            logger.info(f"Building labels: {i}/{len(trade_dates)}")

        td_str = pd.to_datetime(td).strftime("%Y-%m-%d")
        idx = date_to_idx.get(td_str)
        if idx is None:
            continue

        # 找 t+N 对应的交易日
        target_idx = idx + forward_days
        if target_idx >= len(cal_dates):
            continue

        future_date = cal_dates[target_idx]

        # 获取两个日期的截面收盘价
        cs_now = dl.get_cross_section(td, fields=["ts_code", "trade_date", "close"])
        cs_future = dl.get_cross_section(future_date, fields=["ts_code", "trade_date", "close"])

        if cs_now.empty or cs_future.empty:
            continue

        merged = cs_now[["ts_code", "close"]].merge(
            cs_future[["ts_code", "close"]],
            on="ts_code",
            suffixes=("_now", "_future"),
        )

        merged["trade_date"] = td_str
        merged[f"ret_{forward_days}d"] = merged["close_future"] / merged["close_now"] - 1
        merged = merged.rename(columns={f"ret_{forward_days}d": f"ret_{forward_days}d"})

        parts.append(merged[["ts_code", "trade_date", f"ret_{forward_days}d"]])

    if not parts:
        return pd.DataFrame(columns=["ts_code", "trade_date", f"ret_{forward_days}d"])

    return pd.concat(parts, ignore_index=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ml_labels.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml_research/labels.py tests/test_ml_labels.py
git commit -m "feat(ml): add forward return label generation"
```

---

## Task 4: Walk-Forward Splitter

**Files:**
- Create: `ml_research/splitter.py`
- Create: `tests/test_ml_splitter.py`

**Design:** Given a sorted list of trade dates, produce train/test splits:
- Expanding window: train = [start, t), test = [t, t+test_days)
- Rolling window: train = [t-train_days, t), test = [t, t+test_days)
- Each split is a dict: `{"train_dates": [...], "test_dates": [...]}`

- [ ] **Step 1: Write failing test**

```python
# tests/test_ml_splitter.py
import pytest


def test_walk_forward_rolling():
    """walk_forward produces correct rolling splits."""
    from ml_research.splitter import walk_forward

    dates = [f"2020-01-{d:02d}" for d in range(1, 32)]  # 31 dates
    splits = walk_forward(dates, train_days=10, test_days=5, step_days=5, mode="rolling")

    assert len(splits) > 0
    for s in splits:
        assert len(s["train_dates"]) == 10
        assert len(s["test_dates"]) == 5
        # No overlap
        assert set(s["train_dates"]).isdisjoint(set(s["test_dates"]))
        # Train before test
        assert max(s["train_dates"]) < min(s["test_dates"])


def test_walk_forward_expanding():
    """walk_forward expanding window grows train set."""
    from ml_research.splitter import walk_forward

    dates = [f"2020-01-{d:02d}" for d in range(1, 32)]
    splits = walk_forward(dates, train_days=10, test_days=5, step_days=5, mode="expanding")

    assert len(splits) >= 2
    # Expanding: each split's train is longer than previous
    for i in range(1, len(splits)):
        assert len(splits[i]["train_dates"]) >= len(splits[i - 1]["train_dates"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ml_splitter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `ml_research/splitter.py`**

```python
"""
Walk-Forward 滚动训练/测试切分
"""
from typing import List, Dict


def walk_forward(
    trade_dates: List[str],
    train_days: int = 504,
    test_days: int = 63,
    step_days: int = 63,
    mode: str = "rolling",
) -> List[Dict[str, List[str]]]:
    """
    生成 walk-forward 训练/测试切分。

    Args:
        trade_dates: 排序后的交易日期列表
        train_days: 训练窗口长度（rolling 模式）
        test_days: 测试窗口长度
        step_days: 每次推进的步长
        mode: "rolling"（固定窗口滑动）或 "expanding"（窗口递增）

    Returns:
        List of {"train_dates": [...], "test_dates": [...]}
    """
    n = len(trade_dates)
    splits = []

    # 第一个测试集的起始位置
    start_test = train_days if mode == "rolling" else train_days

    i = start_test
    while i + test_days <= n:
        if mode == "rolling":
            train_start = i - train_days
        else:
            train_start = 0

        train = trade_dates[train_start:i]
        test = trade_dates[i:i + test_days]

        splits.append({
            "train_dates": train,
            "test_dates": test,
        })

        i += step_days

    return splits
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ml_splitter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml_research/splitter.py tests/test_ml_splitter.py
git commit -m "feat(ml): add walk-forward train/test splitter"
```

---

## Task 5: Model Base Class and LightGBM Implementation

**Files:**
- Create: `ml_research/models/base.py`
- Create: `ml_research/models/lightgbm_model.py`

**Design:** `BaseModel` defines `fit(X, y)`, `predict(X)`, `save(path)`, `load(path)`, `feature_importance()`. `LightGBMModel` wraps `lightgbm.LGBMRegressor`.

- [ ] **Step 1: Implement `ml_research/models/base.py`**

```python
"""
模型基类：统一接口
"""
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd


class BaseModel(ABC):
    """所有 ML 模型的基类"""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseModel":
        """训练模型"""
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """预测，返回一维数组"""
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """保存模型到文件"""
        ...

    @abstractmethod
    def load(self, path: Path) -> "BaseModel":
        """从文件加载模型"""
        ...

    def feature_importance(self) -> pd.DataFrame:
        """
        返回特征重要性 DataFrame: [feature, importance]
        默认返回空，子类可覆盖
        """
        return pd.DataFrame(columns=["feature", "importance"])
```

- [ ] **Step 2: Implement `ml_research/models/lightgbm_model.py`**

```python
"""
LightGBM 模型封装
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml_research.models.base import BaseModel


class LightGBMModel(BaseModel):
    def __init__(self, params: dict = None):
        default_params = {
            "objective": "regression",
            "metric": "mse",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "max_depth": 7,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "n_estimators": 500,
            "verbose": -1,
            "n_jobs": -1,
        }
        self.params = params or default_params
        self.model = lgb.LGBMRegressor(**self.params)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LightGBMModel":
        self.model.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.model.booster_.save_model(str(path))

    def load(self, path: Path) -> "LightGBMModel":
        path = Path(path)
        booster = lgb.Booster(model_file=str(path))
        self.model.booster_ = booster
        return self

    def feature_importance(self) -> pd.DataFrame:
        booster = self.model.booster_
        names = booster.feature_name()
        importance = booster.feature_importance(importance_type="gain")
        df = pd.DataFrame({"feature": names, "importance": importance})
        return df.sort_values("importance", ascending=False).reset_index(drop=True)
```

- [ ] **Step 3: Commit**

```bash
git add ml_research/models/base.py ml_research/models/lightgbm_model.py
git commit -m "feat(ml): add model base class and LightGBM wrapper"
```

---

## Task 6: Evaluation Module

**Files:**
- Create: `ml_research/evaluate.py`

**Design:** Wraps `factor_analysis.engine` for IC/ICIR, adds feature importance and group return analysis. All functions take DataFrames and return results — no side effects.

- [ ] **Step 1: Implement `ml_research/evaluate.py`**

```python
"""
模型评估：IC、ICIR、分组收益、特征重要性
"""
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import numpy as np
from loguru import logger

from factor_analysis.engine import compute_ic, compute_group_returns, build_summary
from ml_research.models.base import BaseModel


def evaluate_predictions(
    pred_df: pd.DataFrame,
    label_df: pd.DataFrame,
    forward_days: int = 5,
    n_groups: int = 5,
) -> Dict[str, Any]:
    """
    评估模型预测质量。

    Args:
        pred_df: [ts_code, trade_date, pred] — 模型预测值
        label_df: [ts_code, trade_date, ret_{forward_days}d] — 真实标签
        forward_days: 前瞻天数（用于匹配列名）
        n_groups: 分组数

    Returns:
        dict with keys: ic_summary, group_returns, daily_ic
    """
    ret_col = f"ret_{forward_days}d"
    if ret_col not in label_df.columns:
        # Try generic "ret" column
        if "ret" in label_df.columns:
            label_df = label_df.rename(columns={"ret": ret_col})
        else:
            raise ValueError(f"label_df 缺少列 {ret_col}")

    # Prepare factor_df format for factor_analysis
    factor_df = pred_df.rename(columns={"pred": "factor"})[["ts_code", "trade_date", "factor"]]
    return_df = label_df[["ts_code", "trade_date", ret_col]].rename(columns={ret_col: "ret"})

    # IC
    ic_df = compute_ic(factor_df, return_df)

    # Group returns
    group_df = compute_group_returns(factor_df, return_df, n_groups=n_groups)

    # Summary
    from factor_analysis.engine import compute_coverage
    coverage_df = compute_coverage(factor_df)
    summary = build_summary(ic_df, group_df, coverage_df)

    return {
        "summary": summary,
        "daily_ic": ic_df,
        "group_returns": group_df,
    }


def print_evaluation(result: Dict[str, Any]) -> None:
    """打印评估结果到终端"""
    s = result["summary"]
    ic = s.get("ic", {})
    print(f"\n{'='*50}")
    print(f"IC Mean:    {ic.get('mean', 'N/A'):.4f}" if ic.get('mean') else "IC Mean:    N/A")
    print(f"IC Std:     {ic.get('std', 'N/A'):.4f}" if ic.get('std') else "IC Std:     N/A")
    print(f"ICIR:       {ic.get('icir', 'N/A'):.4f}" if ic.get('icir') else "ICIR:       N/A")
    print(f"IC > 0 %:   {ic.get('positive_rate', 'N/A'):.1%}" if ic.get('positive_rate') else "IC > 0 %:   N/A")
    print(f"IC Count:   {ic.get('count', 0)}")

    avg_gr = s.get("avg_group_returns", {})
    if avg_gr:
        print(f"\nGroup Returns (avg):")
        for g, v in sorted(avg_gr.items()):
            print(f"  Group {g}: {v:.4%}")
    print(f"{'='*50}\n")
```

- [ ] **Step 2: Commit**

```bash
git add ml_research/evaluate.py
git commit -m "feat(ml): add model evaluation (IC, group returns)"
```

---

## Task 7: Pipeline

**Files:**
- Create: `ml_research/pipeline.py`

**Design:** Orchestrates the full workflow:
1. Get trade dates from calendar
2. Build feature matrix (with caching to parquet)
3. Build labels (with caching)
4. Walk-forward split
5. For each split: train → predict → collect predictions
6. Save predictions and model artifacts to `experiments/`

- [ ] **Step 1: Implement `ml_research/pipeline.py`**

```python
"""
训练 Pipeline：串联 features → labels → split → train → predict
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
from loguru import logger

from backtest.data_loader import DataLoader
from ml_research.config import MLConfig, default_config
from ml_research.features import build_feature_matrix, rank_normalize
from ml_research.labels import build_labels
from ml_research.splitter import walk_forward
from ml_research.models.lightgbm_model import LightGBMModel
from ml_research.evaluate import evaluate_predictions, print_evaluation


def get_trade_dates(
    dl: DataLoader,
    start_date: str,
    end_date: str,
) -> list[str]:
    """获取区间内的交易日列表（YYYY-MM-DD 格式）"""
    cal = dl.get_trade_calendar(start_date=start_date, end_date=end_date, only_open=True)
    return sorted(cal["trade_date"].tolist())


def run_pipeline(
    start_date: str = "2016-01-01",
    end_date: str = "2026-04-29",
    config: Optional[MLConfig] = None,
    cache_dir: Optional[Path] = None,
) -> dict:
    """
    运行完整的 ML 训练 Pipeline。

    Args:
        start_date: 数据起始日期
        end_date: 数据结束日期
        config: ML 配置，None 使用默认
        cache_dir: 缓存目录，None 不缓存

    Returns:
        dict with keys: predictions, evaluation, model, config
    """
    cfg = config or default_config
    dl = DataLoader()

    # === 1. 交易日 ===
    trade_dates = get_trade_dates(dl, start_date, end_date)
    logger.info(f"Trade dates: {len(trade_dates)} ({trade_dates[0]} ~ {trade_dates[-1]})")

    # === 2. 特征矩阵 ===
    feature_cache = cache_dir / "features.parquet" if cache_dir else None
    if feature_cache and feature_cache.exists():
        logger.info(f"Loading cached features from {feature_cache}")
        feature_df = pd.read_parquet(feature_cache)
    else:
        feature_df = build_feature_matrix(
            dl, trade_dates,
            momentum_windows=cfg.momentum_windows,
            volatility_window=cfg.volatility_window,
        )
        if feature_cache:
            feature_cache.parent.mkdir(parents=True, exist_ok=True)
            feature_df.to_parquet(feature_cache, index=False)
            logger.info(f"Features cached to {feature_cache}")

    # Feature columns = all except ts_code, trade_date
    feature_cols = [c for c in feature_df.columns if c not in ("ts_code", "trade_date")]

    # Rank normalize
    feature_df = rank_normalize(feature_df, feature_cols)
    logger.info(f"Features: {len(feature_df)} rows, {len(feature_cols)} columns")

    # === 3. 标签 ===
    label_cache = cache_dir / f"labels_{cfg.forward_days}d.parquet" if cache_dir else None
    if label_cache and label_cache.exists():
        logger.info(f"Loading cached labels from {label_cache}")
        label_df = pd.read_parquet(label_cache)
    else:
        label_df = build_labels(dl, trade_dates, forward_days=cfg.forward_days)
        if label_cache:
            label_df.to_parquet(label_cache, index=False)
            logger.info(f"Labels cached to {label_cache}")

    logger.info(f"Labels: {len(label_df)} rows")

    # === 4. 合并 & 清洗 ===
    ret_col = f"ret_{cfg.forward_days}d"
    merged = feature_df.merge(
        label_df[["ts_code", "trade_date", ret_col]],
        on=["ts_code", "trade_date"],
        how="inner",
    )
    merged = merged.dropna(subset=[ret_col])
    merged = merged.dropna(subset=feature_cols, how="all")
    logger.info(f"Merged dataset: {len(merged)} rows")

    # === 5. Walk-Forward 训练 ===
    available_dates = sorted(merged["trade_date"].unique().tolist())
    splits = walk_forward(
        available_dates,
        train_days=cfg.train_days,
        test_days=cfg.test_days,
        step_days=cfg.step_days,
        mode="rolling",
    )
    logger.info(f"Walk-forward splits: {len(splits)}")

    all_preds = []
    last_model = None

    for i, split in enumerate(splits):
        logger.info(f"Split {i+1}/{len(splits)}: train {len(split['train_dates'])}d, test {len(split['test_dates'])}d")

        train_data = merged[merged["trade_date"].isin(split["train_dates"])]
        test_data = merged[merged["trade_date"].isin(split["test_dates"])]

        X_train = train_data[feature_cols]
        y_train = train_data[ret_col]
        X_test = test_data[feature_cols]

        # Drop rows with NaN features
        train_mask = X_train.notna().all(axis=1)
        test_mask = X_test.notna().all(axis=1)

        if train_mask.sum() < 100 or test_mask.sum() < 10:
            logger.warning(f"Split {i+1}: insufficient data, skipping")
            continue

        model = LightGBMModel(params=cfg.lgb_params.copy())
        model.fit(X_train[train_mask], y_train[train_mask])

        preds = model.predict(X_test[test_mask])
        pred_df = test_data[test_mask][["ts_code", "trade_date"]].copy()
        pred_df["pred"] = preds
        all_preds.append(pred_df)

        last_model = model

    if not all_preds:
        logger.error("No predictions generated")
        return {"predictions": pd.DataFrame(), "evaluation": {}, "model": None, "config": cfg}

    predictions = pd.concat(all_preds, ignore_index=True)
    logger.info(f"Total predictions: {len(predictions)}")

    # === 6. 评估 ===
    eval_result = evaluate_predictions(predictions, label_df, forward_days=cfg.forward_days)
    print_evaluation(eval_result)

    # === 7. 保存 ===
    exp_dir = Path("ml_research/experiments") / cfg.experiment_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    predictions.to_parquet(exp_dir / "predictions.parquet", index=False)

    if last_model:
        last_model.save(exp_dir / "model.lgb")
        fi = last_model.feature_importance()
        fi.to_csv(exp_dir / "feature_importance.csv", index=False)

    # Save config
    import dataclasses
    with open(exp_dir / "config.json", "w") as f:
        json.dump(dataclasses.asdict(cfg), f, indent=2, default=str)

    logger.info(f"Experiment saved to {exp_dir}")

    return {
        "predictions": predictions,
        "evaluation": eval_result,
        "model": last_model,
        "config": cfg,
    }
```

- [ ] **Step 2: Commit**

```bash
git add ml_research/pipeline.py
git commit -m "feat(ml): add training pipeline with walk-forward and caching"
```

---

## Task 8: Signal Generation (Backtest Integration)

**Files:**
- Create: `ml_research/signal.py`

**Design:** `MLStrategy` is a `StrategyTemplate` subclass. On each rebalance date, it loads model predictions (from a saved parquet), selects top_n stocks by predicted return, and equal-weights them via `order_target_percent()`.

- [ ] **Step 1: Implement `ml_research/signal.py`**

```python
"""
信号生成：将模型预测转为回测策略
"""
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from loguru import logger

from backtest.strategy import StrategyTemplate


class MLStrategy(StrategyTemplate):
    """
    基于 ML 预测的选股策略。

    从 pipeline 输出的 predictions.parquet 加载预测分数，
    每个调仓日选 top_n 等权配置。
    """

    def __init__(
        self,
        predictions_path: str | Path,
        top_n: int = 20,
        rebalance_freq: int = 5,
    ):
        super().__init__("MLStrategy")
        self.predictions_path = Path(predictions_path)
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq
        self.day_count = 0
        self._pred_cache: Optional[pd.DataFrame] = None

    def _load_predictions(self) -> pd.DataFrame:
        if self._pred_cache is None:
            self._pred_cache = pd.read_parquet(self.predictions_path)
            # Normalize date format
            self._pred_cache["trade_date"] = pd.to_datetime(
                self._pred_cache["trade_date"]
            ).dt.strftime("%Y-%m-%d")
        return self._pred_cache

    def init(self, context: Dict):
        logger.info(f"MLStrategy init: top_n={self.top_n}, rebalance_freq={self.rebalance_freq}")
        self._load_predictions()
        self.day_count = 0

    def next(self, context: Dict):
        date = context["current_date"]
        date_str = pd.to_datetime(date).strftime("%Y-%m-%d")

        self.day_count += 1
        if self.day_count % self.rebalance_freq != 1 and self.day_count != 1:
            return

        pred_df = self._load_predictions()
        today_pred = pred_df[pred_df["trade_date"] == date_str]

        if today_pred.empty:
            return

        # Sort by prediction descending, take top N
        top = today_pred.nlargest(self.top_n, "pred")
        selected = set(top["ts_code"].tolist())

        weight = 0.9 / self.top_n if selected else 0

        # Get current holdings
        portfolio = context.get("portfolio", {})
        current_holdings = set(portfolio.get("positions", {}).keys())

        # Sell stocks not in selection
        for ts_code in current_holdings:
            if ts_code not in selected:
                context["order_target_percent"](ts_code, 0)

        # Buy selected stocks
        for ts_code in selected:
            context["order_target_percent"](ts_code, weight)

        logger.debug(f"{date_str} selected {len(selected)} stocks, weight={weight:.4f}")
```

- [ ] **Step 2: Commit**

```bash
git add ml_research/signal.py
git commit -m "feat(ml): add MLStrategy for backtest integration"
```

---

## Task 9: Integration Test — Run Full Pipeline

**Files:**
- Create: `tests/test_ml_pipeline.py`

**Design:** Integration test that runs the pipeline on a tiny date range to verify the full chain works end-to-end.

- [ ] **Step 1: Write integration test**

```python
# tests/test_ml_pipeline.py
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np


def test_pipeline_end_to_end():
    """
    Integration test: run pipeline on a small synthetic dataset.
    Verifies features → labels → split → train → predict → evaluate chain.
    """
    from ml_research.config import MLConfig
    from ml_research.pipeline import run_pipeline

    # This test requires real data to be present.
    # If data dir is empty, skip.
    data_dir = Path(__file__).parent.parent / "data" / "daily_bar"
    if not data_dir.exists() or not any(data_dir.glob("*/*.parquet")):
        pytest.skip("No market data available — skipping integration test")

    cfg = MLConfig(
        momentum_windows=[5, 10],
        volatility_window=10,
        forward_days=5,
        train_days=60,
        test_days=20,
        step_days=20,
        lgb_params={
            "objective": "regression",
            "metric": "mse",
            "learning_rate": 0.1,
            "num_leaves": 15,
            "max_depth": 4,
            "n_estimators": 50,
            "verbose": -1,
            "n_jobs": -1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        },
        experiment_name="test_run",
    )

    result = run_pipeline(
        start_date="2020-01-01",
        end_date="2020-12-31",
        config=cfg,
        cache_dir=None,  # No caching in tests
    )

    assert "predictions" in result
    assert "evaluation" in result
    assert len(result["predictions"]) > 0
    assert "summary" in result["evaluation"]
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_ml_pipeline.py
git commit -m "test(ml): add integration test for full pipeline"
```

---

## Task 10: Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add ML dependencies**

Append to `requirements.txt`:

```
# ML Research
lightgbm>=4.0.0
scikit-learn>=1.3.0
optuna>=3.4.0
matplotlib>=3.7.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install lightgbm scikit-learn optuna matplotlib`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add ML dependencies (lightgbm, sklearn, optuna)"
```

---

## Summary: Execution Order

| Task | What | Verify |
|---|---|---|
| 1 | Config + package skeleton | `import ml_research.config` |
| 2 | Feature engineering | `pytest tests/test_ml_features.py` |
| 3 | Label generation | `pytest tests/test_ml_labels.py` |
| 4 | Walk-forward splitter | `pytest tests/test_ml_splitter.py` |
| 5 | Model base + LightGBM | `from ml_research.models.lightgbm_model import LightGBMModel` |
| 6 | Evaluation module | `from ml_research.evaluate import evaluate_predictions` |
| 7 | Pipeline | `from ml_research.pipeline import run_pipeline` |
| 8 | Signal generation | `from ml_research.signal import MLStrategy` |
| 9 | Integration test | `pytest tests/test_ml_pipeline.py` |
| 10 | Dependencies | `pip install lightgbm scikit-learn` |

**How to use after implementation:**

```python
# 1. 训练模型
from ml_research.pipeline import run_pipeline
from ml_research.config import MLConfig

cfg = MLConfig(
    experiment_name="lgb_v1",
    forward_days=5,
    top_n=20,
)
result = run_pipeline(start_date="2016-01-01", end_date="2026-04-29", config=cfg,
                      cache_dir=Path("ml_research/experiments/lgb_v1/cache"))

# 2. 用预测结果跑回测
from ml_research.signal import MLStrategy
from backtest.strategy import run_strategy

strategy = MLStrategy(
    predictions_path="ml_research/experiments/lgb_v1/predictions.parquet",
    top_n=20,
    rebalance_freq=5,
)
run_strategy(strategy, start_date="20200101", end_date="20260429")
```
