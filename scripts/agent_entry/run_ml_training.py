"""
ML 训练标准入口（Agent 用）

一条命令完成：特征构建 → 标签生成 → Walk-Forward 训练 → 预测 → 评估 → 保存实验

示例：
    python scripts/agent_entry/run_ml_training.py \
        --start 2016-01-01 --end 2026-04-29 \
        --experiment-name lgb_v1 \
        --forward-days 5 --top-n 20

    # 自定义模型参数
    python scripts/agent_entry/run_ml_training.py \
        --start 2018-01-01 --end 2026-04-29 \
        --experiment-name lgb_small_cap \
        --forward-days 10 --top-n 30 \
        --train-days 756 --test-days 63

    # 使用缓存加速重复实验
    python scripts/agent_entry/run_ml_training.py \
        --start 2016-01-01 --end 2026-04-29 \
        --experiment-name lgb_v2 \
        --use-cache
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml_research.config import MLConfig
from ml_research.pipeline import run_pipeline
from ml_research.signal import MLStrategy
from backtest.strategy import run_strategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ML 模型训练 — Walk-Forward LightGBM 截面选股"
    )
    parser.add_argument("--start", default="2016-01-01", help="训练数据起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-04-29", help="训练数据结束日期 (YYYY-MM-DD)")
    parser.add_argument("--experiment-name", default="default", help="实验名称，用于保存目录")

    # 特征参数
    parser.add_argument("--momentum-windows", default="5,10,20,60", help="动量窗口，逗号分隔")
    parser.add_argument("--volatility-window", type=int, default=20, help="波动率窗口")

    # 标签参数
    parser.add_argument("--forward-days", type=int, default=5, help="前瞻收益天数")

    # Walk-Forward 参数
    parser.add_argument("--train-days", type=int, default=504, help="训练窗口（交易日）")
    parser.add_argument("--test-days", type=int, default=63, help="测试窗口（交易日）")
    parser.add_argument("--step-days", type=int, default=63, help="步进（交易日）")

    # 模型参数
    parser.add_argument("--n-estimators", type=int, default=500, help="树数量")
    parser.add_argument("--learning-rate", type=float, default=0.05, help="学习率")
    parser.add_argument("--num-leaves", type=int, default=63, help="叶子数")
    parser.add_argument("--max-depth", type=int, default=7, help="最大深度")

    # 信号参数
    parser.add_argument("--top-n", type=int, default=20, help="选股数量")
    parser.add_argument("--rebalance-freq", type=int, default=5, help="调仓频率（交易日）")
    parser.add_argument("--pool-name", default="all", help="股票池方案：all / sme_smallcap_ml")
    parser.add_argument("--candidate-count", type=int, default=100, help="候选池数量（如先取最小流通市值前100）")
    parser.add_argument("--min-net-profit", type=float, default=0.0, help="最新完整年报净利润下限")

    # 缓存
    parser.add_argument("--use-cache", action="store_true", help="使用特征/标签缓存")

    # 回测验证
    parser.add_argument("--run-backtest", action="store_true", help="训练完成后自动跑回测验证")
    parser.add_argument("--backtest-start", default=None, help="回测开始日期（默认与训练 end 相同）")
    parser.add_argument("--backtest-end", default=None, help="回测结束日期")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    momentum_windows = [int(x) for x in args.momentum_windows.split(",")]

    cfg = MLConfig(
        momentum_windows=momentum_windows,
        volatility_window=args.volatility_window,
        forward_days=args.forward_days,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        lgb_params={
            "objective": "regression",
            "metric": "mse",
            "learning_rate": args.learning_rate,
            "num_leaves": args.num_leaves,
            "max_depth": args.max_depth,
            "n_estimators": args.n_estimators,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "verbose": -1,
            "n_jobs": -1,
        },
        top_n=args.top_n,
        rebalance_freq=args.rebalance_freq,
        pool_name=args.pool_name,
        candidate_count=args.candidate_count,
        min_net_profit=args.min_net_profit,
        experiment_name=args.experiment_name,
    )

    cache_dir = (
        Path("ml_research/experiments") / args.experiment_name / "cache"
        if args.use_cache
        else None
    )

    print(f"[{datetime.now():%H:%M:%S}] Starting ML training: {args.experiment_name}")
    print(f"  Period: {args.start} ~ {args.end}")
    print(f"  Forward: {args.forward_days}d | Top N: {args.top_n}")
    print(f"  Train: {args.train_days}d | Test: {args.test_days}d | Step: {args.step_days}d")

    result = run_pipeline(
        start_date=args.start,
        end_date=args.end,
        config=cfg,
        cache_dir=cache_dir,
    )

    if result["predictions"].empty:
        print("ERROR: No predictions generated. Check data availability.")
        return 1

    # 输出实验摘要
    exp_dir = Path("ml_research/experiments") / args.experiment_name
    summary = result["evaluation"].get("summary", {})
    ic = summary.get("ic", {})

    output = {
        "experiment_name": args.experiment_name,
        "status": "success",
        "predictions_count": len(result["predictions"]),
        "ic_mean": ic.get("mean"),
        "icir": ic.get("icir"),
        "ic_positive_rate": ic.get("positive_rate"),
        "experiment_dir": str(exp_dir),
        "predictions_path": str(exp_dir / "predictions.parquet"),
        "model_path": str(exp_dir / "model.lgb"),
        "feature_importance_path": str(exp_dir / "feature_importance.csv"),
    }

    print(f"\n{'='*50}")
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"{'='*50}")

    # 可选：自动跑回测验证
    if args.run_backtest:
        bt_start = args.backtest_start or args.end
        bt_end = args.backtest_end or args.end
        # 将 YYYY-MM-DD 转为 YYYYMMDD
        bt_start_fmt = bt_start.replace("-", "")
        bt_end_fmt = bt_end.replace("-", "")

        print(f"\n[{datetime.now():%H:%M:%S}] Running backtest: {bt_start} ~ {bt_end}")
        strategy = MLStrategy(
            predictions_path=exp_dir / "predictions.parquet",
            top_n=args.top_n,
            rebalance_freq=args.rebalance_freq,
            pool_name=args.pool_name,
            candidate_count=args.candidate_count,
            min_net_profit=args.min_net_profit,
        )
        bt_result = run_strategy(strategy, start_date=bt_start_fmt, end_date=bt_end_fmt)
        output["backtest"] = {
            "total_return": bt_result.total_return,
            "annual_return": bt_result.annual_return,
            "max_drawdown": bt_result.max_drawdown,
            "sharpe_ratio": bt_result.sharpe_ratio,
        }
        print(f"\nBacktest Result:")
        print(f"  Return: {bt_result.total_return:.2%}")
        print(f"  Sharpe: {bt_result.sharpe_ratio:.2f}")
        print(f"  MaxDD:  {bt_result.max_drawdown:.2%}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
