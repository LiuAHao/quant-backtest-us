"""
示例策略
提供几个常用的策略模板
"""
import sys
from pathlib import Path
from typing import Dict, List
from datetime import datetime

import pandas as pd
import numpy as np
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from backtest.engine import BacktestEngine


class StrategyTemplate:
    """策略模板基类"""
    
    def __init__(self, name: str = "Strategy"):
        self.name = name
        self.params = {}
    
    def init(self, context: Dict):
        """初始化，回测开始前调用一次"""
        pass
    
    def next(self, context: Dict):
        """每日执行"""
        pass

    def on_order_filled(self, context: Dict, order, trade: Dict):
        """订单成交回调"""
        pass

    def on_day_end(self, context: Dict):
        """每日收盘后回调"""
        pass

    def on_backtest_end(self, context: Dict):
        """回测结束回调"""
        pass
    
    def get_callbacks(self):
        """获取回调函数"""
        return self.init, self.next


# ==================== 示例策略1：双均线策略 ====================

class DualMAStrategy(StrategyTemplate):
    """
    双均线策略
    
    参数:
        short_window: 短期均线窗口
        long_window: 长期均线窗口
        stock_pool: 股票池
    """
    
    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        stock_pool: List[str] = None
    ):
        super().__init__("DualMA")
        self.short_window = short_window
        self.long_window = long_window
        self.stock_pool = stock_pool or ['600000.SH', '000001.SZ']
    
    def init(self, context: Dict):
        """初始化"""
        logger.info(f"双均线策略初始化: short={self.short_window}, long={self.long_window}")
    
    def next(self, context: Dict):
        """每日执行"""
        date = context['current_date']
        data_loader = context['data_loader']
        
        for ts_code in self.stock_pool:
            # 获取历史数据
            df = data_loader.get_history(
                ts_code=ts_code,
                end_date=date,
                window=self.long_window + 5,
                adjust='qfq'
            )
            
            if len(df) < self.long_window:
                continue
            
            # 计算均线
            df['ma_short'] = df['close_fq'].rolling(self.short_window).mean()
            df['ma_long'] = df['close_fq'].rolling(self.long_window).mean()
            
            # 获取最新值
            ma_short = df['ma_short'].iloc[-1]
            ma_long = df['ma_long'].iloc[-1]
            prev_short = df['ma_short'].iloc[-2]
            prev_long = df['ma_long'].iloc[-2]
            
            # 金叉买入
            if prev_short <= prev_long and ma_short > ma_long:
                context['order_target_percent'](ts_code, 0.45)
                logger.info(f"{date.date()} {ts_code} 金叉买入")
            
            # 死叉卖出
            elif prev_short >= prev_long and ma_short < ma_long:
                context['order_target_percent'](ts_code, 0)
                logger.info(f"{date.date()} {ts_code} 死叉卖出")


# ==================== 示例策略2：动量策略 ====================

class MomentumStrategy(StrategyTemplate):
    """
    动量策略
    
    参数:
        lookback: 回看周期
        top_n: 选取前N只
        rebalance_freq: 调仓频率（交易日）
    """
    
    def __init__(
        self,
        lookback: int = 20,
        top_n: int = 5,
        rebalance_freq: int = 5,
        stock_pool: List[str] = None
    ):
        super().__init__("Momentum")
        self.lookback = lookback
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq
        self.stock_pool = stock_pool or []
        self.day_count = 0
    
    def init(self, context: Dict):
        """初始化"""
        logger.info(f"动量策略初始化: lookback={self.lookback}, top_n={self.top_n}")
        
        # 如果没有指定股票池，获取全市场
        if not self.stock_pool:
            instruments = context['data_loader'].get_instruments(status='L')
            self.stock_pool = instruments['ts_code'].tolist()[:50]  # 取前50只
        
        self.day_count = 0
    
    def next(self, context: Dict):
        """每日执行"""
        date = context['current_date']
        data_loader = context['data_loader']
        
        self.day_count += 1
        
        # 按频率调仓
        if self.day_count % self.rebalance_freq != 0:
            return
        
        # 计算动量
        momentum_scores = []
        
        for ts_code in self.stock_pool:
            df = data_loader.get_history(
                ts_code=ts_code,
                end_date=date,
                window=self.lookback + 5,
                adjust='qfq'
            )
            
            if len(df) < self.lookback:
                continue
            
            # 计算收益率
            momentum = (df['close_fq'].iloc[-1] / df['close_fq'].iloc[-self.lookback]) - 1
            momentum_scores.append((ts_code, momentum))
        
        # 排序选取top N
        momentum_scores.sort(key=lambda x: x[1], reverse=True)
        selected = [x[0] for x in momentum_scores[:self.top_n]]
        
        logger.info(f"{date.date()} 选中股票: {selected}")
        
        # 调仓
        weight = 0.9 / self.top_n if selected else 0
        
        # 清仓不在选中列表的股票
        for ts_code in self.stock_pool:
            if ts_code not in selected:
                context['order_target_percent'](ts_code, 0)
        
        # 买入选中的股票
        for ts_code in selected:
            context['order_target_percent'](ts_code, weight)


# ==================== 示例策略3：均值回归策略 ====================

class MeanReversionStrategy(StrategyTemplate):
    """
    均值回归策略（布林带）
    
    参数:
        window: 均线窗口
        std_dev: 标准差倍数
    """
    
    def __init__(
        self,
        window: int = 20,
        std_dev: float = 2.0,
        stock_pool: List[str] = None
    ):
        super().__init__("MeanReversion")
        self.window = window
        self.std_dev = std_dev
        self.stock_pool = stock_pool or ['600000.SH', '000001.SZ']
    
    def init(self, context: Dict):
        """初始化"""
        logger.info(f"均值回归策略初始化: window={self.window}, std_dev={self.std_dev}")
    
    def next(self, context: Dict):
        """每日执行"""
        date = context['current_date']
        data_loader = context['data_loader']
        
        for ts_code in self.stock_pool:
            df = data_loader.get_history(
                ts_code=ts_code,
                end_date=date,
                window=self.window + 5,
                adjust='qfq'
            )
            
            if len(df) < self.window:
                continue
            
            # 计算布林带
            df['ma'] = df['close_fq'].rolling(self.window).mean()
            df['std'] = df['close_fq'].rolling(self.window).std()
            df['upper'] = df['ma'] + self.std_dev * df['std']
            df['lower'] = df['ma'] - self.std_dev * df['std']
            
            close = df['close_fq'].iloc[-1]
            upper = df['upper'].iloc[-1]
            lower = df['lower'].iloc[-1]
            
            # 突破下轨买入
            if close < lower:
                context['order_target_percent'](ts_code, 0.45)
                logger.info(f"{date.date()} {ts_code} 突破下轨买入")
            
            # 突破上轨卖出
            elif close > upper:
                context['order_target_percent'](ts_code, 0)
                logger.info(f"{date.date()} {ts_code} 突破上轨卖出")


# ==================== 策略运行辅助函数 ====================

def run_strategy(
    strategy: StrategyTemplate,
    start_date: str,
    end_date: str,
    initial_capital: float = 1000000
):
    """
    运行策略
    
    Args:
        strategy: 策略实例
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        initial_capital: 初始资金
    
    Returns:
        BacktestResult
    """
    engine = BacktestEngine(
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital
    )
    
    init_func, next_func = strategy.get_callbacks()
    engine.set_strategy(init_func, next_func)
    
    result = engine.run()
    print(engine.report(result))
    
    return result


if __name__ == "__main__":
    # 配置日志
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import settings
    logger.add(settings.LOG_DIR / "strategy.log", rotation="10 MB")
    
    # 运行双均线策略示例
    strategy = DualMAStrategy(
        short_window=5,
        long_window=20,
        stock_pool=['600000.SH', '000001.SZ']
    )
    
    result = run_strategy(
        strategy=strategy,
        start_date='20240102',
        end_date='20240131',
        initial_capital=1000000
    )
