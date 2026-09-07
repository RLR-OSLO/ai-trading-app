import unittest
from decimal import Decimal

from trader.config import DEFAULT_CONFIG
from trader.simulation import bullish_momentum, paper_signal_from_klines, simulate_long_trade


class SimulationTests(unittest.TestCase):
    def test_take_profit_and_fees_are_applied(self) -> None:
        trade = simulate_long_trade(
            [Decimal("100"), Decimal("101"), Decimal("102")],
            Decimal("6000"),
            DEFAULT_CONFIG,
        )
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertEqual(trade.exit_price, Decimal("102"))
        self.assertLess(trade.pnl_after_fees, Decimal("48"))

    def test_stop_loss_is_respected(self) -> None:
        trade = simulate_long_trade(
            [Decimal("100"), Decimal("98")],
            Decimal("6000"),
            DEFAULT_CONFIG,
        )
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertLess(trade.pnl_after_fees, Decimal("0"))

    def test_bullish_momentum_requires_enough_data(self) -> None:
        with self.assertRaises(ValueError):
            bullish_momentum([Decimal("1")] * 21)

    def test_paper_signal_reads_kline_close_column(self) -> None:
        rows = [[0, "0", "0", "0", str(100 + i)] for i in range(22)]
        self.assertTrue(paper_signal_from_klines(rows))


if __name__ == "__main__":
    unittest.main()
