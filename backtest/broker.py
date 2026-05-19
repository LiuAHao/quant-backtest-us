"""
模拟券商/交易接口
处理订单、成交、持仓、资金计算
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional
from datetime import datetime
from enum import Enum

import pandas as pd
from loguru import logger


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_price_limit_ratio(
    ts_code: str,
    *,
    is_st: bool = False,
    limit_ratio: Optional[float] = None,
) -> float:
    """Return the default A-share daily price-limit ratio for a security."""
    if limit_ratio is not None:
        return float(limit_ratio)
    if is_st:
        return 0.05

    code = str(ts_code).split('.')[0]
    suffix = str(ts_code).split('.')[-1] if '.' in str(ts_code) else ''
    if suffix == 'BJ' or (suffix == '' and (code.startswith('8') or code.startswith('4'))):
        return 0.30
    if code.startswith('30') or code.startswith('688'):
        return 0.20
    return 0.10


def get_price_limit_status(
    bar: Optional[Mapping[str, Any]] = None,
    *,
    ts_code: Optional[str] = None,
    price: Optional[float] = None,
    pre_close: Optional[float] = None,
    up_limit: Optional[float] = None,
    down_limit: Optional[float] = None,
    is_st: bool = False,
    limit_ratio: Optional[float] = None,
    tolerance: float = 1e-6,
) -> Dict[str, Any]:
    """
    Quickly check whether a price is at the daily up/down limit.

    Prefer exchange/vendor-provided ``up_limit`` and ``down_limit`` when present
    in ``bar``. If they are unavailable, fall back to pre_close * limit ratio.
    """
    if bar is not None:
        ts_code = ts_code or bar.get('ts_code')
        price = _to_float(price if price is not None else bar.get('close'))
        pre_close = _to_float(pre_close if pre_close is not None else bar.get('pre_close'))
        up_limit = _to_float(up_limit if up_limit is not None else bar.get('up_limit'))
        down_limit = _to_float(down_limit if down_limit is not None else bar.get('down_limit'))
        limit_ratio = _to_float(limit_ratio if limit_ratio is not None else bar.get('limit_ratio'))
        is_st = bool(bar.get('is_st', is_st))
    else:
        price = _to_float(price)
        pre_close = _to_float(pre_close)
        up_limit = _to_float(up_limit)
        down_limit = _to_float(down_limit)
        limit_ratio = _to_float(limit_ratio)

    if up_limit is None or down_limit is None:
        if pre_close is not None and pre_close > 0 and ts_code:
            ratio = get_price_limit_ratio(ts_code, is_st=is_st, limit_ratio=limit_ratio)
            up_limit = round(pre_close * (1 + ratio), 2)
            down_limit = round(pre_close * (1 - ratio), 2)
            limit_ratio = ratio
    elif limit_ratio is None and pre_close is not None and pre_close > 0:
        limit_ratio = max(abs(up_limit / pre_close - 1), abs(1 - down_limit / pre_close))

    is_limit_up = bool(price is not None and up_limit is not None and price >= up_limit - tolerance)
    is_limit_down = bool(price is not None and down_limit is not None and price <= down_limit + tolerance)

    return {
        'is_limit_up': is_limit_up,
        'is_limit_down': is_limit_down,
        'up_limit': up_limit,
        'down_limit': down_limit,
        'limit_ratio': limit_ratio,
    }


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"  # 市价单
    LIMIT = "limit"    # 限价单


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"      # 待成交
    FILLED = "filled"        # 已成交
    PARTIAL = "partial"      # 部分成交
    CANCELLED = "cancelled"  # 已取消
    REJECTED = "rejected"    # 已拒绝


@dataclass
class Order:
    """订单对象"""
    id: str
    ts_code: str
    side: OrderSide
    order_type: OrderType
    volume: int
    price: Optional[float] = None  # 限价单价格
    status: OrderStatus = OrderStatus.PENDING
    filled_volume: int = 0
    filled_price: float = 0.0
    create_time: datetime = field(default_factory=datetime.now)
    fill_time: Optional[datetime] = None
    reject_reason: Optional[str] = None


@dataclass
class Position:
    """持仓对象"""
    ts_code: str
    volume: int = 0
    avg_cost: float = 0.0
    buy_dates: Dict[datetime, int] = field(default_factory=dict)  # 记录每日买入的股数 {date: volume}
    
    @property
    def market_value(self) -> float:
        """持仓成本市值 (volume * avg_cost)"""
        return self.volume * self.avg_cost

    def get_market_value(self, current_price: float = None) -> float:
        """持仓市值 (volume * price)，不传价格时回退到成本市值"""
        if current_price is None:
            return self.market_value
        return self.volume * current_price
    
    def add(self, volume: int, price: float, trade_date: datetime = None):
        """增加持仓"""
        total_cost = self.volume * self.avg_cost + volume * price
        self.volume += volume
        if self.volume > 0:
            self.avg_cost = total_cost / self.volume
        
        # 记录买入日期和数量（用于T+1判断）
        if trade_date is not None:
            date_key = trade_date.date() if hasattr(trade_date, 'date') else trade_date
            if date_key not in self.buy_dates:
                self.buy_dates[date_key] = 0
            self.buy_dates[date_key] += volume
    
    def reduce(self, volume: int, trade_date: datetime = None) -> int:
        """
        减少持仓
        
        Args:
            volume: 想卖出的股数
            trade_date: 交易日期
            
        Returns:
            实际可卖出的股数（受T+1限制）
        """
        if trade_date is None:
            # 无日期限制，全部可卖
            self.volume -= volume
            if self.volume <= 0:
                self.volume = 0
                self.avg_cost = 0.0
            return volume
        
        # T+1检查：计算当日可卖数量
        trade_date_key = trade_date.date() if hasattr(trade_date, 'date') else trade_date
        
        # 计算今日买入的股数（不可卖）
        today_bought = self.buy_dates.get(trade_date_key, 0)
        
        # 计算可卖数量（总持仓 - 今日买入）
        sellable_volume = max(0, self.volume - today_bought)
        
        # 实际卖出数量
        actual_sell = min(volume, sellable_volume)
        
        self.volume -= actual_sell
        if self.volume <= 0:
            self.volume = 0
            self.avg_cost = 0.0
        
        return actual_sell
    
    def get_sellable_volume(self, trade_date: datetime) -> int:
        """获取当日可卖出的股数（T+1限制）"""
        if trade_date is None:
            return self.volume
        
        trade_date_key = trade_date.date() if hasattr(trade_date, 'date') else trade_date
        today_bought = self.buy_dates.get(trade_date_key, 0)
        return max(0, self.volume - today_bought)


@dataclass
class Account:
    """账户对象"""
    initial_capital: float
    cash: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.cash == 0:
            self.cash = self.initial_capital
    
    def get_total_value(self, prices: Dict[str, float] = None) -> float:
        """总资产"""
        position_value = 0.0
        if prices:
            for ts_code, pos in self.positions.items():
                price = prices.get(ts_code, 0)
                position_value += pos.volume * price
        return self.cash + position_value
    
    @property
    def total_value(self) -> float:
        """总资产（不含持仓市值）"""
        return self.cash
    
    def get_position(self, ts_code: str) -> Position:
        """获取持仓"""
        if ts_code not in self.positions:
            self.positions[ts_code] = Position(ts_code=ts_code)
        return self.positions[ts_code]


class Broker:
    """
    模拟券商
    
    功能：
    - 接收订单
    - 撮合成交
    - 管理持仓
    - 计算资金
    """
    
    def __init__(
        self,
        initial_capital: float = 1000000.0,
        commission_rate: float = 0.0003,
        min_commission: float = 5.0,
        slippage: float = 0.001,
        stamp_duty_rate: float = 0.0005
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.slippage = slippage
        self.stamp_duty_rate = stamp_duty_rate
        
        self.account = Account(initial_capital=initial_capital)
        self.orders: List[Order] = []
        self.trade_history: List[Dict] = []
        
        self.order_counter = 0
        self.price_limit_rejections = {'up': 0, 'down': 0}
        self.limit_down_rejections = 0  # Backward-compatible alias for reports/logs.
    
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        self.order_counter += 1
        return f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}_{self.order_counter:04d}"
    
    def submit_order(
        self,
        ts_code: str,
        side: OrderSide,
        volume: int,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET,
        trade_date: datetime = None
    ) -> Order:
        """
        提交订单
        
        Args:
            ts_code: 股票代码
            side: 买卖方向
            volume: 数量（股）
            price: 价格（限价单需要）
            order_type: 订单类型
            trade_date: 交易日期（用于T+1检查）
        
        Returns:
            Order对象
        """
        order = Order(
            id=self._generate_order_id(),
            ts_code=ts_code,
            side=side,
            order_type=order_type,
            volume=volume,
            price=price
        )
        
        # 检查订单有效性
        if volume <= 0:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "数量必须大于0"
            logger.warning(f"订单被拒绝: {order.reject_reason}")
            return order

        if side == OrderSide.BUY and volume % 100 != 0:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "A股买入数量需为100股整数倍"
            logger.warning(f"订单被拒绝: {order.reject_reason}")
            return order
        
        if order_type == OrderType.LIMIT and price is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "限价单必须指定价格"
            logger.warning(f"订单被拒绝: {order.reject_reason}")
            return order
        
        # 检查卖出时是否有持仓（考虑T+1限制）
        if side == OrderSide.SELL:
            position = self.account.get_position(ts_code)
            sellable = position.get_sellable_volume(trade_date)
            if sellable < volume:
                order.status = OrderStatus.REJECTED
                order.reject_reason = f"可卖持仓不足: 持有{position.volume}股, 今日可卖{sellable}股, 尝试卖出{volume}股 (T+1限制)"
                logger.warning(f"订单被拒绝: {order.reject_reason}")
                return order
        
        self.orders.append(order)
        logger.info(f"提交订单: {side.value} {ts_code} {volume}股 @ {price if price else '市价'}")
        
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        for order in self.orders:
            if order.id == order_id and order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                logger.info(f"取消订单: {order_id}")
                return True
        return False
    
    def match_orders(self, trade_date: datetime, market_data: Dict[str, pd.Series], price_type: str = 'open'):
        """
        撮合订单
        
        Args:
            trade_date: 交易日期
            market_data: 市场数据 {ts_code: Series(open, high, low, close, volume)}
            price_type: 成交价类型，'open'=开盘价, 'close'=收盘价
        """
        for order in self.orders:
            if order.status != OrderStatus.PENDING:
                continue
            
            if order.ts_code not in market_data:
                continue
            
            bar = market_data[order.ts_code]

            exec_price = float(bar['close']) if price_type == 'close' else float(bar['open'])
            limit_status = get_price_limit_status(bar, ts_code=order.ts_code, price=exec_price)
            if order.side == OrderSide.BUY and limit_status['is_limit_up']:
                self.price_limit_rejections['up'] += 1
                continue
            if order.side == OrderSide.SELL and limit_status['is_limit_down']:
                self.price_limit_rejections['down'] += 1
                self.limit_down_rejections += 1
                continue
            
            # 获取成交价
            if order.order_type == OrderType.MARKET:
                # 市价单以指定价格成交
                fill_price = bar['close'] if price_type == 'close' else bar['open']
            else:
                # 限价单判断是否能成交
                if order.side == OrderSide.BUY:
                    # 买单：限价 >= 最低价 可成交
                    if order.price >= bar['low']:
                        fill_price = min(order.price, bar['open'])
                    else:
                        continue
                else:
                    # 卖单：限价 <= 最高价 可成交
                    if order.price <= bar['high']:
                        fill_price = max(order.price, bar['open'])
                    else:
                        continue
            
            # 应用滑点
            if order.side == OrderSide.BUY:
                fill_price = fill_price * (1 + self.slippage)
            else:
                fill_price = fill_price * (1 - self.slippage)
            
            # 计算费用
            amount = fill_price * order.volume
            commission = max(amount * self.commission_rate, self.min_commission)
            stamp_duty = amount * self.stamp_duty_rate if order.side == OrderSide.SELL else 0.0
            
            # 检查资金/持仓
            if order.side == OrderSide.BUY:
                total_cost = amount + commission
                if self.account.cash < total_cost:
                    order.status = OrderStatus.REJECTED
                    order.reject_reason = "资金不足"
                    logger.warning(f"订单被拒绝: {order.reject_reason}")
                    continue
            else:
                # 再次检查T+1限制
                position = self.account.get_position(order.ts_code)
                sellable = position.get_sellable_volume(trade_date)
                if sellable < order.volume:
                    order.status = OrderStatus.REJECTED
                    order.reject_reason = f"可卖持仓不足(T+1): 可卖{sellable}股, 尝试卖出{order.volume}股"
                    logger.warning(f"订单被拒绝: {order.reject_reason}")
                    continue
            
            # 执行成交
            self._execute_fill(order, fill_price, commission, stamp_duty, trade_date)

        for order in self.orders:
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED

    def _execute_fill(
        self,
        order: Order,
        fill_price: float,
        commission: float,
        stamp_duty: float,
        trade_date: datetime,
    ):
        """执行成交"""
        order.filled_volume = order.volume
        order.filled_price = fill_price
        order.status = OrderStatus.FILLED
        order.fill_time = trade_date
        
        amount = fill_price * order.volume
        
        # 更新账户
        if order.side == OrderSide.BUY:
            self.account.cash -= (amount + commission)
            self.account.get_position(order.ts_code).add(order.volume, fill_price, trade_date)
            realized_pnl = 0.0
        else:
            position = self.account.get_position(order.ts_code)
            realized_pnl = (fill_price - position.avg_cost) * order.volume - commission - stamp_duty
            self.account.cash += (amount - commission - stamp_duty)
            self.account.get_position(order.ts_code).reduce(order.volume, trade_date)
        
        # 记录交易
        self.trade_history.append({
            'trade_date': trade_date,
            'ts_code': order.ts_code,
            'side': order.side.value,
            'volume': order.volume,
            'price': fill_price,
            'amount': amount,
            'commission': commission,
            'stamp_duty': stamp_duty,
            'realized_pnl': realized_pnl
        })
        
        logger.info(
            f"成交: {order.side.value} {order.ts_code} "
            f"{order.volume}股 @ {fill_price:.2f} 手续费:{commission:.2f} 印花税:{stamp_duty:.2f}"
        )

    @staticmethod
    def _get_price_limit_ratio(ts_code: str) -> float:
        return get_price_limit_ratio(ts_code)
    
    def get_portfolio_value(self, current_prices: Dict[str, float]) -> Dict:
        """获取组合当前价值"""
        position_value = 0.0
        for ts_code, pos in self.account.positions.items():
            price = current_prices.get(ts_code, 0)
            position_value += pos.volume * price
        
        total = self.account.cash + position_value
        
        return {
            'cash': self.account.cash,
            'position_value': position_value,
            'total_value': total,
            'positions': {
                ts_code: {
                    'volume': pos.volume,
                    'avg_cost': pos.avg_cost,
                    'market_value': pos.volume * current_prices.get(ts_code, 0)
                }
                for ts_code, pos in self.account.positions.items()
                if pos.volume > 0
            }
        }
    
    def reset(self):
        """重置账户"""
        self.account = Account(initial_capital=self.initial_capital)
        self.orders = []
        self.trade_history = []
        self.order_counter = 0
