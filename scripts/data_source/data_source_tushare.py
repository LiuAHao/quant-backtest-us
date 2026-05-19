"""
Tushare数据源适配器
提供从Tushare获取股票数据的统一接口
"""
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings


class TushareDataSource:
    """Tushare数据源"""
    
    def __init__(self, token: str = None, delay: float = 0.5, max_retries: int = 5):
        """
        初始化
        
        Args:
            token: Tushare API Token
            delay: 请求间隔时间（秒）
            max_retries: 最大重试次数
        """
        # 设置代理（根据用户提供的配置）
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        
        try:
            import tushare as ts
            from tushare.pro.client import DataApi
            self.ts = ts
            if settings.TUSHARE_BASE_URL:
                DataApi._DataApi__http_url = settings.TUSHARE_BASE_URL
            
            token = token or settings.TUSHARE_TOKEN
            if not token:
                raise ValueError("缺少 TUSHARE_TOKEN，请在项目根目录 .env 中配置。")
            
            self.pro = ts.pro_api(token)
            self.delay = delay
            self.max_retries = max_retries
            logger.info("Tushare数据源初始化成功")
        except ImportError:
            raise ImportError("请先安装tushare: pip install tushare")
    
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
        logger.info("从Tushare获取股票列表...")
        
        # 获取所有A股股票
        df = self._fetch_with_retry(
            self.pro.stock_basic,
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry,list_date,market'
        )
        
        if df is None or len(df) == 0:
            logger.warning("未获取到股票列表")
            return pd.DataFrame()
        
        # 统一字段格式 - 使用 name 作为 symbol（股票简称）
        # 注意: Tushare 返回的 symbol 是纯数字代码，name 是股票名称
        df['symbol'] = df['name']  # 用 name 覆盖 symbol
        
        # 添加exchange字段
        df['exchange'] = df['ts_code'].apply(lambda x: x.split('.')[1] if '.' in x else '')
        
        # 添加status字段
        df['status'] = 'L'
        df['delist_date'] = None
        
        # 格式化list_date
        df['list_date'] = df['list_date'].apply(self._format_date)
        
        # 选择需要的字段
        df = df[['ts_code', 'symbol', 'exchange', 'list_date', 'delist_date', 'status']]
        
        logger.info(f"获取到 {len(df)} 只股票")
        return df
    
    def _format_date(self, date_val):
        """格式化日期"""
        if pd.isna(date_val) or date_val is None:
            return None
        if isinstance(date_val, str):
            if len(date_val) == 8:
                return f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:8]}"
            return date_val
        return str(date_val)
    
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取交易日历
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
        
        Returns:
            DataFrame with columns: trade_date, is_open, prev_trade_date, next_trade_date
        """
        logger.info(f"从Tushare获取交易日历: {start_date} ~ {end_date}")
        
        # 获取交易日历
        df = self._fetch_with_retry(
            self.pro.trade_cal,
            exchange='SSE',
            start_date=start_date,
            end_date=end_date,
            fields='cal_date,is_open,pretrade_date'
        )
        
        if df is None or len(df) == 0:
            logger.warning("未获取到交易日历")
            return pd.DataFrame()
        
        # 重命名字段
        df = df.rename(columns={
            'cal_date': 'trade_date',
            'pretrade_date': 'prev_trade_date'
        })
        
        # 转换日期格式
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        df['prev_trade_date'] = pd.to_datetime(df['prev_trade_date'], format='%Y%m%d', errors='coerce')
        
        # 排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        # 计算next_trade_date
        trade_dates = df[df['is_open'] == 1]['trade_date'].tolist()
        
        def get_next_trade_date(current_date, is_open):
            if not trade_dates:
                return None
            for td in trade_dates:
                if td > current_date:
                    return td
            return None
        
        df['next_trade_date'] = df.apply(
            lambda row: get_next_trade_date(row['trade_date'], row['is_open']), 
            axis=1
        )
        
        logger.info(f"获取到 {len(df)} 条日历记录，其中 {df['is_open'].sum()} 个交易日")
        return df[['trade_date', 'is_open', 'prev_trade_date', 'next_trade_date']]
    
    def get_daily_data(self, start_date: str, end_date: str, 
                       stock_codes: Optional[list] = None) -> pd.DataFrame:
        """
        获取日线行情数据
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            stock_codes: 股票代码列表，如 ['600000.SH', '000001.SZ']，None表示全市场
        
        Returns:
            DataFrame with columns: ts_code, trade_date, open, high, low, close, pre_close, volume, amount
        """
        logger.info(f"从Tushare获取日线数据: {start_date} ~ {end_date}")
        
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
                # 使用daily接口获取日线数据
                df = self._fetch_with_retry(
                    self.pro.daily,
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df is None or len(df) == 0:
                    failed_stocks.append(ts_code)
                    continue
                
                # Tushare字段映射
                df = df.rename(columns={
                    'vol': 'volume',
                })
                
                # 转换日期格式
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
                
                # 排序
                df = df.sort_values('trade_date')
                
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
    
    def get_adj_factor(self, start_date: str, end_date: str, 
                       stock_codes: Optional[list] = None) -> pd.DataFrame:
        """
        获取复权因子
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            stock_codes: 股票代码列表
        
        Returns:
            DataFrame with columns: ts_code, trade_date, adj_factor
        """
        logger.info(f"从Tushare获取复权因子: {start_date} ~ {end_date}")
        
        all_data = []
        
        if stock_codes is None:
            stock_codes = ['600000.SH', '000001.SZ']  # 测试用
        
        for ts_code in stock_codes:
            try:
                # 使用adj_factor接口
                df = self._fetch_with_retry(
                    self.pro.adj_factor,
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df is None or len(df) == 0:
                    continue
                
                # 转换日期格式
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
                
                all_data.append(df[['ts_code', 'trade_date', 'adj_factor']])
                
            except Exception as e:
                logger.warning(f"获取 {ts_code} 复权因子失败: {e}")
                continue
        
        if len(all_data) == 0:
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        logger.info(f"获取到 {len(result)} 条复权因子记录")
        return result
    
    def test_connection(self) -> bool:
        """
        测试连接是否正常
        
        Returns:
            是否连接成功
        """
        logger.info("测试Tushare连接...")
        try:
            # 尝试获取指数基本信息作为简单测试
            df = self.pro.index_basic(limit=5, fields=["ts_code", "name", "market", "publisher", "category", "base_date"])
            if df is not None and len(df) > 0:
                logger.info("Tushare连接测试成功！")
                logger.info(f"测试数据:\n{df}")
                return True
            else:
                logger.error("Tushare连接测试失败：返回数据为空")
                return False
        except Exception as e:
            logger.error(f"Tushare连接测试失败: {e}")
            return False


def update_from_tushare(updater, start_date: str = None, end_date: str = None, 
                        stock_codes: list = None, token: str = None):
    """
    使用Tushare更新数据的便捷函数
    
    Args:
        updater: DataUpdater实例
        start_date: 开始日期 (YYYYMMDD)，None表示全量
        end_date: 结束日期 (YYYYMMDD)，None表示今天
        stock_codes: 股票代码列表，None表示全市场
        token: Tushare API Token
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    
    source = TushareDataSource(token=token)
    
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
        # 全量更新：这里简化处理，只获取最近一年的数据
        logger.info("执行全量更新，这可能需要较长时间...")
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
    logger.info("Tushare数据更新完成！")


# 测试入口
if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    
    print("="*60)
    print("Tushare数据源测试")
    print("="*60)
    
    source = TushareDataSource()
    
    # 测试连接
    if source.test_connection():
        print("\n连接成功！继续获取更多数据...\n")
        
        # 测试获取股票列表
        print("-" * 40)
        print("测试获取股票列表:")
        stocks = source.get_stock_list()
        print(f"获取到 {len(stocks)} 只股票")
        print(stocks.head())
        
        # 测试获取交易日历
        print("\n" + "-" * 40)
        print("测试获取交易日历:")
        calendar = source.get_trade_calendar('20240101', '20240110')
        print(calendar)
        
        # 测试获取日线数据（少量股票）
        print("\n" + "-" * 40)
        print("测试获取日线数据 (600000.SH, 000001.SZ):")
        daily = source.get_daily_data('20240101', '20240110', ['600000.SH', '000001.SZ'])
        print(daily)
    else:
        print("\n连接失败，请检查Token和网络配置")
