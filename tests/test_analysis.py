import unittest
from decimal import Decimal

from trader.analysis import analyze_market, bullish_btc_regime


def candles(step: Decimal, *, count: int = 100, last_volume: Decimal = Decimal("150")):
    rows = []
    price = Decimal("100")
    for index in range(count):
        price += -step * Decimal("2") if index % 4 == 0 else step
        volume = last_volume if index == count - 1 else Decimal("100")
        rows.append([0, str(price - Decimal("0.2")), str(price + Decimal("0.5")), str(price - Decimal("0.5")), str(price), str(volume)])
    return rows


def straight_candles(step: Decimal, *, count: int = 100):
    rows = []
    price = Decimal("100")
    for _ in range(count):
        price += step
        rows.append([0, str(price), str(price + Decimal("0.5")), str(price - Decimal("0.5")), str(price), "150"])
    return rows


class AnalysisTests(unittest.TestCase):
    def test_aligned_trend_with_volume_produces_signal(self):
        frames = {"15m": candles(Decimal("0.10")), "1h": candles(Decimal("0.08")), "4h": candles(Decimal("0.06"))}
        result = analyze_market(frames)
        self.assertTrue(result.signal)
        self.assertGreaterEqual(result.score, 7)

    def test_extreme_rsi_vetoes_overheated_market(self):
        frames = {"15m": straight_candles(Decimal("1")), "1h": straight_candles(Decimal("1")), "4h": straight_candles(Decimal("1"))}
        result = analyze_market(frames)
        self.assertFalse(result.signal)
        self.assertIn("risk_veto", result.reasons)

    def test_btc_regime_requires_both_timeframes(self):
        frames = {"1h": candles(Decimal("0.08")), "4h": candles(Decimal("-0.05"))}
        self.assertFalse(bullish_btc_regime(frames))


if __name__ == "__main__":
    unittest.main()
