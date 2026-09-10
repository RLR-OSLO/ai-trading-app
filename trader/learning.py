from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

MIN_CLOSED_TRADES = 4
MIN_FACTOR = Decimal("0.70")
MAX_FACTOR = Decimal("1.15")


def learning_factors(trades: list[dict[str, Any]]) -> dict[tuple[str, str], Decimal]:
    """Return bounded performance factors by (symbol, mode).

    Only closed trades with realized PnL are used. The factor can reduce or modestly
    increase position sizing, but never changes hard risk caps, stop loss, leverage,
    allowed markets, or live-trading locks.
    """
    buckets: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for trade in trades:
        pnl = trade.get("pnl")
        symbol = str(trade.get("symbol") or "")
        mode = str(trade.get("mode") or "")
        if not symbol or not mode or pnl is None:
            continue
        try:
            buckets[(symbol, mode)].append(Decimal(str(pnl)))
        except Exception:
            continue

    factors: dict[tuple[str, str], Decimal] = {}
    for key, pnls in buckets.items():
        recent = pnls[-50:]
        if len(recent) < MIN_CLOSED_TRADES:
            factors[key] = Decimal("1")
            continue
        wins = sum(1 for pnl in recent if pnl > 0)
        losses = sum(1 for pnl in recent if pnl < 0)
        gross_win = sum((pnl for pnl in recent if pnl > 0), Decimal("0"))
        gross_loss = -sum((pnl for pnl in recent if pnl < 0), Decimal("0"))
        win_rate = Decimal(wins) / Decimal(len(recent))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else Decimal("2") if gross_win > 0 else Decimal("1")

        # Conservative adaptation: bad history cuts size faster than good history grows it.
        factor = Decimal("1")
        if win_rate < Decimal("0.35") or profit_factor < Decimal("0.70"):
            factor = Decimal("0.70")
        elif win_rate < Decimal("0.45") or profit_factor < Decimal("0.90"):
            factor = Decimal("0.85")
        elif win_rate >= Decimal("0.60") and profit_factor >= Decimal("1.35"):
            factor = Decimal("1.15")
        elif win_rate >= Decimal("0.52") and profit_factor >= Decimal("1.10"):
            factor = Decimal("1.07")
        factors[key] = max(MIN_FACTOR, min(MAX_FACTOR, factor))
    return factors


def factor_for(factors: dict[tuple[str, str], Decimal], symbol: str, mode: str) -> Decimal:
    return factors.get((symbol, mode), Decimal("1"))
