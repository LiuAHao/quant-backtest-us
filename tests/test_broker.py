from __future__ import annotations

import unittest
from datetime import datetime

from backtest.broker import (
    Broker,
    Position,
    OrderSide,
    OrderType,
    OrderStatus,
    get_price_limit_status,
)


class PositionMarketValueTest(unittest.TestCase):
    """Tests for Position.market_value and get_market_value."""

    def test_market_value_property(self):
        """Position.market_value should return volume * avg_cost."""
        pos = Position(ts_code="000001.SZ", volume=100, avg_cost=10.0)
        self.assertAlmostEqual(pos.market_value, 1000.0, places=4)

    def test_market_value_zero_position(self):
        pos = Position(ts_code="000001.SZ", volume=0, avg_cost=0.0)
        self.assertAlmostEqual(pos.market_value, 0.0, places=4)

    def test_get_market_value_with_price(self):
        """get_market_value(price) should return volume * price."""
        pos = Position(ts_code="000001.SZ", volume=100, avg_cost=10.0)
        self.assertAlmostEqual(pos.get_market_value(12.0), 1200.0, places=4)

    def test_get_market_value_default(self):
        pos = Position(ts_code="000001.SZ", volume=100, avg_cost=10.0)
        self.assertAlmostEqual(pos.get_market_value(), 1000.0, places=4)


class BrokerFeeTest(unittest.TestCase):
    """Tests for Broker fee defaults."""

    def test_default_stamp_duty_rate(self):
        """Default stamp_duty_rate should be 0.0005 (A-share sell-side)."""
        broker = Broker()
        self.assertAlmostEqual(broker.stamp_duty_rate, 0.0005, places=6)

    def test_custom_stamp_duty_rate(self):
        broker = Broker(stamp_duty_rate=0.001)
        self.assertAlmostEqual(broker.stamp_duty_rate, 0.001, places=6)

    def test_stamp_duty_only_on_sell(self):
        """Stamp duty should only apply to sell orders."""
        broker = Broker(initial_capital=10000000, stamp_duty_rate=0.0005)

        # Buy should not incur stamp duty
        order = broker.submit_order("000001.SZ", OrderSide.BUY, 100, trade_date=datetime(2025, 1, 2))
        self.assertEqual(order.status, OrderStatus.PENDING)

        market_data = {
            "000001.SZ": {"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "pre_close": 10.0}
        }
        broker.match_orders(datetime(2025, 1, 2), market_data)

        buy_trade = broker.trade_history[-1]
        self.assertAlmostEqual(buy_trade["stamp_duty"], 0.0, places=4)

        # Sell should incur stamp duty
        order = broker.submit_order("000001.SZ", OrderSide.SELL, 100, trade_date=datetime(2025, 1, 3))
        market_data = {
            "000001.SZ": {"open": 10.5, "high": 11.0, "low": 10.0, "close": 10.5, "pre_close": 10.0}
        }
        broker.match_orders(datetime(2025, 1, 3), market_data)

        sell_trade = broker.trade_history[-1]
        self.assertGreater(sell_trade["stamp_duty"], 0.0)

    def test_default_commission_rate(self):
        broker = Broker()
        self.assertAlmostEqual(broker.commission_rate, 0.0003, places=6)


class BrokerT1Test(unittest.TestCase):
    """Tests for T+1 trading restriction."""

    def test_cannot_sell_same_day(self):
        broker = Broker(initial_capital=10000000)
        # Buy on day 1
        broker.submit_order("000001.SZ", OrderSide.BUY, 100, trade_date=datetime(2025, 1, 2))
        market_data = {
            "000001.SZ": {"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "pre_close": 10.0}
        }
        broker.match_orders(datetime(2025, 1, 2), market_data)

        # Try to sell on same day — should be rejected
        order = broker.submit_order("000001.SZ", OrderSide.SELL, 100, trade_date=datetime(2025, 1, 2))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("T+1", order.reject_reason)

    def test_can_sell_next_day(self):
        broker = Broker(initial_capital=10000000)
        # Buy on day 1
        broker.submit_order("000001.SZ", OrderSide.BUY, 100, trade_date=datetime(2025, 1, 2))
        market_data = {
            "000001.SZ": {"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "pre_close": 10.0}
        }
        broker.match_orders(datetime(2025, 1, 2), market_data)

        # Sell on day 2 — should succeed
        order = broker.submit_order("000001.SZ", OrderSide.SELL, 100, trade_date=datetime(2025, 1, 3))
        self.assertEqual(order.status, OrderStatus.PENDING)


class PriceLimitStatusTest(unittest.TestCase):
    """Tests for reusable price limit helpers."""

    def test_uses_explicit_up_down_limit_when_available(self):
        status = get_price_limit_status({
            "ts_code": "000001.SZ",
            "close": 10.52,
            "pre_close": 10.0,
            "up_limit": 10.52,
            "down_limit": 9.48,
        })

        self.assertTrue(status["is_limit_up"])
        self.assertFalse(status["is_limit_down"])
        self.assertAlmostEqual(status["up_limit"], 10.52)

    def test_falls_back_to_code_based_ratio(self):
        status = get_price_limit_status({
            "ts_code": "300001.SZ",
            "close": 12.0,
            "pre_close": 10.0,
        })

        self.assertTrue(status["is_limit_up"])
        self.assertAlmostEqual(status["limit_ratio"], 0.20)

    def test_accepts_st_override_for_legacy_five_percent_limit(self):
        status = get_price_limit_status({
            "ts_code": "600001.SH",
            "close": 9.5,
            "pre_close": 10.0,
            "is_st": True,
        })

        self.assertTrue(status["is_limit_down"])
        self.assertAlmostEqual(status["limit_ratio"], 0.05)


class AccountTotalValueTest(unittest.TestCase):
    def test_get_total_value(self):
        from backtest.broker import Account
        account = Account(initial_capital=1000000)
        account.get_position("000001.SZ").add(100, 10.0)
        total = account.get_total_value({"000001.SZ": 12.0})
        # Direct add() doesn't change cash, so cash stays at 1000000
        # position = 100 * 12 = 1200
        self.assertAlmostEqual(total, 1000000 + 1200, places=2)


if __name__ == "__main__":
    unittest.main()
