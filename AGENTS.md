# AGENTS.md

Repo-specific guidance for OpenCode agents. See also `CLAUDE.md` for behavioral guidelines.

## Architecture

- **Backend**: FastAPI (`backend/main.py`), SQLite metadata (`backend/storage/quant_backtest.db`), DuckDB for market data queries (`data/`)
- **Backtest engine**: `backtest/` — `engine.py`, `data_loader.py`, `broker.py`, `strategy.py`, `reporting.py`
- **Event analysis**: `event_analysis/` — `engine.py`, `template.py`, `result_builder.py`, `loader.py`
- **Factor analysis**: `factor_analysis/` — `engine.py`, `metrics.py`, `template.py`, `loader.py`
- **ML research**: `ml_research/` — `pipeline.py`, `features.py`, `labels.py`, `models/`, `signal.py` (local only, no frontend)
- **Frontend**: React + Vite (`frontend/`), single-file app (`frontend/src/App.jsx`, ~2800 lines)
- **Config**: Pydantic settings loaded from `.env` via `config.py`. Secrets only in `.env`, never hardcoded.

## Directory Boundaries

| Directory | Role |
|---|---|
| `backend/api/` | FastAPI route handlers |
| `backend/services/` | Business logic, validators, AI prompts |
| `backend/db/database.py` | SQLite schema, migrations, `get_conn()` context manager |
| `backend/storage/strategies/` | **Auto-generated** strategy `.py` files — do not edit directly, managed by `StrategyService` |
| `backend/storage/event_analyses/generated/` | **Auto-generated** event analysis code |
| `backend/storage/event_analyses/results/` | Event analysis result JSONs |
| `backend/storage/factor_analyses/generated/` | **Auto-generated** factor analysis code |
| `backend/storage/factor_analyses/results/` | Factor analysis result JSONs |
| `backtest/` | Core engine — no backend imports allowed |
| `event_analysis/` | Event analysis engine — no backend imports allowed |
| `factor_analysis/` | Factor analysis engine — no backend imports allowed |
| `ml_research/` | ML model training — no backend imports allowed, local research only |
| `strategies/` | Strategy templates/examples (legacy, read-only reference) |
| `scripts/` | Standalone scripts — see `scripts/README.md` for subdirectory layout |
| `scripts/data_download/` | Data download/update scripts |
| `scripts/data_utils/` | Data utility/maintenance scripts |
| `scripts/data_source/` | Data source adapters (Tushare, AkShare) |
| `scripts/agent_entry/` | Standard CLI entry points for external agents |
| `scripts/agent_simulation/` | Agent experiment/simulation scripts (**not in git** — `.gitignore`) — 非规范的自定义运行脚本放这里，规范的策略/事件分析代码放后端对应目录 |
| `tests/` | Unit tests |
| `data/` | Local parquet market data (not in git) |
| `docs/` | API guides, agent guides, plans |

## Commands

### Backend
```bash
# Start dev server (MUST use --reload-exclude to avoid restart loops)
python -m uvicorn backend.main:app --reload \
  --reload-exclude 'backend/storage/strategies/*' \
  --reload-exclude 'backend/storage/event_analyses/generated/*' \
  --reload-exclude 'backend/storage/factor_analyses/generated/*' \
  --host 127.0.0.1 --port 8000

# Health check
curl http://127.0.0.1:8000/api/health
```

### Frontend
```bash
cd frontend && npm run dev    # Vite dev server on :5173
cd frontend && npm run build  # Production build
```

### Tests
```bash
python -m unittest discover -s tests -v    # All tests
python -m unittest tests.test_backend_api.BacktestServiceTest.test_create_task -v  # Single test
```

### Data
```bash
python scripts/data_utils/validate_data.py                          # Check data quality
python scripts/data_download/download_by_date.py --start 20140102 --end 20260429  # Update daily bars
python scripts/data_download/update_extra_data.py --start 20140102 --end 20260429 --tasks daily_basic stk_limit
```

### Standard Agent Entry Points
```bash
python scripts/agent_entry/run_standard_backtest.py --strategy-file <path> --start 2026-01-01 --end 2026-04-29
python scripts/agent_entry/run_standard_event_analysis.py --event-file <path> --start 2025-01-01 --end 2025-12-31 --windows 5,10,15
python scripts/agent_entry/run_standard_factor_analysis.py --factor-file <path> --start 2025-01-01 --end 2025-12-31 --windows 1,5,10,20
python scripts/agent_entry/run_ml_training.py --experiment-name lgb_v1 --start 2016-01-01 --end 2026-04-29 --forward-days 5 --top-n 20
```

## Key Conventions

### Strategy Code Rules
- Must inherit `StrategyTemplate` from `backtest.strategy`
- Must implement `init(self, context)` and `next(self, context)`
- **Banned imports**: `os`, `subprocess`, `socket`, `shutil`, `requests`, `httpx`, `urllib`, `ftplib`, `pathlib`
- **Banned calls**: `eval`, `exec`, `compile`, `open`, `__import__`
- Validator: `backend/services/strategy_validator.py` — AST-based static analysis

### Event Analysis Code Rules
- Must inherit `EventAnalysisTemplate` from `event_analysis.template`
- Must implement `scan(self, context)` returning a `DataFrame` with at least `ts_code` and `trade_date` columns
- Do NOT compute future returns (`ret_5d` etc.) — the platform does this
- Do NOT write trading/portfolio logic

### Factor Analysis Code Rules
- Must inherit `FactorAnalysisTemplate` from `factor_analysis.template`
- Must implement `compute(self, context)` returning a `DataFrame` with at least `ts_code`, `trade_date`, and `factor_value` columns
- Do NOT compute future returns (`ret_5d`, `forward_return`, etc.) — the platform does this
- Do NOT write trading/portfolio/order/rebalance logic
- Use `context["market_data"]` for the current cross-section when possible; use `context["conn"]` for batch DuckDB queries when history is needed

### Data Access Pattern
- `context["market_data"]` in strategies: pre-loaded DataFrame with `ts_code`, `close`, `amount`, `circ_mv`, `total_mv`, `pe_ttm`, `pb`, `turnover_rate` (auto-joined from `daily_basic`)
- `context["data_loader"].conn`: DuckDB connection for direct queries
- `context["get_history"](ts_code, end_date, window, adjust)`: individual stock history
- All dates in DuckDB queries must be `YYYY-MM-DD` strings

### Database
- **Metadata DB**: SQLite at `backend/storage/quant_backtest.db` — strategies, tasks, settings, templates
- **Market data**: DuckDB reading parquet from `data/` subdirectories
- Migrations: `_migrate_db()` in `backend/db/database.py` uses `ALTER TABLE ADD COLUMN` (idempotent)
- Use `get_conn()` context manager for all SQLite access

### Frontend
- Single-file React app (`App.jsx`) — all views in one file
- State: `activeTab`, `selectedBacktestId`, `selectedEventAnalysisId` persisted to URL params
- Top overlays (`taskOpen`, `noticeOpen`, `accountOpen`) are mutually exclusive via `topOverlay` state
- Polls backtests/event analyses every 2.5s when API is online

## Testing Patterns

Tests in `tests/test_backend_api.py` use:
- Temp directories under `.test-tmp/<test_name>` (cleaned up in `tearDown`)
- `unittest.mock.patch` to redirect `database.STORAGE_DIR`, `DB_PATH`, `GENERATED_STRATEGY_DIR`, `config.settings.DATA_DIR`
- `fastapi.testclient.TestClient` for API tests
- `NoopExecutor` to prevent async backtest execution during tests
- Always call `database.init_db()` in `setUp`

## Gotchas

1. **Hot reload loops**: `backend/storage/strategies/` and `backend/storage/event_analyses/generated/` are written by the backend itself. Without `--reload-exclude`, uvicorn detects changes and restarts infinitely.
2. **Two data systems**: DuckDB (read-only parquet queries) vs SQLite (mutable metadata). Don't mix them up.
3. **Strategy file sync**: `StrategyService._sync_current_files()` overwrites strategy files from DB on startup. Edit DB records, not files.
4. **Report generation**: `backtest/reporting.py` generates both JSON and HTML. HTML is a self-contained single file with inline JS/CSS.
5. **`data/` not in git**: Market data is local-only. Tests create minimal fixture data in temp dirs.
6. **Frontend dist**: `frontend/dist/` is the production build output. `scripts/serve_frontend.py` can serve it.

## Docs Reference

| File | Content |
|---|---|
| `docs/API_GUIDE.md` | Full API reference, agent integration guide |
| `docs/STRATEGY_BUILD_GUIDE.md` | Strategy code conventions, `context` object reference |
| `docs/EVENT_ANALYSIS_BUILD_GUIDE.md` | Event analysis code conventions |
| `docs/FACTOR_ANALYSIS_BUILD_GUIDE.md` | Factor analysis code conventions |
| `docs/AGENT_STANDARD_BACKTEST_GUIDE.md` | Standard backtest entry point for agents |
| `docs/AGENT_STANDARD_EVENT_ANALYSIS_GUIDE.md` | Standard event analysis entry point |
| `docs/AGENT_STANDARD_FACTOR_ANALYSIS_GUIDE.md` | Standard factor analysis entry point |
| `docs/AGENT_ML_RESEARCH_GUIDE.md` | ML research module — training, evaluation, backtest integration |
| `STRATEGY_SPEC.md` | Quick-reference strategy spec |
| `CLAUDE.md` | Behavioral guidelines (caution, simplicity, surgical changes) |
