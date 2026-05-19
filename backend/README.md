# Backend

FastAPI skeleton for `quant-backtest-us`.

## Run

```bash
python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

- `GET /api/health`
- `GET /api/about`

Future US data, backtesting, strategy, factor, and reporting APIs should be added only after their module boundaries are designed.
