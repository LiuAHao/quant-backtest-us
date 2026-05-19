from __future__ import annotations

import pandas as pd

from factor_analysis.template import FactorAnalysisTemplate


class DividendYieldFactor(FactorAnalysisTemplate):
    def __init__(self):
        super().__init__("股息率因子")

    def compute(self, context):
        current_date = context["current_date"].strftime("%Y-%m-%d")
        sql = f"""
            SELECT ts_code,
                   '{current_date}' AS trade_date,
                   dv_ttm AS factor_value
            FROM daily_basic
            WHERE trade_date = '{current_date}'
              AND dv_ttm IS NOT NULL
        """
        factor_df = context["conn"].execute(sql).fetchdf()
        market_codes = context["market_data"][["ts_code"]].drop_duplicates()
        result = market_codes.merge(factor_df, on="ts_code", how="inner")
        return result[["ts_code", "trade_date", "factor_value"]]
