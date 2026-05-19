"""
量化回测系统配置
"""
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).parent


class Settings(BaseSettings):
    """系统配置"""
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # 项目根目录
    PROJECT_ROOT: Path = PROJECT_ROOT
    
    # 数据目录
    DATA_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data")
    
    # 各数据子目录
    DAILY_BAR_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "daily_bar")
    ADJ_FACTOR_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "adj_factor")
    DAILY_BASIC_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "daily_basic")
    STK_LIMIT_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "stk_limit")
    SUSPEND_D_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "suspend_d")
    NAMECHANGE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "namechange")
    CALENDAR_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "calendar")
    INSTRUMENTS_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "instruments")
    META_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "meta")
    
    # 指数成分股数据目录
    INDEX_MEMBER_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "index_member")
    CONCEPT_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "concept")
    INDEX_DAILY_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "index_daily")
    FUND_BASIC_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "fund_basic")
    
    # 补充数据目录
    INDUSTRY_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "industry")
    FINANCIAL_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "financial")
    ETF_DAILY_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "etf_daily")
    HOLDER_NUMBER_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "holder_number")
    
    # 元数据库路径
    META_DB_PATH: Path = Field(default_factory=lambda: Path(__file__).parent / "data" / "meta" / "meta.duckdb")
    
    # 日志目录
    LOG_DIR: Path = Field(default_factory=lambda: Path(__file__).parent / "logs")
    
    # 数据更新配置
    UPDATE_LOOKBACK_DAYS: int = 10  # 增量更新时回溯天数
    
    # 回测配置
    DEFAULT_INITIAL_CAPITAL: float = 1000000.0  # 默认初始资金
    DEFAULT_COMMISSION_RATE: float = 0.0003      # 默认手续费率
    DEFAULT_SLIPPAGE: float = 0.001              # 默认滑点
    
    # 敏感 API 信息：只从环境变量或 .env 读取，不在代码里硬编码
    TUSHARE_TOKEN: Optional[str] = None
    TUSHARE_BASE_URL: Optional[str] = None
    AI_BASE_URL: str = "https://api.deepseek.com"
    AI_MODEL: str = "deepseek-v4-pro"
    AI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None


# 全局配置实例
settings = Settings()

# 确保目录存在
for dir_path in [
    settings.DAILY_BAR_DIR,
    settings.ADJ_FACTOR_DIR,
    settings.DAILY_BASIC_DIR,
    settings.STK_LIMIT_DIR,
    settings.SUSPEND_D_DIR,
    settings.NAMECHANGE_DIR,
    settings.CALENDAR_DIR,
    settings.INSTRUMENTS_DIR,
    settings.META_DIR,
    settings.LOG_DIR,
    settings.INDUSTRY_DIR,
    settings.FINANCIAL_DIR,
    settings.ETF_DAILY_DIR,
    settings.HOLDER_NUMBER_DIR,
]:
    dir_path.mkdir(parents=True, exist_ok=True)
