from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).parent


class Settings(BaseSettings):
    """Application settings for the US-market research skeleton."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_ROOT: Path = PROJECT_ROOT
    DATA_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    LOG_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "logs")

    US_DAILY_BAR_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "us_daily_bar")
    US_ADJUSTMENTS_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "us_adjustments")
    US_CALENDAR_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "us_calendar")
    US_INSTRUMENTS_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "us_instruments")
    US_FUNDAMENTALS_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "us_fundamentals")
    META_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "meta")

    DEFAULT_INITIAL_CAPITAL: float = 1_000_000.0
    DEFAULT_COMMISSION_RATE: float = 0.0
    DEFAULT_SLIPPAGE: float = 0.0

    POLYGON_API_KEY: Optional[str] = None
    TIINGO_API_KEY: Optional[str] = None
    ALPACA_API_KEY: Optional[str] = None
    ALPACA_API_SECRET: Optional[str] = None
    NASDAQ_DATA_LINK_API_KEY: Optional[str] = None

    AI_BASE_URL: Optional[str] = None
    AI_MODEL: Optional[str] = None
    AI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None


settings = Settings()

for directory in [
    settings.DATA_DIR,
    settings.LOG_DIR,
    settings.US_DAILY_BAR_DIR,
    settings.US_ADJUSTMENTS_DIR,
    settings.US_CALENDAR_DIR,
    settings.US_INSTRUMENTS_DIR,
    settings.US_FUNDAMENTALS_DIR,
    settings.META_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)
