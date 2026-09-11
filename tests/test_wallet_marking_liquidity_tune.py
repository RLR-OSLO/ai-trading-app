import unittest
from trader.worker import ACTIVE_MARKET_COUNT, ticker_is_liquid

class WalletMarkingLiquidityTuneTests(unittest.TestCase):
    def test_daytrader_liquidity_floor_accepts_meaningfully_liquid_market(self):
        item = {"quoteVolume": "8000000", "count": 9000, "bidPrice": "100", "askPrice": "100.10"}
        self.assertTrue(ticker_is_liquid(item))
        self.assertEqual(ACTIVE_MARKET_COUNT, 5)
    def test_rejects_low_transaction_count(self):
        item = {"quoteVolume": "8000000", "count": 1000, "bidPrice": "100", "askPrice": "100.10"}
        self.assertFalse(ticker_is_liquid(item))
