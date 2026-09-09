import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from trader.portfolio_live import Position, PortfolioState, _cancel_protection, save_state
from trader.binance import BinanceError

class FakeClient:
    def __init__(self):
        self.cancelled=[]
    def cancel_order_list(self, **kwargs):
        raise BinanceError("stale order list")
    def open_orders(self, *, symbol):
        if self.cancelled:
            return []
        return [{"symbol":symbol,"orderId":11,"orderListId":99,"clientOrderId":"ait-oco-x"}]
    def cancel_order(self, *, symbol, order_id):
        self.cancelled.append(order_id)
        return {}

class FailsafeTests(unittest.TestCase):
    def test_fallback_cancels_bot_order_when_list_cancel_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"state.json"
            pos=Position("DOTUSDC","10","1.2","12",1,protective_order_list_id=99,protective_order_ids=(11,))
            state=PortfolioState(day="2099-01-01",positions=[pos])
            save_state(path,state)
            client=FakeClient()
            self.assertTrue(_cancel_protection(client,state,path,pos))
            self.assertEqual(client.cancelled,[11])
            self.assertIsNone(pos.protective_order_list_id)

if __name__ == "__main__":
    unittest.main()
