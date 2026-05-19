"""
纯小市值策略 v2 — 复刻 PTrade 小市值策略（主板扩展版）

选股逻辑（复刻 PTrade 小市值日线交易策略）：
1. 股票池：中证全指 -> 沪深主板（排除科创板、创业板、北交所）
2. 过滤次新股（上市不足 180 天）
3. 剔除 ST / *ST 股票
4. 按流通市值排序，取最小的 100 只
5. 剔除停牌股票
6. 取前 10 只作为候选池
7. 盘前已持仓且涨停的股票锁定保留（不卖不补）
8. 从候选池补足剩余仓位 → 取前 N 只
9. 每日扫描，池子不同才调仓
10. 4/20 ~ 5/1 空仓窗口，规避年报暴雷风险

运行方式：
    python strategies/pure_small_cap_strategy.py --start 20240102 --end 20260429
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backtest.engine import BacktestEngine
from config import settings


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def _is_main_board(ts_code: str) -> bool:
    """沪深主板判定（排除科创板、创业板、北交所）"""
    if ts_code.startswith("688"):
        return False
    if ts_code.startswith("30"):
        return False
    if ts_code.startswith("8") or ts_code.startswith("4"):
        return False
    if ts_code.endswith(".BJ"):
        return False
    return True


def _code_prefix(code: str) -> str:
    """取 ts_code 的数字前缀（不含交易所后缀）"""
    return code.split(".")[0]


# ══════════════════════════════════════════════════════════════

class PureSmallCapStrategy:
    """纯小市值策略 v2 — 复刻 PTrade 小市值策略（主板扩展版）"""

    def __init__(
        self,
        buy_stock_count: int = 5,
        screen_stock_count: int = 10,
        new_stock_days: int = 180,
        empty_start: str = "0420",
        empty_end: str = "0501",
    ):
        self.name = "纯小市值v2"
        self.buy_stock_count = buy_stock_count
        self.screen_stock_count = screen_stock_count
        self.new_stock_days = new_stock_days
        self.empty_start = empty_start
        self.empty_end = empty_end

        # 缓存数据（由 init 加载）
        self.st_codes: set[str] = set()
        self.list_date_map: dict[str, str] = {}      # ts_code -> list_date (YYYYMMDD)
        self.all_listed: set[str] = set()             # 所有已上市股票代码

        # 运行时状态
        self.current_targets: set[str] = set()

    # ── 空仓窗口 ───────────────────────────────────────────

    def _is_empty_window(self, date: datetime) -> bool:
        monthday = date.strftime("%m%d")
        return self.empty_start <= monthday <= self.empty_end

    # ── 次新股过滤 ─────────────────────────────────────────

    def _is_new_stock(self, ts_code: str, trade_date: datetime) -> bool:
        list_date_str = self.list_date_map.get(ts_code)
        if list_date_str is None:
            return True  # 无上市日期信息，保守排除
        try:
            list_date = datetime.strptime(list_date_str, "%Y%m%d")
            return (trade_date.date() - list_date.date()).days < self.new_stock_days
        except Exception:
            return True

    # ── 生命周期 ────────────────────────────────────────────

    def init(self, context: dict):
        """回测初始化：加载 ST 清单、上市日期、股票池"""
        logger.info(f"纯小市值v2初始化: 持仓数={self.buy_stock_count}, "
                     f"候选数={self.screen_stock_count}, "
                     f"次新股过滤={self.new_stock_days}天, "
                     f"空仓窗口={self.empty_start}~{self.empty_end}")
        self.current_targets = set()

        loader = context["data_loader"]

        # 1. 加载 ST 股票清单
        try:
            st_df = loader.conn.execute("""
                SELECT ts_code FROM instruments
                WHERE symbol LIKE '%ST%'
            """).fetchdf()
            self.st_codes = set(st_df["ts_code"].tolist())
        except Exception:
            logger.warning("无法加载 ST 清单")
            self.st_codes = set()

        # 2. 加载所有已上市股票的上市日期
        try:
            info_df = loader.conn.execute("""
                SELECT ts_code, list_date, status
                FROM instruments
            """).fetchdf()
            self.all_listed = set(info_df[info_df["status"] == "L"]["ts_code"].tolist())
            # list_date 格式可能是 datetime.date，统一转成 YYYYMMDD 字符串
            date_map = {}
            for _, row in info_df.iterrows():
                ld = row["list_date"]
                if ld is None:
                    continue
                if hasattr(ld, "strftime"):
                    date_map[row["ts_code"]] = ld.strftime("%Y%m%d")
                else:
                    text = str(ld).replace("-", "").replace("/", "")[:8]
                    if len(text) == 8 and text.isdigit():
                        date_map[row["ts_code"]] = text
            self.list_date_map = date_map
        except Exception as e:
            logger.warning(f"无法加载 instruments 信息: {e}")
            self.all_listed = set()
            self.list_date_map = {}

        # 统计有效主板股票数
        main_board = {c for c in self.all_listed if _is_main_board(c) and c not in self.st_codes}
        logger.info(f"主板上市: {len(self.all_listed)}, 有效: {len(main_board)}")

    # ── 每日选股核心 ────────────────────────────────────────

    def _select_targets(self, context: dict, date: datetime) -> tuple[list[str], set[str]] | None:
        """
        两阶段选股：
        1. 从全市场选出流通市值最小 100 只，过滤 ST/次新股/停牌
        2. 取前 screen_stock_count 只
        3. 涨停锁仓：已持仓且涨停的股票保留
        4. 补足剩余坑位

        Returns:
            (target_buy_stocks, locked_stocks) 或 None
        """
        loader = context["data_loader"]
        market_data = context["market_data"]
        broker = context["broker"]

        if market_data.empty:
            return None

        codes = market_data["ts_code"]

        # ── 第一步：主板 + 非ST 过滤 ──
        mask = codes.apply(_is_main_board) & ~codes.isin(self.st_codes)
        valid_df = market_data[mask].copy()

        if valid_df.empty:
            return None

        # ── 第二步：按流通市值排序 ──
        # 优先使用 circ_mv，兜底用 float_share * close 或 total_mv
        if "circ_mv" in valid_df.columns:
            mv_col = "circ_mv"
        elif "float_share" in valid_df.columns and "close" in valid_df.columns:
            # 手动计算流通市值
            valid_df["circ_mv"] = valid_df["float_share"] * valid_df["close"]
            mv_col = "circ_mv"
        else:
            mv_col = "total_mv" if "total_mv" in valid_df.columns else None

        if mv_col is None:
            return None

        valid_df = valid_df.dropna(subset=[mv_col])
        valid_df = valid_df[valid_df[mv_col] > 0]

        if valid_df.empty:
            return None

        # 取流通市值最小的 200 只（留出过滤余量）
        top_n = max(self.screen_stock_count * 20, 200)
        candidate_df = valid_df.nsmallest(top_n, mv_col)

        # ── 第三步：过滤次新股 ──
        if self.new_stock_days > 0:
            mask_new = ~candidate_df["ts_code"].apply(
                lambda c: self._is_new_stock(c, date)
            )
            candidate_df = candidate_df[mask_new]

        if candidate_df.empty:
            return None

        # ── 第四步：停牌过滤 ──
        trade_date_str = date.strftime("%Y-%m-%d")
        try:
            suspend_codes = set(
                loader.conn.execute(
                    f"SELECT DISTINCT ts_code FROM suspend_d WHERE trade_date = '{trade_date_str}'"
                ).fetchdf()["ts_code"].tolist()
            )
            candidate_df = candidate_df[~candidate_df["ts_code"].isin(suspend_codes)]
        except Exception:
            pass  # 停牌数据不可用时跳过

        if candidate_df.empty:
            return None

        # ── 第五步：取前 screen_stock_count 只 ──
        shortlisted = candidate_df.head(self.screen_stock_count)

        # ── 第六步：涨停锁仓 ──
        locked_stocks: list[str] = []

        # 查询当日涨跌停价格
        limit_up_stocks: set[str] = set()
        limit_down_stocks: set[str] = set()
        try:
            limit_df = loader.conn.execute(f"""
                SELECT ts_code, up_limit, down_limit
                FROM stk_limit
                WHERE trade_date = '{trade_date_str}'
            """).fetchdf()
            if not limit_df.empty:
                limit_map = {
                    row["ts_code"]: (float(row["up_limit"]), float(row["down_limit"]))
                    for _, row in limit_df.iterrows()
                }
                # 检查当前持仓是否涨停
                for ts_code, pos in broker.account.positions.items():
                    if pos.volume <= 0:
                        continue
                    if ts_code in limit_map:
                        up_limit, down_limit = limit_map[ts_code]
                        price_info = market_data[market_data["ts_code"] == ts_code]
                        if not price_info.empty:
                            close = float(price_info.iloc[0].get("close", 0) or 0)
                            if close >= round(up_limit, 2):  # 涨停
                                locked_stocks.append(ts_code)
                                limit_up_stocks.add(ts_code)
                            elif close <= round(down_limit, 2):  # 跌停
                                limit_down_stocks.add(ts_code)
        except Exception:
            pass  # 涨跌停数据不可用时跳过

        locked_set = set(locked_stocks)

        # ── 第七步：从候选池排除锁定股，补足剩余坑位 ──
        target_list = shortlisted["ts_code"].tolist()

        # 统一格式（不重复）
        target_list = list(dict.fromkeys(target_list))  # 去重保序

        # 跌停股不买入
        target_list = [c for c in target_list if c not in limit_down_stocks]

        # 排除已锁定的（锁定股靠 locked_set 保留，不从候选池买入）
        active_candidates = [c for c in target_list if c not in locked_set]

        # 计算还需要买几只
        active_count = max(self.buy_stock_count - len(locked_set), 0)
        active_buy = active_candidates[:active_count]

        # 最终目标 = 锁定股 + 活跃买入股
        final_targets = list(locked_set) + active_buy
        # 保留锁定的股票的持仓顺序不变

        return final_targets, locked_set

    # ── 每日执行 ────────────────────────────────────────────

    def next(self, context: dict):
        """每日执行：扫描排名，池子不同才调仓"""
        date = context["current_date"]

        # ── 空仓窗口检查 ──
        if self._is_empty_window(date):
            broker = context["broker"]
            current_positions = {
                ts for ts, pos in broker.account.positions.items()
                if pos.volume > 0
            }
            if current_positions:
                logger.info(f"{date.date()} 空仓窗口, 执行清仓")
                for ts_code in current_positions:
                    context["order_target_percent"](ts_code, 0)
            self.current_targets = set()
            return

        # ── 每日选股 ──
        result = self._select_targets(context, date)
        if result is None:
            return

        targets, locked_stocks = result
        target_set = set(targets)

        # 池子没变 → 不动
        if target_set == self.current_targets:
            return

        # ── 池子变了 → 调仓 ──
        market_data = context["market_data"]
        mv_col = "circ_mv" if "circ_mv" in market_data.columns else "total_mv"

        old_set = self.current_targets
        dropped = old_set - target_set
        added = target_set - old_set

        action_parts = []
        if dropped:
            action_parts.append(f"卖出{len(dropped)}只")
        if added:
            action_parts.append(f"买入{len(added)}只")

        # 日志详情
        details = []
        for code in targets:
            row = market_data[market_data["ts_code"] == code]
            if not row.empty:
                mv = row.iloc[0].get(mv_col)
                if mv and mv > 0:
                    details.append(f"{code}({mv/1e4:.1f}亿)")
                else:
                    details.append(f"{code}")
            else:
                details.append(f"{code}")

        lock_tag = f" [涨停锁仓:{list(locked_stocks)}]" if locked_stocks else ""
        logger.info(
            f"{date.date()} 调仓, {'; '.join(action_parts)}, "
            f"持有: {', '.join(details)}{lock_tag}"
        )

        self.current_targets = target_set

        # 执行调仓
        broker = context["broker"]

        # 清仓落榜股票（涨停锁仓的不会出现在 dropped 中，因为 locked_set 在 target_set 里）
        for ts_code in list(broker.account.positions.keys()):
            pos = broker.account.get_position(ts_code)
            if pos.volume > 0 and ts_code not in target_set:
                context["order_target_percent"](ts_code, 0)

        # 等权买入目标股票
        if targets:
            weight = min(0.95 / len(targets), 0.95)
            for stock in targets:
                if stock in locked_stocks:
                    continue  # 涨停股不补仓
                context["order_target_percent"](stock, weight)


# ══════════════════════════════════════════════════════════════
# 命令行入口
# ══════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description="纯小市值策略 v2")
    parser.add_argument("--start", default="20240102", help="回测开始日期 YYYYMMDD")
    parser.add_argument("--end", default="20260429", help="回测结束日期 YYYYMMDD")
    parser.add_argument("--capital", type=float, default=1000000, help="初始资金")
    parser.add_argument("--count", type=int, default=5, help="持有股票数量")
    parser.add_argument("--screen", type=int, default=10, help="候选股票数量")
    parser.add_argument("--commission", type=float, default=0.0003, help="手续费率")
    parser.add_argument("--slippage", type=float, default=0.001, help="滑点")
    return parser.parse_args()


def main():
    args = parse_args()

    logger.add(
        settings.LOG_DIR / "pure_small_cap_strategy.log",
        rotation="10 MB",
        level="INFO",
    )

    strategy = PureSmallCapStrategy(
        buy_stock_count=args.count,
        screen_stock_count=args.screen,
    )

    engine = BacktestEngine(
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        commission_rate=args.commission,
        slippage=args.slippage,
    )
    engine.set_strategy(strategy.init, strategy.next)
    result = engine.run()
    print(engine.report(result))


if __name__ == "__main__":
    main()
