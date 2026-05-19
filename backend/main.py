from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    backtest_templates,
    backtests,
    config_center,
    event_analyses,
    event_definitions,
    factor_analyses,
    factor_definitions,
    reports,
    settings,
    strategies,
)
from backend.db.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="Quant Backtest Local API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ],
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    init_db()

    app.include_router(strategies.router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(event_definitions.router, prefix="/api/event-definitions", tags=["event-definitions"])
    app.include_router(event_analyses.router, prefix="/api/event-analyses", tags=["event-analyses"])
    app.include_router(factor_definitions.router, prefix="/api/factor-definitions", tags=["factor-definitions"])
    app.include_router(factor_analyses.router, prefix="/api/factor-analyses", tags=["factor-analyses"])
    app.include_router(backtest_templates.router, prefix="/api/backtest-templates", tags=["backtest-templates"])
    app.include_router(backtests.router, prefix="/api/backtests", tags=["backtests"])
    app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    app.include_router(config_center.router, prefix="/api/config", tags=["config"])

    @app.get("/api/health")
    def health_check():
        return {"status": "ok"}

    @app.on_event("shutdown")
    def shutdown_event():
        from backend.services.backtest_service import EXECUTOR as bt_executor
        from backend.services.event_analysis_service import EXECUTOR as ea_executor
        from backend.services.factor_analysis_service import EXECUTOR as fa_executor
        bt_executor.shutdown(wait=False, cancel_futures=True)
        ea_executor.shutdown(wait=False, cancel_futures=True)
        fa_executor.shutdown(wait=False, cancel_futures=True)

    return app


app = create_app()
