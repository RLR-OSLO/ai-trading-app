import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from trader.portfolio_live import PortfolioLimits, PortfolioState, Position, run_portfolio_cycle, save_state, load_state

class C:
    def __init__(self): self.price=Decimal("90"); self.sells=0; self.cancelled=0
    def account(self): return {"balances":[{"asset":"DOT","free":"10","locked":"0"},{"asset":"USDC","free":"100","locked":"0"}]}
    def ticker_price(self,s): return self.price
    def symbol_info(self,s): return {"filters":[{"filterType":"LOT_SIZE","stepSize":"0.01"},{"filterType":"PRICE_FILTER","tickSize":"0.01"}]}
    def place_spot_order(self,**k): self.sells+=1; return {"cummulativeQuoteQty":"900"}
    def cancel_order_list(self,**k): self.cancelled+=1; return {}
    def open_orders(self,**k): return []

class LocalStopTests(unittest.TestCase):
    def test_local_stop_sells_without_installing_oco(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{"EXCHANGE_PROTECTION_ENABLED":"false"}):
            path=Path(d)/"s.json"
            pos=Position("DOTUSDC","10","100","1000",1)
            save_state(path,PortfolioState(day="2099-01-01",positions=[pos]))
            c=C(); lim=PortfolioLimits.from_values("100","10","1.5","3","5",max_trades=80,cooldown=15,max_positions=5)
            r=run_portfolio_cycle(c,{"DOTUSDC":False},path,lim)
            self.assertIn("reason=hard_stop",r); self.assertEqual(c.sells,1); self.assertEqual(load_state(path).positions,[])

if __name__=="__main__": unittest.main()
