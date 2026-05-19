import unittest
import pandas as pd
import numpy as np

from backtest.indicators import sma, ema, rsi, macd, bollinger_bands, atr


class TestSMA(unittest.TestCase):
    def test_basic(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        result = sma(s, window=3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)
        self.assertAlmostEqual(result.iloc[9], 9.0)

    def test_window_equals_length(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = sma(s, window=5)
        for i in range(4):
            self.assertTrue(np.isnan(result.iloc[i]))
        self.assertAlmostEqual(result.iloc[4], 3.0)


class TestEMA(unittest.TestCase):
    def test_basic(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        result = ema(s, window=3)
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertFalse(np.isnan(result.iloc[2]))

    def test_converges_to_last_value(self):
        s = pd.Series([100.0] * 50 + [200.0] * 50)
        result = ema(s, window=5)
        self.assertAlmostEqual(result.iloc[-1], 200.0, places=1)


class TestRSI(unittest.TestCase):
    def test_all_gains(self):
        s = pd.Series(range(1, 20), dtype=float)
        result = rsi(s, window=5)
        valid = result.dropna()
        self.assertTrue((valid > 90).all())

    def test_all_losses(self):
        s = pd.Series(range(20, 1, -1), dtype=float)
        result = rsi(s, window=5)
        valid = result.dropna()
        self.assertTrue((valid < 10).all())

    def test_range(self):
        s = pd.Series([44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
                        46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
                        46.22, 45.64], dtype=float)
        result = rsi(s, window=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())

    def test_nan_handling(self):
        s = pd.Series(range(1, 20), dtype=float)
        result = rsi(s, window=14)
        for i in range(14):
            self.assertTrue(np.isnan(result.iloc[i]))
        self.assertFalse(np.isnan(result.iloc[14]))


class TestMACD(unittest.TestCase):
    def test_columns(self):
        s = pd.Series(range(1, 50), dtype=float)
        result = macd(s)
        self.assertEqual(list(result.columns), ["macd", "signal", "histogram"])

    def test_histogram_equals_macd_minus_signal(self):
        s = pd.Series(range(1, 50), dtype=float)
        result = macd(s)
        pd.testing.assert_series_equal(
            result["histogram"], result["macd"] - result["signal"], check_names=False
        )

    def test_fast_equals_slow_returns_zeros(self):
        s = pd.Series(range(1, 50), dtype=float)
        result = macd(s, fast=12, slow=12, signal=9)
        valid = result.dropna()
        np.testing.assert_allclose(valid["macd"].values, 0.0, atol=1e-10)


class TestBollingerBands(unittest.TestCase):
    def test_columns(self):
        s = pd.Series(range(1, 30), dtype=float)
        result = bollinger_bands(s)
        self.assertEqual(list(result.columns), ["upper", "middle", "lower"])

    def test_upper_middle_lower_order(self):
        s = pd.Series([10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17, 19, 18, 20], dtype=float)
        result = bollinger_bands(s, window=10)
        valid = result.dropna()
        self.assertTrue((valid["upper"] > valid["middle"]).all())
        self.assertTrue((valid["middle"] > valid["lower"]).all())

    def test_nan_handling(self):
        s = pd.Series(range(1, 30), dtype=float)
        result = bollinger_bands(s, window=10)
        for i in range(9):
            self.assertTrue(np.isnan(result["upper"].iloc[i]))
            self.assertTrue(np.isnan(result["middle"].iloc[i]))
            self.assertTrue(np.isnan(result["lower"].iloc[i]))
        self.assertFalse(np.isnan(result["middle"].iloc[9]))


class TestATR(unittest.TestCase):
    def test_basic(self):
        high = pd.Series([12, 13, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17, 19, 18, 20], dtype=float)
        low = pd.Series([10, 11, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18], dtype=float)
        close = pd.Series([11, 12, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17, 19], dtype=float)
        result = atr(high, low, close, window=5)
        self.assertTrue(np.isnan(result.iloc[0]))
        valid = result.dropna()
        self.assertTrue((valid > 0).all())

    def test_constant_price_returns_zero(self):
        n = 30
        price = pd.Series([100.0] * n)
        result = atr(price, price, price, window=14)
        valid = result.dropna()
        np.testing.assert_allclose(valid.values, 0.0, atol=1e-10)


if __name__ == "__main__":
    unittest.main()
