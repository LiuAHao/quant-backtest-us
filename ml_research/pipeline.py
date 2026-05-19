"""
训练 Pipeline：串联 features → labels → split → train → predict
"""
import json
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from backtest.data_loader import DataLoader
from ml_research.config import MLConfig, default_config
from ml_research.features import build_feature_matrix, rank_normalize
from ml_research.labels import build_labels
from ml_research.pool_filters import filter_to_candidate_pool, filter_to_mainboard_pool
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
    """
    cfg = config or default_config
    dl = DataLoader()

    trade_dates = get_trade_dates(dl, start_date, end_date)
    logger.info(f"Trade dates: {len(trade_dates)} ({trade_dates[0]} ~ {trade_dates[-1]})")

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

    if cfg.pool_name == "sme_smallcap_ml":
        before_rows = len(feature_df)
        feature_df = filter_to_candidate_pool(
            feature_df,
            dl,
            candidate_count=cfg.candidate_count,
            min_net_profit=cfg.min_net_profit,
            trade_dates=trade_dates,
        )
        logger.info(f"Feature pool filter: {before_rows} -> {len(feature_df)}")
    elif cfg.pool_name == "mainboard":
        before_rows = len(feature_df)
        feature_df = filter_to_mainboard_pool(feature_df, dl, trade_dates=trade_dates)
        logger.info(f"Feature mainboard filter: {before_rows} -> {len(feature_df)}")

    feature_cols = [c for c in feature_df.columns if c not in ("ts_code", "trade_date")]
    feature_df = rank_normalize(feature_df, feature_cols)
    logger.info(f"Features: {len(feature_df)} rows, {len(feature_cols)} columns")

    label_cache = cache_dir / f"labels_{cfg.forward_days}d.parquet" if cache_dir else None
    if label_cache and label_cache.exists():
        logger.info(f"Loading cached labels from {label_cache}")
        label_df = pd.read_parquet(label_cache)
    else:
        label_df = build_labels(dl, trade_dates, forward_days=cfg.forward_days)
        if label_cache:
            label_df.to_parquet(label_cache, index=False)
            logger.info(f"Labels cached to {label_cache}")

    if cfg.pool_name == "sme_smallcap_ml":
        before_rows = len(label_df)
        label_df = filter_to_candidate_pool(
            label_df,
            dl,
            candidate_count=cfg.candidate_count,
            min_net_profit=cfg.min_net_profit,
            trade_dates=trade_dates,
        )
        logger.info(f"Label pool filter: {before_rows} -> {len(label_df)}")
    elif cfg.pool_name == "mainboard":
        before_rows = len(label_df)
        label_df = filter_to_mainboard_pool(label_df, dl, trade_dates=trade_dates)
        logger.info(f"Label mainboard filter: {before_rows} -> {len(label_df)}")

    logger.info(f"Labels: {len(label_df)} rows")

    ret_col = f"ret_{cfg.forward_days}d"
    merged = feature_df.merge(
        label_df[["ts_code", "trade_date", ret_col]],
        on=["ts_code", "trade_date"],
        how="inner",
    )
    merged = merged.dropna(subset=[ret_col])
    merged = merged.dropna(subset=feature_cols, how="all")
    logger.info(f"Merged dataset: {len(merged)} rows")

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

    eval_result = evaluate_predictions(predictions, label_df, forward_days=cfg.forward_days)
    print_evaluation(eval_result)

    exp_dir = Path("ml_research/experiments") / cfg.experiment_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    predictions.to_parquet(exp_dir / "predictions.parquet", index=False)

    if last_model:
        last_model.save(exp_dir / "model.lgb")
        fi = last_model.feature_importance()
        fi.to_csv(exp_dir / "feature_importance.csv", index=False)

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
