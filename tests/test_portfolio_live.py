import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from trader.portfolio_live import PortfolioLimits, PortfolioState, load_state, run_portfolio_cycle, save_state


class FakeClient:
    def __init__(self):
        self.live_buys = 0
        self.oco_orders = 0
        self.price = Decimal("100")

    def account(self):
        return {"balances": [{"asset": "USDC", "free": "200", "locked": "0"}]}

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

    def place_protective_oco_sell(self, **_kwargs):
        self.oco_orders += 1
        base = 1000 + self.oco_orders * 10
        return {"orderListId": self.oco_orders, "orders": [{"orderId": base + 1}, {"orderId": base + 2}]}

    def query_order_list(self, **_kwargs):
        return {"listOrderStatus": "EXECUTING", "orders": []}

    def query_order_by_id(self, **_kwargs):
        return {"status": "NEW", "executedQty": "0", "cummulativeQuoteQty": "0"}


class PortfolioLiveTests(unittest.TestCase):
    def limits(self):
        return PortfolioLimits.from_values("200", "25", "1", "2", "5", max_trades=40, cooldown=15, max_positions=5)

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
        self.assertEqual(state.positions[0].protective_order_list_id, 77)

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

    def test_high_profile_is_aggressive_but_bounded(self):
        limits = PortfolioLimits.from_settings({
            "risk_profile": "high",
            "trade_cap_usdc": "200",
            "order_size_usdc": "25",
            "stop_loss_percent": "1",
            "take_profit_percent": "2",
            "max_daily_loss_usdc": "5",
        })
        self.assertEqual(limits.max_open_positions, 5)
        self.assertEqual(limits.cooldown_seconds, 30)
        self.assertEqual(limits.max_trades_per_day, 40)


if __name__ == "__main__":
    unittest.main()
