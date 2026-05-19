from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backtest.data_loader import DataLoader
from factor_analysis.metrics import (
    build_summary,
    compute_coverage,
    compute_group_returns,
    compute_ic,
    compute_long_short_returns,
    compute_rank_ic,
    summarize_by_window,
)


@dataclass
class FactorAnalysisResult:
    start_date: str
    end_date: str
    sample_count: int
    date_count: int
    stock_count: int
    summary: dict[str, Any]
    charts: dict[str, list[dict[str, Any]]]
    tables: dict[str, list[dict[str, Any]]]
    details: list[dict[str, Any]]


class FactorAnalysisEngine:
    """执行单因子截面分析并统一计算 IC、分组收益和覆盖率。"""

    def __init__(
        self,
        start_date: str,
        end_date: str,
        windows: list[int] | None = None,
        universe: str = "all_a",
        filters: list[str] | None = None,
        rebalance_rule: str = "daily",
        quantiles: int = 5,
        ic_method: str = "spearman",
        factor_direction: str = "higher_better",
        winsorize: str | None = "mad",
        standardize: str | None = "zscore",
        neutralize: list[str] | None = None,
        data_loader: DataLoader | None = None,
        detail_limit: int = 1000,
    ):
        self.start_date = self._to_datetime(start_date)
        self.end_date = self._to_datetime(end_date)
        self.windows = sorted({int(item) for item in (windows or [1, 5, 10, 20]) if int(item) > 0})
        self.universe = universe
        self.filters = list(filters or [])
        self.rebalance_rule = rebalance_rule
        self.quantiles = max(2, int(quantiles))
        self.ic_method = ic_method
        self.factor_direction = factor_direction
        self.winsorize = winsorize
        self.standardize = standardize
        self.neutralize = list(neutralize or [])
        self.data_loader = data_loader or DataLoader()
        self.detail_limit = max(1, int(detail_limit))
        self.compute_func = None
        self.runtime_logs: list[dict[str, Any]] = []

    def set_compute(self, compute_func):
        self.compute_func = compute_func

    def run(self) -> FactorAnalysisResult:
        if self.compute_func is None:
            raise ValueError("未设置因子计算函数")
        if not self.windows:
            raise ValueError("至少需要一个收益窗口")

        trade_dates = self._load_trade_dates()
        if not trade_dates:
            raise ValueError("分析区间内没有交易日")
        factor_dates = self._select_factor_dates(trade_dates)

        factor_frames: list[pd.DataFrame] = []
        total_frames: list[pd.DataFrame] = []
        for date_str in factor_dates:
            current_date = pd.to_datetime(date_str)
            cross_section = self.data_loader.get_cross_section(
                current_date,
                fields=["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "volume", "amount"],
                adjust=None,
            )
            if cross_section is None or cross_section.empty:
                continue
            cross_section = self._filter_universe(cross_section)
            cross_section = self._apply_filters(cross_section)
            total_frames.append(cross_section[["ts_code", "trade_date"]].copy())
            context = {
                "start_date": self.start_date,
                "end_date": self.end_date,
                "current_date": current_date,
                "windows": self.windows,
                "universe": self.universe,
                "filters": self.filters,
                "data_loader": self.data_loader,
                "conn": self.data_loader.conn,
                "market_data": cross_section,
                "get_history": self.data_loader.get_history,
                "get_cross_section": self.data_loader.get_cross_section,
                "trade_date_index": self.data_loader.get_trade_date_index,
                "get_trade_dates": lambda values=trade_dates: values,
            }
            raw = self.compute_func(context)
            factor_df = self._normalize_factor_frame(raw, date_str)
            factor_df = self._filter_universe(factor_df)
            factor_df = self._apply_filters(factor_df)
            factor_df = self._preprocess_factor(factor_df)
            if not factor_df.empty:
                factor_frames.append(factor_df)

        if factor_frames:
            factor_df = pd.concat(factor_frames, ignore_index=True)
        else:
            factor_df = pd.DataFrame(columns=["ts_code", "trade_date", "factor"])
        total_df = pd.concat(total_frames, ignore_index=True) if total_frames else pd.DataFrame(columns=["ts_code", "trade_date"])

        returns_by_window = self._build_forward_returns(factor_df, trade_dates)
        ic_frames: list[pd.DataFrame] = []
        rank_ic_frames: list[pd.DataFrame] = []
        group_frames: list[pd.DataFrame] = []
        long_short_frames: list[pd.DataFrame] = []
        for window, return_df in returns_by_window.items():
            ic = compute_ic(factor_df, return_df, method=self.ic_method)
            ic["window"] = window
            ic_frames.append(ic)
            rank_ic = compute_rank_ic(factor_df, return_df)
            rank_ic = rank_ic.rename(columns={"ic": "rank_ic"})
            rank_ic["window"] = window
            rank_ic_frames.append(rank_ic)
            groups = compute_group_returns(factor_df, return_df, self.quantiles)
            groups["window"] = window
            group_frames.append(groups)
            long_short = compute_long_short_returns(groups, self.quantiles, self.factor_direction)
            long_short["window"] = window
            long_short_frames.append(long_short)

        ic_df = pd.concat(ic_frames, ignore_index=True) if ic_frames else pd.DataFrame(columns=["trade_date", "ic", "n", "window"])
        rank_ic_df = pd.concat(rank_ic_frames, ignore_index=True) if rank_ic_frames else pd.DataFrame(columns=["trade_date", "rank_ic", "n", "window"])
        group_df = pd.concat(group_frames, ignore_index=True) if group_frames else pd.DataFrame(columns=["trade_date", "group", "avg_ret", "n", "window"])
        long_short_df = pd.concat(long_short_frames, ignore_index=True) if long_short_frames else pd.DataFrame(columns=["trade_date", "long_short_ret", "window"])
        coverage_df = compute_coverage(factor_df, total_df)

        summary = self._build_window_summary(factor_df, ic_df, rank_ic_df, group_df, long_short_df, coverage_df)
        details = self._to_records(factor_df.head(self.detail_limit).rename(columns={"factor": "factor_value"}))
        charts = {
            "ic_series": self._to_records(ic_df.merge(rank_ic_df[["trade_date", "window", "rank_ic"]], on=["trade_date", "window"], how="left")),
            "group_returns": self._to_records(group_df),
            "long_short_curve": self._to_records(self._with_cumulative_long_short(long_short_df)),
            "coverage_series": self._to_records(coverage_df),
        }
        tables = {
            "latest_factor_samples": details[:100],
            "ic_table": self._summary_table(summary.get("ic", {}), "ic"),
            "group_return_table": self._to_records(group_df.groupby(["window", "group"], as_index=False)["avg_ret"].mean()) if not group_df.empty else [],
        }
        return FactorAnalysisResult(
            start_date=self.start_date.strftime("%Y-%m-%d"),
            end_date=self.end_date.strftime("%Y-%m-%d"),
            sample_count=int(len(factor_df)),
            date_count=int(factor_df["trade_date"].nunique()) if not factor_df.empty else 0,
            stock_count=int(factor_df["ts_code"].nunique()) if not factor_df.empty else 0,
            summary=summary,
            charts=charts,
            tables=tables,
            details=details,
        )

    def _load_trade_dates(self) -> list[str]:
        max_window = max(self.windows or [0])
        calendar = self.data_loader.get_trade_calendar(
            start_date=self.start_date,
            end_date=self.end_date + timedelta(days=max_window * 3 + 30),
            only_open=True,
        )
        if calendar.empty:
            return []
        return pd.to_datetime(calendar["trade_date"]).dt.strftime("%Y-%m-%d").tolist()

    def _select_factor_dates(self, trade_dates: list[str]) -> list[str]:
        start = self.start_date.strftime("%Y-%m-%d")
        end = self.end_date.strftime("%Y-%m-%d")
        dates = [date for date in trade_dates if start <= date <= end]
        if self.rebalance_rule == "weekly":
            grouped = pd.Series(dates, index=pd.to_datetime(dates)).groupby(pd.to_datetime(dates).to_period("W")).last()
            return grouped.tolist()
        if self.rebalance_rule == "monthly":
            grouped = pd.Series(dates, index=pd.to_datetime(dates)).groupby(pd.to_datetime(dates).to_period("M")).last()
            return grouped.tolist()
        return dates

    def _normalize_factor_frame(self, raw, current_date: str) -> pd.DataFrame:
        if raw is None:
            return pd.DataFrame(columns=["ts_code", "trade_date", "factor"])
        if not isinstance(raw, pd.DataFrame):
            raise ValueError("compute(context) 必须返回 pandas DataFrame")
        df = raw.copy()
        value_col = next((col for col in ["factor_value", "factor", "value"] if col in df.columns), None)
        if value_col is None:
            raise ValueError("因子结果缺少必要列: factor_value")
        if "ts_code" not in df.columns:
            raise ValueError("因子结果缺少必要列: ts_code")
        if "trade_date" not in df.columns:
            df["trade_date"] = current_date
        df = df.rename(columns={value_col: "factor"})
        df["ts_code"] = df["ts_code"].astype(str)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        df["factor"] = pd.to_numeric(df["factor"], errors="coerce")
        df = df.dropna(subset=["factor"])
        df = df[(df["trade_date"] >= self.start_date.strftime("%Y-%m-%d")) & (df["trade_date"] <= self.end_date.strftime("%Y-%m-%d"))].copy()
        before = len(df)
        df = df.drop_duplicates(["ts_code", "trade_date"], keep="last")
        if before != len(df):
            self.runtime_logs.append({"level": "warning", "message": f"因子样本去重 {before - len(df)} 条"})
        return df[["ts_code", "trade_date", "factor"]]

    def _build_forward_returns(self, factor_df: pd.DataFrame, trade_dates: list[str]) -> dict[int, pd.DataFrame]:
        results = {window: pd.DataFrame(columns=["ts_code", "trade_date", "ret"]) for window in self.windows}
        if factor_df.empty:
            return results
        date_index = {date: idx for idx, date in enumerate(trade_dates)}
        start = min(factor_df["trade_date"])
        max_idx = min(len(trade_dates) - 1, max(date_index.get(date, 0) for date in factor_df["trade_date"]) + max(self.windows))
        end = trade_dates[max_idx]
        price_df = self.data_loader.conn.execute(
            """
            SELECT ts_code, trade_date, close
            FROM daily_bar
            WHERE trade_date BETWEEN ? AND ?
            """,
            [start, end],
        ).fetchdf()
        if price_df.empty:
            return results
        price_df["ts_code"] = price_df["ts_code"].astype(str)
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.strftime("%Y-%m-%d")
        price_map = {
            (row["ts_code"], row["trade_date"]): float(row["close"])
            for row in price_df.to_dict(orient="records")
            if row.get("close") is not None
        }
        for window in self.windows:
            rows = []
            for item in factor_df[["ts_code", "trade_date"]].to_dict(orient="records"):
                idx = date_index.get(item["trade_date"])
                if idx is None or idx + window >= len(trade_dates):
                    continue
                future_date = trade_dates[idx + window]
                start_price = price_map.get((item["ts_code"], item["trade_date"]))
                future_price = price_map.get((item["ts_code"], future_date))
                if start_price is None or future_price is None or start_price == 0:
                    continue
                rows.append({"ts_code": item["ts_code"], "trade_date": item["trade_date"], "ret": future_price / start_price - 1})
            results[window] = pd.DataFrame(rows, columns=["ts_code", "trade_date", "ret"])
        return results

    def _preprocess_factor(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        work = df.copy()
        if self.winsorize == "mad":
            work["factor"] = work.groupby("trade_date")["factor"].transform(self._mad_clip)
        if self.standardize == "zscore":
            work["factor"] = work.groupby("trade_date")["factor"].transform(self._zscore)
        return work.dropna(subset=["factor"])

    def _filter_universe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or self.universe == "all_a":
            return df
        work = df.copy()
        if self.universe == "exclude_beijing":
            return work[~work["ts_code"].str.endswith(".BJ")].copy()
        if self.universe == "main_board_only":
            return work[~work["ts_code"].str.startswith(("300", "301", "688")) & ~work["ts_code"].str.endswith(".BJ")].copy()
        return work

    def _apply_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or not self.filters:
            return df
        work = df.copy()
        filters = set(self.filters)
        instruments: pd.DataFrame | None = None

        def get_instruments() -> pd.DataFrame:
            nonlocal instruments
            if instruments is None:
                try:
                    instruments = self.data_loader.conn.execute(
                        """
                        SELECT ts_code, symbol, exchange, list_date
                        FROM instruments
                        WHERE status = 'L'
                        """
                    ).fetchdf()
                except Exception:
                    instruments = pd.DataFrame(columns=["ts_code", "symbol", "exchange", "list_date"])
                if not instruments.empty:
                    instruments["ts_code"] = instruments["ts_code"].astype(str)
            return instruments

        if "exclude_beijing" in filters:
            work = work[~work["ts_code"].str.endswith(".BJ")].copy()
        if "exclude_kcb_cyb" in filters:
            work = work[~work["ts_code"].str.startswith(("300", "301", "688"))].copy()
        if "exclude_main_board" in filters:
            work = work[work["ts_code"].str.startswith(("300", "301", "688")) | work["ts_code"].str.endswith(".BJ")].copy()
        if "exclude_st" in filters:
            inst = get_instruments()
            if not inst.empty and "symbol" in inst.columns:
                st_codes = set(inst.loc[inst["symbol"].astype(str).str.contains("ST", na=False), "ts_code"])
                work = work[~work["ts_code"].isin(st_codes)].copy()
        if "exclude_new_stock" in filters:
            inst = get_instruments()
            if not inst.empty and "list_date" in inst.columns:
                list_dates = inst.set_index("ts_code")["list_date"].to_dict()
                keep_mask = work.apply(
                    lambda row: self._days_since_list(list_dates.get(row["ts_code"]), row["trade_date"]) >= 180,
                    axis=1,
                )
                work = work[keep_mask].copy()
        return work

    def _build_window_summary(self, factor_df, ic_df, rank_ic_df, group_df, long_short_df, coverage_df) -> dict[str, Any]:
        first_window = self.windows[0] if self.windows else None
        legacy = build_summary(
            ic_df[ic_df["window"] == first_window].drop(columns=["window"], errors="ignore") if first_window else ic_df,
            group_df[group_df["window"] == first_window].drop(columns=["window"], errors="ignore") if first_window else group_df,
            coverage_df,
            long_short_df[long_short_df["window"] == first_window].drop(columns=["window"], errors="ignore") if first_window else long_short_df,
        )
        summary: dict[str, Any] = {
            "sample_count": int(len(factor_df)),
            "date_count": int(factor_df["trade_date"].nunique()) if not factor_df.empty else 0,
            "stock_count": int(factor_df["ts_code"].nunique()) if not factor_df.empty else 0,
            "ic": summarize_by_window(ic_df, "ic"),
            "rank_ic": summarize_by_window(rank_ic_df, "rank_ic"),
            "group_returns": self._summarize_group_returns(group_df),
            "long_short": summarize_by_window(long_short_df, "long_short_ret"),
            "coverage": legacy.get("coverage", {}),
        }
        if not summary["ic"]:
            summary["ic"] = legacy.get("ic", {})
        return summary

    def _summarize_group_returns(self, group_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
        if group_df.empty:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for window, frame in group_df.groupby("window"):
            result[f"{int(window)}d"] = {
                str(int(group)): float(value)
                for group, value in frame.groupby("group")["avg_ret"].mean().items()
            }
        return result

    def _with_cumulative_long_short(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        work = df.sort_values(["window", "trade_date"]).copy()
        work["cumulative_long_short_ret"] = work.groupby("window")["long_short_ret"].transform(lambda s: (1 + s.fillna(0)).cumprod() - 1)
        return work

    def _summary_table(self, data: dict[str, Any], metric: str) -> list[dict[str, Any]]:
        rows = []
        for window, values in data.items():
            if isinstance(values, dict):
                rows.append({"window": window, metric: values.get("mean"), **values})
        return rows

    @staticmethod
    def _mad_clip(values: pd.Series) -> pd.Series:
        median = values.median()
        mad = (values - median).abs().median()
        if pd.isna(mad) or mad == 0:
            return values
        return values.clip(median - 5 * mad, median + 5 * mad)

    @staticmethod
    def _zscore(values: pd.Series) -> pd.Series:
        std = values.std()
        if pd.isna(std) or std == 0:
            return values - values.mean()
        return (values - values.mean()) / std

    @staticmethod
    def _to_datetime(date_value: str | datetime) -> datetime:
        if isinstance(date_value, datetime):
            return date_value
        text = str(date_value)
        return datetime.strptime(text, "%Y-%m-%d" if "-" in text else "%Y%m%d")

    @staticmethod
    def _days_since_list(list_date, trade_date) -> int:
        if list_date is None or pd.isna(list_date):
            return 999999
        try:
            listed_at = FactorAnalysisEngine._to_datetime(str(list_date))
            traded_at = FactorAnalysisEngine._to_datetime(str(trade_date))
            return (traded_at - listed_at).days
        except Exception:
            return 999999

    @staticmethod
    def _to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
        records = []
        for row in df.replace({np.nan: None}).to_dict(orient="records"):
            records.append({key: _json_value(value) for key, value in row.items()})
        return records


def _json_value(value):
    if hasattr(value, "item"):
        return value.item()
    return value
