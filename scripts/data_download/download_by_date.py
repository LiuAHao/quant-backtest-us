"""
按日期下载全市场数据（高效版）

Tushare支持按日期获取全市场数据，一次请求获取一天所有股票
比按股票逐只下载快100倍！

用法:
    python scripts/data_download/download_by_date.py --start 20250318 --end 20260318
"""
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from update_daily import DataUpdater

# 设置代理
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)


class DateBasedDownloader:
    """按日期下载全市场数据"""
    
    def __init__(self, force: bool = False):
        import tushare as ts
        from tushare.pro.client import DataApi
        if settings.TUSHARE_BASE_URL:
            DataApi._DataApi__http_url = settings.TUSHARE_BASE_URL
        if not settings.TUSHARE_TOKEN:
            raise ValueError("缺少 TUSHARE_TOKEN，请在项目根目录 .env 中配置。")
        self.pro = ts.pro_api(settings.TUSHARE_TOKEN)
        self.updater = DataUpdater()
        self.force = force
        logger.info("下载器初始化完成")

    @staticmethod
    def _has_partition(base_dir: Path, trade_date: str) -> bool:
        date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        return (base_dir / f"trade_date={date_str}" / "part-000.parquet").exists()
    
    def get_trade_dates(self, start_date: str, end_date: str) -> list:
        """获取交易日列表"""
        calendar_path = settings.CALENDAR_DIR / "calendar.parquet"
        if calendar_path.exists():
            df_local = pd.read_parquet(calendar_path)
            df_local["trade_date"] = pd.to_datetime(df_local["trade_date"])
            start = pd.to_datetime(start_date, format="%Y%m%d")
            end = pd.to_datetime(end_date, format="%Y%m%d")
            mask = (
                (df_local["trade_date"] >= start)
                & (df_local["trade_date"] <= end)
                & (df_local["is_open"] == 1)
            )
            dates = df_local.loc[mask, "trade_date"].dt.strftime("%Y%m%d").tolist()
            if dates:
                return sorted(dates)

        df = self.pro.trade_cal(
            exchange='SSE',
            start_date=start_date,
            end_date=end_date,
            fields='cal_date,is_open'
        )
        if df is None or len(df) == 0:
            return []
        dates = df[df['is_open'].astype(str) == '1']['cal_date'].tolist()
        dates.sort()
        return dates
    
    def download_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        """下载某一天全市场日线数据"""
        for retry in range(3):
            try:
                time.sleep(0.3)
                df = self.pro.daily(trade_date=trade_date)
                if df is not None and len(df) > 0:
                    # 字段处理
                    df = df.rename(columns={'vol': 'volume'})
                    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
                    df['is_trading'] = 1
                    df = df[['ts_code', 'trade_date', 'open', 'high', 'low', 'close',
                            'pre_close', 'volume', 'amount', 'is_trading']]
                    return df
                return pd.DataFrame()
            except Exception as e:
                logger.warning(f"下载 {trade_date} 失败(重试{retry+1}): {e}")
                time.sleep(1)
        return pd.DataFrame()
    
    def download_adj_by_date(self, trade_date: str) -> pd.DataFrame:
        """下载某一天全市场复权因子"""
        for retry in range(3):
            try:
                time.sleep(0.3)
                df = self.pro.adj_factor(trade_date=trade_date)
                if df is not None and len(df) > 0:
                    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
                    return df[['ts_code', 'trade_date', 'adj_factor']]
                return pd.DataFrame()
            except Exception as e:
                logger.warning(f"下载复权因子 {trade_date} 失败(重试{retry+1}): {e}")
                time.sleep(1)
        return pd.DataFrame()
    
    def update_stock_list(self):
        """更新股票列表"""
        logger.info("更新股票列表...")
        frames = []
        fields = 'ts_code,symbol,name,list_date,delist_date,market'
        for status in ['L', 'D', 'P']:
            df = self.pro.stock_basic(exchange='', list_status=status, fields=fields)
            if df is not None and len(df) > 0:
                df['status'] = status
                frames.append(df)
        if frames:
            df = pd.concat(frames, ignore_index=True).drop_duplicates('ts_code', keep='first')
            df['symbol'] = df['name']
            df['exchange'] = df['ts_code'].apply(lambda x: x.split('.')[1])
            df['list_date'] = df['list_date'].apply(
                lambda x: f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:8]}" if pd.notna(x) and len(str(x)) == 8 else None
            )
            df['delist_date'] = df['delist_date'].apply(
                lambda x: f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:8]}" if pd.notna(x) and len(str(x)) == 8 else None
            )
            df = df[['ts_code', 'symbol', 'exchange', 'list_date', 'delist_date', 'status']]
            self.updater.update_instruments(df)
            logger.info(f"股票列表更新完成: {len(df)} 条")
    
    def update_calendar(self, start_date: str, end_date: str):
        """更新交易日历"""
        logger.info("更新交易日历...")
        calendar_start = '20140101'
        df = self.pro.trade_cal(exchange='SSE', start_date=calendar_start, end_date=end_date,
                                fields='cal_date,is_open,pretrade_date')
        if df is not None and len(df) > 0:
            df = df.rename(columns={'cal_date': 'trade_date', 'pretrade_date': 'prev_trade_date'})
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            df['prev_trade_date'] = pd.to_datetime(df['prev_trade_date'], format='%Y%m%d', errors='coerce')
            df = df.sort_values('trade_date').reset_index(drop=True)
            
            # 计算next_trade_date
            trade_dates = df[df['is_open'] == 1]['trade_date'].tolist()
            def get_next(d):
                for td in trade_dates:
                    if td > d:
                        return td
                return None
            df['next_trade_date'] = df['trade_date'].apply(get_next)
            
            self.updater.update_calendar(df[['trade_date', 'is_open', 'prev_trade_date', 'next_trade_date']])
            logger.info(f"交易日历更新完成: {len(df)} 天")
    
    def run(self, start_date: str, end_date: str):
        """执行下载"""
        start_time = datetime.now()
        
        logger.info("="*60)
        logger.info(f"开始下载: {start_date} ~ {end_date}")
        logger.info("="*60)
        
        # 1. 更新基础数据
        self.update_stock_list()
        self.update_calendar(start_date, end_date)
        
        # 2. 获取交易日列表
        trade_dates = self.get_trade_dates(start_date, end_date)
        total_days = len(trade_dates)
        logger.info(f"共 {total_days} 个交易日需要下载")
        
        # 3. 按日期下载
        success_days = 0
        fail_days = 0
        skipped_days = 0
        total_records = 0
        
        for i, date in enumerate(trade_dates, 1):
            logger.info(f"\n[{i}/{total_days}] 下载 {date}...")

            has_daily = self._has_partition(settings.DAILY_BAR_DIR, date)
            has_adj = self._has_partition(settings.ADJ_FACTOR_DIR, date)
            if not self.force and has_daily and has_adj:
                skipped_days += 1
                logger.info("  跳过: 日线和复权因子分区已存在")
                continue
            
            # 下载日线数据
            df_daily = pd.DataFrame() if (has_daily and not self.force) else self.download_daily_by_date(date)
            if len(df_daily) > 0:
                self.updater.update_daily_bar(df_daily)

            daily_ok = (has_daily and not self.force) or len(df_daily) > 0
            if daily_ok:
                
                # 下载复权因子
                df_adj = pd.DataFrame() if (has_adj and not self.force) else self.download_adj_by_date(date)
                if len(df_adj) > 0:
                    self.updater.update_adj_factor(df_adj)
                
                success_days += 1
                total_records += len(df_daily)
                logger.info(f"  成功: {len(df_daily)} 条记录")
            else:
                fail_days += 1
                logger.warning(f"  失败: 无数据")
            
            # 进度报告
            if i % 20 == 0:
                elapsed = datetime.now() - start_time
                eta = elapsed / i * (total_days - i)
                logger.info(f"\n>>> 进度: {i}/{total_days} ({i/total_days*100:.1f}%), "
                           f"已用: {elapsed}, 预计剩余: {eta}")
        
        # 4. 完成统计
        duration = datetime.now() - start_time
        logger.info("\n" + "="*60)
        logger.info("下载完成!")
        logger.info(f"  交易日: {success_days} 成功, {skipped_days} 跳过, {fail_days} 失败")
        logger.info(f"  总记录: {total_records:,} 条")
        logger.info(f"  耗时: {duration}")
        logger.info("="*60)
    
    def close(self):
        if self.updater:
            self.updater.close()


def main():
    parser = argparse.ArgumentParser(description='按日期下载全市场数据')
    parser.add_argument('--start', type=str, required=True, help='开始日期 (YYYYMMDD)')
    parser.add_argument('--end', type=str, help='结束日期 (YYYYMMDD)，默认今天')
    args = parser.parse_args()
    
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    logger.add(settings.LOG_DIR / "download_by_date.log", rotation="50 MB")
    
    end_date = args.end or datetime.now().strftime('%Y%m%d')
    
    downloader = DateBasedDownloader()
    try:
        downloader.run(args.start, end_date)
    except KeyboardInterrupt:
        logger.warning("\n用户中断")
    except Exception as e:
        logger.error(f"下载失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        downloader.close()


if __name__ == "__main__":
    main()
