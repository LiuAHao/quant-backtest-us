from __future__ import annotations

from backend.db.database import init_db
from backend.schemas import StrategyCreate, StrategyUpdate
from backend.services.strategy_service import StrategyService


SMALL_CAP_CODE = r'''from backtest.strategy import StrategyTemplate


class LocalSmallCapRotationStrategy(StrategyTemplate):
    def __init__(self):
        super().__init__("本地小市值轮动策略")
        self.top_n = 10
        self.rebalance_days = 20
        self.max_weight = 0.95
        self.day_count = 0
        self.universe = set()

    def init(self, context):
        instruments = context["data_loader"].get_instruments(status="L")
        universe = []
        for _, row in instruments.iterrows():
            ts_code = str(row.get("ts_code", ""))
            symbol = str(row.get("symbol", ""))
            raw_code = ts_code.split(".")[0]
            if not ts_code:
                continue
            if "ST" in symbol or raw_code.startswith(("30", "68", "8")):
                continue
            universe.append(ts_code)
        self.universe = set(universe)
        self.day_count = 0

    def _fallback_market_cap(self, ts_code, close_price):
        raw_code = ts_code.split(".")[0]
        code_score = sum((index + 1) * int(char) for index, char in enumerate(raw_code) if char.isdigit())
        estimated_shares = 50000 + code_score * 1000
        return close_price * estimated_shares

    def _market_cap(self, row):
        for field in ("circ_mv", "total_mv"):
            value = row.get(field)
            if value is not None and value == value and float(value) > 0:
                return float(value)
        close_price = float(row.get("close") or 0)
        if close_price <= 0:
            return None
        return self._fallback_market_cap(str(row.get("ts_code")), close_price)

    def next(self, context):
        self.day_count += 1
        if self.day_count % self.rebalance_days != 1:
            return

        market_data = context["market_data"]
        if market_data.empty:
            return

        candidates = []
        for _, row in market_data.iterrows():
            ts_code = str(row.get("ts_code", ""))
            if ts_code not in self.universe:
                continue
            close_price = float(row.get("close") or 0)
            if close_price <= 0:
                continue
            market_cap = self._market_cap(row)
            if market_cap is None:
                continue
            candidates.append((ts_code, market_cap, close_price))

        candidates.sort(key=lambda item: item[1])
        selected = candidates[:self.top_n]
        if not selected:
            return

        selected_codes = {item[0] for item in selected}
        current_positions = context["broker"].account.positions
        for ts_code, position in list(current_positions.items()):
            if position.volume > 0 and ts_code not in selected_codes:
                context["order_target_percent"](ts_code, 0)

        target_weight = self.max_weight / len(selected)
        price_map = {ts_code: close_price for ts_code, _, close_price in selected}
        for ts_code in selected_codes:
            context["order_target_percent"](ts_code, target_weight, price_map.get(ts_code))
'''


def main() -> None:
    init_db()
    service = StrategyService()
    payload = StrategyCreate(
        key="local_small_cap_rotation",
        name="本地小市值轮动策略",
        description="从本地日线截面中选取小市值股票，剔除 ST、创业板、科创板和北交所，按 20 个交易日轮动调仓。",
        source="manual",
        tags=["小市值", "轮动", "本地策略"],
        code=SMALL_CAP_CODE,
        status="enabled",
    )

    exists = next((item for item in service.list_strategies() if item.key == payload.key), None)
    if exists:
        saved = service.update_strategy(
            exists.id,
            StrategyUpdate(
                name=payload.name,
                description=payload.description,
                source=payload.source,
                tags=payload.tags,
                code=payload.code,
                status=payload.status,
            ),
        )
        action = "updated"
    else:
        saved = service.create_strategy(payload)
        action = "created"

    if saved is None:
        raise RuntimeError("小市值策略写入失败")
    print(f"{action}: id={saved.id}, key={saved.key}, name={saved.name}, version={saved.version}")


if __name__ == "__main__":
    main()
