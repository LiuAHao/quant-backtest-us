from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
STORAGE_DIR = BACKEND_DIR / "storage"
GENERATED_STRATEGY_DIR = STORAGE_DIR / "strategies"
GENERATED_EVENT_ANALYSIS_DIR = STORAGE_DIR / "event_analyses" / "generated"
EVENT_ANALYSIS_RESULT_DIR = STORAGE_DIR / "event_analyses" / "results"
GENERATED_FACTOR_ANALYSIS_DIR = STORAGE_DIR / "factor_analyses" / "generated"
FACTOR_ANALYSIS_RESULT_DIR = STORAGE_DIR / "factor_analyses" / "results"
DB_PATH = STORAGE_DIR / "quant_backtest.db"


def ensure_storage() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_EVENT_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    EVENT_ANALYSIS_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_FACTOR_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FACTOR_ANALYSIS_RESULT_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    ensure_storage()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate_db(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(backtest_tasks)").fetchall()}
    migrations = [
        ("total_return", "REAL"),
        ("max_drawdown", "REAL"),
        ("sharpe_ratio", "REAL"),
        ("runtime_logs_json", "TEXT"),
        ("benchmark", "TEXT"),
    ]
    for col, col_type in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE backtest_tasks ADD COLUMN {col} {col_type}")

    event_existing = {row[1] for row in conn.execute("PRAGMA table_info(event_analysis_tasks)").fetchall()}
    event_migrations = [
        ("sample_count", "INTEGER"),
        ("summary_json", "TEXT"),
        ("filters_json", "TEXT"),
        ("runtime_logs_json", "TEXT"),
    ]
    for col, col_type in event_migrations:
        if event_existing and col not in event_existing:
            conn.execute(f"ALTER TABLE event_analysis_tasks ADD COLUMN {col} {col_type}")

    factor_existing = {row[1] for row in conn.execute("PRAGMA table_info(factor_analysis_tasks)").fetchall()}
    factor_migrations = [
        ("sample_count", "INTEGER"),
        ("summary_json", "TEXT"),
        ("runtime_logs_json", "TEXT"),
    ]
    for col, col_type in factor_migrations:
        if factor_existing and col not in factor_existing:
            conn.execute(f"ALTER TABLE factor_analysis_tasks ADD COLUMN {col} {col_type}")


def init_db() -> None:
    ensure_storage()
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                tags_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'enabled',
                current_version_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                code TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                file_path TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                validation_message TEXT NOT NULL DEFAULT '',
                dependencies_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(strategy_id, version),
                FOREIGN KEY(strategy_id) REFERENCES strategies(id)
            );

            CREATE TABLE IF NOT EXISTS backtest_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                strategy_version_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                commission_rate REAL NOT NULL,
                slippage REAL NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                report_json_path TEXT,
                report_html_path TEXT,
                runtime_logs_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY(strategy_id) REFERENCES strategies(id),
                FOREIGN KEY(strategy_version_id) REFERENCES strategy_versions(id)
            );

            CREATE TABLE IF NOT EXISTS event_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                tags_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'enabled',
                current_version_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS event_definition_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_definition_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                code TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                file_path TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                validation_message TEXT NOT NULL DEFAULT '',
                dependencies_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_definition_id, version),
                FOREIGN KEY(event_definition_id) REFERENCES event_definitions(id)
            );

            CREATE TABLE IF NOT EXISTS event_analysis_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_definition_id INTEGER NOT NULL,
                event_definition_version_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                windows_json TEXT NOT NULL DEFAULT '[5, 10, 15]',
                entry_rule TEXT NOT NULL DEFAULT 'next_open',
                dedup_rule TEXT NOT NULL DEFAULT 'none',
                universe TEXT NOT NULL DEFAULT 'all_a',
                filters_json TEXT NOT NULL DEFAULT '[]',
                progress INTEGER NOT NULL DEFAULT 0,
                sample_count INTEGER,
                summary_json TEXT,
                result_json_path TEXT,
                runtime_logs_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY(event_definition_id) REFERENCES event_definitions(id),
                FOREIGN KEY(event_definition_version_id) REFERENCES event_definition_versions(id)
            );

            CREATE TABLE IF NOT EXISTS factor_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                tags_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'enabled',
                current_version_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS factor_definition_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_definition_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                code TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                file_path TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                validation_message TEXT NOT NULL DEFAULT '',
                dependencies_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(factor_definition_id, version),
                FOREIGN KEY(factor_definition_id) REFERENCES factor_definitions(id)
            );

            CREATE TABLE IF NOT EXISTS factor_analysis_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_definition_id INTEGER NOT NULL,
                factor_definition_version_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                windows_json TEXT NOT NULL DEFAULT '[1, 5, 10, 20]',
                universe TEXT NOT NULL DEFAULT 'all_a',
                filters_json TEXT NOT NULL DEFAULT '[]',
                rebalance_rule TEXT NOT NULL DEFAULT 'daily',
                quantiles INTEGER NOT NULL DEFAULT 5,
                ic_method TEXT NOT NULL DEFAULT 'spearman',
                factor_direction TEXT NOT NULL DEFAULT 'higher_better',
                preprocessing_json TEXT NOT NULL DEFAULT '{}',
                progress INTEGER NOT NULL DEFAULT 0,
                sample_count INTEGER,
                summary_json TEXT,
                result_json_path TEXT,
                runtime_logs_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY(factor_definition_id) REFERENCES factor_definitions(id),
                FOREIGN KEY(factor_definition_version_id) REFERENCES factor_definition_versions(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backtest_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                commission_rate REAL NOT NULL,
                slippage REAL NOT NULL,
                benchmark TEXT NOT NULL DEFAULT 'hs300',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backtest_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                initial_capital REAL NOT NULL DEFAULT 1000000,
                commission_rate REAL NOT NULL DEFAULT 0.0003,
                slippage REAL NOT NULL DEFAULT 0.001,
                benchmark TEXT NOT NULL DEFAULT 'hs300',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                api_endpoint TEXT NOT NULL,
                api_key TEXT,
                default_strategy_key TEXT,
                default_preset_id INTEGER,
                auto_run INTEGER NOT NULL DEFAULT 0,
                schedule_cron TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(default_preset_id) REFERENCES backtest_presets(id)
            );
            """
        )
        _migrate_db(conn)

        # Performance indexes (M4.3)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_backtest_tasks_strategy_id ON backtest_tasks(strategy_id);
            CREATE INDEX IF NOT EXISTS idx_backtest_tasks_status ON backtest_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_backtest_tasks_created_at ON backtest_tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_event_analysis_tasks_def_id ON event_analysis_tasks(event_definition_id);
            CREATE INDEX IF NOT EXISTS idx_event_analysis_tasks_status ON event_analysis_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_factor_analysis_tasks_def_id ON factor_analysis_tasks(factor_definition_id);
            CREATE INDEX IF NOT EXISTS idx_factor_analysis_tasks_status ON factor_analysis_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_strategy_versions_sid_ver ON strategy_versions(strategy_id, version);
            CREATE INDEX IF NOT EXISTS idx_event_def_versions_did_ver ON event_definition_versions(event_definition_id, version);
            CREATE INDEX IF NOT EXISTS idx_factor_def_versions_did_ver ON factor_definition_versions(factor_definition_id, version);
            """
        )
