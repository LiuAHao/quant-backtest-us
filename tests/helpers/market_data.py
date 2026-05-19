from __future__ import annotations

from pathlib import Path

import pandas as pd


def _resolve_dir(root: Path, dataset: str, partition: str | None = None) -> Path:
    path = root / dataset
    if partition:
        path = path / partition
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_calendar(root: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "calendar") / "calendar.parquet", index=False)


def write_daily_bar(root: Path, rows: list[dict], *, partition: str) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "daily_bar", partition) / "daily_bar.parquet", index=False)


def write_adj_factor(root: Path, rows: list[dict], *, partition: str) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "adj_factor", partition) / "adj_factor.parquet", index=False)


def write_daily_basic(root: Path, rows: list[dict], *, partition: str) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "daily_basic", partition) / "daily_basic.parquet", index=False)


def write_stk_limit(root: Path, rows: list[dict], *, partition: str) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "stk_limit", partition) / "stk_limit.parquet", index=False)


def write_instruments(root: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "instruments") / "instruments.parquet", index=False)


def write_index_daily(root: Path, rows: list[dict], *, partition: str) -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "index_daily", partition) / "index_daily.parquet", index=False)


def write_financial(root: Path, rows: list[dict], *, filename: str = "fina_indicator.parquet") -> None:
    pd.DataFrame(rows).to_parquet(_resolve_dir(root, "financial") / filename, index=False)
