from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="Quant Backtest US API",
        version="0.1.0",
        description="Skeleton API for US market data research and backtesting.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "market": "US"}

    @app.get("/api/about")
    def about() -> dict[str, object]:
        return {
            "name": "quant-backtest-us",
            "market": "US equities",
            "status": "skeleton",
            "planned_modules": [
                "us_market_data",
                "backtest_engine",
                "strategy_research",
                "factor_research",
                "reports",
            ],
        }

    return app


app = create_app()
