# Scripts

Utility scripts for the US-market rewrite.

- `data_source/`: source adapters such as Alpaca, Polygon, Tiingo, or Nasdaq Data Link.
- `data_download/`: ingestion jobs that write local market data.
- `data_utils/`: validation, maintenance, and migration helpers.

## US Daily Bars

```bash
python3 scripts/data_download/reset_us_data.py
python3 scripts/data_download/download_us_daily_staged.py \
  --stage 1y \
  --symbols-file data/universe/us_core.txt \
  --end 2025-05-20

python3 scripts/data_utils/validate_us_data.py
```

The downloader writes raw single-symbol caches, compacts them into year-partitioned parquet files, and stores a resumable checkpoint at `data/meta/download_us_daily_1y_checkpoint.json`.

To populate reference tables:

```bash
python3 scripts/data_download/download_us_instruments.py
python3 scripts/data_download/download_us_calendar.py --start 2024-05-20 --end 2026-05-20
python3 scripts/data_download/download_us_corporate_actions.py --since 2026-01-01 --until 2026-05-21 --symbol AAPL,MSFT,SPY
python3 scripts/data_utils/validate_us_reference_data.py --table instruments
python3 scripts/data_utils/validate_us_reference_data.py --table calendar
python3 scripts/data_utils/validate_us_reference_data.py --table corporate_actions
```

For later stage expansion:

```bash
python3 scripts/data_download/download_us_daily_staged.py --stage 2y --symbols-file data/universe/us_core.txt --end 2025-05-20
python3 scripts/data_download/download_us_daily_staged.py --stage 5y --symbols-file data/universe/us_core.txt --end 2025-05-20
```

After each run, inspect:

```text
data/meta/stage_1y/download_us_daily_report.json
data/meta/stage_1y/failed_symbols.txt
data/meta/stage_1y/missing_symbols.txt
```

To retry only unresolved symbols:

```bash
python3 scripts/data_download/download_us_daily_staged.py \
  --stage 1y \
  --symbols-file data/universe/us_core.txt \
  --retry-failed-only \
  --end 2025-05-20
```

To build a broader universe file:

```bash
python3 scripts/data_download/build_us_universe.py
```

That writes `data/universe/us_all.txt` using NASDAQ Trader symbol directories, filtered to remove test issues and zero round-lot entries.

For Alpaca/IEX runs, you can also rebuild a provider-clean universe by excluding the
current known missing-symbol list:

```bash
python3 scripts/data_download/build_us_universe.py \
  --output data/universe/us_all_alpaca.txt \
  --exclude-file data/universe/us_all_alpaca_exclude.txt
```
