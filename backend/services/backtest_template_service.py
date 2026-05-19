from __future__ import annotations

from datetime import datetime

from backend.db.database import get_conn
from backend.schemas import BacktestTemplateCreate, BacktestTemplateOut
from backend.services.settings_service import SettingsService


class BacktestTemplateService:
    def __init__(self):
        self.settings = SettingsService()

    def list_templates(self) -> list[BacktestTemplateOut]:
        builtins = self._builtin_templates()
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_templates ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        saved = [self._row_to_out(row) for row in rows]
        return [*builtins, *saved]

    def create_template(self, payload: BacktestTemplateCreate) -> BacktestTemplateOut:
        self._validate_payload(payload)
        with get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backtest_templates (
                    name, start_date, end_date, initial_capital, commission_rate, slippage, benchmark
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name.strip(),
                    payload.start_date,
                    payload.end_date,
                    payload.initial_capital,
                    payload.commission_rate,
                    payload.slippage,
                    payload.benchmark,
                ),
            )
            template_id = int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM backtest_templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            raise ValueError("回测模板保存失败")
        return self._row_to_out(row)

    def delete_template(self, template_id: int) -> bool:
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM backtest_templates WHERE id = ?", (template_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM backtest_templates WHERE id = ?", (template_id,))
        return True

    def _builtin_templates(self) -> list[BacktestTemplateOut]:
        settings_payload = self.settings.get_all()
        data_window = settings_payload.get("data", {})
        backtest_defaults = settings_payload.get("backtest", {})
        earliest = data_window.get("earliest_trade_date")
        latest = data_window.get("latest_trade_date")
        if not earliest or not latest:
            return []

        templates = [
            ("builtin-recent-month", "近一个月", self._shift_months(latest, -1), latest),
            ("builtin-ytd-2025", "2025-01-01 至今", "2025-01-01", latest),
            ("builtin-ytd-2020", "2020-01-01 至今", "2020-01-01", latest),
        ]

        normalized = []
        for template_id, name, start_date, end_date in templates:
            effective_start = max(start_date, earliest)
            if effective_start > latest:
                effective_start = latest
            normalized.append(
                BacktestTemplateOut(
                    id=template_id,
                    db_id=None,
                    name=name,
                    kind="builtin",
                    start_date=effective_start,
                    end_date=end_date,
                    initial_capital=float(backtest_defaults.get("initial_capital", 1_000_000)),
                    commission_rate=float(backtest_defaults.get("commission_rate", 0.0003)),
                    slippage=float(backtest_defaults.get("slippage", 0.001)),
                    benchmark=str(backtest_defaults.get("benchmark", "hs300")),
                    created_at=None,
                    updated_at=None,
                )
            )
        return normalized

    def _validate_payload(self, payload: BacktestTemplateCreate) -> None:
        self._parse_date(payload.start_date, "开始日期")
        self._parse_date(payload.end_date, "结束日期")
        if payload.start_date > payload.end_date:
            raise ValueError("模板开始日期不能晚于结束日期")
        if payload.initial_capital <= 0:
            raise ValueError("模板初始资金必须大于 0")
        if payload.commission_rate < 0:
            raise ValueError("模板手续费率不能小于 0")
        if payload.slippage < 0:
            raise ValueError("模板滑点不能小于 0")

    def _row_to_out(self, row) -> BacktestTemplateOut:
        return BacktestTemplateOut(
            id=f"saved-{row['id']}",
            db_id=row["id"],
            name=row["name"],
            kind="saved",
            start_date=row["start_date"],
            end_date=row["end_date"],
            initial_capital=row["initial_capital"],
            commission_rate=row["commission_rate"],
            slippage=row["slippage"],
            benchmark=row["benchmark"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _parse_date(self, value: str, label: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{label}格式不正确，请使用 YYYY-MM-DD") from exc

    def _shift_months(self, value: str, months: int) -> str:
        current = datetime.strptime(value, "%Y-%m-%d")
        month_index = current.month - 1 + months
        year = current.year + month_index // 12
        month = month_index % 12 + 1
        day = min(current.day, self._days_in_month(year, month))
        return datetime(year, month, day).strftime("%Y-%m-%d")

    def _days_in_month(self, year: int, month: int) -> int:
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        current_month = datetime(year, month, 1)
        return (next_month - current_month).days
