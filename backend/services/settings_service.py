from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import duckdb

from config import settings as app_settings

from backend.db.database import get_conn


DEFAULT_SETTINGS = {
    "ai": {
        "provider": "openai-compatible",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "AI_API_KEY",
        "temperature": 0.2,
        "max_tokens": 4096,
    },
    "backtest": {
        "initial_capital": 1_000_000,
        "commission_rate": 0.0003,
        "slippage": 0.001,
    },
    "ui": {
        "theme": "light",
    },
}

ALLOWED_SETTING_KEYS = set(DEFAULT_SETTINGS) | {"custom"}


class SettingsService:
    def get_all(self) -> dict:
        with get_conn() as conn:
            rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
        if not rows:
            self.update_many(DEFAULT_SETTINGS)
            result = dict(DEFAULT_SETTINGS)
        else:
            result = {}
            for row in rows:
                result[row["key"]] = json.loads(row["value_json"])
        result["data"] = self._get_data_window()
        return result

    def update_many(self, payload: dict) -> None:
        payload = {key: value for key, value in payload.items() if key in ALLOWED_SETTING_KEYS}
        if not payload:
            return
        with get_conn() as conn:
            for key, value in payload.items():
                if isinstance(value, dict):
                    current = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
                    base = dict(DEFAULT_SETTINGS.get(key, {}))
                    if current:
                        try:
                            existing = json.loads(current["value_json"])
                            if isinstance(existing, dict):
                                base.update(existing)
                        except (TypeError, json.JSONDecodeError):
                            pass
                    base.update(value)
                    value = base
                conn.execute(
                    """
                    INSERT INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    def _get_data_window(self) -> dict:
        calendar_path = app_settings.CALENDAR_DIR / "calendar.parquet"
        if not calendar_path.exists():
            return {
                "earliest_trade_date": None,
                "latest_trade_date": None,
            }

        conn = duckdb.connect()
        try:
            earliest = conn.execute(
                f"""
                SELECT trade_date
                FROM '{Path(calendar_path)}'
                WHERE is_open = 1
                ORDER BY trade_date ASC
                LIMIT 1
                """
            ).fetchone()
            latest = conn.execute(
                f"""
                SELECT trade_date
                FROM '{Path(calendar_path)}'
                WHERE is_open = 1
                ORDER BY trade_date DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()

        return {
            "earliest_trade_date": self._normalize_trade_date(earliest[0]) if earliest else None,
            "latest_trade_date": self._normalize_trade_date(latest[0]) if latest else None,
        }

    def _normalize_trade_date(self, value) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        if not text:
            return None
        if len(text) >= 10:
            return text[:10]
        return text
