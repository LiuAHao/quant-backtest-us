# US Data Layer Roadmap

## Current State

The repository already has a usable local-first US daily research base:

- `us_daily_bar`: daily OHLCV research layer
- `us_daily_bar_raw`: raw per-symbol daily cache
- `us_instruments`: security master data
- `us_calendar`: US trading calendar
- `universe/*.txt`: broad, provider-clean, and core symbol universes

This is enough for:

- daily technical indicators
- momentum / volatility / liquidity studies
- simple cross-sectional research
- baseline daily backtests

This is not yet a complete quant research data source.

## What Is Still Missing

For serious US equity quant research, daily bars alone are not enough. The next layers should focus on:

1. corporate actions and adjustments
2. shares outstanding and market cap
3. fundamentals
4. industry classification and benchmark support
5. delisting / symbol history

## Recommended Priority

### Priority 1: Corporate Actions

Create a `us_corporate_actions` layer with at least:

- `symbol`
- `action_date`
- `action_type`
- `split_ratio`
- `cash_dividend`
- `source`
- `updated_at`

Why it matters:

- long-horizon returns break without split handling
- dividend-aware backtests need cash distribution data
- adjusted and raw price layers should be reconcilable

This is the highest-priority gap after daily bars, calendar, and instruments.

### Priority 2: Shares Outstanding and Market Cap

Create a `us_daily_basic`-style layer with at least:

- `symbol`
- `date`
- `close`
- `shares_outstanding`
- `float_shares` (if available)
- `market_cap`
- `float_market_cap` (if available)
- `source`
- `updated_at`

Why it matters:

- market cap is one of the most common research filters
- many factors depend on size
- turnover and liquidity analysis improve when share counts are available

This is the fastest way to move from "price-only" to "usable quant research base".

### Priority 3: Fundamentals

Create a `us_fundamentals` layer with point-in-time financial fields where possible.

Suggested minimum fields:

- `symbol`
- `report_date`
- `filing_date`
- `fiscal_period`
- `revenue`
- `gross_profit`
- `operating_income`
- `net_income`
- `total_assets`
- `total_liabilities`
- `shareholders_equity`
- `operating_cash_flow`
- `capex`
- `source`
- `updated_at`

Why it matters:

- needed for value, quality, profitability, and leverage factors
- needed for financial ratio construction
- should be treated as point-in-time data, not hindsight-cleaned snapshots

### Priority 4: Industry / Sector Classification

Create a `us_industry_classification` layer with:

- `symbol`
- `sector`
- `industry`
- `sub_industry` (if available)
- `classification_system`
- `source`
- `updated_at`

Why it matters:

- industry-neutral backtests
- grouped research
- exposure analysis

### Priority 5: Benchmark and Risk-Free Inputs

Keep benchmark and macro support simple:

- benchmark ETFs such as `SPY`, `QQQ`, `IWM`
- risk-free series from a stable source such as FRED

Why it matters:

- excess return calculations
- Sharpe and alpha/beta analysis
- report normalization

### Priority 6: Delisting and Symbol History

Eventually track:

- delisting date
- symbol rename history
- merger / corporate succession notes

Why it matters:

- survivorship-bias control
- better historical universe management
- safer long-horizon backtests

## Suggested Target Table Set

For a practical, compact US quant research base, the target table set should be:

1. `us_daily_bar`
2. `us_daily_bar_raw`
3. `us_calendar`
4. `us_instruments`
5. `us_corporate_actions`
6. `us_daily_basic`
7. `us_fundamentals`
8. `us_industry_classification`

The first four already exist.

## Practical Build Order

Recommended next implementation order:

1. `us_corporate_actions`
2. `us_daily_basic`
3. `us_fundamentals`
4. `us_industry_classification`

This order is chosen for research usefulness, not abstract completeness.

## Short Summary

If the goal is to build a complete quant-ready US daily data source, the most important missing layers are:

- corporate actions / adjustments
- shares outstanding / market cap
- financial fundamentals

Those three layers matter more right now than minute bars.
