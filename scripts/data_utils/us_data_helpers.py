from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd


CANONICAL_COLUMNS = [
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
    "amount",
    "source",
    "updated_at",
]

UNSUPPORTED_SUFFIXES = (".U", ".R", ".WS", ".W", ".RT")


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for item in symbols:
        symbol = item.strip().upper() if item else ""
        if symbol and symbol not in seen:
            seen.add(symbol)
            clean.append(symbol)
    return clean


def normalize_download_symbol(symbol: str) -> tuple[str | None, str | None]:
    clean = symbol.strip().upper()
    if not clean:
        return None, "empty"
    if "$" in clean:
        return None, "preferred_or_special_share"
    if clean.endswith(UNSUPPORTED_SUFFIXES):
        return None, "unsupported_suffix"
    if "." in clean:
        left, right = clean.rsplit(".", 1)
        if len(right) == 1 and right.isalpha():
            return f"{left}-{right}", None
    return clean, None


def prepare_download_symbols(symbols: Iterable[str]) -> tuple[list[str], list[str]]:
    prepared: list[str] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    for original in normalize_symbols(symbols):
        normalized, _reason = normalize_download_symbol(original)
        if normalized:
            if normalized not in seen:
                seen.add(normalized)
                prepared.append(normalized)
        else:
            unsupported.append(original)
    return prepared, unsupported


def read_symbols_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].replace(",", " ").strip()
        if clean:
            symbols.extend(clean.split())
    return normalize_symbols(symbols)


def batch_symbols(symbols: Iterable[str], batch_size: int) -> Iterator[list[str]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    clean = normalize_symbols(symbols)
    for start in range(0, len(clean), batch_size):
        batch = clean[start : start + batch_size]
        if batch:
            yield batch


def merge_daily_bars(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        merged = incoming.copy()
    elif incoming is None or incoming.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, incoming], ignore_index=True, sort=False)

    if merged.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    merged["symbol"] = merged["symbol"].astype(str).str.upper()
    merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
    if "updated_at" not in merged:
        merged["updated_at"] = ""
    merged = merged.sort_values(["symbol", "date", "updated_at"], kind="mergesort")
    merged = merged.drop_duplicates(["symbol", "date"], keep="last")
    return merged.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)


def _read_existing_partition(partition_dir: Path) -> pd.DataFrame:
    files = sorted(partition_dir.glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat((pd.read_parquet(file) for file in files), ignore_index=True, sort=False)


def write_partitioned_daily_bars(frame: pd.DataFrame, output_dir: Path) -> dict[int, int]:
    if frame.empty:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
    data["year"] = data["date"].str.slice(0, 4).astype(int)
    counts: dict[int, int] = {}

    for year, year_frame in data.groupby("year", sort=True):
        partition_dir = output_dir / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        existing = _read_existing_partition(partition_dir)
        merged = merge_daily_bars(existing.drop(columns=["year"], errors="ignore"), year_frame.drop(columns=["year"]))
        final_path = partition_dir / "us_daily_bar.parquet"
        tmp_path = partition_dir / f".{final_path.name}.tmp"
        merged.to_parquet(tmp_path, index=False)
        tmp_path.replace(final_path)
        for old_file in partition_dir.glob("*.parquet"):
            if old_file != final_path:
                old_file.unlink()
        counts[int(year)] = len(merged)

    return counts


def build_coverage_report(checkpoint: dict[str, object], requested_symbols: Iterable[str]) -> dict[str, int]:
    requested = normalize_symbols(requested_symbols)
    status_map = checkpoint.get("symbol_status", {})
    counts = {"success": 0, "missing": 0, "failed": 0, "unknown": 0}
    for symbol in requested:
        status = status_map.get(symbol, {}).get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "requested_symbols": len(requested),
        "success_symbols": counts.get("success", 0),
        "missing_symbols": counts.get("missing", 0),
        "failed_symbols": counts.get("failed", 0),
        "unknown_symbols": counts.get("unknown", 0),
    }


def write_symbol_list(path: Path, symbols: Iterable[str]) -> None:
    clean = normalize_symbols(symbols)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(clean)
    if clean:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def write_status_files(meta_dir: Path, checkpoint: dict[str, object]) -> None:
    status_map = checkpoint.get("symbol_status", {})
    success = [symbol for symbol, payload in status_map.items() if payload.get("status") == "success"]
    missing = [symbol for symbol, payload in status_map.items() if payload.get("status") == "missing"]
    failed = [symbol for symbol, payload in status_map.items() if payload.get("status") == "failed"]
    unsupported = [symbol for symbol, payload in status_map.items() if payload.get("status") == "unsupported"]
    write_symbol_list(meta_dir / "success_symbols.txt", success)
    write_symbol_list(meta_dir / "missing_symbols.txt", missing)
    write_symbol_list(meta_dir / "failed_symbols.txt", failed)
    write_symbol_list(meta_dir / "unsupported_symbols.txt", unsupported)
    summary_path = meta_dir / "download_us_daily_report.json"
    summary = {
        "coverage_report": checkpoint.get("coverage_report", {}),
        "last_run": checkpoint.get("last_run", {}),
        "failed_symbols": normalize_symbols(failed),
        "missing_symbols": normalize_symbols(missing),
        "success_symbols": normalize_symbols(success),
        "unsupported_symbols": normalize_symbols(unsupported),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
