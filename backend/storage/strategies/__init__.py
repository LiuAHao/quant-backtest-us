"""
Strategy package.

Convention:
- Each strategy module defines one or more StrategyTemplate subclasses.
- BacktestEngine auto-generates strategy reports into:
  `backend/storage/strategies/reports/<strategy_file_stem>.json|html`
"""

from backtest.strategy import StrategyTemplate

__all__ = ["StrategyTemplate"]
