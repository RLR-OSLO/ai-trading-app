from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence


@dataclass(frozen=True)
class ScalpAnalysis:
    signal: bool
    score: int
    confidence: Decimal
    rsi_1m: Decimal
    volume_ratio_1m: Decimal
    momentum_3m_percent: Decimal
    reasons: tuple[str, ...]


def _series(klines: Sequence[Sequence[object]], column: int) -> list[Decimal]:
    return [Decimal(str(row[column])) for row in klines]


def _ema(values: Sequence[Decimal], period: int) -> Decimal:
    if len(values) < period:
        raise ValueError(f"Need at least {period} values")
    multiplier = Decimal("2") / Decimal(period + 1)
    value = sum(values[:period], Decimal("0")) / Decimal(period)
    for item in values[period:]:
        value = (item - value) * multiplier + value
    return value


def _ema_rising(values: Sequence[Decimal], period: int) -> bool:
    return _ema(values, period) > _ema(values[:-1], period)


def _rsi(values: Sequence[Decimal], period: int = 14) -> Decimal:
    if len(values) < period + 1:
        raise ValueError("Not enough values for RSI")
    changes = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = sum((max(change, Decimal("0")) for change in changes), Decimal("0")) / Decimal(period)
    losses = sum((max(-change, Decimal("0")) for change in changes), Decimal("0")) / Decimal(period)
    if losses == 0:
        return Decimal("100")
    rs = gains / losses
    return Decimal("100") - Decimal("100") / (Decimal("1") + rs)


def analyze_scalp(timeframes: dict[str, Sequence[Sequence[object]]], *, aggressive: bool = False) -> ScalpAnalysis:
    required = {"1m", "5m"}
    if not required.issubset(timeframes):
        raise ValueError("1m and 5m data are required")

    closes_1m = _series(timeframes["1m"], 4)
    closes_5m = _series(timeframes["5m"], 4)
    volumes_1m = _series(timeframes["1m"], 5)
    if len(closes_1m) < 30 or len(closes_5m) < 30:
        raise ValueError("Scalping requires at least 30 closed candles per timeframe")

    score = 0
    reasons: list[str] = []

    if _ema(closes_1m, 5) > _ema(closes_1m, 13) and _ema_rising(closes_1m, 5):
        score += 2
        reasons.append("1m_fast_trend")

    if _ema(closes_5m, 8) > _ema(closes_5m, 21) and _ema_rising(closes_5m, 8):
        score += 2
        reasons.append("5m_trend")

    rsi = _rsi(closes_1m)
    if Decimal("50") <= rsi <= Decimal("72"):
        score += 1
        reasons.append("1m_rsi_window")

    baseline_volume = sum(volumes_1m[-21:-1], Decimal("0")) / Decimal("20")
    volume_ratio = volumes_1m[-1] / baseline_volume if baseline_volume > 0 else Decimal("0")
    if volume_ratio >= (Decimal("1.10") if aggressive else Decimal("1.15")):
        score += 1
        reasons.append("1m_volume_burst")

    three_min_ago = closes_1m[-4]
    momentum = ((closes_1m[-1] / three_min_ago) - Decimal("1")) * Decimal("100") if three_min_ago > 0 else Decimal("0")
    if momentum >= (Decimal("0.12") if aggressive else Decimal("0.15")):
        score += 1
        reasons.append("3m_momentum")

    recent_high = max(closes_1m[-11:-1])
    if closes_1m[-1] > recent_high:
        score += 1
        reasons.append("10m_breakout")

    overextended = rsi >= Decimal("82") or momentum >= Decimal("2.5")
    falling = _ema(closes_1m, 5) < _ema(closes_1m, 13) and not _ema_rising(closes_1m, 5)
    veto = overextended or falling
    if overextended:
        reasons.append("scalp_overextended")
    if falling:
        reasons.append("scalp_falling")

    threshold = 6
    trend_confirmed = "5m_trend" in reasons
    momentum_confirmed = any(reason in reasons for reason in ("1m_volume_burst", "3m_momentum", "10m_breakout"))
    confidence = min(Decimal("1"), Decimal(score) / Decimal("8"))
    return ScalpAnalysis(
        not veto and trend_confirmed and momentum_confirmed and score >= threshold,
        score, confidence, rsi, volume_ratio, momentum, tuple(reasons)
    )
