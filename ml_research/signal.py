"""
信号生成：将模型预测转为回测策略
"""
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from loguru import logger

from backtest.strategy import StrategyTemplate
from backtest.data_loader import DataLoader
from ml_research.pool_filters import get_candidate_pool, get_mainboard_pool


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
        pool_name: str = "all",
        candidate_count: int = 100,
        min_net_profit: float = 0.0,
        avoid_limit_up: bool = True,
        replace_on_limit_up: bool = True,
        limit_up_tolerance: float = 0.01,
    ):
        super().__init__("MLStrategy")
        self.predictions_path = Path(predictions_path)
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq
        self.pool_name = pool_name
        self.candidate_count = candidate_count
        self.min_net_profit = min_net_profit
        self.avoid_limit_up = avoid_limit_up
        self.replace_on_limit_up = replace_on_limit_up
        self.limit_up_tolerance = limit_up_tolerance
        self.day_count = 0
        self._pred_cache: Optional[pd.DataFrame] = None
        self._dl: Optional[DataLoader] = None

    def _load_predictions(self) -> pd.DataFrame:
        if self._pred_cache is None:
            self._pred_cache = pd.read_parquet(self.predictions_path)
            self._pred_cache["trade_date"] = pd.to_datetime(
                self._pred_cache["trade_date"]
            ).dt.strftime("%Y-%m-%d")
        return self._pred_cache

    def init(self, context: Dict):
        logger.info(
            f"MLStrategy init: top_n={self.top_n}, rebalance_freq={self.rebalance_freq}, pool={self.pool_name}"
        )
        self._load_predictions()
        self.day_count = 0
        self._dl = context.get("data_loader") or DataLoader()

    def _get_tradeable_predictions(self, today_pred: pd.DataFrame, date_str: str) -> pd.DataFrame:
        if self._dl is None:
            self._dl = DataLoader()

        if self.pool_name == "sme_smallcap_ml":
            candidate_df = get_candidate_pool(
                self._dl,
                date_str,
                candidate_count=self.candidate_count,
                min_net_profit=self.min_net_profit,
            )
            if candidate_df.empty:
                logger.warning(f"{date_str} candidate pool empty")
                return today_pred.iloc[0:0].copy()
            today_pred = today_pred.merge(candidate_df[["ts_code"]], on="ts_code", how="inner")
            logger.debug(f"{date_str} candidate pool size={len(candidate_df)}, pred_in_pool={len(today_pred)}")
        elif self.pool_name == "mainboard":
            candidate_df = get_mainboard_pool(self._dl, date_str, exclude_st=True)
            if candidate_df.empty:
                logger.warning(f"{date_str} mainboard pool empty")
                return today_pred.iloc[0:0].copy()
            today_pred = today_pred.merge(candidate_df, on="ts_code", how="inner")
            logger.debug(f"{date_str} mainboard pool size={len(candidate_df)}, pred_in_pool={len(today_pred)}")

        if today_pred.empty or not self.avoid_limit_up:
            return today_pred

        limit_df = self._dl.conn.execute(
            f"""
            SELECT ts_code, up_limit
            FROM stk_limit
            WHERE trade_date = '{date_str}'
            """
        ).fetchdf()
        if limit_df.empty:
            return today_pred

        merged = today_pred.merge(limit_df, on="ts_code", how="left")
        merged["close"] = pd.to_numeric(merged.get("close"), errors="coerce")
        merged["up_limit"] = pd.to_numeric(merged.get("up_limit"), errors="coerce")
        near_limit = merged["close"] >= (merged["up_limit"] - self.limit_up_tolerance)
        blocked = int(near_limit.fillna(False).sum())
        if blocked > 0:
            logger.info(f"{date_str} 过滤接近涨停候选 {blocked} 只")
        return merged[~near_limit.fillna(False)].copy()

    def next(self, context: Dict):
        date = context["current_date"]
        date_str = pd.to_datetime(date).strftime("%Y-%m-%d")

        self.day_count += 1
        if self.day_count % self.rebalance_freq != 1 and self.day_count != 1:
            return

        pred_df = self._load_predictions()
        today_pred = pred_df[pred_df["trade_date"] == date_str].copy()

        if today_pred.empty:
            return

        today_pred = self._get_tradeable_predictions(today_pred, date_str)
        if today_pred.empty:
            logger.warning(f"{date_str} 无可交易候选，跳过调仓")
            return

        top = today_pred.nlargest(self.top_n, "pred")
        selected = set(top["ts_code"].tolist())
        weight = 0.9 / self.top_n if selected else 0

        portfolio = context.get("portfolio", {})
        current_holdings = set(portfolio.get("positions", {}).keys())

        for ts_code in current_holdings:
            if ts_code not in selected:
                context["order_target_percent"](ts_code, 0)

        cash = float(getattr(context.get("broker").account, "cash", 0.0)) if context.get("broker") else 0.0
        logger.debug(f"{date_str} initial cash={cash:.2f}")

        for ts_code in sorted(selected):
            context["order_target_percent"](ts_code, weight)

        logger.debug(f"{date_str} selected {len(selected)} stocks, weight={weight:.4f}")
