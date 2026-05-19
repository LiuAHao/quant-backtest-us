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
