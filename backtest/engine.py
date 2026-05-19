"""
回测引擎
协调数据加载、策略执行、订单撮合、结果统计
"""
import sys
import inspect
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

import pandas as pd
import numpy as np
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings
from backtest.data_loader import DataLoader
from backtest.broker import Broker, OrderSide, get_price_limit_status

BENCHMARK_MAP = {
    "hs300": "000300.SH",
    "zz500": "000905.SH",
    "zz1000": "000852.SH",
}


@dataclass
class BacktestResult:
    """回测结果"""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_value: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    win_rate: float
    daily_returns: pd.Series
    equity_curve: pd.Series
    trades: pd.DataFrame
    calmar_ratio: float = 0.0
    sortino_ratio: float = 0.0
    volatility: float = 0.0
    downside_volatility: float = 0.0
    profit_loss_ratio: float = 0.0
    avg_holding_days: float = 0.0
    turnover: float = 0.0
    benchmark_return: float | None = None
    excess_return: float | None = None
    alpha: float | None = None
    beta: float | None = None
    tracking_error: float | None = None
    information_ratio: float | None = None
    benchmark_daily_returns: pd.Series | None = None
    benchmark_curve: pd.Series | None = None
    benchmark_available: bool = False


class BacktestEngine:
    """
    回测引擎

    默认执行顺序（重要）：
    1. 当日开盘先撮合上一交易日收盘后提交的订单
    2. 当日收盘后策略读取当日数据并生成下一交易日开盘执行的订单
    """

    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_capital: float = None,
        commission_rate: float = None,
        slippage: float = None,
        prepare_data: bool = True,
        data_warmup_days: int = 400,
        enable_reports: bool = True,
        risk_free_rate: float = 0.0,
        benchmark: str = None,
        execution_mode: str = "next_open",
    ):
        if execution_mode not in {"next_open", "same_close"}:
            raise ValueError("execution_mode must be 'next_open' or 'same_close'")

        self.start_date = datetime.strptime(start_date, '%Y%m%d')
        self.end_date = datetime.strptime(end_date, '%Y%m%d')

        self.initial_capital = initial_capital or settings.DEFAULT_INITIAL_CAPITAL
        self.commission_rate = commission_rate or settings.DEFAULT_COMMISSION_RATE
        self.slippage = slippage or settings.DEFAULT_SLIPPAGE
        self.prepare_data = prepare_data
        self.data_warmup_days = data_warmup_days
        self.enable_reports = enable_reports
        self.risk_free_rate = risk_free_rate
        self.benchmark = benchmark
        self.execution_mode = execution_mode

        self.data_loader = DataLoader()
        self.broker = Broker(
            initial_capital=self.initial_capital,
            commission_rate=self.commission_rate,
            slippage=self.slippage,
        )

        self.strategy_init = None
        self.strategy_next = None
        self.strategy_obj = None
        self.current_date = None
        self.is_running = False

        self.daily_values: List[Dict] = []
        self.signals = []
        self.latest_prices: Dict[str, float] = {}
        self.current_market_data: Dict[str, Dict[str, Any]] = {}
        self.current_market_df = pd.DataFrame()
        self.strategy_name: str = "strategy"
        self.strategy_file_stem: str = "strategy"
        self.last_report_paths: Dict[str, Path] = {}
        self.report_enricher: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None

    def set_strategy(self, init_func: Callable, next_func: Callable, strategy_obj=None):
        self.strategy_init = init_func
        self.strategy_next = next_func
        self.strategy_obj = strategy_obj
        self.strategy_name = self._infer_strategy_name()
        self.strategy_file_stem = self._infer_strategy_file_stem()

    def set_report_enricher(self, enricher: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]):
        self.report_enricher = enricher

    def _get_trading_dates(self) -> List[datetime]:
        calendar = self.data_loader.get_trade_calendar(
            start_date=self.start_date,
            end_date=self.end_date,
            only_open=True,
        )
        return pd.to_datetime(calendar['trade_date']).tolist()

    def _create_context(self) -> Dict:
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'current_date': self.current_date,
            'data_loader': self.data_loader,
            'broker': self.broker,
            'get_history': self.data_loader.get_history,
            'get_cross_section': self.data_loader.get_cross_section,
            'get_position': lambda ts_code: self.broker.account.get_position(ts_code),
            'get_cash': lambda: self.broker.account.cash,
            'get_market_price': self._get_market_price,
            'get_portfolio_value': self._get_total_portfolio_value,
            'order_target_percent': self._order_target_percent,
            'order': self._order,
            'market_data': self.current_market_df,
            'market_data_map': self.current_market_data,
            'trade_date_index': self.data_loader.get_trade_date_index,
            'get_hold_days': self.data_loader.get_hold_days,
            'get_price_limit_status': get_price_limit_status,
            'is_limit_up': lambda bar, price=None: get_price_limit_status(bar, price=price)['is_limit_up'],
            'is_limit_down': lambda bar, price=None: get_price_limit_status(bar, price=price)['is_limit_down'],
        }

    def _order(self, ts_code: str, volume: int, side: str):
        side_enum = OrderSide.BUY if side == 'buy' else OrderSide.SELL
        self.broker.submit_order(ts_code, side_enum, abs(volume), trade_date=self.current_date)

    def _order_target_percent(self, ts_code: str, target_percent: float, current_price: float = None):
        if target_percent < 0 or target_percent > 1:
            logger.warning(f"目标仓位比例无效: {target_percent}")
            return

        if current_price is None:
            current_price = self._get_market_price(ts_code)
            if current_price is None or current_price <= 0:
                logger.warning(f"无法获取 {ts_code} 价格")
                return

        total_value = self._get_total_portfolio_value()
        target_value = total_value * target_percent
        target_volume = int(target_value / current_price / 100) * 100

        current_volume = self.broker.account.get_position(ts_code).volume
        diff_volume = target_volume - current_volume

        if diff_volume > 0:
            self.broker.submit_order(ts_code, OrderSide.BUY, diff_volume, trade_date=self.current_date)
        elif diff_volume < 0:
            self.broker.submit_order(ts_code, OrderSide.SELL, abs(diff_volume), trade_date=self.current_date)

    def _get_market_price(self, ts_code: str) -> Optional[float]:
        if ts_code in self.current_market_data:
            bar = self.current_market_data[ts_code]
            price = float(bar.get('close', 0) or 0)
            if price > 0:
                return price
        return self.latest_prices.get(ts_code)

    def _get_total_portfolio_value(self) -> float:
        return self.broker.get_portfolio_value(self.latest_prices)['total_value']

    def _infer_strategy_name(self) -> str:
        strategy_obj = getattr(self.strategy_next, "__self__", None)
        if strategy_obj is not None and hasattr(strategy_obj, "name"):
            return str(getattr(strategy_obj, "name"))
        if self.strategy_next is not None:
            return getattr(self.strategy_next, "__name__", "strategy")
        return "strategy"

    def _infer_strategy_file_stem(self) -> str:
        candidates = [self.strategy_next, self.strategy_init]
        for func in candidates:
            if func is None:
                continue
            source_file = inspect.getsourcefile(func)
            if source_file:
                return Path(source_file).stem
        return "strategy"

    def _collect_strategy_extension(self) -> Dict[str, Any]:
        strategy_obj = getattr(self.strategy_next, "__self__", None)
        if strategy_obj is None:
            return {}

        extension: Dict[str, Any] = {}
        if hasattr(strategy_obj, "get_strategy_snapshot"):
            try:
                extension["strategy"] = strategy_obj.get_strategy_snapshot()
            except Exception as exc:
                logger.warning("策略快照扩展失败: {}", exc)

        if hasattr(strategy_obj, "get_trade_summary"):
            try:
                trade_df = strategy_obj.get_trade_summary()
                if isinstance(trade_df, pd.DataFrame):
                    records = []
                    for row in trade_df.to_dict(orient="records"):
                        normalized = {}
                        for key, value in row.items():
                            if isinstance(value, (pd.Timestamp, datetime)):
                                normalized[key] = value.strftime("%Y-%m-%d %H:%M:%S")
                            elif isinstance(value, (np.integer,)):
                                normalized[key] = int(value)
                            elif isinstance(value, (np.floating,)):
                                normalized[key] = float(value)
                            else:
                                normalized[key] = value
                        records.append(normalized)
                    strategy_block = extension.setdefault("strategy", {})
                    strategy_block["event_count"] = len(records)
                    strategy_block["events"] = records
            except Exception as exc:
                logger.warning("策略事件扩展失败: {}", exc)

        return extension

    def _write_strategy_reports(self, result: BacktestResult):
        from backtest.reporting import build_report_payload, write_payload_json, write_html_report

        payload = build_report_payload(
            result=result,
            strategy_name=self.strategy_name,
            title=f"{self.strategy_name} 回测报告",
            subtitle="回测引擎自动生成",
        )
        payload.update(self._collect_strategy_extension())
        if self.report_enricher:
            try:
                extra_payload = self.report_enricher(payload)
                if isinstance(extra_payload, dict):
                    payload.update(extra_payload)
            except Exception as exc:
                logger.warning("报告扩展信息写入失败: {}", exc)

        reports_dir = Path(__file__).resolve().parent.parent / "strategies" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 生成带时间戳和回测区间的唯一文件名
        start_str = result.start_date.strftime("%Y%m%d")
        end_str = result.end_date.strftime("%Y%m%d")
        timestamp = datetime.now().strftime("%H%M%S")
        filename_stem = f"{self.strategy_file_stem}_{start_str}_{end_str}_{timestamp}"

        json_path = reports_dir / f"{filename_stem}.json"
        html_path = reports_dir / f"{filename_stem}.html"
        write_payload_json(payload, json_path)
        write_html_report(payload, html_path)
        self.last_report_paths = {"json": json_path, "html": html_path}
        logger.info("已输出策略报告: {}", json_path)
        logger.info("已输出策略报告: {}", html_path)

    def run(self) -> BacktestResult:
        logger.info(f"开始回测: {self.start_date.date()} ~ {self.end_date.date()}")
        logger.info(f"初始资金: {self.initial_capital:,.2f}")

        self.is_running = True
        self.daily_values = []
        self.latest_prices = {}
        self.current_market_data = {}
        self.current_market_df = pd.DataFrame()

        if self.prepare_data:
            self.data_loader.prepare_backtest_data(
                self.start_date,
                self.end_date,
                warmup_days=self.data_warmup_days,
            )

        trading_dates = self._get_trading_dates()
        logger.info(f"共 {len(trading_dates)} 个交易日")

        if self.strategy_init:
            self.strategy_init(self._create_context())

        for i, date in enumerate(trading_dates):
            self.current_date = date
            market_data, market_df = self._get_market_data(date)
            self.current_market_data = market_data
            self.current_market_df = market_df
            self.latest_prices.update({ts_code: float(bar['close']) for ts_code, bar in market_data.items()})

            if self.execution_mode == "next_open":
                # 先撮合已有订单（上一交易日信号）
                self.broker.match_orders(date, market_data, price_type='open')
            else:
                # 当日信号当日收盘成交，用于模拟 14:50 下单、收盘价成交等场景。
                if self.strategy_next:
                    try:
                        self.strategy_next(self._create_context())
                    except Exception as e:
                        import traceback
                        logger.error(f"策略执行错误 {date.date()}: {e}")
                        logger.error(traceback.format_exc())

                self.broker.match_orders(date, market_data, price_type='close')

            # on_order_filled 回调
            if self.strategy_obj and hasattr(self.strategy_obj, 'on_order_filled'):
                for trade in self.broker.trade_history:
                    if trade.get('trade_date') == date and not trade.get('_callback_fired'):
                        try:
                            self.strategy_obj.on_order_filled(self._create_context(), None, trade)
                        except Exception as e:
                            logger.warning(f"on_order_filled 回调异常: {e}")
                        trade['_callback_fired'] = True

            if self.execution_mode == "next_open":
                # 再运行策略（当日收盘信号，下一交易日执行）
                if self.strategy_next:
                    try:
                        self.strategy_next(self._create_context())
                    except Exception as e:
                        import traceback
                        logger.error(f"策略执行错误 {date.date()}: {e}")
                        logger.error(traceback.format_exc())

            # on_day_end 回调
            if self.strategy_obj and hasattr(self.strategy_obj, 'on_day_end'):
                try:
                    self.strategy_obj.on_day_end(self._create_context())
                except Exception as e:
                    logger.warning(f"on_day_end 回调异常: {e}")

            portfolio = self.broker.get_portfolio_value(self.latest_prices)
            holding_count = len([p for p in self.broker.account.positions.values() if p.volume > 0])
            self.daily_values.append({
                'date': date,
                'total_value': portfolio['total_value'],
                'cash': portfolio['cash'],
                'position_value': portfolio['position_value'],
                'holding_count': holding_count,
            })

            if (i + 1) % 20 == 0 or i == len(trading_dates) - 1:
                logger.info(f"进度: {i + 1}/{len(trading_dates)} {date.date()} 净值 {portfolio['total_value']:,.2f}")

        self.is_running = False
        logger.info("回测完成")
        logger.info(f"涨跌停未成交订单数: {self.broker.price_limit_rejections}")
        result = self._generate_result()

        # on_backtest_end 回调
        if self.strategy_obj and hasattr(self.strategy_obj, 'on_backtest_end'):
            try:
                self.strategy_obj.on_backtest_end(self._create_context())
            except Exception as e:
                logger.warning(f"on_backtest_end 回调异常: {e}")

        if self.enable_reports:
            try:
                self._write_strategy_reports(result)
            except Exception as exc:
                logger.warning("策略报告导出失败: {}", exc)
        return result

    def _get_market_data(self, date: datetime) -> tuple[Dict[str, Dict[str, Any]], pd.DataFrame]:
        df = self.data_loader.get_cross_section(date)
        if df.empty:
            return {}, df
        records = df.to_dict(orient='records')
        market_data = {row['ts_code']: row for row in records}
        return market_data, df

    def _generate_result(self) -> BacktestResult:
        values_df = pd.DataFrame(self.daily_values)
        if values_df.empty:
            logger.warning("回测区间没有可用净值记录，返回空结果")
            empty_index = pd.DatetimeIndex([self.start_date], name='date')
            empty_equity = pd.Series([self.initial_capital], index=empty_index, name='total_value')
            trades_df = pd.DataFrame(self.broker.trade_history)
            return BacktestResult(
                start_date=self.start_date,
                end_date=self.end_date,
                initial_capital=self.initial_capital,
                final_value=self.initial_capital,
                total_return=0.0,
                annual_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                trade_count=len(trades_df),
                win_rate=0.0,
                daily_returns=pd.Series(dtype=float),
                equity_curve=empty_equity,
                trades=trades_df,
            )

        values_df.set_index('date', inplace=True)
        values_df['daily_return'] = values_df['total_value'].pct_change()

        total_return = (values_df['total_value'].iloc[-1] / self.initial_capital) - 1
        days = len(values_df)
        years = days / 252
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

        cummax = values_df['total_value'].cummax()
        drawdown = (values_df['total_value'] - cummax) / cummax
        max_drawdown = drawdown.min()

        daily_returns = values_df['daily_return'].dropna()

        # --- Sharpe / Sortino using excess returns ---
        excess_returns = daily_returns - self.risk_free_rate / 252
        if len(excess_returns) > 1 and excess_returns.std() > 0:
            sharpe_ratio = float(excess_returns.mean() / excess_returns.std() * np.sqrt(252))
        else:
            sharpe_ratio = 0.0

        trades_df = pd.DataFrame(self.broker.trade_history)
        trade_count = len(trades_df)
        win_rate = self._calc_win_rate(trades_df)

        # --- Extended metrics (M3.2) ---
        volatility = float(daily_returns.std() * np.sqrt(252)) if len(daily_returns) > 1 else 0.0

        downside = excess_returns[excess_returns < 0]
        downside_volatility = float(downside.std() * np.sqrt(252)) if len(downside) > 1 else 0.0
        sortino_ratio = float(excess_returns.mean() / downside.std() * np.sqrt(252)) if len(downside) > 1 and downside.std() > 0 else 0.0

        calmar_ratio = float(annual_return / abs(max_drawdown)) if max_drawdown != 0 else 0.0

        profit_loss_ratio = 0.0
        if trades_df is not None and len(trades_df) > 0 and "realized_pnl" in trades_df.columns:
            gains = trades_df["realized_pnl"].clip(lower=0).sum()
            losses = abs(trades_df["realized_pnl"].clip(upper=0).sum())
            profit_loss_ratio = float(gains / losses) if losses > 0 else float(gains > 0)

        avg_holding_days = 0.0
        if trades_df is not None and len(trades_df) > 0 and "trade_date" in trades_df.columns:
            buy_dates = trades_df[trades_df["side"] == "buy"]["trade_date"]
            sell_dates = trades_df[trades_df["side"] == "sell"]["trade_date"]
            if len(buy_dates) > 0 and len(sell_dates) > 0:
                pairs = min(len(buy_dates), len(sell_dates))
                if pairs > 0:
                    diffs = [(sell_dates.iloc[i] - buy_dates.iloc[i]).days for i in range(pairs)]
                    avg_holding_days = float(np.mean(diffs))

        turnover = 0.0
        if trades_df is not None and len(trades_df) > 0 and "amount" in trades_df.columns:
            total_trade_value = trades_df["amount"].sum()
            avg_portfolio = values_df['total_value'].mean()
            if avg_portfolio > 0:
                turnover = float(total_trade_value / avg_portfolio)

        # --- Benchmark metrics ---
        benchmark_return_val: float | None = None
        excess_return_val: float | None = None
        alpha_val: float | None = None
        beta_val: float | None = None
        tracking_error_val: float | None = None
        information_ratio_val: float | None = None
        benchmark_daily_ret: pd.Series | None = None
        benchmark_curve: pd.Series | None = None
        benchmark_available = False

        benchmark_code = self._resolve_benchmark_code()
        if benchmark_code:
            bm = self._fetch_benchmark_series(benchmark_code)
            if bm is not None and len(bm) > 1:
                bm_aligned = bm.reindex(daily_returns.index)
                if bm_aligned.notna().sum() > 1:
                    benchmark_available = True
                    bm_aligned = bm_aligned.fillna(0.0)
                    benchmark_daily_ret = bm_aligned

                    benchmark_total = float((1 + bm_aligned).prod() - 1)
                    benchmark_return_val = benchmark_total
                    excess_return_val = float(total_return - benchmark_total)

                    bm_curve = (1 + bm_aligned).cumprod() * self.initial_capital
                    benchmark_curve = bm_curve

                    cov_matrix = np.cov(daily_returns.values, bm_aligned.values)
                    bm_var = cov_matrix[1, 1]
                    if bm_var > 0:
                        beta_val = float(cov_matrix[0, 1] / bm_var)
                        alpha_val = float(
                            annual_return
                            - self.risk_free_rate
                            - beta_val * ((1 + benchmark_total) ** (1 / years) - 1 - self.risk_free_rate)
                        ) if years > 0 else 0.0

                    active_returns = daily_returns.values - bm_aligned.values
                    te = float(np.std(active_returns) * np.sqrt(252))
                    tracking_error_val = te
                    if te > 0:
                        information_ratio_val = float(np.mean(active_returns) / np.std(active_returns) * np.sqrt(252))

        return BacktestResult(
            start_date=self.start_date,
            end_date=self.end_date,
            initial_capital=self.initial_capital,
            final_value=float(values_df['total_value'].iloc[-1]),
            total_return=float(total_return),
            annual_return=float(annual_return),
            max_drawdown=float(max_drawdown),
            sharpe_ratio=float(sharpe_ratio),
            trade_count=trade_count,
            win_rate=float(win_rate),
            daily_returns=daily_returns,
            equity_curve=values_df['total_value'],
            trades=trades_df,
            calmar_ratio=calmar_ratio,
            sortino_ratio=sortino_ratio,
            volatility=volatility,
            downside_volatility=downside_volatility,
            profit_loss_ratio=profit_loss_ratio,
            avg_holding_days=avg_holding_days,
            turnover=turnover,
            benchmark_return=benchmark_return_val,
            excess_return=excess_return_val,
            alpha=alpha_val,
            beta=beta_val,
            tracking_error=tracking_error_val,
            information_ratio=information_ratio_val,
            benchmark_daily_returns=benchmark_daily_ret,
            benchmark_curve=benchmark_curve,
            benchmark_available=benchmark_available,
        )

    @staticmethod
    def _calc_win_rate(trades_df: pd.DataFrame) -> float:
        if trades_df.empty or 'side' not in trades_df.columns:
            return 0.0
        if 'realized_pnl' not in trades_df.columns:
            return 0.0
        sell_trades = trades_df[trades_df['side'] == 'sell']
        if len(sell_trades) == 0:
            return 0.0
        return float((sell_trades['realized_pnl'] > 0).mean())

    def _resolve_benchmark_code(self) -> str | None:
        if not self.benchmark:
            return None
        key = self.benchmark.strip().lower()
        if key in BENCHMARK_MAP:
            return BENCHMARK_MAP[key]
        if "." in self.benchmark:
            return self.benchmark
        return None

    def _fetch_benchmark_series(self, benchmark_code: str) -> pd.Series | None:
        try:
            df = self.data_loader.get_index_history(
                benchmark_code,
                self.start_date,
                self.end_date,
                fields=["trade_date", "close"],
            )
        except Exception as exc:
            logger.warning("获取 benchmark 数据失败: {}", exc)
            return None
        if df is None or df.empty or "close" not in df.columns:
            return None
        df = df.sort_values("trade_date").drop_duplicates(subset=["trade_date"])
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        daily_ret = df["close"].pct_change().dropna()
        if daily_ret.empty:
            return None
        return daily_ret

    def plot(self, result: BacktestResult = None):
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("请安装 matplotlib 以使用绘图功能: pip install matplotlib")
            return

        if result is None:
            logger.warning("请先运行回测")
            return

        fig, axes = plt.subplots(2, 1, figsize=(12, 8))

        ax1 = axes[0]
        result.equity_curve.plot(ax=ax1, label='Strategy')
        ax1.axhline(y=self.initial_capital, color='r', linestyle='--', label='Initial')
        ax1.set_title('Equity Curve')
        ax1.set_ylabel('Value')
        ax1.legend()
        ax1.grid(True)

        ax2 = axes[1]
        cummax = result.equity_curve.cummax()
        drawdown = (result.equity_curve - cummax) / cummax
        drawdown.plot(ax=ax2, color='red')
        ax2.fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.3)
        ax2.set_title('Drawdown')
        ax2.set_ylabel('Drawdown')
        ax2.grid(True)

        plt.tight_layout()
        plt.show()

    def report(self, result: BacktestResult = None) -> str:
        if result is None:
            return "请先运行回测"

        return f"""
{'='*50}
回测报告
{'='*50}
回测区间: {result.start_date.date()} ~ {result.end_date.date()}
初始资金: {result.initial_capital:,.2f}
最终资金: {result.final_value:,.2f}

收益指标:
  总收益率:  {result.total_return*100:>8.2f}%
  年化收益:  {result.annual_return*100:>8.2f}%
  最大回撤:  {result.max_drawdown*100:>8.2f}%
  夏普比率:  {result.sharpe_ratio:>8.2f}

交易统计:
  交易次数:  {result.trade_count}
  胜率:      {result.win_rate*100:.2f}%
{'='*50}
"""


if __name__ == "__main__":
    from config import settings

    logger.add(settings.LOG_DIR / "backtest.log", rotation="10 MB")

    engine = BacktestEngine(
        start_date='20240102',
        end_date='20240131',
        initial_capital=1000000,
    )

    def init(context):
        logger.info("策略初始化")
        context['selected_stocks'] = ['600000.SH', '000001.SZ']

    def next_func(context):
        date = context['current_date']
        if date.day <= 5:
            for ts_code in context['selected_stocks']:
                context['order_target_percent'](ts_code, 0.4)

    engine.set_strategy(init, next_func)
    result = engine.run()
    print(engine.report(result))
