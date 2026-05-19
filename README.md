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

- Data source adapter for yfinance first, with room for Polygon, Tiingo, Alpaca, Nasdaq Data Link, or another US source.
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

The first data source is yfinance. It is useful for quickly prototyping a large local daily-bar store, but the code keeps yfinance behind an adapter so a paid provider can replace it later.

Download a small universe:

```bash
python3 scripts/data_download/download_us_daily.py \
  --symbols AAPL MSFT NVDA SPY QQQ \
  --start 2015-01-01 \
  --end 2026-05-20 \
  --batch-size 80
```

Download from a symbols file:

```bash
python3 scripts/data_download/download_us_daily.py \
  --symbols-file data/universe/us_core.txt \
  --start 2010-01-01 \
  --end 2026-05-20 \
  --batch-size 80
```

Build a larger US symbol universe first:

```bash
python3 scripts/data_download/build_us_universe.py
python3 scripts/data_download/download_us_daily.py \
  --symbols-file data/universe/us_all.txt \
  --start 2010-01-01 \
  --end 2026-05-20 \
  --batch-size 50 \
  --fallback-to-single-symbol
```

Daily bars are written as year-partitioned parquet files:

```text
data/us_daily_bar/
  year=2024/us_daily_bar.parquet
  year=2025/us_daily_bar.parquet
```

Validate the local store:

```bash
python3 scripts/data_utils/validate_us_data.py
```

For larger universes, tune `--batch-size` and `--threads`. A practical starting point is `--batch-size 50` to `100` with yfinance threading enabled. The checkpoint file lets you rerun interrupted jobs without reprocessing successful batches.
The checkpoint now also records per-symbol status and a coverage summary so you can see how many requested symbols were downloaded, missing, failed, or still unknown.

For unattended runs, the downloader also writes:

```text
data/meta/download_us_daily_checkpoint.json
data/meta/download_us_daily_report.json
data/meta/success_symbols.txt
data/meta/missing_symbols.txt
data/meta/failed_symbols.txt
```

If a batch fails and `--fallback-to-single-symbol` is enabled, the downloader retries the symbols in that batch one by one. To rerun only the unresolved names later:

```bash
python3 scripts/data_download/download_us_daily.py \
  --retry-failed-only \
  --start 2010-01-01 \
  --end 2026-05-20 \
  --batch-size 20 \
  --fallback-to-single-symbol
```

## Verification

```bash
python3 -m compileall backend config.py
cd frontend && npm run build
```
