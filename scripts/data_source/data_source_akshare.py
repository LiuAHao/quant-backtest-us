"""
AkShare数据源适配器
提供从AkShare获取股票数据的统一接口
"""
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))


class AkShareDataSource:
    """AkShare数据源"""
    
    def __init__(self, delay: float = 2.0, max_retries: int = 5):
        """
        初始化
        
        Args:
            delay: 请求间隔时间（秒）
            max_retries: 最大重试次数
        """
        try:
            import akshare as ak
            self.ak = ak
            self.delay = delay
            self.max_retries = max_retries
            logger.info("AkShare数据源初始化成功")
        except ImportError:
            raise ImportError("请先安装akshare: pip install akshare")
    
    def _fetch_with_retry(self, fetch_func, *args, **kwargs):
        """带重试的数据获取"""
        for i in range(self.max_retries):
            try:
                time.sleep(self.delay)  # 请求间隔
                return fetch_func(*args, **kwargs)
            except Exception as e:
                if i < self.max_retries - 1:
                    logger.warning(f"请求失败，{i+1}/{self.max_retries}次重试: {e}")
                    time.sleep(self.delay * 2)  # 重试时增加等待时间
                else:
                    raise
    
    def get_stock_list(self) -> pd.DataFrame:
        """
        获取A股股票列表
        
        Returns:
            DataFrame with columns: ts_code, symbol, exchange, list_date, delist_date, status
        """
        logger.info("从AkShare获取股票列表...")
        
        # 获取上海股票
        df_sh = self.ak.stock_info_sh_name_code()
        # 获取深圳股票
        df_sz = self.ak.stock_info_sz_name_code()
        # 获取北京股票
        df_bj = self.ak.stock_info_bj_name_code()
        
        # 统一字段格式
        stocks = []
        
        # 处理上海股票
        for _, row in df_sh.iterrows():
            stocks.append({
                'ts_code': f"{row['证券代码']}.SH",
                'symbol': row['证券简称'],
                'exchange': 'SH',
                'list_date': self._format_date(row['上市日期']),
                'delist_date': None,
                'status': 'L'  # 上市
            })
        
        # 处理深圳股票
        for _, row in df_sz.iterrows():
            stocks.append({
                'ts_code': f"{row['A股代码']}.SZ",
                'symbol': row['A股简称'],
                'exchange': 'SZ',
                'list_date': self._format_date(row['A股上市日期']),
                'delist_date': None,
                'status': 'L'
            })
        
        # 处理北京股票
        for _, row in df_bj.iterrows():
            stocks.append({
                'ts_code': f"{row['证券代码']}.BJ",
                'symbol': row['证券简称'],
                'exchange': 'BJ',
                'list_date': self._format_date(row['上市日期']),
                'delist_date': None,
                'status': 'L'
            })
        
        df = pd.DataFrame(stocks)
        logger.info(f"获取到 {len(df)} 只股票")
        return df
    
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取交易日历
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
        
        Returns:
            DataFrame with columns: trade_date, is_open, prev_trade_date, next_trade_date
        """
        logger.info(f"从AkShare获取交易日历: {start_date} ~ {end_date}")
        
        # 转换日期格式
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        
        # 获取交易日历
        df = self.ak.tool_trade_date_hist_sina()
        df.columns = ['trade_date']
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        
        # 筛选日期范围
        df = df[(df['trade_date'] >= start) & (df['trade_date'] <= end)]
        
        # 生成完整的日期序列
        all_dates = pd.date_range(start=start, end=end, freq='D')
        calendar = pd.DataFrame({'trade_date': all_dates})
        calendar['is_open'] = calendar['trade_date'].isin(df['trade_date']).astype(int)
        
        # 计算前后交易日
        trade_dates = calendar[calendar['is_open'] == 1]['trade_date'].tolist()
        date_to_idx = {d: i for i, d in enumerate(trade_dates)}
        
        calendar['prev_trade_date'] = None
        calendar['next_trade_date'] = None
        
        for idx, row in calendar.iterrows():
            if row['is_open'] == 1 and row['trade_date'] in date_to_idx:
                curr_idx = date_to_idx[row['trade_date']]
                if curr_idx > 0:
                    calendar.at[idx, 'prev_trade_date'] = trade_dates[curr_idx - 1]
                if curr_idx < len(trade_dates) - 1:
                    calendar.at[idx, 'next_trade_date'] = trade_dates[curr_idx + 1]
        
        logger.info(f"获取到 {len(calendar)} 个日期，其中 {calendar['is_open'].sum()} 个交易日")
        return calendar
    
    def get_daily_data(self, start_date: str, end_date: str, stock_codes: Optional[list] = None) -> pd.DataFrame:
        """
        获取日线行情数据
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            stock_codes: 股票代码列表，如 ['600000.SH', '000001.SZ']，None表示全市场
        
        Returns:
            DataFrame with columns: ts_code, trade_date, open, high, low, close, pre_close, volume, amount
        """
        logger.info(f"从AkShare获取日线数据: {start_date} ~ {end_date}")
        
        all_data = []
        failed_stocks = []
        
        if stock_codes is None:
            # 获取全市场数据
            stock_list = self.get_stock_list()
            stock_codes = stock_list['ts_code'].tolist()
            logger.info(f"全市场共 {len(stock_codes)} 只股票")
        
        total = len(stock_codes)
        logger.info(f"开始下载 {total} 只股票数据...")
        
        for i, ts_code in enumerate(stock_codes, 1):
            try:
                code = ts_code.split('.')[0]
                
                # 使用stock_zh_a_hist接口获取数据（统一接口，无需区分交易所）
                df = self._fetch_with_retry(
                    self.ak.stock_zh_a_hist,
                    symbol=code, 
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"  # 前复权
                )
                
                if df is None or len(df) == 0:
                    failed_stocks.append(ts_code)
                    continue
                
                # 字段映射 (AkShare字段 -> 系统标准字段)
                df = df.rename(columns={
                    '日期': 'trade_date',
                    '开盘': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '收盘': 'close',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '振幅': 'amplitude',
                    '涨跌幅': 'pct_change',
                    '涨跌额': 'change',
                    '换手率': 'turnover'
                })
                
                # 添加股票代码
                df['ts_code'] = ts_code
                
                # 转换日期格式
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                
                # 计算pre_close
                df = df.sort_values('trade_date')
                df['pre_close'] = df['close'].shift(1)
                
                # 添加is_trading标记
                df['is_trading'] = 1
                
                # 选择需要的字段
                df = df[['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 
                        'pre_close', 'volume', 'amount', 'is_trading']]
                
                all_data.append(df)
                
                # 每50只打印进度
                if i % 50 == 0:
                    logger.info(f"已下载 {i}/{total} 只股票 ({i/total*100:.1f}%)")
                
            except Exception as e:
                logger.warning(f"获取 {ts_code} 数据失败: {e}")
                failed_stocks.append(ts_code)
                continue
        
        if len(all_data) == 0:
            logger.warning("未获取到任何日线数据")
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        logger.info(f"获取到 {len(result)} 条日线记录，成功 {total-len(failed_stocks)}/{total} 只股票")
        
        if failed_stocks:
            logger.warning(f"下载失败 {len(failed_stocks)} 只: {failed_stocks[:10]}{'...' if len(failed_stocks) > 10 else ''}")
        
        return result
    
    def get_adj_factor(self, start_date: str, end_date: str, stock_codes: Optional[list] = None) -> pd.DataFrame:
        """
        获取复权因子
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            stock_codes: 股票代码列表
        
        Returns:
            DataFrame with columns: ts_code, trade_date, adj_factor
        """
        logger.info(f"从AkShare获取复权因子: {start_date} ~ {end_date}")
        
        all_data = []
        
        if stock_codes is None:
            stock_codes = ['600000.SH', '600001.SH', '000001.SZ', '000002.SZ']
        
        for ts_code in stock_codes:
            try:
                code = ts_code.split('.')[0]
                
                # 获取后复权数据
                df = self._fetch_with_retry(
                    self.ak.stock_zh_a_hist,
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="hfq"  # 后复权
                )
                
                if len(df) == 0:
                    continue
                
                # 获取不复权数据
                df_raw = self._fetch_with_retry(
                    self.ak.stock_zh_a_hist,
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=""
                )
                
                if len(df_raw) == 0:
                    continue
                
                # 计算复权因子
                df = df.rename(columns={'日期': 'trade_date', '收盘': 'close_fq'})
                df_raw = df_raw.rename(columns={'日期': 'trade_date', '收盘': 'close_raw'})
                
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                df_raw['trade_date'] = pd.to_datetime(df_raw['trade_date'])
                
                merged = pd.merge(df[['trade_date', 'close_fq']], 
                                df_raw[['trade_date', 'close_raw']], 
                                on='trade_date')
                
                # 复权因子 = 后复权价 / 原始价
                merged['adj_factor'] = merged['close_fq'] / merged['close_raw']
                merged['ts_code'] = ts_code
                
                all_data.append(merged[['ts_code', 'trade_date', 'adj_factor']])
                
            except Exception as e:
                logger.warning(f"获取 {ts_code} 复权因子失败: {e}")
                # 使用默认复权因子1.0
                dates = pd.date_range(start=start_date, end=end_date, freq='D')
                df_default = pd.DataFrame({
                    'ts_code': ts_code,
                    'trade_date': dates,
                    'adj_factor': 1.0
                })
                all_data.append(df_default)
                continue
        
        if len(all_data) == 0:
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        logger.info(f"获取到 {len(result)} 条复权因子记录")
        return result
    
    def _format_date(self, date_val) -> Optional[str]:
        """格式化日期"""
        if pd.isna(date_val):
            return None
        if isinstance(date_val, str):
            # 处理YYYY-MM-DD格式
            return date_val.replace('-', '')
        return str(date_val)


def update_from_akshare(updater, start_date: str = None, end_date: str = None, stock_codes: list = None):
    """
    使用AkShare更新数据的便捷函数
    
    Args:
        updater: DataUpdater实例
        start_date: 开始日期 (YYYYMMDD)，None表示全量
        end_date: 结束日期 (YYYYMMDD)，None表示今天
        stock_codes: 股票代码列表，None表示全市场
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    
    source = AkShareDataSource()
    
    # 1. 更新股票列表
    logger.info("="*50)
    logger.info("更新股票列表")
    instruments = source.get_stock_list()
    updater.update_instruments(instruments)
    
    # 2. 更新交易日历
    logger.info("="*50)
    logger.info("更新交易日历")
    if start_date is None:
        start_date_cal = '20200101'  # 默认从2020年开始
    else:
        start_date_cal = start_date
    calendar = source.get_trade_calendar(start_date_cal, end_date)
    updater.update_calendar(calendar)
    
    # 3. 更新日线数据
    logger.info("="*50)
    logger.info("更新日线数据")
    if start_date is None:
        # 全量更新：获取每只股票的全部历史
        logger.info("执行全量更新，这可能需要较长时间...")
        # 这里简化处理，只获取最近一年的数据
        from datetime import timedelta
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
    
    daily_data = source.get_daily_data(start_date, end_date, stock_codes)
    if len(daily_data) > 0:
        updater.update_daily_bar(daily_data)
    
    # 4. 更新复权因子
    logger.info("="*50)
    logger.info("更新复权因子")
    adj_factor = source.get_adj_factor(start_date, end_date, stock_codes)
    if len(adj_factor) > 0:
        updater.update_adj_factor(adj_factor)
    
    logger.info("="*50)
    logger.info("AkShare数据更新完成！")


if __name__ == "__main__":
    # 测试代码
    from scripts.data_download.update_daily import DataUpdater
    
    updater = DataUpdater()
    try:
        # 测试获取最近30天的数据
        from datetime import timedelta
        end = datetime.now()
        start = (end - timedelta(days=30)).strftime('%Y%m%d')
        end = end.strftime('%Y%m%d')
        
        update_from_akshare(
            updater, 
            start_date=start, 
            end_date=end,
            stock_codes=['600000.SH', '000001.SZ']  # 测试两只股票
        )
    finally:
        updater.close()
