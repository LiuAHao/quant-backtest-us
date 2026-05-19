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

- Data source adapter for yfinance, Polygon, Tiingo, Alpaca, Nasdaq Data Link, or another US source.
- Local daily-bar storage under `data/`.
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

## Verification

```bash
python3 -m compileall backend config.py
cd frontend && npm run build
```
