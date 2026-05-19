"""
量化回测系统

模块:
- data_loader: 数据加载器
- broker: 模拟券商
- engine: 回测引擎
- strategy: 策略模板
"""

from backtest.data_loader import DataLoader, create_data_loader
from backtest.broker import (
    Broker,
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    Account,
    get_price_limit_ratio,
    get_price_limit_status,
)
from backtest.engine import BacktestEngine, BacktestResult
from backtest.strategy import StrategyTemplate, DualMAStrategy, MomentumStrategy, MeanReversionStrategy

__all__ = [
    'DataLoader',
    'create_data_loader',
    'Broker',
    'Order',
    'OrderSide',
    'OrderType',
    'OrderStatus',
    'Position',
    'Account',
    'get_price_limit_ratio',
    'get_price_limit_status',
    'BacktestEngine',
    'BacktestResult',
    'StrategyTemplate',
    'DualMAStrategy',
    'MomentumStrategy',
    'MeanReversionStrategy',
]
