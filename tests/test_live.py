import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from trader.live import LiveLimits, LiveState, load_state, run_live_cycle, save_state


class FakeClient:
    def __init__(self):
        self.test_orders = 0
        self.live_buys = 0

    def account(self):
        return {"balances": [{"asset": "USDC", "free": "293", "locked": "0"}]}

    def test_market_buy(self, **_kwargs):
        self.test_orders += 1
        return {}

    def market_buy_by_quote(self, **_kwargs):
        self.live_buys += 1
        return {
            "executedQty": "0.00031675",
            "cummulativeQuoteQty": "25",
            "fills": [{"commissionAsset": "BTC", "commission": "0.00000031"}],
        }

    def ticker_price(self, _symbol):
        return Decimal("78922")


class LiveTradingTests(unittest.TestCase):
    def limits(self):
        return LiveLimits(Decimal("100"), Decimal("25"), Decimal("0.01"), Decimal("0.02"), Decimal("2"), 6, 1800)

    def test_absolute_cap_cannot_exceed_100(self):
        with patch.dict(os.environ, {"LIVE_CAP_USDC": "101"}, clear=False):
            with self.assertRaisesRegex(ValueError, "absolute 100"):
                LiveLimits.from_env()

    def test_dashboard_settings_use_same_hard_cap(self):
        settings = {"trade_cap_usdc": 100, "order_size_usdc": 20, "stop_loss_percent": 1.5, "take_profit_percent": 3, "max_daily_loss_usdc": 4}
        limits = LiveLimits.from_settings(settings)
        self.assertEqual(limits.capital_cap, Decimal("100"))
        self.assertEqual(limits.order_size, Decimal("20"))

    def test_no_signal_never_places_order(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            result = run_live_cycle(client, {"BTCUSDC": False}, Path(directory) / "state.json", self.limits())
        self.assertEqual(result, "no_signal")
        self.assertEqual(client.live_buys, 0)

    def test_signal_runs_test_then_one_live_buy_and_persists_net_quantity(self):
        client = FakeClient()
        reports = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            result = run_live_cycle(client, {"BTCUSDC": True}, path, self.limits(), reports.append)
            state = load_state(path)
        self.assertEqual(result, "bought:BTCUSDC:spent=25")
        self.assertEqual(client.test_orders, 1)
        self.assertEqual(client.live_buys, 1)
        self.assertEqual(state.position.quantity, "0.00031644")
        self.assertIsNone(state.pending_action)
        self.assertEqual(reports[0]["side"], "BUY")
        self.assertEqual(reports[0]["symbol"], "BTCUSDC")

    def test_pending_action_blocks_duplicate_order_after_restart(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, LiveState(day="2099-01-01", pending_action="BUY:BTCUSDC"))
            result = run_live_cycle(client, {"BTCUSDC": True}, path, self.limits())
        self.assertTrue(result.startswith("paused_pending_reconciliation"))
        self.assertEqual(client.live_buys, 0)


if __name__ == "__main__":
    unittest.main()
