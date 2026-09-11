import json
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal
from pathlib import Path

from trader.portfolio_live import PortfolioLimits, load_state, run_portfolio_cycle, save_state


class FakeClient:
    def __init__(self):
        self.live_buys = 0
        self.oco_orders = 0
        self.cancelled_oco = 0
        self.live_sells = 0
        self.price = Decimal("100")
        self.last_oco_kwargs = None

    def account(self):
        return {"balances": [
            {"asset": "USDC", "free": "200", "locked": "0"},
            {"asset": "BTC", "free": "0.25", "locked": "0"},
            {"asset": "ETH", "free": "0.25", "locked": "0"},
        ]}

    def test_market_buy(self, **_kwargs):
        return {}

    def market_buy_by_quote(self, **_kwargs):
        self.live_buys += 1
        return {"executedQty": "0.25", "cummulativeQuoteQty": "25", "fills": []}

    def ticker_price(self, _symbol):
        return self.price

    def symbol_info(self, _symbol):
        return {"filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00000001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        ]}

    def place_protective_oco_sell(self, **kwargs):
        self.oco_orders += 1
        self.last_oco_kwargs = kwargs
        base = 1000 + self.oco_orders * 10
        return {"orderListId": self.oco_orders, "orders": [{"orderId": base + 1}, {"orderId": base + 2}]}

    def query_order_list(self, **_kwargs):
        return {"listOrderStatus": "EXECUTING", "orders": []}

    def query_order_by_id(self, **_kwargs):
        return {"status": "NEW", "executedQty": "0", "cummulativeQuoteQty": "0"}

    def cancel_order_list(self, **_kwargs):
        self.cancelled_oco += 1
        return {"orderListId": 1, "listOrderStatus": "ALL_DONE"}

    def place_spot_order(self, **_kwargs):
        self.live_sells += 1
        return {"cummulativeQuoteQty": "25.10"}


class PortfolioLiveTests(unittest.TestCase):
    def setUp(self):
        self._protection = patch.dict("os.environ", {"EXCHANGE_PROTECTION_ENABLED": "true"})
        self._protection.start()

    def tearDown(self):
        self._protection.stop()

    def limits(self):
        return PortfolioLimits.from_values("200", "25", "1", "2", "5", max_trades=80, cooldown=15, max_positions=5)

    def test_migrates_legacy_single_position_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({
                "day": "2099-01-01",
                "realized_pnl": "0",
                "trades_today": 1,
                "cooldown_until": 0,
                "position": {"symbol": "BNBUSDC", "quantity": "0.1", "entry_price": "700", "quote_spent": "70", "opened_at": 1, "protective_order_list_id": 77, "protective_order_ids": [1, 2]},
            }), encoding="utf-8")
            state = load_state(path)
        self.assertEqual(len(state.positions), 1)
        self.assertEqual(state.positions[0].symbol, "BNBUSDC")
        self.assertEqual(state.positions[0].strategy, "swing")
        self.assertEqual(state.positions[0].protective_order_list_id, 77)
        self.assertFalse(state.positions[0].trailing_active)

    def test_can_hold_multiple_symbols_at_once(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            first = run_portfolio_cycle(client, {"BTCUSDC": True, "ETHUSDC": True}, path, self.limits())
            state = load_state(path)
            state.cooldown_until = 0
            save_state(path, state)
            second = run_portfolio_cycle(client, {"BTCUSDC": True, "ETHUSDC": True}, path, self.limits())
            final = load_state(path)
        self.assertTrue(first.startswith("bought:BTCUSDC"))
        self.assertTrue(second.startswith("bought:ETHUSDC"))
        self.assertEqual({p.symbol for p in final.positions}, {"BTCUSDC", "ETHUSDC"})
        self.assertEqual(client.live_buys, 2)
        self.assertEqual(client.oco_orders, 2)

    def test_scalp_entry_gets_tight_limits_and_timebox(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            result = run_portfolio_cycle(
                client,
                {"BTCUSDC": True},
                path,
                self.limits(),
                entry_strategies={"BTCUSDC": "scalp"},
            )
            state = load_state(path)
        position = state.positions[0]
        self.assertIn("strategy=scalp", result)
        self.assertEqual(position.strategy, "scalp")
        self.assertEqual(position.stop_fraction, "0.0060")
        self.assertEqual(position.target_fraction, "0.0080")
        self.assertEqual(position.max_hold_seconds, 2700)
        self.assertEqual(client.oco_orders, 1)

    def test_target_becomes_trailing_activation_and_profit_can_run(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            run_portfolio_cycle(client, {"BTCUSDC": True}, path, self.limits())
            self.assertEqual(client.last_oco_kwargs["target_price"], Decimal("150.00"))
            state = load_state(path)
            state.cooldown_until = 0
            save_state(path, state)
            client.price = Decimal("110")
            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())
            state = load_state(path)
        position = state.positions[0]
        self.assertIn("trailing_active:BTCUSDC", result)
        self.assertTrue(position.trailing_active)
        self.assertEqual(Decimal(position.peak_price), Decimal("110"))
        self.assertEqual(Decimal(position.trailing_stop_price), Decimal("109.5050"))
        self.assertEqual(client.cancelled_oco, 1)
        self.assertEqual(client.oco_orders, 2)
        self.assertEqual(client.live_sells, 0)

    def test_trailing_stop_rises_with_new_high(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            run_portfolio_cycle(client, {"BTCUSDC": True}, path, self.limits())
            state = load_state(path)
            state.cooldown_until = 0
            save_state(path, state)
            client.price = Decimal("103")
            run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())
            client.price = Decimal("110")
            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())
            state = load_state(path)
        position = state.positions[0]
        self.assertIn("trailing_raise:BTCUSDC", result)
        self.assertEqual(Decimal(position.peak_price), Decimal("110"))
        self.assertEqual(Decimal(position.trailing_stop_price), Decimal("109.5050"))
        self.assertGreaterEqual(client.cancelled_oco, 2)

    def test_expired_scalp_only_time_exits_when_profitable(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            run_portfolio_cycle(
                client,
                {"BTCUSDC": True},
                path,
                self.limits(),
                entry_strategies={"BTCUSDC": "scalp"},
            )
            state = load_state(path)
            state.positions[0].opened_at = int(__import__("time").time()) - 2800
            state.cooldown_until = 0
            save_state(path, state)
            client.price = Decimal("100.45")
            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())
        self.assertIn("reason=timeout_profit", result)
        self.assertEqual(client.cancelled_oco, 1)
        self.assertEqual(client.live_sells, 1)

    def test_expired_scalp_does_not_force_sell_material_loss(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            run_portfolio_cycle(
                client,
                {"BTCUSDC": True},
                path,
                self.limits(),
                entry_strategies={"BTCUSDC": "scalp"},
            )
            state = load_state(path)
            state.positions[0].opened_at = int(__import__("time").time()) - 5600
            state.cooldown_until = 0
            save_state(path, state)
            client.price = Decimal("99.50")
            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())
            final = load_state(path)
        self.assertEqual(client.live_sells, 0)
        self.assertEqual(len(final.positions), 1)
        self.assertIn("holding:BTCUSDC", result)

    def test_expired_scalp_can_exit_small_loss_after_signal_disappears(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            run_portfolio_cycle(
                client,
                {"BTCUSDC": True},
                path,
                self.limits(),
                entry_strategies={"BTCUSDC": "scalp"},
            )
            state = load_state(path)
            state.positions[0].opened_at = int(__import__("time").time()) - 5600
            state.cooldown_until = 0
            save_state(path, state)
            client.price = Decimal("99.80")
            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())
        self.assertIn("reason=signal_timeout", result)
        self.assertEqual(client.live_sells, 1)

    def test_high_profile_is_aggressive_but_bounded(self):
        limits = PortfolioLimits.from_settings({
            "risk_profile": "high",
            "trade_cap_usdc": "200",
            "order_size_usdc": "25",
            "stop_loss_percent": "1",
            "take_profit_percent": "2",
            "max_daily_loss_usdc": "5",
        })
        self.assertEqual(limits.max_open_positions, 3)
        self.assertEqual(limits.cooldown_seconds, 90)
        self.assertEqual(limits.max_trades_per_day, 36)


if __name__ == "__main__":
    unittest.main()
