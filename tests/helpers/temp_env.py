from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import backend.db.database as database
import config


class TempProjectEnv:
    def __init__(self, root: Path):
        self.root = root
        self.storage = root / "storage"
        self.db_path = self.storage / "quant_backtest.db"
        self.data_dir = root / "data"
        self.patchers = []

    @classmethod
    def under_cwd(cls, test_name: str) -> "TempProjectEnv":
        root = Path.cwd() / ".test-tmp" / test_name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        return cls(root)

    def patch_data_dirs(self) -> "TempProjectEnv":
        self.patchers.extend(
            [
                patch.object(config.settings, "DATA_DIR", self.data_dir),
                patch.object(config.settings, "DAILY_BAR_DIR", self.data_dir / "daily_bar"),
                patch.object(config.settings, "ADJ_FACTOR_DIR", self.data_dir / "adj_factor"),
                patch.object(config.settings, "CALENDAR_DIR", self.data_dir / "calendar"),
                patch.object(config.settings, "DAILY_BASIC_DIR", self.data_dir / "daily_basic"),
                patch.object(config.settings, "STK_LIMIT_DIR", self.data_dir / "stk_limit"),
                patch.object(config.settings, "SUSPEND_D_DIR", self.data_dir / "suspend_d"),
                patch.object(config.settings, "NAMECHANGE_DIR", self.data_dir / "namechange"),
                patch.object(config.settings, "INSTRUMENTS_DIR", self.data_dir / "instruments"),
                patch.object(config.settings, "INDEX_MEMBER_DIR", self.data_dir / "index_member"),
                patch.object(config.settings, "CONCEPT_DIR", self.data_dir / "concept"),
                patch.object(config.settings, "INDEX_DAILY_DIR", self.data_dir / "index_daily"),
                patch.object(config.settings, "FUND_BASIC_DIR", self.data_dir / "fund_basic"),
                patch.object(config.settings, "INDUSTRY_DIR", self.data_dir / "industry"),
                patch.object(config.settings, "FINANCIAL_DIR", self.data_dir / "financial"),
                patch.object(config.settings, "ETF_DAILY_DIR", self.data_dir / "etf_daily"),
                patch.object(config.settings, "HOLDER_NUMBER_DIR", self.data_dir / "holder_number"),
            ]
        )
        return self

    def patch_database(self, **overrides: Path) -> "TempProjectEnv":
        values = {
            "STORAGE_DIR": self.storage,
            "DB_PATH": self.db_path,
        }
        values.update(overrides)
        self.patchers.extend(patch.object(database, name, value) for name, value in values.items())
        return self

    def start(self) -> "TempProjectEnv":
        for patcher in self.patchers:
            patcher.start()
        return self

    def stop(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)
