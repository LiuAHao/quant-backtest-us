from __future__ import annotations

from factor_analysis.template import FactorAnalysisTemplate


class Momentum20Factor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("20日动量因子")

    def compute(self, context):
        current_date = context["current_date"].strftime("%Y-%m-%d")
        market = context["market_data"][["ts_code"]].drop_duplicates().copy()
        market["ts_code"] = market["ts_code"].astype(str)
        if market.empty:
            return market.assign(trade_date=current_date, factor_value=[])

        sql = f"""
            WITH recent AS (
                SELECT
                    d.ts_code,
                    d.close,
                    ROW_NUMBER() OVER (PARTITION BY d.ts_code ORDER BY d.trade_date DESC) AS rn
                FROM daily_bar d
                WHERE d.trade_date <= '{current_date}'
                  AND d.ts_code IN (
                      SELECT ts_code FROM market_codes
                  )
            ), pivoted AS (
                SELECT
                    ts_code,
                    MAX(CASE WHEN rn = 1 THEN close END) AS close_now,
                    MAX(CASE WHEN rn = 21 THEN close END) AS close_then
                FROM recent
                WHERE rn <= 21
                GROUP BY ts_code
            )
            SELECT
                ts_code,
                '{current_date}' AS trade_date,
                close_now / NULLIF(close_then, 0) - 1 AS factor_value
            FROM pivoted
            WHERE close_now IS NOT NULL
              AND close_then IS NOT NULL
        """
        context["conn"].register("market_codes", market)
        try:
            return context["conn"].execute(sql).fetchdf()
        finally:
            context["conn"].unregister("market_codes")