"""
中小板综小市值策略 — 复刻 PTrade 小市值日线交易策略（交易优化版）

选股逻辑：
1. 股票池：399101.SZ 中小板综成分股
2. 剔除 ST / *ST 股票
3. 按流通市值排序，取最小的 100 只
4. 剔除停牌股票
5. 取前 screen_stock_count 只作为候选池
6. 盘前已持仓且涨停的股票锁定保留（不卖不补）
7. 从候选池补足剩余仓位 → 取前 buy_stock_count 只
8. 每日扫描，池子不同才调仓
9. 无次新股过滤，无空仓窗口（与交易优化版一致）

运行方式：
    python strategies/pure_small_cap_sme.py --start 20250101 --end 20260504
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


class PureSmallCapSMEStrategy:
    """中小板综小市值策略 — 复刻 PTrade 交易优化版"""

    def __init__(
        self,
        buy_stock_count: int = 5,
        screen_stock_count: int = 10,
    ):
        self.name = "中小板综小市值v1"
        self.buy_stock_count = buy_stock_count
        self.screen_stock_count = screen_stock_count

        # 缓存数据
        self.st_codes: set[str] = set()
        self.index_name = "399101.SZ"  # 中小板综

        # 运行时状态
        self.current_targets: set[str] = set()

    # ── 工具 ─────────────────────────────────────────────

    def _normalize_code(self, code: str) -> str:
        """统一股票代码格式"""
        # index_member 用的 Tushare 格式是 .SZ/.SH
        # daily_basic 里的 ts_code 也是 .SZ/.SH，一致
        return code

    # ── 生命周期 ─────────────────────────────────────────

    def init(self, context: dict):
        """回测初始化"""
        logger.info(f"中小板综小市值初始化: 持仓数={self.buy_stock_count}, "
                     f"候选数={self.screen_stock_count}")
        self.current_targets = set()

        loader = context["data_loader"]

        # 1. 加载 ST 股票清单
        try:
            # 从 namechange 表找最近被 ST 的股票
            st_df = loader.conn.execute("""
                SELECT DISTINCT ts_code FROM instruments
                WHERE symbol LIKE '%ST%'
            """).fetchdf()
            self.st_codes = set(st_df["ts_code"].tolist())
            logger.info(f"ST 股票 {len(self.st_codes)} 只")
        except Exception:
            logger.warning("无法加载 ST 清单")
            self.st_codes = set()

        # 2. 验证中小板综数据存在
        try:
            cnt = loader.conn.execute("""
                SELECT COUNT(*) FROM index_member
                WHERE index_code = '399101.SZ' AND out_date IS NULL
            """).fetchone()[0]
            logger.info(f"399101.SZ 中小板综当前成分股: {cnt} 只")
        except Exception as e:
            logger.warning(f"无法查询 index_member: {e}")

    # ── 每日选股核心 ─────────────────────────────────────

    def _select_targets(self, context: dict, date: datetime) -> tuple[list[str], set[str]] | None:
        """
        两阶段选股（仿 PTrade 交易优化版）：
        1. 从 399101.SZ 成分股选出流通市值最小 100 只
        2. 过滤 ST / 停牌
        3. 取前 screen_stock_count 只
        4. 涨停锁仓
        5. 补足剩余坑位
        """
        loader = context["data_loader"]
        market_data = context["market_data"]
        broker = context["broker"]

        if market_data.empty:
            return None

        trade_date_str = date.strftime("%Y-%m-%d")

        # ── 第一步：取 399101.SZ 成分股 ──
        try:
            sme_codes = set(
                loader.conn.execute(f"""
                    SELECT con_code FROM index_member
                    WHERE index_code = '399101.SZ'
                      AND in_date <= '{trade_date_str}'
                      AND (out_date IS NULL OR out_date > '{trade_date_str}')
                """).fetchdf()["con_code"].tolist()
            )
        except Exception:
            sme_codes = set()

        if not sme_codes:
            logger.warning(f"{trade_date_str} 无 399101.SZ 成分股")
            return None

        # 只保留当天市场数据中存在的股票
        valid_df = market_data[market_data["ts_code"].isin(sme_codes)].copy()

        if valid_df.empty:
            return None

        # ── 第二步：剔除 ST ──
        valid_df = valid_df[~valid_df["ts_code"].isin(self.st_codes)]

        if valid_df.empty:
            return None

        # ── 第三步：按流通市值排序 ──
        if "circ_mv" in valid_df.columns:
            mv_col = "circ_mv"
        elif "total_mv" in valid_df.columns:
            mv_col = "total_mv"
        else:
            return None

        valid_df = valid_df.dropna(subset=[mv_col])
        valid_df = valid_df[valid_df[mv_col] > 0]

        if valid_df.empty:
            return None

        # 取流通市值最小的 200 只（留出过滤余量）
        top_n = max(self.screen_stock_count * 20, 200)
        candidate_df = valid_df.nsmallest(top_n, mv_col)

        # ── 第四步：停牌过滤 ──
        try:
            suspend_codes = set(
                loader.conn.execute(
                    f"SELECT DISTINCT ts_code FROM suspend_d WHERE trade_date = '{trade_date_str}'"
                ).fetchdf()["ts_code"].tolist()
            )
            candidate_df = candidate_df[~candidate_df["ts_code"].isin(suspend_codes)]
        except Exception:
            pass

        if candidate_df.empty:
            return None

        # ── 第五步：取前 screen_stock_count 只 ──
        shortlisted = candidate_df.head(self.screen_stock_count)

        # ── 第六步：涨停锁仓 ──
        locked_stocks: list[str] = []

        limit_up_stocks: set[str] = set()
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
                for ts_code, pos in broker.account.positions.items():
                    if pos.volume <= 0:
                        continue
                    if ts_code in limit_map:
                        up_limit, down_limit = limit_map[ts_code]
                        price_info = market_data[market_data["ts_code"] == ts_code]
                        if not price_info.empty:
                            close = float(price_info.iloc[0].get("close", 0) or 0)
                            if close >= round(up_limit, 2):
                                locked_stocks.append(ts_code)
                                limit_up_stocks.add(ts_code)
        except Exception:
            pass

        locked_set = set(locked_stocks)

        # ── 第七步：从候选池排除锁定股，补足剩余坑位 ──
        target_list = shortlisted["ts_code"].tolist()
        target_list = list(dict.fromkeys(target_list))  # 去重保序

        # 排除已锁定的
        active_candidates = [c for c in target_list if c not in locked_set]

        # 计算还需要买几只
        active_count = max(self.buy_stock_count - len(locked_set), 0)
        active_buy = active_candidates[:active_count]

        # 最终目标 = 锁定股 + 活跃买入股
        final_targets = list(locked_set) + active_buy

        return final_targets, locked_set

    # ── 每日执行 ─────────────────────────────────────────

    def next(self, context: dict):
        """每日执行：扫描排名，池子不同才调仓"""
        date = context["current_date"]
        market_data = context["market_data"]

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

        # 清仓落榜股票
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
    parser = argparse.ArgumentParser(description="中小板综小市值策略")
    parser.add_argument("--start", default="20250101", help="回测开始日期 YYYYMMDD")
    parser.add_argument("--end", default="20260504", help="回测结束日期 YYYYMMDD")
    parser.add_argument("--capital", type=float, default=1000000, help="初始资金")
    parser.add_argument("--count", type=int, default=5, help="持有股票数量")
    parser.add_argument("--screen", type=int, default=10, help="候选股票数量")
    parser.add_argument("--commission", type=float, default=0.0003, help="手续费率")
    parser.add_argument("--slippage", type=float, default=0.001, help="滑点")
    return parser.parse_args()


def main():
    args = parse_args()

    logger.add(
        settings.LOG_DIR / "pure_small_cap_sme.log",
        rotation="10 MB",
        level="INFO",
    )

    strategy = PureSmallCapSMEStrategy(
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
