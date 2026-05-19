# Scripts

Utility scripts for the US-market rewrite.

- `data_source/`: source adapters such as yfinance, Polygon, Tiingo, Alpaca, or Nasdaq Data Link.
- `data_download/`: ingestion jobs that write local market data.
- `data_utils/`: validation, maintenance, and migration helpers.

## US Daily Bars

```bash
python3 scripts/data_download/download_us_daily.py \
  --symbols-file data/universe/us_core.txt \
  --start 2015-01-01 \
  --end 2026-05-20

python3 scripts/data_utils/validate_us_data.py
```

The downloader batches symbols, writes year-partitioned parquet files, and stores a resumable checkpoint at `data/meta/download_us_daily_checkpoint.json`.

For longer unattended runs, prefer:

```bash
python3 scripts/data_download/download_us_daily.py \
  --symbols-file data/universe/us_all.txt \
  --start 2010-01-01 \
  --end 2026-05-20 \
  --batch-size 50 \
  --fallback-to-single-symbol
```

After each run, inspect:

```text
data/meta/download_us_daily_report.json
data/meta/failed_symbols.txt
data/meta/missing_symbols.txt
```

To retry only unresolved symbols:

```bash
python3 scripts/data_download/download_us_daily.py \
  --retry-failed-only \
  --start 2010-01-01 \
  --end 2026-05-20 \
  --batch-size 20 \
  --fallback-to-single-symbol
```

To build a broader universe file:

```bash
python3 scripts/data_download/build_us_universe.py
```

That writes `data/universe/us_all.txt` using NASDAQ Trader symbol directories, filtered to remove test issues and zero round-lot entries.
