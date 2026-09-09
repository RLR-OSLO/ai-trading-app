from pathlib import Path

p=Path('trader/portfolio_live.py')
s=p.read_text()
s=s.replace('return os.getenv("EXCHANGE_PROTECTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}', 'return os.getenv("EXCHANGE_PROTECTION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}')
old='''    for position in list(state.positions or []):\n        expired_scalp = position.strategy == "scalp" and position.max_hold_seconds is not None and now - position.opened_at >= position.max_hold_seconds\n'''
new='''    for position in list(state.positions or []):\n        if not _protection_enabled() and (position.protective_order_list_id is not None or position.protective_order_ids):\n            if not _cancel_protection(client, state, state_path, position):\n                notes.append(f"local_stop_release_failed:{position.symbol}")\n                continue\n            notes.append(f"local_stop_protection_removed:{position.symbol}")\n\n        expired_scalp = position.strategy == "scalp" and position.max_hold_seconds is not None and now - position.opened_at >= position.max_hold_seconds\n'''
if old not in s: raise SystemExit('loop anchor missing')
s=s.replace(old,new,1)
old='''    free_balance = _free_balance(client, base_asset)\n    quantity = _sellable_quantity(client, position.symbol, min(Decimal(position.quantity), free_balance))\n    if quantity <= 0:\n        return f"unsellable:{position.symbol}:free={free_balance}"\n'''
new='''    account = client.account()\n    free_balance = Decimal("0")\n    total_balance = Decimal("0")\n    for row in account.get("balances", []):\n        if row.get("asset") == base_asset:\n            free_balance = Decimal(str(row.get("free", "0")))\n            total_balance = free_balance + Decimal(str(row.get("locked", "0")))\n            break\n    quantity = _sellable_quantity(client, position.symbol, min(Decimal(position.quantity), free_balance))\n    if quantity <= 0:\n        total_sellable = _sellable_quantity(client, position.symbol, min(Decimal(position.quantity), total_balance))\n        if total_sellable <= 0:\n            _remove(state, position.symbol)\n            save_state(state_path, state)\n            return f"stale_removed:{position.symbol}:free={free_balance}:total={total_balance}"\n        return f"unsellable_locked:{position.symbol}:free={free_balance}:total={total_balance}"\n'''
if old not in s: raise SystemExit('sell block missing')
s=s.replace(old,new,1)
p.write_text(s)

# ensure old tests expecting OCO explicitly opt in
p=Path('tests/test_portfolio_live.py')
t=p.read_text()
t=t.replace('import unittest\n', 'import unittest\nfrom unittest.mock import patch\n')
# wrap class with env patch setup/teardown
needle='''class PortfolioLiveTests(unittest.TestCase):\n    def limits(self):\n'''
rep='''class PortfolioLiveTests(unittest.TestCase):\n    def setUp(self):\n        self._protection = patch.dict("os.environ", {"EXCHANGE_PROTECTION_ENABLED": "true"})\n        self._protection.start()\n\n    def tearDown(self):\n        self._protection.stop()\n\n    def limits(self):\n'''
if needle not in t: raise SystemExit('test class anchor missing')
t=t.replace(needle,rep,1)
p.write_text(t)

Path('tests/test_local_stoploss.py').write_text('''import json\nimport os\nimport tempfile\nimport unittest\nfrom decimal import Decimal\nfrom pathlib import Path\nfrom unittest.mock import patch\nfrom trader.portfolio_live import PortfolioLimits, PortfolioState, Position, run_portfolio_cycle, save_state, load_state\n\nclass C:\n    def __init__(self): self.price=Decimal("90"); self.sells=0; self.cancelled=0\n    def account(self): return {"balances":[{"asset":"DOT","free":"10","locked":"0"},{"asset":"USDC","free":"100","locked":"0"}]}\n    def ticker_price(self,s): return self.price\n    def symbol_info(self,s): return {"filters":[{"filterType":"LOT_SIZE","stepSize":"0.01"},{"filterType":"PRICE_FILTER","tickSize":"0.01"}]}\n    def place_spot_order(self,**k): self.sells+=1; return {"cummulativeQuoteQty":"900"}\n    def cancel_order_list(self,**k): self.cancelled+=1; return {}\n    def open_orders(self,**k): return []\n\nclass LocalStopTests(unittest.TestCase):\n    def test_local_stop_sells_without_installing_oco(self):\n        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{"EXCHANGE_PROTECTION_ENABLED":"false"}):\n            path=Path(d)/"s.json"\n            pos=Position("DOTUSDC","10","100","1000",1)\n            save_state(path,PortfolioState(day="2099-01-01",positions=[pos]))\n            c=C(); lim=PortfolioLimits.from_values("100","10","1.5","3","5",max_trades=80,cooldown=15,max_positions=5)\n            r=run_portfolio_cycle(c,{"DOTUSDC":False},path,lim)\n            self.assertIn("reason=hard_stop",r); self.assertEqual(c.sells,1); self.assertEqual(load_state(path).positions,[])\n\nif __name__=="__main__": unittest.main()\n''')

Path('scripts/apply_local_stoploss.py').unlink(missing_ok=True)
Path('.github/workflows/apply-local-stoploss.yml').unlink(missing_ok=True)
