from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backtest.data_loader import DataLoader
from event_analysis.result_builder import build_summary


@dataclass
class EventAnalysisResult:
    start_date: str
    end_date: str
    sample_count: int
    summary: dict[str, Any]
    details: list[dict[str, Any]]


class EventAnalysisEngine:
    """执行事件扫描并统一计算未来收益。"""

    def __init__(
        self,
        start_date: str,
        end_date: str,
        windows: list[int] | None = None,
        entry_rule: str = "next_open",
        dedup_rule: str = "none",
        universe: str = "all_a",
        filters: list[str] | None = None,
    ):
        self.start_date = self._to_datetime(start_date)
        self.end_date = self._to_datetime(end_date)
        self.windows = sorted({int(item) for item in (windows or [5, 10, 15]) if int(item) > 0})
        self.entry_rule = entry_rule
        self.dedup_rule = dedup_rule
        self.universe = universe
        self.filters = list(filters or [])
        self.data_loader = DataLoader()
        self.scan_func = None

    def set_scan(self, scan_func):
        self.scan_func = scan_func

    def run(self) -> EventAnalysisResult:
        if self.scan_func is None:
            raise ValueError("未设置事件扫描函数")

        trade_dates = self.data_loader.get_trade_calendar(
            start_date=self.start_date,
            end_date=self.end_date + timedelta(days=max(self.windows or [0]) * 3 + 30),
            only_open=True,
        )
        trade_date_list = pd.to_datetime(trade_dates["trade_date"]).dt.strftime("%Y-%m-%d").tolist()
        trade_date_index = {value: idx for idx, value in enumerate(trade_date_list)}

        context = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "windows": self.windows,
            "entry_rule": self.entry_rule,
            "dedup_rule": self.dedup_rule,
            "universe": self.universe,
            "filters": self.filters,
            "data_loader": self.data_loader,
            "conn": self.data_loader.conn,
            "get_history": self.data_loader.get_history,
            "get_cross_section": self.data_loader.get_cross_section,
            "trade_date_index": self.data_loader.get_trade_date_index,
            "get_trade_dates": lambda: trade_date_list,
        }

        raw_samples = self.scan_func(context)
        sample_df = self._normalize_samples(raw_samples)
        sample_df = self._filter_universe(sample_df)
        sample_df = self._apply_filters(sample_df)
        sample_df = self._apply_dedup(sample_df, trade_date_index)
        detail_df = self._attach_returns(sample_df, trade_date_index)
        detail_df = detail_df.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        summary = build_summary(detail_df, self.windows)
        return EventAnalysisResult(
            start_date=self.start_date.strftime("%Y-%m-%d"),
            end_date=self.end_date.strftime("%Y-%m-%d"),
            sample_count=int(len(detail_df)),
            summary=summary,
            details=self._to_records(detail_df),
        )

    def _normalize_samples(self, raw_samples) -> pd.DataFrame:
        if raw_samples is None:
            return pd.DataFrame(columns=["ts_code", "trade_date"])
        if not isinstance(raw_samples, pd.DataFrame):
            raise ValueError("scan(context) 必须返回 pandas DataFrame")
        sample_df = raw_samples.copy()
        required = {"ts_code", "trade_date"}
        missing = [field for field in required if field not in sample_df.columns]
        if missing:
            raise ValueError(f"事件样本缺少必要列: {', '.join(missing)}")
        sample_df["ts_code"] = sample_df["ts_code"].astype(str)
        sample_df["trade_date"] = pd.to_datetime(sample_df["trade_date"]).dt.strftime("%Y-%m-%d")
        sample_df = sample_df[
            (sample_df["trade_date"] >= self.start_date.strftime("%Y-%m-%d"))
            & (sample_df["trade_date"] <= self.end_date.strftime("%Y-%m-%d"))
        ].copy()
        return sample_df

    def _filter_universe(self, sample_df: pd.DataFrame) -> pd.DataFrame:
        if sample_df.empty or self.universe == "all_a":
            return sample_df
        work = sample_df.copy()
        if self.universe == "exclude_beijing":
            return work[~work["ts_code"].str.endswith(".BJ")].copy()
        if self.universe == "main_board_only":
            return work[
                ~work["ts_code"].str.startswith(("300", "301", "688"))
                & ~work["ts_code"].str.endswith(".BJ")
            ].copy()
        return work

    def _apply_filters(self, sample_df: pd.DataFrame) -> pd.DataFrame:
        if sample_df.empty or not self.filters:
            return sample_df
        work = sample_df.copy()
        instruments = None

        def get_instruments() -> pd.DataFrame:
            nonlocal instruments
            if instruments is None:
                instruments = self.data_loader.conn.execute(
                    """
                    SELECT ts_code, symbol, exchange, list_date
                    FROM instruments
                    WHERE status = 'L'
                    """
                ).fetchdf()
            return instruments

        filters_set = set(self.filters)

        if "exclude_beijing" in filters_set:
            work = work[~work["ts_code"].str.endswith(".BJ")].copy()

        if "exclude_kcb_cyb" in filters_set:
            work = work[~work["ts_code"].str.startswith(("300", "301", "688"))].copy()

        if "exclude_main_board" in filters_set:
            work = work[
                work["ts_code"].str.startswith(("300", "301", "688")) | work["ts_code"].str.endswith(".BJ")
            ].copy()

        if "exclude_st" in filters_set:
            instr = get_instruments()
            if not instr.empty:
                st_codes = set(instr[instr["symbol"].astype(str).str.contains("ST", na=False)]["ts_code"].astype(str).tolist())
                work = work[~work["ts_code"].isin(st_codes)].copy()

        if "exclude_new_stock" in filters_set:
            instr = get_instruments()
            if not instr.empty:
                list_map = {
                    str(row["ts_code"]): str(row["list_date"])
                    for row in instr.to_dict(orient="records")
                    if row.get("list_date")
                }
                work = work[
                    work.apply(
                        lambda row: self._days_since_list(list_map.get(str(row["ts_code"])), str(row["trade_date"])) >= 180,
                        axis=1,
                    )
                ].copy()

        return work

    @staticmethod
    def _days_since_list(list_date: str | None, trade_date: str) -> int:
        if not list_date:
            return -1
        try:
            start = datetime.strptime(list_date, "%Y-%m-%d" if "-" in list_date else "%Y%m%d")
            end = datetime.strptime(trade_date, "%Y-%m-%d")
            return (end - start).days
        except ValueError:
            return -1

    def _apply_dedup(self, sample_df: pd.DataFrame, trade_date_index: dict[str, int]) -> pd.DataFrame:
        if sample_df.empty:
            return sample_df
        work = sample_df.sort_values(["ts_code", "trade_date"]).drop_duplicates(["ts_code", "trade_date"]).copy()
        gap_map = {
            "per_stock_gap_5": 5,
            "per_stock_gap_10": 10,
        }
        gap = gap_map.get(self.dedup_rule)
        if gap is None:
            return work
        kept_rows = []
        last_index_by_code: dict[str, int] = {}
        for row in work.itertuples(index=False):
            current_idx = trade_date_index.get(row.trade_date)
            if current_idx is None:
                continue
            last_idx = last_index_by_code.get(row.ts_code)
            if last_idx is not None and current_idx - last_idx < gap:
                continue
            kept_rows.append(row)
            last_index_by_code[row.ts_code] = current_idx
        return pd.DataFrame(kept_rows, columns=work.columns)

    def _attach_returns(self, sample_df: pd.DataFrame, trade_date_index: dict[str, int]) -> pd.DataFrame:
        if sample_df.empty:
            return sample_df

        max_window = max(self.windows or [0])
        all_dates = list(trade_date_index.keys())
        entry_dates: list[str | None] = []
        for trade_date in sample_df["trade_date"]:
            idx = trade_date_index.get(trade_date)
            if idx is None:
                entry_dates.append(None)
                continue
            if self.entry_rule == "event_close":
                entry_dates.append(trade_date)
            else:
                next_idx = idx + 1
                entry_dates.append(all_dates[next_idx] if next_idx < len(all_dates) else None)
        sample_df = sample_df.copy()
        sample_df["entry_date"] = entry_dates

        valid_codes = sample_df["ts_code"].dropna().unique().tolist()
        valid_entry_dates = [value for value in sample_df["entry_date"].dropna().tolist()]
        if not valid_codes or not valid_entry_dates:
            for window in self.windows:
                sample_df[f"ret_{window}d"] = pd.NA
            sample_df["entry_price"] = pd.NA
            return sample_df

        min_date = min(sample_df["trade_date"].min(), min(valid_entry_dates))
        max_needed_index = min(max(trade_date_index.values()), max(trade_date_index.get(date, 0) for date in valid_entry_dates) + max_window)
        max_date = all_dates[max_needed_index]
        code_list = ", ".join(f"'{code}'" for code in valid_codes)
        sql = f"""
            SELECT
                d.ts_code,
                d.trade_date,
                d.open,
                d.close,
                COALESCE(a.adj_factor, 1.0) AS adj_factor
            FROM daily_bar d
            LEFT JOIN adj_factor a
                ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.ts_code IN ({code_list})
              AND d.trade_date BETWEEN '{min_date}' AND '{max_date}'
        """
        price_df = self.data_loader.conn.execute(sql).fetchdf()
        if price_df.empty:
            for window in self.windows:
                sample_df[f"ret_{window}d"] = pd.NA
            sample_df["entry_price"] = pd.NA
            return sample_df

        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.strftime("%Y-%m-%d")
        price_df["open_adj"] = pd.to_numeric(price_df["open"], errors="coerce") * pd.to_numeric(price_df["adj_factor"], errors="coerce")
        price_df["close_adj"] = pd.to_numeric(price_df["close"], errors="coerce") * pd.to_numeric(price_df["adj_factor"], errors="coerce")
        price_map = price_df.set_index(["ts_code", "trade_date"])[["open_adj", "close_adj"]].to_dict("index")

        entry_prices: list[float | None] = []
        return_columns: dict[int, list[float | None]] = {window: [] for window in self.windows}
        for row in sample_df.itertuples(index=False):
            entry_date = row.entry_date
            if not entry_date:
                entry_prices.append(None)
                for window in self.windows:
                    return_columns[window].append(None)
                continue
            entry_key = (row.ts_code, entry_date)
            price_row = price_map.get(entry_key)
            if not price_row:
                entry_prices.append(None)
                for window in self.windows:
                    return_columns[window].append(None)
                continue
            entry_price = price_row["close_adj"] if self.entry_rule == "event_close" else price_row["open_adj" if self.entry_rule == "next_open" else "close_adj"]
            entry_prices.append(float(entry_price) if pd.notna(entry_price) else None)
            entry_idx = trade_date_index.get(entry_date)
            for window in self.windows:
                if entry_idx is None:
                    return_columns[window].append(None)
                    continue
                exit_idx = entry_idx + window
                if exit_idx >= len(all_dates):
                    return_columns[window].append(None)
                    continue
                exit_date = all_dates[exit_idx]
                exit_row = price_map.get((row.ts_code, exit_date))
                exit_price = None if exit_row is None else exit_row["close_adj"]
                if not entry_price or pd.isna(entry_price) or exit_price is None or pd.isna(exit_price):
                    return_columns[window].append(None)
                    continue
                return_columns[window].append(float(exit_price / entry_price - 1.0))

        sample_df["entry_price"] = entry_prices
        for window in self.windows:
            sample_df[f"ret_{window}d"] = return_columns[window]
        return sample_df

    def _to_records(self, detail_df: pd.DataFrame) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in detail_df.to_dict(orient="records"):
            normalized: dict[str, Any] = {}
            for key, value in row.items():
                if pd.isna(value):
                    normalized[key] = None
                elif isinstance(value, pd.Timestamp):
                    normalized[key] = value.strftime("%Y-%m-%d")
                elif hasattr(value, "item"):
                    normalized[key] = value.item()
                else:
                    normalized[key] = value
            records.append(normalized)
        return records

    @staticmethod
    def _to_datetime(value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.strptime(str(value), "%Y-%m-%d" if "-" in str(value) else "%Y%m%d")
