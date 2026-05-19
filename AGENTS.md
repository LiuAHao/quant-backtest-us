# AGENTS.md

Repo-specific guidance for agents working in `quant-backtest-us`.

## Project State

This repository is intentionally a clean US-market skeleton. The previous A-share data layer, backtest engine, strategy examples, generated reports, factor/event implementations, and ML experiment outputs were removed during initialization.

## Current Boundaries

| Path | Purpose |
|---|---|
| `backend/` | FastAPI skeleton. Keep it lightweight until real US modules are designed. |
| `frontend/` | React + Vite skeleton for the future local dashboard. |
| `data/` | Local US market data. Ignored by git. |
| `backtest/` | Placeholder for the future US backtest engine. |
| `event_analysis/` | Placeholder for future US event-study code. |
| `factor_analysis/` | Placeholder for future US factor research. |
| `ml_research/` | Placeholder for future ML research code and ignored experiment outputs. |
| `strategies/` | Placeholder for future US strategy examples. |
| `scripts/data_source/` | Future US data adapters. |
| `scripts/data_download/` | Future US data ingestion scripts. |
| `scripts/data_utils/` | Future data validation and maintenance scripts. |
| `tests/` | Future test suite. |

## Commands

```bash
python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/health

cd frontend && npm run dev
cd frontend && npm run build
```

## Development Notes

- Keep new public APIs, docs, fixtures, and examples centered on US equities and ETFs.
- Prefer US-market naming in new public APIs and docs. Internal compatibility fields such as `ts_code` and `trade_date` may be introduced later if they deliberately simplify migration.
- Keep generated data, reports, databases, model artifacts, and local credentials out of git.
- Add tests alongside the first real US data or backtest module.
