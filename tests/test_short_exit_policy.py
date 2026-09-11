from decimal import Decimal

from trader.derivatives_live import ShortPosition, _update_short_position


def make_position() -> ShortPosition:
    return ShortPosition(
        mode="margin",
        symbol="ETHUSDC",
        quantity="0.01",
        entry_price="100",
        notional="1",
        opened_at=1,
        stop_fraction="0.015",
        target_fraction="0.03",
        trough_price="100",
    )


def test_short_trailing_locks_profit_after_one_percent_move():
    position = make_position()
    assert _update_short_position(position, Decimal("99"), True) is None
    assert position.trailing_active is True
    assert Decimal(position.trailing_stop_price) < Decimal("100")
    assert _update_short_position(position, Decimal("99.8"), True) == "trailing_stop"


def test_short_signal_reversal_exits_only_when_profitable():
    position = make_position()
    assert _update_short_position(position, Decimal("100.2"), False) is None
    assert _update_short_position(position, Decimal("99.5"), False) == "signal_reversal"


def test_short_target_is_allowed_to_run_to_three_percent():
    position = make_position()
    assert _update_short_position(position, Decimal("97"), True) == "take_profit"
