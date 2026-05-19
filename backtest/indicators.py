import pandas as pd
import numpy as np


def sma(series: pd.Series, window: int = 20) -> pd.Series:
    """Simple Moving Average.

    Args:
        series: Price series.
        window: Lookback period. Default 20.

    Returns:
        Series of SMA values; first (window-1) values are NaN.
    """
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int = 20) -> pd.Series:
    """Exponential Moving Average.

    Args:
        series: Price series.
        window: Lookback period. Default 20.

    Returns:
        Series of EMA values; first (window-1) values are NaN.
    """
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index.

    Args:
        series: Price series.
        window: Lookback period. Default 14.

    Returns:
        Series of RSI values in [0, 100]; first (window) values are NaN.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD (Moving Average Convergence Divergence).

    Args:
        series: Price series.
        fast: Fast EMA period. Default 12.
        slow: Slow EMA period. Default 26.
        signal: Signal line EMA period. Default 9.

    Returns:
        DataFrame with columns ['macd', 'signal', 'histogram'].
    """
    fast_ema = series.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = series.ewm(span=slow, adjust=False, min_periods=slow).mean()

    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram},
        index=series.index,
    )


def bollinger_bands(
    series: pd.Series, window: int = 20, num_std: float = 2
) -> pd.DataFrame:
    """Bollinger Bands.

    Args:
        series: Price series.
        window: Lookback period. Default 20.
        num_std: Number of standard deviations. Default 2.

    Returns:
        DataFrame with columns ['upper', 'middle', 'lower'].
        First (window-1) values are NaN.
    """
    middle = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()

    return pd.DataFrame(
        {
            "upper": middle + num_std * std,
            "middle": middle,
            "lower": middle - num_std * std,
        },
        index=series.index,
    )


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range.

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        window: Lookback period. Default 14.

    Returns:
        Series of ATR values; first (window) values are NaN.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
