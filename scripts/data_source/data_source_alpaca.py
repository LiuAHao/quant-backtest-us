from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import requests

from config import settings
from scripts.data_utils.us_data_helpers import CANONICAL_COLUMNS, normalize_symbols


ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"
INSTRUMENT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "asset_class",
    "status",
    "tradable",
    "shortable",
    "fractionable",
    "easy_to_borrow",
    "marginable",
    "source",
    "updated_at",
]
CALENDAR_COLUMNS = [
    "date",
    "open",
    "close",
    "session_open",
    "session_close",
    "is_open",
    "source",
    "updated_at",
]
CORPORATE_ACTION_COLUMNS = [
    "symbol",
    "ca_type",
    "ca_sub_type",
    "declaration_date",
    "effective_date",
    "ex_date",
    "record_date",
    "payable_date",
    "cash",
    "old_rate",
    "new_rate",
    "source",
    "updated_at",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_alpaca_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if "-" in clean:
        left, right = clean.rsplit("-", 1)
        if len(right) == 1 and right.isalpha():
            return f"{left}.{right}"
    return clean


def from_alpaca_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if "." in clean:
        left, right = clean.rsplit(".", 1)
        if len(right) == 1 and right.isalpha():
            return f"{left}-{right}"
    return clean


def normalize_alpaca_bars(payload: dict[str, list[dict[str, object]]], *, updated_at: str | None = None, source: str = "alpaca_iex") -> pd.DataFrame:
    updated_at = updated_at or utc_now_iso()
    rows: list[dict[str, object]] = []
    for external_symbol, bars in payload.items():
        symbol = from_alpaca_symbol(external_symbol)
        for bar in bars or []:
            close = float(bar["c"])
            volume = int(bar["v"])
            rows.append(
                {
                    "symbol": symbol,
                    "date": pd.to_datetime(bar["t"], utc=True).strftime("%Y-%m-%d"),
                    "open": float(bar["o"]),
                    "high": float(bar["h"]),
                    "low": float(bar["l"]),
                    "close": close,
                    "adj_close": close,
                    "volume": volume,
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                    "amount": close * volume,
                    "source": source,
                    "updated_at": updated_at,
                }
            )
    if not rows:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    frame = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)
    return frame.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)


def normalize_alpaca_assets(
    payload: list[dict[str, object]],
    *,
    updated_at: str | None = None,
    source: str = "alpaca_assets",
) -> pd.DataFrame:
    updated_at = updated_at or utc_now_iso()
    rows: list[dict[str, object]] = []
    for item in payload:
        rows.append(
            {
                "symbol": from_alpaca_symbol(str(item.get("symbol", ""))),
                "name": str(item.get("name", "")),
                "exchange": str(item.get("exchange", "")),
                "asset_class": str(item.get("class", "")),
                "status": str(item.get("status", "")),
                "tradable": bool(item.get("tradable", False)),
                "shortable": bool(item.get("shortable", False)),
                "fractionable": bool(item.get("fractionable", False)),
                "easy_to_borrow": bool(item.get("easy_to_borrow", False)),
                "marginable": bool(item.get("marginable", False)),
                "source": source,
                "updated_at": updated_at,
            }
        )
    if not rows:
        return pd.DataFrame(columns=INSTRUMENT_COLUMNS)
    return pd.DataFrame(rows, columns=INSTRUMENT_COLUMNS).sort_values(["symbol"], kind="mergesort").reset_index(drop=True)


def normalize_alpaca_calendar(
    payload: list[dict[str, object]],
    *,
    updated_at: str | None = None,
    source: str = "alpaca_calendar",
) -> pd.DataFrame:
    updated_at = updated_at or utc_now_iso()
    rows: list[dict[str, object]] = []
    for item in payload:
        rows.append(
            {
                "date": str(item.get("date", "")),
                "open": str(item.get("open", "")),
                "close": str(item.get("close", "")),
                "session_open": str(item.get("session_open", "")),
                "session_close": str(item.get("session_close", "")),
                "is_open": True,
                "source": source,
                "updated_at": updated_at,
            }
        )
    if not rows:
        return pd.DataFrame(columns=CALENDAR_COLUMNS)
    return pd.DataFrame(rows, columns=CALENDAR_COLUMNS).sort_values(["date"], kind="mergesort").reset_index(drop=True)


def normalize_alpaca_corporate_actions(
    payload: list[dict[str, object]],
    *,
    updated_at: str | None = None,
    source: str = "alpaca_corporate_actions",
) -> pd.DataFrame:
    updated_at = updated_at or utc_now_iso()
    rows: list[dict[str, object]] = []
    for item in payload:
        rows.append(
            {
                "symbol": from_alpaca_symbol(str(item.get("target_symbol") or item.get("initiating_symbol") or "")),
                "ca_type": str(item.get("ca_type", "")),
                "ca_sub_type": str(item.get("ca_sub_type", "")),
                "declaration_date": str(item.get("declaration_date", "")),
                "effective_date": str(item.get("effective_date", "")),
                "ex_date": str(item.get("ex_date", "")),
                "record_date": str(item.get("record_date", "")),
                "payable_date": str(item.get("payable_date", "")),
                "cash": float(item.get("cash", 0.0) or 0.0),
                "old_rate": float(item.get("old_rate", 0.0) or 0.0),
                "new_rate": float(item.get("new_rate", 0.0) or 0.0),
                "source": source,
                "updated_at": updated_at,
            }
        )
    if not rows:
        return pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS)
    return (
        pd.DataFrame(rows, columns=CORPORATE_ACTION_COLUMNS)
        .sort_values(["symbol", "ex_date", "ca_type"], kind="mergesort")
        .reset_index(drop=True)
    )


def fetch_daily_bars(
    symbols: Iterable[str],
    *,
    start: str,
    end: str,
    feed: str = "iex",
    adjustment: str = "all",
    limit: int = 10000,
    timeout: int = 30,
) -> pd.DataFrame:
    clean_symbols = normalize_symbols(symbols)
    if not clean_symbols:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    if not settings.ALPACA_API_KEY or not settings.ALPACA_API_SECRET:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env before downloading bars.")

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET,
    }
    params = {
        "symbols": ",".join(to_alpaca_symbol(symbol) for symbol in clean_symbols),
        "timeframe": "1Day",
        "start": start,
        "end": end,
        "adjustment": adjustment,
        "feed": feed,
        "limit": limit,
    }

    merged_bars: dict[str, list[dict[str, object]]] = {}
    page_token: str | None = None
    while True:
        if page_token:
            params["page_token"] = page_token
        else:
            params.pop("page_token", None)
        response = requests.get(f"{ALPACA_DATA_BASE_URL}/stocks/bars", params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        for symbol, bars in (data.get("bars") or {}).items():
            merged_bars.setdefault(symbol, []).extend(bars or [])
        page_token = data.get("next_page_token")
        if not page_token:
            break

    return normalize_alpaca_bars(merged_bars)


def fetch_assets(*, status: str = "active", asset_class: str = "us_equity", timeout: int = 60) -> pd.DataFrame:
    if not settings.ALPACA_API_KEY or not settings.ALPACA_API_SECRET:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env before downloading assets.")

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET,
    }
    response = requests.get(
        f"{settings.ALPACA_API_BASE_URL}/assets",
        params={"status": status, "asset_class": asset_class},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return normalize_alpaca_assets(response.json())


def fetch_calendar(*, start: str, end: str, timeout: int = 60) -> pd.DataFrame:
    if not settings.ALPACA_API_KEY or not settings.ALPACA_API_SECRET:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env before downloading calendar.")

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET,
    }
    response = requests.get(
        f"{settings.ALPACA_API_BASE_URL}/calendar",
        params={"start": start, "end": end},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return normalize_alpaca_calendar(response.json())


def fetch_corporate_actions(
    *,
    since: str,
    until: str,
    ca_types: str = "dividend,split",
    symbol: str | None = None,
    timeout: int = 60,
) -> pd.DataFrame:
    if not settings.ALPACA_API_KEY or not settings.ALPACA_API_SECRET:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env before downloading corporate actions.")

    headers = {
        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET,
    }
    params = {"ca_types": ca_types, "since": since, "until": until}
    if symbol:
        params["symbol"] = symbol
    response = requests.get(
        f"{settings.ALPACA_API_BASE_URL}/corporate_actions/announcements",
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return normalize_alpaca_corporate_actions(response.json())
