import unittest
from decimal import Decimal

from trader.scalping import analyze_scalp


def kline(close: Decimal, volume: Decimal) -> list[object]:
    return [0, str(close), str(close), str(close), str(close), str(volume)]


def trend_series(count: int, start: str, up: str, pullback: str, volume: str = "100") -> list[list[object]]:
    price = Decimal(start)
    rows = []
    for index in range(count):
        price += Decimal(up) if index % 3 != 0 else Decimal(pullback)
        rows.append(kline(price, Decimal(volume)))
    return rows


class ScalpingTests(unittest.TestCase):
    def test_aggressive_scalp_detects_short_term_momentum(self):
        one_minute = trend_series(60, "100", "0.05", "-0.04")
        five_minute = trend_series(60, "100", "0.20", "-0.05")
        one_minute[-1][5] = "140"
        analysis = analyze_scalp({"1m": one_minute, "5m": five_minute}, aggressive=True)
        self.assertTrue(analysis.signal)
        self.assertGreaterEqual(analysis.score, 5)
        self.assertIn("1m_fast_trend", analysis.reasons)
        self.assertIn("5m_trend", analysis.reasons)

    def test_overextended_spike_is_vetoed(self):
        one_minute = []
        price = Decimal("100")
        for _ in range(60):
            price *= Decimal("1.01")
            one_minute.append(kline(price, Decimal("150")))
        five_minute = trend_series(60, "100", "0.20", "-0.05")
        analysis = analyze_scalp({"1m": one_minute, "5m": five_minute}, aggressive=True)
        self.assertFalse(analysis.signal)
        self.assertIn("scalp_overextended", analysis.reasons)

    def test_requires_both_short_timeframes(self):
        with self.assertRaisesRegex(ValueError, "1m and 5m"):
            analyze_scalp({"1m": trend_series(60, "100", "0.05", "-0.04")}, aggressive=True)


if __name__ == "__main__":
    unittest.main()
