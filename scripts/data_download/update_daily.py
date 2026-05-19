"""
数据更新模块：日线行情、复权因子、股票列表、交易日历
支持全量初始化 + 增量更新
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
import json

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


class DataUpdater:
    """数据更新器"""
    
    def __init__(self):
        self.meta_conn = None
        self._init_meta_db()
    
    def _init_meta_db(self):
        """初始化元数据库"""
        settings.META_DIR.mkdir(parents=True, exist_ok=True)
        self.meta_conn = duckdb.connect(str(settings.META_DB_PATH))
        
        # 创建更新记录表
        self.meta_conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS update_log_seq START 1;
            CREATE TABLE IF NOT EXISTS update_log (
                id INTEGER PRIMARY KEY DEFAULT nextval('update_log_seq'),
                table_name VARCHAR NOT NULL,
                trade_date DATE,
                record_count INTEGER,
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR DEFAULT 'success',
                message VARCHAR
            )
        """)
        
        # 创建数据校验记录表
        self.meta_conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS validation_log_seq START 1;
            CREATE TABLE IF NOT EXISTS validation_log (
                id INTEGER PRIMARY KEY DEFAULT nextval('validation_log_seq'),
                trade_date DATE,
                check_item VARCHAR NOT NULL,
                passed BOOLEAN,
                details VARCHAR,
                check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    def _get_last_update_date(self, table_name: str) -> Optional[datetime]:
        """获取某表的最后更新日期"""
        result = self.meta_conn.execute(f"""
            SELECT MAX(trade_date) FROM update_log 
            WHERE table_name = '{table_name}' AND status = 'success'
        """).fetchone()
        return result[0] if result and result[0] else None
    
    def _log_update(self, table_name: str, trade_date: Optional[datetime], 
                    record_count: int, status: str = 'success', message: str = ''):
        """记录更新日志"""
        date_str = 'NULL' if trade_date is None else f"'{trade_date}'"
        self.meta_conn.execute(f"""
            INSERT INTO update_log (table_name, trade_date, record_count, status, message)
            VALUES ('{table_name}', {date_str}, {record_count}, '{status}', '{message.replace("'", "''")}')
        """)
    
    # ==================== 股票列表更新 ====================
    
    def update_instruments(self, df: Optional[pd.DataFrame] = None):
        """
        更新股票列表
        
        Args:
            df: 股票列表数据，如果为None则需要从数据源获取
                必需字段: ts_code, symbol, exchange, list_date, status
        """
        logger.info("开始更新股票列表...")
        
        if df is None:
            # TODO: 接入实际数据源（tushare/akshare等）
            logger.warning("未提供数据，请传入股票列表DataFrame")
            return
        
        # 确保字段完整
        required_cols = ['ts_code', 'symbol', 'exchange', 'list_date', 'status']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必需字段: {col}")
        
        # 添加可选字段
        if 'delist_date' not in df.columns:
            df['delist_date'] = None
        
        # 写入parquet
        output_path = settings.INSTRUMENTS_DIR / "instruments.parquet"
        df.to_parquet(output_path, index=False)
        
        self._log_update('instruments', None, len(df))
        logger.info(f"股票列表更新完成: {len(df)} 条记录")
    
    # ==================== 交易日历更新 ====================
    
    def update_calendar(self, df: Optional[pd.DataFrame] = None):
        """
        更新交易日历
        
        Args:
            df: 交易日历数据，如果为None则需要从数据源获取
                必需字段: trade_date, is_open
        """
        logger.info("开始更新交易日历...")
        
        if df is None:
            logger.warning("未提供数据，请传入交易日历DataFrame")
            return
        
        # 确保字段完整
        required_cols = ['trade_date', 'is_open']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必需字段: {col}")
        
        # 计算前后交易日
        df = df.sort_values('trade_date').reset_index(drop=True)
        trade_dates = df[df['is_open'] == 1]['trade_date'].tolist()
        
        date_to_idx = {d: i for i, d in enumerate(trade_dates)}
        
        df['prev_trade_date'] = None
        df['next_trade_date'] = None
        
        for idx, row in df.iterrows():
            if row['is_open'] == 1 and row['trade_date'] in date_to_idx:
                curr_idx = date_to_idx[row['trade_date']]
                if curr_idx > 0:
                    df.at[idx, 'prev_trade_date'] = trade_dates[curr_idx - 1]
                if curr_idx < len(trade_dates) - 1:
                    df.at[idx, 'next_trade_date'] = trade_dates[curr_idx + 1]
        
        # 写入parquet
        output_path = settings.CALENDAR_DIR / "calendar.parquet"
        df.to_parquet(output_path, index=False)
        
        self._log_update('calendar', None, len(df))
        logger.info(f"交易日历更新完成: {len(df)} 条记录")
    
    # ==================== 日线行情更新 ====================
    
    def update_daily_bar(self, df: Optional[pd.DataFrame] = None, 
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None):
        """
        更新日线行情数据
        
        Args:
            df: 日线数据，如果为None则需要从数据源获取
                必需字段: ts_code, trade_date, open, high, low, close, pre_close, volume, amount
            start_date: 开始日期 (YYYYMMDD)，用于增量更新
            end_date: 结束日期 (YYYYMMDD)
        """
        logger.info(f"开始更新日线行情...")
        
        if df is None:
            logger.warning("未提供数据，请传入日线数据DataFrame")
            return
        
        # 确保字段完整
        required_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 
                        'close', 'pre_close', 'volume', 'amount']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必需字段: {col}")
        
        # 添加is_trading字段（如果不存在）
        if 'is_trading' not in df.columns:
            df['is_trading'] = 1
        
        # 确保trade_date是日期类型
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        
        # 按日期分区写入
        trade_dates = df['trade_date'].dt.date.unique()
        total_records = 0
        
        for trade_date in trade_dates:
            date_str = trade_date.strftime('%Y-%m-%d')
            date_df = df[df['trade_date'].dt.date == trade_date].copy()
            
            # 创建分区目录
            partition_dir = settings.DAILY_BAR_DIR / f"trade_date={date_str}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            
            # 写入parquet（覆盖）
            output_path = partition_dir / "part-000.parquet"
            date_df.to_parquet(output_path, index=False)
            
            total_records += len(date_df)
            self._log_update('daily_bar', trade_date, len(date_df))
        
        logger.info(f"日线行情更新完成: {len(trade_dates)} 个交易日, {total_records} 条记录")
    
    # ==================== 复权因子更新 ====================
    
    def update_adj_factor(self, df: Optional[pd.DataFrame] = None,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None):
        """
        更新复权因子数据
        
        Args:
            df: 复权因子数据，如果为None则需要从数据源获取
                必需字段: ts_code, trade_date, adj_factor
        """
        logger.info("开始更新复权因子...")
        
        if df is None:
            logger.warning("未提供数据，请传入复权因子DataFrame")
            return
        
        # 确保字段完整
        required_cols = ['ts_code', 'trade_date', 'adj_factor']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必需字段: {col}")
        
        # 确保trade_date是日期类型
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        
        # 按日期分区写入
        trade_dates = df['trade_date'].dt.date.unique()
        total_records = 0
        
        for trade_date in trade_dates:
            date_str = trade_date.strftime('%Y-%m-%d')
            date_df = df[df['trade_date'].dt.date == trade_date].copy()
            
            # 创建分区目录
            partition_dir = settings.ADJ_FACTOR_DIR / f"trade_date={date_str}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            
            # 写入parquet（覆盖）
            output_path = partition_dir / "part-000.parquet"
            date_df.to_parquet(output_path, index=False)
            
            total_records += len(date_df)
            self._log_update('adj_factor', trade_date, len(date_df))
        
        logger.info(f"复权因子更新完成: {len(trade_dates)} 个交易日, {total_records} 条记录")
    
    # ==================== 增量更新逻辑 ====================
    
    def _update_partitioned_by_date(
        self,
        df: Optional[pd.DataFrame],
        date_col: str,
        output_dir: Path,
        table_name: str,
        required_cols: list,
    ):
        """按日期分区写入补充数据。"""
        if df is None or len(df) == 0:
            logger.warning("{} 没有可写入数据", table_name)
            return

        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必需字段: {col}")

        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        trade_dates = df[date_col].dt.date.unique()
        total_records = 0

        for trade_date in trade_dates:
            date_str = trade_date.strftime("%Y-%m-%d")
            date_df = df[df[date_col].dt.date == trade_date].copy()
            partition_dir = output_dir / f"{date_col}={date_str}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            output_path = partition_dir / "part-000.parquet"
            date_df.to_parquet(output_path, index=False)
            total_records += len(date_df)
            self._log_update(table_name, trade_date, len(date_df))

        logger.info("{} 更新完成: {} 个日期, {} 条记录", table_name, len(trade_dates), total_records)

    def update_daily_basic(self, df: Optional[pd.DataFrame] = None):
        """更新每日基础指标数据。"""
        self._update_partitioned_by_date(
            df=df,
            date_col="trade_date",
            output_dir=settings.DAILY_BASIC_DIR,
            table_name="daily_basic",
            required_cols=["ts_code", "trade_date"],
        )

    def update_stk_limit(self, df: Optional[pd.DataFrame] = None):
        """更新每日涨跌停价格数据。"""
        self._update_partitioned_by_date(
            df=df,
            date_col="trade_date",
            output_dir=settings.STK_LIMIT_DIR,
            table_name="stk_limit",
            required_cols=["ts_code", "trade_date", "up_limit", "down_limit"],
        )

    def update_suspend_d(self, df: Optional[pd.DataFrame] = None):
        """更新停复牌明细数据。"""
        self._update_partitioned_by_date(
            df=df,
            date_col="trade_date",
            output_dir=settings.SUSPEND_D_DIR,
            table_name="suspend_d",
            required_cols=["ts_code", "trade_date"],
        )

    def update_namechange(self, df: Optional[pd.DataFrame] = None):
        """更新股票历史名称变更数据。"""
        if df is None or len(df) == 0:
            logger.warning("namechange 没有可写入数据")
            return
        output_path = settings.NAMECHANGE_DIR / "namechange.parquet"
        df.to_parquet(output_path, index=False)
        self._log_update("namechange", None, len(df))
        logger.info("namechange 更新完成: {} 条记录", len(df))

    def incremental_update(self, get_data_func, table_name: str, lookback_days: int = None):
        """
        执行增量更新
        
        Args:
            get_data_func: 获取数据的回调函数，接收(start_date, end_date)返回DataFrame
            table_name: 表名 ('daily_bar' 或 'adj_factor')
            lookback_days: 回溯天数，默认使用配置
        """
        if lookback_days is None:
            lookback_days = settings.UPDATE_LOOKBACK_DAYS
        
        # 获取最后更新日期
        last_update = self._get_last_update_date(table_name)
        
        if last_update is None:
            logger.warning(f"{table_name} 无历史更新记录，请执行全量初始化")
            return
        
        # 计算更新范围（回溯lookback_days天）
        start_date = (last_update - timedelta(days=lookback_days)).strftime('%Y%m%d')
        end_date = datetime.now().strftime('%Y%m%d')
        
        logger.info(f"{table_name} 增量更新: {start_date} ~ {end_date}")
        
        # 获取数据
        df = get_data_func(start_date, end_date)
        
        if df is None or len(df) == 0:
            logger.info(f"{table_name} 无新数据")
            return
        
        # 执行更新
        if table_name == 'daily_bar':
            self.update_daily_bar(df, start_date, end_date)
        elif table_name == 'adj_factor':
            self.update_adj_factor(df, start_date, end_date)
    
    def close(self):
        """关闭连接"""
        if self.meta_conn:
            self.meta_conn.close()


# ==================== 示例数据生成（用于测试） ====================

def generate_sample_data():
    """生成示例数据用于测试"""
    import numpy as np
    
    # 股票列表
    instruments = pd.DataFrame({
        'ts_code': ['600000.SH', '600001.SH', '000001.SZ', '000002.SZ'],
        'symbol': ['浦发银行', '邯郸钢铁', '平安银行', '万科A'],
        'exchange': ['SH', 'SH', 'SZ', 'SZ'],
        'list_date': ['1999-11-10', '1998-01-22', '1991-04-03', '1991-01-29'],
        'delist_date': [None, None, None, None],
        'status': ['L', 'L', 'L', 'L']
    })
    
    # 交易日历（2024年1月部分）
    dates = pd.date_range('2024-01-01', '2024-01-31', freq='D')
    calendar = pd.DataFrame({
        'trade_date': dates,
        'is_open': [1 if d.weekday() < 5 else 0 for d in dates]
    })
    # 调整节假日（简单示例）
    calendar.loc[calendar['trade_date'] == '2024-01-01', 'is_open'] = 0
    
    # 日线行情
    daily_bars = []
    np.random.seed(42)
    for ts_code in instruments['ts_code']:
        base_price = np.random.uniform(10, 100)
        for date in pd.date_range('2024-01-02', '2024-01-31', freq='D'):
            if date.weekday() >= 5:
                continue
            change = np.random.normal(0, 0.02)
            close = base_price * (1 + change)
            high = close * (1 + abs(np.random.normal(0, 0.01)))
            low = close * (1 - abs(np.random.normal(0, 0.01)))
            open_price = base_price * (1 + np.random.normal(0, 0.01))
            
            daily_bars.append({
                'ts_code': ts_code,
                'trade_date': date,
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(close, 2),
                'pre_close': round(base_price, 2),
                'volume': int(np.random.uniform(1000000, 10000000)),
                'amount': int(np.random.uniform(10000000, 100000000)),
                'is_trading': 1
            })
            base_price = close
    
    daily_bar = pd.DataFrame(daily_bars)
    
    # 复权因子
    adj_factors = []
    for ts_code in instruments['ts_code']:
        factor = 1.0
        for date in pd.date_range('2024-01-02', '2024-01-31', freq='D'):
            if date.weekday() >= 5:
                continue
            # 偶尔发生除权除息
            if np.random.random() < 0.05:
                factor *= np.random.uniform(0.9, 1.1)
            adj_factors.append({
                'ts_code': ts_code,
                'trade_date': date,
                'adj_factor': round(factor, 6)
            })
    
    adj_factor = pd.DataFrame(adj_factors)
    
    return instruments, calendar, daily_bar, adj_factor


if __name__ == "__main__":
    # 配置日志
    from config import settings
    logger.add(settings.LOG_DIR / "update.log", rotation="10 MB")
    
    # 创建更新器
    updater = DataUpdater()
    
    try:
        # 生成示例数据（实际使用时替换为真实数据源）
        instruments, calendar, daily_bar, adj_factor = generate_sample_data()
        
        # 全量更新
        updater.update_instruments(instruments)
        updater.update_calendar(calendar)
        updater.update_daily_bar(daily_bar)
        updater.update_adj_factor(adj_factor)
        
        logger.info("数据初始化完成！")
        
    finally:
        updater.close()
