"""
策略示例和模板库

提供多种预定义策略模板，方便用户快速创建和测试。
所有策略都经过验证，可以直接使用或作为参考。
"""
from __future__ import annotations

from backtest.strategy import StrategyTemplate


# ==================== 基础模板 ====================

class BaseTemplate(StrategyTemplate):
    """基础策略模板
    
    最简单的策略结构，适合作为起点。
    """
    
    def __init__(self):
        super().__init__("基础模板")
    
    def init(self, context):
        """初始化，回测开始前调用一次"""
        pass
    
    def next(self, context):
        """每日执行"""
        pass


# ==================== 示例策略 ====================

class BuyAndHold(StrategyTemplate):
    """买入持有策略
    
    简单的买入持有策略，适合测试回测系统。
    策略逻辑：
    - 第一天买入等权重的股票组合
    - 之后不再操作
    """
    
    def __init__(self, stock_count: int = 5):
        super().__init__("买入持有")
        self.stock_count = stock_count
        self.bought = False
    
    def init(self, context):
        """初始化"""
        self.bought = False
    
    def next(self, context):
        """每日执行"""
        if not self.bought:
            market_data = context["market_data"]
            
            if len(market_data) >= self.stock_count:
                # 选择市值最小的N只股票
                stocks = market_data.nsmallest(self.stock_count, "total_mv")["ts_code"].tolist()
                
                # 等权买入
                weight = 1.0 / len(stocks)
                for stock in stocks:
                    context["order_target_percent"](stock, weight)
                
                self.bought = True


class SmallCapRotation(StrategyTemplate):
    """小市值轮动策略
    
    经典的小市值轮动策略，定期调仓。
    策略逻辑：
    - 每N天调仓一次
    - 选择市值最小的M只股票
    - 等权配置
    """
    
    def __init__(self, hold_days: int = 5, stock_count: int = 10):
        super().__init__("小市值轮动")
        self.hold_days = hold_days
        self.stock_count = stock_count
    
    def init(self, context):
        """初始化"""
        self.day_count = 0
    
    def next(self, context):
        """每日执行"""
        self.day_count += 1
        
        # 每N天调仓一次
        if self.day_count % self.hold_days == 1:
            market_data = context["market_data"]
            
            # 选出市值最小的N只股票
            small_caps = market_data.nsmallest(self.stock_count, "total_mv")
            target_stocks = small_caps["ts_code"].tolist()
            
            # 清仓不在目标列表中的股票
            positions = context["broker"].account.positions
            for stock in positions:
                if stock not in target_stocks:
                    context["order_target_percent"](stock, 0)
            
            # 等权买入目标股票
            if target_stocks:
                weight = 1.0 / len(target_stocks)
                for stock in target_stocks:
                    context["order_target_percent"](stock, weight)


class DualMAStrategy(StrategyTemplate):
    """双均线策略
    
    基于移动平均线的趋势跟踪策略。
    策略逻辑：
    - 短期均线上穿长期均线时买入
    - 短期均线下穿长期均线时卖出
    """
    
    def __init__(self, stock: str = "000001.SZ", short_window: int = 5, long_window: int = 20):
        super().__init__("双均线策略")
        self.stock = stock
        self.short_window = short_window
        self.long_window = long_window
    
    def init(self, context):
        """初始化"""
        pass
    
    def next(self, context):
        """每日执行"""
        # 获取历史数据
        history = context["get_history"](self.stock, self.long_window + 10)
        
        if len(history) < self.long_window:
            return
        
        # 计算均线
        history["ma_short"] = history["close"].rolling(self.short_window).mean()
        history["ma_long"] = history["close"].rolling(self.long_window).mean()
        
        # 获取最新值
        latest = history.iloc[-1]
        prev = history.iloc[-2]
        
        # 金叉买入，死叉卖出
        if prev["ma_short"] <= prev["ma_long"] and latest["ma_short"] > latest["ma_long"]:
            context["order_target_percent"](self.stock, 1.0)
        elif prev["ma_short"] >= prev["ma_long"] and latest["ma_short"] < latest["ma_long"]:
            context["order_target_percent"](self.stock, 0)


class MomentumStrategy(StrategyTemplate):
    """动量策略
    
    基于价格动量的轮动策略。
    策略逻辑：
    - 每N天调仓一次
    - 选择过去M天涨幅最大的K只股票
    - 等权配置
    """
    
    def __init__(self, hold_days: int = 5, lookback_days: int = 20, stock_count: int = 10):
        super().__init__("动量策略")
        self.hold_days = hold_days
        self.lookback_days = lookback_days
        self.stock_count = stock_count
    
    def init(self, context):
        """初始化"""
        self.day_count = 0
    
    def next(self, context):
        """每日执行"""
        self.day_count += 1
        
        # 每N天调仓一次
        if self.day_count % self.hold_days == 1:
            market_data = context["market_data"]
            
            # 获取所有股票的代码
            all_stocks = market_data["ts_code"].tolist()
            
            # 计算每只股票的动量（收益率）
            momentum_scores = {}
            for stock in all_stocks:
                history = context["get_history"](stock, self.lookback_days + 1)
                if len(history) > self.lookback_days:
                    # 计算收益率
                    returns = (history["close"].iloc[-1] / history["close"].iloc[0]) - 1
                    momentum_scores[stock] = returns
            
            # 选择动量最大的N只股票
            sorted_stocks = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
            target_stocks = [s[0] for s in sorted_stocks[:self.stock_count]]
            
            # 清仓不在目标列表中的股票
            positions = context["broker"].account.positions
            for stock in positions:
                if stock not in target_stocks:
                    context["order_target_percent"](stock, 0)
            
            # 等权买入目标股票
            if target_stocks:
                weight = 1.0 / len(target_stocks)
                for stock in target_stocks:
                    context["order_target_percent"](stock, weight)


class LowVolatilityStrategy(StrategyTemplate):
    """低波动率策略
    
    选择波动率较低的股票进行配置。
    策略逻辑：
    - 每N天调仓一次
    - 选择过去M天波动率最小的K只股票
    - 等权配置
    """
    
    def __init__(self, hold_days: int = 5, lookback_days: int = 20, stock_count: int = 10):
        super().__init__("低波动率策略")
        self.hold_days = hold_days
        self.lookback_days = lookback_days
        self.stock_count = stock_count
    
    def init(self, context):
        """初始化"""
        self.day_count = 0
    
    def next(self, context):
        """每日执行"""
        self.day_count += 1
        
        # 每N天调仓一次
        if self.day_count % self.hold_days == 1:
            market_data = context["market_data"]
            
            # 获取所有股票的代码
            all_stocks = market_data["ts_code"].tolist()
            
            # 计算每只股票的波动率
            volatility_scores = {}
            for stock in all_stocks:
                history = context["get_history"](stock, self.lookback_days + 1)
                if len(history) > self.lookback_days:
                    # 计算日收益率的标准差
                    returns = history["close"].pct_change().dropna()
                    volatility = returns.std()
                    volatility_scores[stock] = volatility
            
            # 选择波动率最小的N只股票
            sorted_stocks = sorted(volatility_scores.items(), key=lambda x: x[1])
            target_stocks = [s[0] for s in sorted_stocks[:self.stock_count]]
            
            # 清仓不在目标列表中的股票
            positions = context["broker"].account.positions
            for stock in positions:
                if stock not in target_stocks:
                    context["order_target_percent"](stock, 0)
            
            # 等权买入目标股票
            if target_stocks:
                weight = 1.0 / len(target_stocks)
                for stock in target_stocks:
                    context["order_target_percent"](stock, weight)


class ValueStrategy(StrategyTemplate):
    """价值策略
    
    基于市盈率和市净率的价值投资策略。
    策略逻辑：
    - 每N天调仓一次
    - 选择市盈率和市净率较低的股票
    - 等权配置
    """
    
    def __init__(self, hold_days: int = 20, stock_count: int = 10):
        super().__init__("价值策略")
        self.hold_days = hold_days
        self.stock_count = stock_count
    
    def init(self, context):
        """初始化"""
        self.day_count = 0
    
    def next(self, context):
        """每日执行"""
        self.day_count += 1
        
        # 每N天调仓一次
        if self.day_count % self.hold_days == 1:
            market_data = context["market_data"]
            
            # 过滤掉市盈率为负的股票
            valid_stocks = market_data[market_data["pe_ttm"] > 0].copy()

            if len(valid_stocks) < self.stock_count:
                return

            # 计算综合得分（市盈率和市净率的综合）
            # 得分越低越好
            valid_stocks["score"] = valid_stocks["pe_ttm"] * 0.5 + valid_stocks["pb"] * 0.5
            
            # 选择得分最低的N只股票
            selected = valid_stocks.nsmallest(self.stock_count, "score")
            target_stocks = selected["ts_code"].tolist()
            
            # 清仓不在目标列表中的股票
            positions = context["broker"].account.positions
            for stock in positions:
                if stock not in target_stocks:
                    context["order_target_percent"](stock, 0)
            
            # 等权买入目标股票
            if target_stocks:
                weight = 1.0 / len(target_stocks)
                for stock in target_stocks:
                    context["order_target_percent"](stock, weight)


# ==================== 策略注册表 ====================

STRATEGY_TEMPLATES = {
    "base_template": {
        "class": BaseTemplate,
        "name": "基础模板",
        "description": "最简单的策略结构，适合作为起点",
        "params": {},
    },
    "buy_and_hold": {
        "class": BuyAndHold,
        "name": "买入持有",
        "description": "简单的买入持有策略，适合测试回测系统",
        "params": {"stock_count": 5},
    },
    "small_cap_rotation": {
        "class": SmallCapRotation,
        "name": "小市值轮动",
        "description": "经典的小市值轮动策略，定期调仓",
        "params": {"hold_days": 5, "stock_count": 10},
    },
    "dual_ma": {
        "class": DualMAStrategy,
        "name": "双均线策略",
        "description": "基于移动平均线的趋势跟踪策略",
        "params": {"stock": "000001.SZ", "short_window": 5, "long_window": 20},
    },
    "momentum": {
        "class": MomentumStrategy,
        "name": "动量策略",
        "description": "基于价格动量的轮动策略",
        "params": {"hold_days": 5, "lookback_days": 20, "stock_count": 10},
    },
    "low_volatility": {
        "class": LowVolatilityStrategy,
        "name": "低波动率策略",
        "description": "选择波动率较低的股票进行配置",
        "params": {"hold_days": 5, "lookback_days": 20, "stock_count": 10},
    },
    "value": {
        "class": ValueStrategy,
        "name": "价值策略",
        "description": "基于市盈率和市净率的价值投资策略",
        "params": {"hold_days": 20, "stock_count": 10},
    },
}


def get_template_code(template_key: str) -> str:
    """获取策略模板的代码
    
    Args:
        template_key: 模板键名
        
    Returns:
        策略代码字符串
    """
    import inspect
    
    if template_key not in STRATEGY_TEMPLATES:
        raise ValueError(f"未知的模板: {template_key}")
    
    template = STRATEGY_TEMPLATES[template_key]
    code = inspect.getsource(template["class"])
    
    # 添加导入语句
    import_code = "from backtest.strategy import StrategyTemplate\n\n"
    
    return import_code + code


def list_templates() -> list[dict]:
    """列出所有可用的策略模板
    
    Returns:
        模板信息列表
    """
    return [
        {
            "key": key,
            "name": info["name"],
            "description": info["description"],
            "params": info["params"],
        }
        for key, info in STRATEGY_TEMPLATES.items()
    ]
