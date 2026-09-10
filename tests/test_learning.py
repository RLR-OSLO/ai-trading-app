from decimal import Decimal

from trader.learning import learning_factors


def test_learning_waits_for_enough_closed_trades():
    trades = [{"symbol": "BTCUSDC", "mode": "live", "pnl": "1"} for _ in range(3)]
    assert learning_factors(trades)[("BTCUSDC", "live")] == Decimal("1")


def test_learning_reduces_size_after_poor_history():
    trades = [{"symbol": "ETHUSDC", "mode": "futures", "pnl": "-1"} for _ in range(5)]
    assert learning_factors(trades)[("ETHUSDC", "futures")] == Decimal("0.70")


def test_learning_only_modestly_increases_size_after_strong_history():
    trades = [{"symbol": "SOLUSDC", "mode": "futures", "pnl": "1"} for _ in range(6)]
    assert learning_factors(trades)[("SOLUSDC", "futures")] == Decimal("1.15")
