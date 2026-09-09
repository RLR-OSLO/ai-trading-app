import unittest
from decimal import Decimal

from trader.analysis import MarketAnalysis
from trader.scalping import ScalpAnalysis
from trader.worker import bullrun_candidate, bullrun_profile, ticker_is_liquid


class MarketBrainV2Tests(unittest.TestCase):
    def test_liquidity_gate_requires_volume_trades_and_tight_spread(self):
        good = {"quoteVolume": "50000000", "count": 50000, "bidPrice": "100", "askPrice": "100.10"}
        thin = {"quoteVolume": "1000000", "count": 500, "bidPrice": "100", "askPrice": "101"}
        self.assertTrue(ticker_is_liquid(good))
        self.assertFalse(ticker_is_liquid(thin))

    def test_bullrun_requires_multitimeframe_strength_and_volume(self):
        analysis = MarketAnalysis(True, 8, Decimal("0.88"), Decimal("62"), Decimal("1.4"), Decimal("1.6"), ("15m_trend","1h_trend","4h_trend","volume_confirmation"))
        scalp = ScalpAnalysis(True, 6, Decimal("0.01"), Decimal("0.02"), Decimal("1.4"), ("1m_fast_trend",))
        self.assertTrue(bullrun_candidate(analysis, scalp, "high"))
        weak = MarketAnalysis(True, 8, Decimal("0.88"), Decimal("62"), Decimal("1.4"), Decimal("1.0"), ("15m_trend",))
        self.assertFalse(bullrun_candidate(weak, scalp, "high"))

    def test_bullrun_profile_is_wider_but_bounded(self):
        analysis = MarketAnalysis(True, 8, Decimal("0.88"), Decimal("62"), Decimal("1.5"), Decimal("1.6"), ())
        stop, activation, multiplier = bullrun_profile(analysis, "1.5", "high")
        self.assertEqual(stop, Decimal("0.0225"))
        self.assertEqual(activation, Decimal("0.028125"))
        self.assertEqual(multiplier, Decimal("1.50"))


if __name__ == "__main__":
    unittest.main()
