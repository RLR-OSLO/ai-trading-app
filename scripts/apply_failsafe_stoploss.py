from pathlib import Path

binance = Path('trader/binance.py')
text = binance.read_text()
anchor = '''    def cancel_order_list(self, *, symbol: str, order_list_id: int) -> dict[str, Any]:\n        return self._request(\n            "DELETE",\n            "/api/v3/orderList",\n            {"symbol": symbol, "orderListId": order_list_id},\n            signed=True,\n        )\n'''
addition = anchor + '''\n    def cancel_order(self, *, symbol: str, order_id: int) -> dict[str, Any]:\n        return self._request(\n            "DELETE",\n            "/api/v3/order",\n            {"symbol": symbol, "orderId": order_id},\n            signed=True,\n        )\n'''
if anchor not in text:
    raise SystemExit('cancel_order_list anchor not found')
text = text.replace(anchor, addition, 1)
binance.write_text(text)

portfolio = Path('trader/portfolio_live.py')
text = portfolio.read_text()
old_cancel = '''def _cancel_protection(client, state, path, position: Position) -> bool:\n    if position.protective_order_list_id is None:\n        return True\n    try:\n        client.cancel_order_list(symbol=position.symbol, order_list_id=position.protective_order_list_id)\n    except BinanceError:\n        return False\n    position.protective_order_list_id = None\n    position.protective_order_ids = ()\n    save_state(path, state)\n    return True\n'''
new_cancel = '''def _cancel_protection(client, state, path, position: Position) -> bool:\n    if position.protective_order_list_id is None and not position.protective_order_ids:\n        return True\n    cancelled = False\n    if position.protective_order_list_id is not None:\n        try:\n            client.cancel_order_list(symbol=position.symbol, order_list_id=position.protective_order_list_id)\n            cancelled = True\n        except BinanceError:\n            pass\n    if not cancelled:\n        try:\n            open_orders = client.open_orders(symbol=position.symbol)\n        except BinanceError:\n            return False\n        bot_orders = [\n            order for order in open_orders\n            if str(order.get("clientOrderId") or "").startswith("ait-")\n            or int(order.get("orderId", -1)) in set(position.protective_order_ids)\n            or (position.protective_order_list_id is not None and int(order.get("orderListId", -1)) == position.protective_order_list_id)\n        ]\n        for order in bot_orders:\n            order_id = int(order.get("orderId", -1))\n            if order_id < 0:\n                continue\n            try:\n                client.cancel_order(symbol=position.symbol, order_id=order_id)\n                cancelled = True\n            except BinanceError:\n                continue\n        try:\n            still_open = client.open_orders(symbol=position.symbol)\n        except BinanceError:\n            return False\n        blocked_ids = set(position.protective_order_ids)\n        for order in still_open:\n            if (str(order.get("clientOrderId") or "").startswith("ait-")\n                or int(order.get("orderId", -1)) in blocked_ids\n                or (position.protective_order_list_id is not None and int(order.get("orderListId", -1)) == position.protective_order_list_id)):\n                return False\n    position.protective_order_list_id = None\n    position.protective_order_ids = ()\n    save_state(path, state)\n    return True\n'''
if old_cancel not in text:
    raise SystemExit('old cancel block not found')
text = text.replace(old_cancel, new_cancel, 1)
old_sell = '''def _market_sell(client, state, state_path, position, limits, report_trade, now: int, reason: str) -> str:\n    quantity = _sellable_quantity(client, position.symbol, Decimal(position.quantity))\n    if quantity <= 0:\n        return f"unsellable:{position.symbol}"\n'''
new_sell = '''def _market_sell(client, state, state_path, position, limits, report_trade, now: int, reason: str) -> str:\n    base_asset = position.symbol.removesuffix("USDC") if position.symbol.endswith("USDC") else position.symbol.removesuffix("USDT")\n    free_balance = _free_balance(client, base_asset)\n    quantity = _sellable_quantity(client, position.symbol, min(Decimal(position.quantity), free_balance))\n    if quantity <= 0:\n        return f"unsellable:{position.symbol}:free={free_balance}"\n'''
if old_sell not in text:
    raise SystemExit('market sell block not found')
text = text.replace(old_sell, new_sell, 1)
portfolio.write_text(text)

# Add focused regression tests.
test = Path('tests/test_failsafe_stoploss.py')
test.write_text('''import tempfile\nimport unittest\nfrom decimal import Decimal\nfrom pathlib import Path\nfrom trader.portfolio_live import Position, PortfolioState, _cancel_protection, save_state\nfrom trader.binance import BinanceError\n\nclass FakeClient:\n    def __init__(self):\n        self.cancelled=[]\n    def cancel_order_list(self, **kwargs):\n        raise BinanceError("stale order list")\n    def open_orders(self, *, symbol):\n        if self.cancelled:\n            return []\n        return [{"symbol":symbol,"orderId":11,"orderListId":99,"clientOrderId":"ait-oco-x"}]\n    def cancel_order(self, *, symbol, order_id):\n        self.cancelled.append(order_id)\n        return {}\n\nclass FailsafeTests(unittest.TestCase):\n    def test_fallback_cancels_bot_order_when_list_cancel_fails(self):\n        with tempfile.TemporaryDirectory() as d:\n            path=Path(d)/"state.json"\n            pos=Position("DOTUSDC","10","1.2","12",1,protective_order_list_id=99,protective_order_ids=(11,))\n            state=PortfolioState(day="2099-01-01",positions=[pos])\n            save_state(path,state)\n            client=FakeClient()\n            self.assertTrue(_cancel_protection(client,state,path,pos))\n            self.assertEqual(client.cancelled,[11])\n            self.assertIsNone(pos.protective_order_list_id)\n\nif __name__ == "__main__":\n    unittest.main()\n''')

Path('scripts/apply_failsafe_stoploss.py').unlink(missing_ok=True)
Path('.github/workflows/apply-failsafe-stoploss.yml').unlink(missing_ok=True)
