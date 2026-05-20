# Quant Backtest US

Local-first research skeleton for US equity data, strategy research, and backtesting.

This repository was initialized from `quant-backtest`, then cleaned for a US-market rewrite. The previous A-share data adapters, engines, strategies, generated reports, and research outputs have been removed. What remains is a lightweight project shell ready for new US data and research modules.

## Current Scope

- FastAPI backend skeleton with health/about endpoints.
- React + Vite frontend skeleton.
- Empty module directories for future US market data, backtesting, event analysis, factor analysis, ML research, strategies, reports, scripts, and tests.
- Local data and runtime outputs remain ignored by git.

## Intended Direction

The first usable milestone should be a minimal US daily-bar research loop:

- Data source adapter for Alpaca Basic first, with room for Polygon, Tiingo, or another US source later.
- Local daily-bar storage under `data/us_daily_bar/`.
- Instrument and calendar loaders for US equities and ETFs.
- A small backtest engine that can run simple AAPL/MSFT/NVDA/SPY experiments.
- Strategy and report formats designed around US-market concepts instead of A-share fields.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
```

## Run

Backend:

```bash
python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

## Repository Layout

```text
backend/          FastAPI service skeleton
frontend/         React + Vite frontend skeleton
data/             Local US market data, ignored by git
backtest/         Placeholder for the future US backtest engine
event_analysis/   Placeholder for future US event studies
factor_analysis/  Placeholder for future US factor research
ml_research/      Placeholder for future ML experiments
strategies/       Placeholder for future strategy examples
scripts/          Placeholder for future data and maintenance scripts
tests/            Placeholder for future tests
docs/             Placeholder for future design and usage docs
```

## US Daily Data

The first active data source is Alpaca Basic. The repository now stores:

- raw single-symbol parquet caches under `data/us_daily_bar_raw/`
- a standardized year-partitioned research layer under `data/us_daily_bar/`
- stage-level checkpoints and coverage reports under `data/meta/`

Reset old local data before a fresh import:

```bash
python3 scripts/data_download/reset_us_data.py
```

Download the initial one-year core universe:

```bash
python3 scripts/data_download/download_us_daily_staged.py \
  --stage 1y \
  --symbols-file data/universe/us_core.txt \
  --end 2025-05-20
```

Expand later to two, five, or ten years:

```bash
python3 scripts/data_download/download_us_daily_staged.py --stage 2y --symbols-file data/universe/us_core.txt --end 2025-05-20
python3 scripts/data_download/download_us_daily_staged.py --stage 5y --symbols-file data/universe/us_core.txt --end 2025-05-20
python3 scripts/data_download/download_us_daily_staged.py --stage 10y --symbols-file data/universe/us_core.txt --end 2025-05-20
```

The standardized research store remains year-partitioned:

```text
data/us_daily_bar/
  year=2024/us_daily_bar.parquet
  year=2025/us_daily_bar.parquet
```

Raw symbol caches are kept separately:

```text
data/us_daily_bar_raw/
  bucket=A/AAPL.parquet
  bucket=M/MSFT.parquet
```

Reference data can be stored alongside daily bars:

```bash
python3 scripts/data_download/download_us_instruments.py
python3 scripts/data_download/download_us_calendar.py --start 2024-05-20 --end 2026-05-20
python3 scripts/data_download/download_us_corporate_actions.py --since 2026-01-01 --until 2026-05-21 --symbol AAPL,MSFT,SPY
python3 scripts/data_utils/validate_us_reference_data.py --table instruments
python3 scripts/data_utils/validate_us_reference_data.py --table calendar
python3 scripts/data_utils/validate_us_reference_data.py --table corporate_actions
```

Validate the local store:

```bash
python3 scripts/data_utils/validate_us_data.py
```

The stage checkpoint records per-symbol status and a coverage summary so you can see how many requested symbols were downloaded, missing, failed, or still unknown.

For unattended runs, the downloader also writes:

```text
data/meta/download_us_daily_1y_checkpoint.json
data/meta/stage_1y/download_us_daily_report.json
data/meta/stage_1y/success_symbols.txt
data/meta/stage_1y/missing_symbols.txt
data/meta/stage_1y/failed_symbols.txt
```

For Alpaca/IEX downloads, keep the broad and provider-clean universes separate:

```text
data/universe/us_all.txt
data/universe/us_all_alpaca.txt
data/universe/us_all_alpaca_exclude.txt
```

`us_all.txt` stays as the broad NASDAQ Trader universe. `us_all_alpaca.txt` is the
provider-clean version rebuilt against the current exclude list.

To rerun only unresolved symbols for a stage later:

```bash
python3 scripts/data_download/download_us_daily_staged.py \
  --stage 1y \
  --symbols-file data/universe/us_core.txt \
  --retry-failed-only \
  --end 2025-05-20
```

## Verification

```bash
python3 -m compileall backend config.py
cd frontend && npm run build
```
