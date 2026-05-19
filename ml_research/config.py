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

    # === 股票池 / 过滤 ===
    pool_name: str = "all"
    candidate_count: int = 100
    min_net_profit: float = 0.0

    # === 路径 ===
    experiment_name: str = "default"


# 默认配置实例
default_config = MLConfig()
