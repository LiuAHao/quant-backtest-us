from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def parse_nasdaq_trader_rows(rows: list[dict[str, str]]) -> dict[str, object]:
    symbols: list[str] = []
    filtered = 0
    for row in rows:
        symbol = (row.get("Symbol") or row.get("ACT Symbol") or "").strip().upper()
        if not symbol:
            filtered += 1
            continue
        is_test_issue = (row.get("Test Issue") or row.get("TestIssue") or "").strip().upper() == "Y"
        round_lot = (row.get("Round Lot Size") or row.get("RoundLotSize") or "").strip()
        if is_test_issue or round_lot == "0":
            filtered += 1
            continue
        symbols.append(symbol)
    deduped = []
    seen = set()
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            deduped.append(symbol)
    return {
        "symbols": deduped,
        "counts": {
            "kept": len(deduped),
            "filtered": filtered,
            "raw": len(rows),
        },
    }


def fetch_nasdaq_trader_rows(url: str) -> list[dict[str, str]]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    text = response.text
    data_lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    reader = csv.DictReader(io.StringIO("\n".join(data_lines)), delimiter="|")
    return list(reader)


def build_universe() -> dict[str, object]:
    nasdaq = parse_nasdaq_trader_rows(fetch_nasdaq_trader_rows(NASDAQ_LISTED_URL))
    other = parse_nasdaq_trader_rows(fetch_nasdaq_trader_rows(OTHER_LISTED_URL))
    symbols = sorted(set(nasdaq["symbols"]) | set(other["symbols"]))
    return {
        "symbols": symbols,
        "counts": {
            "nasdaq_kept": nasdaq["counts"]["kept"],
            "other_kept": other["counts"]["kept"],
            "combined": len(symbols),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a US equity and ETF symbol universe file.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "universe" / "us_all.txt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_universe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(report["symbols"]) + "\n", encoding="utf-8")
    print(
        f"Wrote {report['counts']['combined']} symbols to {args.output} "
        f"(NASDAQ {report['counts']['nasdaq_kept']}, other {report['counts']['other_kept']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
