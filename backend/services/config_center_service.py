from __future__ import annotations

from datetime import datetime

from backend.db.database import get_conn
from backend.schemas import (
    AgentConfig,
    AgentConfigOut,
    BacktestPreset,
    BacktestPresetOut,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"


def _resolve_agent_api_key(payload_key: str | None, existing_key: str | None = None) -> str | None:
    if payload_key is None:
        return existing_key
    text = payload_key.strip()
    if not text:
        return None
    if existing_key and text == _mask_secret(existing_key):
        return existing_key
    return text


def _row_to_preset(row) -> BacktestPresetOut:
    return BacktestPresetOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        initial_capital=row["initial_capital"],
        commission_rate=row["commission_rate"],
        slippage=row["slippage"],
        benchmark=row["benchmark"],
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_agent(row) -> AgentConfigOut:
    return AgentConfigOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        api_endpoint=row["api_endpoint"],
        api_key=_mask_secret(row["api_key"]),
        default_strategy_key=row["default_strategy_key"],
        default_preset_id=row["default_preset_id"],
        auto_run=bool(row["auto_run"]),
        schedule_cron=row["schedule_cron"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ConfigCenterService:
    # ==================== 回测预设管理 ====================

    def list_presets(self) -> list[BacktestPresetOut]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_presets ORDER BY is_default DESC, created_at DESC"
            ).fetchall()
        return [_row_to_preset(row) for row in rows]

    def get_default_preset(self) -> BacktestPresetOut | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_presets WHERE is_default = 1 LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return _row_to_preset(row)

    def get_preset(self, preset_id: int) -> BacktestPresetOut | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_presets WHERE id = ?", (preset_id,)
            ).fetchone()
        if not row:
            return None
        return _row_to_preset(row)

    def create_preset(self, payload: BacktestPreset) -> BacktestPresetOut:
        with get_conn() as conn:
            if payload.is_default:
                conn.execute("UPDATE backtest_presets SET is_default = 0")

            cursor = conn.execute(
                """INSERT INTO backtest_presets
                   (name, description, initial_capital, commission_rate, slippage, benchmark, is_default)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload.name,
                    payload.description,
                    payload.initial_capital,
                    payload.commission_rate,
                    payload.slippage,
                    payload.benchmark,
                    int(payload.is_default),
                ),
            )
            preset_id = int(cursor.lastrowid)
            row = conn.execute(
                "SELECT * FROM backtest_presets WHERE id = ?", (preset_id,)
            ).fetchone()

        return _row_to_preset(row)

    def update_preset(self, preset_id: int, payload: BacktestPreset) -> BacktestPresetOut | None:
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM backtest_presets WHERE id = ?", (preset_id,)
            ).fetchone()
            if not exists:
                return None

            if payload.is_default:
                conn.execute("UPDATE backtest_presets SET is_default = 0")

            conn.execute(
                """UPDATE backtest_presets
                   SET name = ?, description = ?, initial_capital = ?, commission_rate = ?,
                       slippage = ?, benchmark = ?, is_default = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    payload.name,
                    payload.description,
                    payload.initial_capital,
                    payload.commission_rate,
                    payload.slippage,
                    payload.benchmark,
                    int(payload.is_default),
                    _now(),
                    preset_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM backtest_presets WHERE id = ?", (preset_id,)
            ).fetchone()

        return _row_to_preset(row)

    def delete_preset(self, preset_id: int) -> bool:
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM backtest_presets WHERE id = ?", (preset_id,)
            ).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM backtest_presets WHERE id = ?", (preset_id,))
        return True

    # ==================== Agent配置管理 ====================

    def list_agents(self) -> list[AgentConfigOut]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_configs ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_agent(row) for row in rows]

    def get_agent(self, agent_id: int) -> AgentConfigOut | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_configs WHERE id = ?", (agent_id,)
            ).fetchone()
        if not row:
            return None
        return _row_to_agent(row)

    def create_agent(self, payload: AgentConfig) -> AgentConfigOut:
        with get_conn() as conn:
            api_key = _resolve_agent_api_key(payload.api_key)
            cursor = conn.execute(
                """INSERT INTO agent_configs
                   (name, description, api_endpoint, api_key, default_strategy_key,
                    default_preset_id, auto_run, schedule_cron)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload.name,
                    payload.description,
                    payload.api_endpoint,
                    api_key,
                    payload.default_strategy_key,
                    payload.default_preset_id,
                    int(payload.auto_run),
                    payload.schedule_cron,
                ),
            )
            agent_id = int(cursor.lastrowid)
            row = conn.execute(
                "SELECT * FROM agent_configs WHERE id = ?", (agent_id,)
            ).fetchone()

        return _row_to_agent(row)

    def update_agent(self, agent_id: int, payload: AgentConfig) -> AgentConfigOut | None:
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id, api_key FROM agent_configs WHERE id = ?", (agent_id,)
            ).fetchone()
            if not existing:
                return None

            api_key = _resolve_agent_api_key(payload.api_key, existing["api_key"])
            conn.execute(
                """UPDATE agent_configs
                   SET name = ?, description = ?, api_endpoint = ?, api_key = ?,
                       default_strategy_key = ?, default_preset_id = ?, auto_run = ?,
                       schedule_cron = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    payload.name,
                    payload.description,
                    payload.api_endpoint,
                    api_key,
                    payload.default_strategy_key,
                    payload.default_preset_id,
                    int(payload.auto_run),
                    payload.schedule_cron,
                    _now(),
                    agent_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_configs WHERE id = ?", (agent_id,)
            ).fetchone()

        return _row_to_agent(row)

    def delete_agent(self, agent_id: int) -> bool:
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM agent_configs WHERE id = ?", (agent_id,)
            ).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM agent_configs WHERE id = ?", (agent_id,))
        return True

    # ==================== 系统信息 ====================

    def get_system_info(self) -> dict:
        import duckdb
        from pathlib import Path
        from config import settings as app_settings
        from backend.db.database import DB_PATH

        calendar_path = app_settings.CALENDAR_DIR / "calendar.parquet"
        data_range: dict[str, str | None] = {"earliest": None, "latest": None}

        if calendar_path.exists():
            try:
                conn = duckdb.connect()
                try:
                    earliest = conn.execute(
                        f"SELECT MIN(trade_date) FROM '{Path(calendar_path)}' WHERE is_open = 1"
                    ).fetchone()
                    latest = conn.execute(
                        f"SELECT MAX(trade_date) FROM '{Path(calendar_path)}' WHERE is_open = 1"
                    ).fetchone()
                    if earliest and earliest[0]:
                        data_range["earliest"] = str(earliest[0])[:10]
                    if latest and latest[0]:
                        data_range["latest"] = str(latest[0])[:10]
                finally:
                    conn.close()
            except Exception:
                pass

        try:
            with get_conn() as conn:
                total_strategies = conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]
                total_backtests = conn.execute("SELECT COUNT(*) FROM backtest_tasks").fetchone()[0]
                total_presets = conn.execute("SELECT COUNT(*) FROM backtest_presets").fetchone()[0]
        except Exception:
            total_strategies = 0
            total_backtests = 0
            total_presets = 0

        return {
            "version": "0.1.0",
            "data_dir": str(app_settings.DATA_DIR),
            "db_path": str(DB_PATH),
            "strategy_dir": str(app_settings.PROJECT_ROOT / "backend" / "storage" / "strategies"),
            "available_data_range": data_range,
            "total_strategies": total_strategies,
            "total_backtests": total_backtests,
            "total_presets": total_presets,
        }
