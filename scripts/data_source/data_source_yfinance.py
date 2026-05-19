from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd


PRICE_FIELDS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "stock_splits",
}

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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for item in symbols:
        symbol = item.strip().upper() if item else ""
        if symbol and symbol not in seen:
            seen.add(symbol)
            clean.append(symbol)
    return clean


def _field_symbol_pairs(columns: pd.Index) -> list[tuple[str, str, object]]:
    if not isinstance(columns, pd.MultiIndex) and any(isinstance(column, tuple) for column in columns):
        columns = pd.MultiIndex.from_tuples(columns)

    if not isinstance(columns, pd.MultiIndex):
        return [(field, "", field) for field in columns if field in PRICE_FIELDS]

    pairs: list[tuple[str, str, object]] = []
    for column in columns:
        left, right = column[0], column[1]
        if left in PRICE_FIELDS:
            pairs.append((left, str(right).upper(), column))
        elif right in PRICE_FIELDS:
            pairs.append((right, str(left).upper(), column))
    return pairs


def normalize_yfinance_download(
    raw: pd.DataFrame,
    *,
    symbols: Iterable[str] | None = None,
    source: str = "yfinance",
    updated_at: str | None = None,
) -> pd.DataFrame:
    """Convert a yfinance download frame into the local daily-bar schema."""

    if raw is None or raw.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    updated_at = updated_at or utc_now_iso()
    requested_symbols = _normalize_symbols(symbols or [])
    pairs = _field_symbol_pairs(raw.columns)
    discovered = _normalize_symbols(symbol for _, symbol, _ in pairs)
    output_symbols = discovered or requested_symbols or ["UNKNOWN"]

    frames: list[pd.DataFrame] = []
    for symbol in output_symbols:
        data = pd.DataFrame(index=raw.index)
        for original_field, column_symbol, column_key in pairs:
            if discovered and symbol != str(column_key[1] if column_key[0] in PRICE_FIELDS else column_key[0]).upper():
                continue
            data[PRICE_FIELDS[original_field]] = raw[column_key]

        if data.empty:
            continue

        data = data.reset_index()
        date_column = data.columns[0]
        data["symbol"] = symbol
        data["date"] = pd.to_datetime(data[date_column], utc=True).dt.strftime("%Y-%m-%d")
        data = data.drop(columns=[date_column])
        frames.append(data)

    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    result = pd.concat(frames, ignore_index=True)
    for column in ["open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"]:
        if column not in result:
            result[column] = 0 if column in {"volume", "dividends", "stock_splits"} else pd.NA

    for column in ["open", "high", "low", "close", "adj_close", "dividends", "stock_splits"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce").fillna(0).astype("int64")
    result["amount"] = (result["close"].fillna(0) * result["volume"]).astype("float64")
    result["source"] = source
    result["updated_at"] = updated_at

    result = result.dropna(subset=["open", "high", "low", "close"], how="all")
    result = result[CANONICAL_COLUMNS]
    result = result.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)
    return result


def fetch_daily_bars(
    symbols: Iterable[str],
    *,
    start: str,
    end: str | None = None,
    batch_threads: bool | int = True,
    timeout: int = 30,
) -> pd.DataFrame:
    """Fetch daily bars from yfinance and return canonical rows."""

    clean_symbols = _normalize_symbols(symbols)
    if not clean_symbols:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install yfinance to download US daily bars: pip install yfinance") from exc

    raw = yf.download(
        tickers=" ".join(clean_symbols),
        start=start,
        end=end,
        interval="1d",
        group_by="column",
        auto_adjust=False,
        actions=True,
        progress=False,
        threads=batch_threads,
        timeout=timeout,
    )
    return normalize_yfinance_download(raw, symbols=clean_symbols)
