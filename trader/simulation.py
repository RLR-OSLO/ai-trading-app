"""Deterministic paper-trading helpers used before any live order is allowed."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .config import TradingConfig
from .risk import position_notional_for_stop


@dataclass(frozen=True)
class SimulationTrade:
    entry_price: Decimal
    exit_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    notional: Decimal
    quantity: Decimal
    pnl_after_fees: Decimal
    exit_reason: str


def bullish_momentum(closes: Sequence[Decimal], fast: int = 8, slow: int = 21) -> bool:
    """Return true only when the fast and slow moving averages are rising."""
    if fast <= 1 or slow <= fast or len(closes) < slow + 1:
        raise ValueError("Not enough closes for the requested moving averages")
    fast_now = sum(closes[-fast:], Decimal("0")) / Decimal(fast)
    fast_prev = sum(closes[-fast - 1:-1], Decimal("0")) / Decimal(fast)
    slow_now = sum(closes[-slow:], Decimal("0")) / Decimal(slow)
    slow_prev = sum(closes[-slow - 1:-1], Decimal("0")) / Decimal(slow)
    return fast_now > slow_now and fast_now > fast_prev and slow_now >= slow_prev


def simulate_long_trade(
    prices: Sequence[Decimal],
    equity: Decimal,
    config: TradingConfig,
    *,
    stop_fraction: Decimal = Decimal("0.01"),
    target_multiple: Decimal = Decimal("2"),
    fee_rate: Decimal = Decimal("0.001"),
) -> SimulationTrade:
    """Simulate one long trade against sequential close prices."""
    if len(prices) < 2 or any(price <= 0 for price in prices):
        raise ValueError("At least two positive prices are required")
    if not (Decimal("0") < stop_fraction < Decimal("1")):
        raise ValueError("stop_fraction must be between zero and one")
    if target_multiple <= 0 or fee_rate < 0:
        raise ValueError("target_multiple must be positive and fee_rate non-negative")

    entry = prices[0]
    stop = entry * (Decimal("1") - stop_fraction)
    risk_distance = entry - stop
    target = entry + risk_distance * target_multiple
    notional = position_notional_for_stop(equity, entry, stop, config)
    quantity = notional / entry

    exit_price = prices[-1]
    reason = "end_of_sample"
    for price in prices[1:]:
        if price <= stop:
            exit_price, reason = stop, "stop_loss"
            break
        if price >= target:
            exit_price, reason = target, "take_profit"
            break

    gross = (exit_price - entry) * quantity
    fees = (entry * quantity + exit_price * quantity) * fee_rate
    return SimulationTrade(
        entry_price=entry,
        exit_price=exit_price,
        stop_price=stop,
        target_price=target,
        notional=notional,
        quantity=quantity,
        pnl_after_fees=gross - fees,
        exit_reason=reason,
    )
