"""
统一数据访问层 (DataLoader)
封装所有数据读取接口，策略不直接操作文件
"""
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
from functools import lru_cache

import duckdb
import pandas as pd
import numpy as np
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


class DataLoader:
    """
    统一数据加载器
    
    提供接口：
    - get_history(): 获取个股历史数据
    - get_cross_section(): 获取某日期全市场截面数据
    - get_adj_price(): 获取复权价格
    - get_trade_calendar(): 获取交易日历
    - is_trade_date(): 判断是否为交易日
    - get_next_trade_date(): 获取下一交易日
    - get_prev_trade_date(): 获取上一交易日
    """
    
    def __init__(self):
        self.conn = None
        self._has_stk_limit = False
        self._init_connection()
        self._cache = {}
        self._daily_bar_source = "daily_bar"
        self._cross_section_cache: Dict[tuple, pd.DataFrame] = {}
        self._trade_date_index: Dict[object, int] = {}

    _SAFE_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    _VALID_EXCHANGES = {"SH", "SZ", "BJ"}
    _VALID_STATUSES = {"L", "D", "P"}
    _VALID_FINANCIAL_TABLES = {"fina_indicator", "income_stmt", "balancesheet", "cashflow"}
    
    def _init_connection(self):
        """初始化DuckDB连接"""
        self.conn = duckdb.connect(config={'memory_limit': '12GB', 'temp_directory': '/tmp/duckdb_work', 'threads': '4'})
        # 注册parquet目录为视图
        self._register_views()
    
    def _register_views(self):
        """注册parquet目录为可查询视图"""
        # 日线行情视图
        if settings.DAILY_BAR_DIR.exists() and any(settings.DAILY_BAR_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW daily_bar AS
                SELECT * FROM read_parquet('{settings.DAILY_BAR_DIR}/*/*.parquet', hive_partitioning=1)
            """)
        
        # 复权因子视图
        if settings.ADJ_FACTOR_DIR.exists() and any(settings.ADJ_FACTOR_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW adj_factor AS
                SELECT * FROM read_parquet('{settings.ADJ_FACTOR_DIR}/*/*.parquet', hive_partitioning=1)
            """)

        if settings.DAILY_BASIC_DIR.exists() and any(settings.DAILY_BASIC_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW daily_basic AS
                SELECT * FROM read_parquet('{settings.DAILY_BASIC_DIR}/*/*.parquet', hive_partitioning=1)
            """)

        if settings.STK_LIMIT_DIR.exists() and any(settings.STK_LIMIT_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW stk_limit AS
                SELECT * FROM read_parquet('{settings.STK_LIMIT_DIR}/*/*.parquet', hive_partitioning=1)
            """)
            self._has_stk_limit = True

        if settings.SUSPEND_D_DIR.exists() and any(settings.SUSPEND_D_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW suspend_d AS
                SELECT * FROM read_parquet('{settings.SUSPEND_D_DIR}/*/*.parquet', hive_partitioning=1)
            """)

        namechange_path = settings.NAMECHANGE_DIR / "namechange.parquet"
        if namechange_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW namechange AS
                SELECT * FROM '{namechange_path}'
            """)
        
        # 股票列表视图
        instruments_path = settings.INSTRUMENTS_DIR / "instruments.parquet"
        if instruments_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW instruments AS
                SELECT * FROM '{instruments_path}'
            """)
        
        # 交易日历视图
        calendar_path = settings.CALENDAR_DIR / "calendar.parquet"
        if calendar_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW calendar AS
                SELECT * FROM '{calendar_path}'
            """)
        
        # 指数成分股视图
        index_member_path = settings.INDEX_MEMBER_DIR / "index_member.parquet"
        if index_member_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW index_member AS
                SELECT * FROM '{index_member_path}'
            """)
        
        # 概念板块视图
        concept_path = settings.CONCEPT_DIR / "concept.parquet"
        concept_member_path = settings.CONCEPT_DIR / "concept_member.parquet"
        if concept_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW concept AS
                SELECT * FROM '{concept_path}'
            """)
        if concept_member_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW concept_member AS
                SELECT * FROM '{concept_member_path}'
            """)
        
        # 指数日线视图（按年分区）
        if settings.INDEX_DAILY_DIR.exists() and any(settings.INDEX_DAILY_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW index_daily AS
                SELECT * FROM read_parquet('{settings.INDEX_DAILY_DIR}/*/*.parquet', hive_partitioning=1)
            """)
        
        # 基金基本资料视图
        fund_basic_path = settings.FUND_BASIC_DIR / "fund_basic.parquet"
        if fund_basic_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW fund_basic AS
                SELECT * FROM '{fund_basic_path}'
            """)
        
        # 行业分类视图
        stock_industry_path = settings.INDUSTRY_DIR / "stock_industry.parquet"
        if stock_industry_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW stock_industry AS
                SELECT * FROM '{stock_industry_path}'
            """)
        
        # 财务指标视图
        fina_indicator_path = settings.FINANCIAL_DIR / "fina_indicator.parquet"
        if fina_indicator_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW fina_indicator AS
                SELECT * FROM '{fina_indicator_path}'
            """)
        
        income_path = settings.FINANCIAL_DIR / "income.parquet"
        if income_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW income_stmt AS
                SELECT * FROM '{income_path}'
            """)
        
        balancesheet_path = settings.FINANCIAL_DIR / "balancesheet.parquet"
        if balancesheet_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW balancesheet AS
                SELECT * FROM '{balancesheet_path}'
            """)
        
        cashflow_path = settings.FINANCIAL_DIR / "cashflow.parquet"
        if cashflow_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW cashflow AS
                SELECT * FROM '{cashflow_path}'
            """)

        # 业绩快报视图
        express_path = settings.FINANCIAL_DIR / "performance_express.parquet"
        if express_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW performance_express AS
                SELECT * FROM '{express_path}'
            """)

        # 业绩预告视图
        forecast_path = settings.FINANCIAL_DIR / "forecast.parquet"
        if forecast_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW forecast AS
                SELECT * FROM '{forecast_path}'
            """)

        # 分红送转视图
        dividend_path = settings.FINANCIAL_DIR / "dividend.parquet"
        if dividend_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW dividend AS
                SELECT * FROM '{dividend_path}'
            """)

        # 股东人数视图
        holder_path = settings.HOLDER_NUMBER_DIR / "holder_number.parquet"
        if holder_path.exists():
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW holder_number AS
                SELECT * FROM '{holder_path}'
            """)
        
        # ETF日线视图
        if settings.ETF_DAILY_DIR.exists() and any(settings.ETF_DAILY_DIR.glob("*/*.parquet")):
            self.conn.execute(f"""
                CREATE OR REPLACE VIEW etf_daily AS
                SELECT * FROM read_parquet('{settings.ETF_DAILY_DIR}/*/*.parquet', hive_partitioning=1)
            """)

    def prepare_backtest_data(
        self,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        warmup_days: int = 400,
    ):
        """
        为一次回测准备较小的数据工作集。

        DuckDB 会先把回测区间附近的日线数据物化为临时表，后续逐日截面和历史窗口查询
        都从这个临时表读取，避免反复扫描完整 Parquet 目录。
        """
        start_dt = self._to_datetime(start_date) - timedelta(days=max(0, warmup_days))
        end_dt = self._to_datetime(end_date)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        self.conn.execute("DROP TABLE IF EXISTS prepared_daily_bar")
        self.conn.execute(
            """
            CREATE TEMP TABLE prepared_daily_bar AS
            SELECT *
            FROM daily_bar
            WHERE trade_date BETWEEN ? AND ?
            """,
            [start_str, end_str],
        )
        self._daily_bar_source = "prepared_daily_bar"
        self._cross_section_cache.clear()
        self._cache.clear()
        self._build_trade_date_index(start_date, end_date)

    def clear_prepared_data(self):
        """恢复为直接读取完整日线视图。"""
        self.conn.execute("DROP TABLE IF EXISTS prepared_daily_bar")
        self._daily_bar_source = "daily_bar"
        self._cross_section_cache.clear()
        self._cache.clear()

    @staticmethod
    def _to_datetime(date_value: Union[str, datetime]) -> datetime:
        if isinstance(date_value, datetime):
            return date_value
        text = str(date_value)
        fmt = "%Y-%m-%d" if "-" in text else "%Y%m%d"
        return datetime.strptime(text, fmt)

    def _build_trade_date_index(
        self,
        start_date: Optional[Union[str, datetime]] = None,
        end_date: Optional[Union[str, datetime]] = None,
    ):
        calendar = self.get_trade_calendar(start_date=start_date, end_date=end_date, only_open=True)
        self._trade_date_index = {
            pd.to_datetime(row["trade_date"]).date(): idx
            for idx, row in calendar.reset_index(drop=True).iterrows()
        }

    def get_trade_date_index(self, date_value: Union[str, datetime]) -> Optional[int]:
        if not self._trade_date_index:
            self._build_trade_date_index()
        return self._trade_date_index.get(pd.to_datetime(date_value).date())

    def get_hold_days(self, entry_date: Union[str, datetime], current_date: Union[str, datetime]) -> int:
        start_idx = self.get_trade_date_index(entry_date)
        end_idx = self.get_trade_date_index(current_date)
        if start_idx is None or end_idx is None:
            cal = self.get_trade_calendar(start_date=entry_date, end_date=current_date, only_open=True)
            return max(0, len(cal) - 1)
        return max(0, end_idx - start_idx)
    
    # ==================== 核心查询接口 ====================
    
    def get_history(
        self,
        ts_code: str,
        end_date: Union[str, datetime],
        fields: Optional[List[str]] = None,
        window: int = 20,
        adjust: str = 'qfq'  # 'qfq'前复权, 'hfq'后复权, None不复权
    ) -> pd.DataFrame:
        """
        获取个股历史数据
        
        Args:
            ts_code: 股票代码，如 '600000.SH'
            end_date: 结束日期 (YYYYMMDD 或 datetime)
            fields: 需要的字段列表，None返回所有
            window: 窗口大小（交易日数）
            adjust: 复权方式
        
        Returns:
            DataFrame，按日期升序排列
        """
        if isinstance(end_date, str):
            end_date = self._to_datetime(end_date)
        end_date_str = end_date.strftime('%Y-%m-%d')
        window = int(window)
        if window <= 0:
            return pd.DataFrame()

        if fields is None:
            fields = ['trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'volume', 'amount']
        fields = self._validate_column_names(fields)

        # --- Cache path ---
        cached_df = self._cache.get(ts_code)
        if cached_df is not None and len(cached_df) > 0:
            date_key = self._normalize_trade_date_series(cached_df['trade_date'])
            df = cached_df[date_key <= end_date_str].copy()
            if len(df) > window:
                df = df.tail(window)
            if len(df) == 0:
                return pd.DataFrame()

            if adjust and adjust in ('qfq', 'hfq') and 'adj_factor' in df.columns:
                df = self._apply_adjustment(df, adjust)

            keep = [c for c in ['ts_code', 'trade_date'] if c in df.columns]
            keep += [f for f in fields if f not in keep and f in df.columns]
            if adjust and 'close_fq' in df.columns:
                fq_cols = [c for c in df.columns if c.endswith('_fq')]
                keep += [c for c in fq_cols if c not in keep]
            if 'adj_factor' in df.columns:
                keep.append('adj_factor')
            df = df[[c for c in keep if c in df.columns]]
            return df.sort_values('trade_date').reset_index(drop=True)

        # --- SQL path ---
        if adjust and adjust in ['qfq', 'hfq']:
            select_cols = ["d.ts_code", "d.trade_date"]
            select_cols.extend(f"d.{f}" for f in fields if f not in {"ts_code", "trade_date"})
            select_cols.append("a.adj_factor")
            query = f"""
                SELECT {', '.join(select_cols)}
                FROM {self._daily_bar_source} d
                LEFT JOIN adj_factor a 
                    ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
                WHERE d.ts_code = ?
                  AND d.trade_date <= ?
                ORDER BY d.trade_date DESC
                LIMIT ?
            """
            params = [ts_code, end_date_str, window]
        else:
            select_cols = ["ts_code", "trade_date"]
            select_cols.extend(f for f in fields if f not in {"ts_code", "trade_date"})
            query = f"""
                SELECT {', '.join(select_cols)}
                FROM {self._daily_bar_source}
                WHERE ts_code = ?
                  AND trade_date <= ?
                ORDER BY trade_date DESC
                LIMIT ?
            """
            params = [ts_code, end_date_str, window]
        
        df = self.conn.execute(query, params).fetchdf()
        
        if len(df) == 0:
            return pd.DataFrame()
        
        if adjust and 'adj_factor' in df.columns and len(df) > 0:
            df = self._apply_adjustment(df, adjust)
        
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        return df
    
    def get_cross_section(
        self,
        trade_date: Union[str, datetime],
        fields: Optional[List[str]] = None,
        adjust: str = None
    ) -> pd.DataFrame:
        """
        获取某交易日全市场截面数据
        
        Args:
            trade_date: 交易日期 (YYYYMMDD 或 datetime)
            fields: 需要的字段列表
            adjust: 复权方式
        
        Returns:
            DataFrame，每行一只股票
        """
        if isinstance(trade_date, str):
            trade_date = self._to_datetime(trade_date)
        date_str = trade_date.strftime('%Y-%m-%d')
        
        if fields is None:
            fields = ['ts_code', 'open', 'high', 'low', 'close', 'pre_close', 'volume', 'amount']
        fields = self._validate_column_names(fields)

        cache_key = (date_str, tuple(fields), adjust)
        if adjust is None and cache_key in self._cross_section_cache:
            return self._cross_section_cache[cache_key].copy()
        
        if adjust and adjust in ['qfq', 'hfq']:
            select_cols = ["d.ts_code", "d.trade_date"]
            select_cols.extend(f"d.{f}" for f in fields if f not in ['ts_code', 'trade_date'])
            select_cols.append("a.adj_factor")
            query = f"""
                SELECT {', '.join(select_cols)}
                FROM {self._daily_bar_source} d
                LEFT JOIN adj_factor a 
                    ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
                WHERE d.trade_date = ?
            """
            params = [date_str]
        else:
            # LEFT JOIN daily_basic to include market-cap fields (circ_mv, total_mv, etc.)
            basic_fields = ['circ_mv', 'total_mv', 'total_share', 'float_share', 'free_share',
                            'turnover_rate', 'pe_ttm', 'pb']
            select_cols = [f'd.{f}' for f in fields if f not in ['ts_code', 'trade_date']]
            select_cols += [f'db.{f}' for f in basic_fields]
            limit_cols = ", sl.up_limit, sl.down_limit" if self._has_stk_limit else ""
            limit_join = """
                LEFT JOIN stk_limit sl
                    ON d.ts_code = sl.ts_code AND d.trade_date = sl.trade_date
            """ if self._has_stk_limit else ""
            query = f"""
                SELECT 
                    d.ts_code,
                    d.trade_date,
                    {', '.join(select_cols)}
                    {limit_cols}
                FROM {self._daily_bar_source} d
                LEFT JOIN daily_basic db
                    ON d.ts_code = db.ts_code AND d.trade_date = db.trade_date
                {limit_join}
                WHERE d.trade_date = ?
            """
            params = [date_str]
        
        df = self.conn.execute(query, params).fetchdf()
        
        if adjust and 'adj_factor' in df.columns and len(df) > 0:
            df = self._apply_adjustment(df, adjust)

        if adjust is None:
            self._cross_section_cache[cache_key] = df.copy()
        
        return df
    
    def get_index_history(
        self,
        index_code: str,
        start_date: Union[str, datetime],
        end_date: Union[str, datetime],
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """获取指数日线行情。

        Args:
            index_code: 指数代码，如 '000300.SH'
            start_date: 开始日期
            end_date: 结束日期
            fields: 需要的字段列表，None 返回 ['trade_date', 'close']

        Returns:
            DataFrame，按 trade_date 升序排列；视图不存在时返回空 DataFrame
        """
        start_str = self._to_datetime(start_date).strftime("%Y-%m-%d")
        end_str = self._to_datetime(end_date).strftime("%Y-%m-%d")

        if fields is None:
            fields = ["trade_date", "close"]
        fields = self._validate_column_names(fields)

        if "trade_date" not in fields:
            fields = ["trade_date"] + fields

        col_list = ", ".join(fields)
        query = f"""
            SELECT {col_list}
            FROM index_daily
            WHERE ts_code = ?
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
        """
        try:
            df = self.conn.execute(query, [index_code, start_str, end_str]).fetchdf()
        except Exception:
            return pd.DataFrame()
        return df

    def get_adj_factor(
        self,
        ts_code: str,
        trade_date: Union[str, datetime]
    ) -> Optional[float]:
        """
        获取某股票某日的复权因子
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
        
        Returns:
            复权因子值，找不到返回None
        """
        if isinstance(trade_date, str):
            trade_date = self._to_datetime(trade_date)
        date_str = trade_date.strftime('%Y-%m-%d')
        
        query = """
            SELECT adj_factor FROM adj_factor
            WHERE ts_code = ? AND trade_date = ?
        """

        result = self.conn.execute(query, [ts_code, date_str]).fetchone()
        return result[0] if result else None

    def get_latest_financial(
        self,
        ts_code: str,
        trade_date: Union[str, datetime],
        table: str = "fina_indicator",
        fields: Optional[List[str]] = None,
    ) -> Optional[pd.DataFrame]:
        """
        获取截至 trade_date 已公告的最新财报数据（避免前瞻偏差）。

        通过 ann_date <= trade_date 过滤，确保只使用在当前日期之前
        已经公告的财报数据。如果同一天有多条（修正公告），取 end_date
        最新的一条。

        Args:
            ts_code: 股票代码，如 '600000.SH'
            trade_date: 当前交易日期
            table: 财报表名，可选 fina_indicator / income_stmt / balancesheet / cashflow
            fields: 需要的字段列表，None 返回全部字段

        Returns:
            DataFrame（一行），找不到返回 None
        """
        date_str = self._to_datetime(trade_date).strftime("%Y-%m-%d")
        if table not in self._VALID_FINANCIAL_TABLES:
            logger.warning(f"不支持的财务表: {table}, 可选: {self._VALID_FINANCIAL_TABLES}")
            return None
        if fields:
            self._validate_column_names(fields)
            field_str = ", ".join(fields)
        else:
            field_str = "*"

        query = f"""
            SELECT {field_str}
            FROM {table}
            WHERE ts_code = ?
              AND ann_date <= ?
            ORDER BY end_date DESC
            LIMIT 1
        """
        result = self.conn.execute(query, [ts_code, date_str]).fetchdf()
        return result if not result.empty else None

    def get_financial_cross_section(
        self,
        trade_date: Union[str, datetime],
        table: str = "fina_indicator",
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        获取截至 trade_date 全市场已公告的最新财报截面。

        对每只股票取 ann_date <= trade_date 且 end_date 最大的那条记录。

        Args:
            trade_date: 当前交易日期
            table: 财报表名
            fields: 需要的字段列表

        Returns:
            DataFrame，每行一只股票的最新财报
        """
        date_str = self._to_datetime(trade_date).strftime("%Y-%m-%d")
        if table not in self._VALID_FINANCIAL_TABLES:
            logger.warning(f"不支持的财务表: {table}")
            return pd.DataFrame()
        if fields:
            self._validate_column_names(fields)
            field_str = ", ".join(fields)
        else:
            field_str = "*"

        query = f"""
            SELECT {field_str}
            FROM {table}
            WHERE ann_date <= ?
              AND (ts_code, end_date) IN (
                  SELECT ts_code, MAX(end_date)
                  FROM {table}
                  WHERE ann_date <= ?
                  GROUP BY ts_code
              )
        """
        return self.conn.execute(query, [date_str, date_str]).fetchdf()

    def get_trade_calendar(
        self,
        start_date: Optional[Union[str, datetime]] = None,
        end_date: Optional[Union[str, datetime]] = None,
        only_open: bool = True
    ) -> pd.DataFrame:
        """
        获取交易日历
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            only_open: 只返回交易日
        
        Returns:
            DataFrame
        """
        conditions = []
        params = []

        if start_date:
            if isinstance(start_date, str):
                start_date = self._to_datetime(start_date)
            conditions.append("trade_date >= ?")
            params.append(start_date.strftime('%Y-%m-%d'))

        if end_date:
            if isinstance(end_date, str):
                end_date = self._to_datetime(end_date)
            conditions.append("trade_date <= ?")
            params.append(end_date.strftime('%Y-%m-%d'))

        if only_open:
            conditions.append("is_open = 1")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT * FROM calendar
            WHERE {where_clause}
            ORDER BY trade_date
        """

        return self.conn.execute(query, params).fetchdf()
    
    def is_trade_date(self, date: Union[str, datetime]) -> bool:
        """判断是否为交易日"""
        if isinstance(date, str):
            date = self._to_datetime(date)
        date_str = date.strftime('%Y-%m-%d')

        query = """
            SELECT is_open FROM calendar
            WHERE trade_date = ?
        """

        result = self.conn.execute(query, [date_str]).fetchone()
        return result[0] == 1 if result else False
    
    def get_next_trade_date(self, date: Union[str, datetime]) -> Optional[datetime]:
        """获取下一交易日"""
        if isinstance(date, str):
            date = self._to_datetime(date)
        date_str = date.strftime('%Y-%m-%d')

        query = """
            SELECT next_trade_date FROM calendar
            WHERE trade_date = ?
        """

        result = self.conn.execute(query, [date_str]).fetchone()
        if result and result[0]:
            return pd.to_datetime(result[0])
        return None
    
    def get_prev_trade_date(self, date: Union[str, datetime]) -> Optional[datetime]:
        """获取上一交易日"""
        if isinstance(date, str):
            date = self._to_datetime(date)
        date_str = date.strftime('%Y-%m-%d')

        query = """
            SELECT prev_trade_date FROM calendar
            WHERE trade_date = ?
        """

        result = self.conn.execute(query, [date_str]).fetchone()
        if result and result[0]:
            return pd.to_datetime(result[0])
        return None
    
    def get_instruments(
        self,
        exchange: Optional[str] = None,
        status: Optional[str] = None
    ) -> pd.DataFrame:
        """
        获取股票列表
        
        Args:
            exchange: 交易所筛选 (SH/SZ/BJ)
            status: 状态筛选 (L上市/D退市/P暂停)
        
        Returns:
            DataFrame
        """
        if exchange and exchange not in self._VALID_EXCHANGES:
            raise ValueError(f"非法 exchange 值: {exchange}, 可选: {self._VALID_EXCHANGES}")
        if status and status not in self._VALID_STATUSES:
            raise ValueError(f"非法 status 值: {status}, 可选: {self._VALID_STATUSES}")

        conditions = []
        params = []

        if exchange:
            conditions.append("exchange = ?")
            params.append(exchange)

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT * FROM instruments
            WHERE {where_clause}
        """

        return self.conn.execute(query, params).fetchdf()
    
    # ==================== 辅助方法 ====================

    def _validate_column_names(self, fields: List[str]) -> List[str]:
        """Validate SQL column identifiers before interpolating them into SELECT lists."""
        validated = []
        for field in fields:
            if not isinstance(field, str) or not self._SAFE_COLUMN_RE.match(field):
                raise ValueError(f"非法字段名: {field}")
            if field not in validated:
                validated.append(field)
        return validated

    def _normalize_trade_date_series(self, series: pd.Series) -> pd.Series:
        """Return YYYY-MM-DD strings for comparing cached trade_date values consistently."""
        return pd.to_datetime(series).dt.strftime('%Y-%m-%d')
    
    def _apply_adjustment(self, df: pd.DataFrame, adjust: str) -> pd.DataFrame:
        """Apply price adjustment (qfq / hfq).

        The DataFrame is sorted by trade_date ascending internally so that
        ``iloc[0]`` is the earliest day and ``iloc[-1]`` is the latest day,
        regardless of the caller's ordering.
        """
        if 'adj_factor' not in df.columns or len(df) == 0:
            price_cols = ['open', 'high', 'low', 'close', 'pre_close']
            for col in price_cols:
                if col in df.columns:
                    df[f'{col}_fq'] = df[col]
            return df

        df = df.sort_values('trade_date').reset_index(drop=True)
        df['adj_factor'] = df['adj_factor'].fillna(1.0)

        price_cols = ['open', 'high', 'low', 'close', 'pre_close']

        if adjust == 'qfq':
            latest_factor = df['adj_factor'].iloc[-1]
            if latest_factor and latest_factor != 0:
                for col in price_cols:
                    if col in df.columns:
                        df[f'{col}_fq'] = df[col] * df['adj_factor'] / latest_factor
            else:
                for col in price_cols:
                    if col in df.columns:
                        df[f'{col}_fq'] = df[col]

        elif adjust == 'hfq':
            first_factor = df['adj_factor'].iloc[0]
            if first_factor and first_factor != 0:
                for col in price_cols:
                    if col in df.columns:
                        df[f'{col}_fq'] = df[col] * df['adj_factor'] / first_factor
            else:
                for col in price_cols:
                    if col in df.columns:
                        df[f'{col}_fq'] = df[col]

        return df
    
    def warm_up_cache(self, ts_codes: List[str], start_date: datetime, end_date: datetime):
        """
        预热缓存 - 批量加载常用数据到内存
        
        Args:
            ts_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
        """
        logger.info(f"预热缓存: {len(ts_codes)} 只股票, {start_date.date()} ~ {end_date.date()}")
        if not ts_codes:
            return
        
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        placeholders = ", ".join(["?"] * len(ts_codes))
        
        # 批量加载日线数据
        query = f"""
            SELECT 
                d.*,
                a.adj_factor
            FROM daily_bar d
            LEFT JOIN adj_factor a 
                ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.ts_code IN ({placeholders})
              AND d.trade_date BETWEEN ? AND ?
            ORDER BY d.ts_code, d.trade_date
        """
        
        df = self.conn.execute(query, [*ts_codes, start_str, end_str]).fetchdf()
        
        # 按股票分组缓存
        for ts_code in ts_codes:
            code_df = df[df['ts_code'] == ts_code].copy()
            if len(code_df) > 0:
                self._cache[ts_code] = code_df.reset_index(drop=True)
        
        logger.info(f"缓存完成: {len(self._cache)} 只股票")
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()


# ==================== 便捷函数 ====================

def create_data_loader() -> DataLoader:
    """创建数据加载器实例"""
    return DataLoader()


if __name__ == "__main__":
    # 测试代码
    from config import settings
    logger.add(settings.LOG_DIR / "data_loader.log", rotation="10 MB")
    
    loader = DataLoader()
    
    try:
        # 测试获取历史数据
        df = loader.get_history('600000.SH', '20240115', window=10)
        print("历史数据:")
        print(df)
        print()
        
        # 测试获取截面数据
        cs = loader.get_cross_section('20240115')
        print("截面数据:")
        print(cs)
        print()
        
        # 测试交易日历
        cal = loader.get_trade_calendar('20240101', '20240131')
        print("交易日历:")
        print(cal)
        
    finally:
        loader.close()
