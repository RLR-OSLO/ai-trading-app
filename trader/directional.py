from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence


@dataclass(frozen=True)
class BearishAnalysis:
    signal: bool
    score: int
    confidence: Decimal
    rsi_1h: Decimal
    atr_percent_1h: Decimal
    volume_ratio_15m: Decimal
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


def _ema_falling(values: Sequence[Decimal], period: int) -> bool:
    return _ema(values, period) < _ema(values[:-1], period)


def _rsi(values: Sequence[Decimal], period: int = 14) -> Decimal:
    changes = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = sum((max(change, Decimal("0")) for change in changes), Decimal("0")) / Decimal(period)
    losses = sum((max(-change, Decimal("0")) for change in changes), Decimal("0")) / Decimal(period)
    if losses == 0:
        return Decimal("100")
    rs = gains / losses
    return Decimal("100") - Decimal("100") / (Decimal("1") + rs)


def _atr_percent(klines: Sequence[Sequence[object]], period: int = 14) -> Decimal:
    ranges: list[Decimal] = []
    for index in range(len(klines) - period, len(klines)):
        high = Decimal(str(klines[index][2]))
        low = Decimal(str(klines[index][3]))
        previous_close = Decimal(str(klines[index - 1][4]))
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    close = Decimal(str(klines[-1][4]))
    return (sum(ranges, Decimal("0")) / Decimal(period)) / close * Decimal("100")


def analyze_bearish_market(timeframes: dict[str, Sequence[Sequence[object]]]) -> BearishAnalysis:
    required = {"15m", "1h", "4h"}
    if not required.issubset(timeframes):
        raise ValueError("15m, 1h and 4h data are required")

    closes = {interval: _series(timeframes[interval], 4) for interval in required}
    volumes_15m = _series(timeframes["15m"], 5)
    score = 0
    reasons: list[str] = []

    for interval, weight in {"15m": 1, "1h": 2, "4h": 2}.items():
        values = closes[interval]
        if _ema(values, 8) < _ema(values, 21) and _ema_falling(values, 8) and _ema_falling(values, 21):
            score += weight
            reasons.append(f"{interval}_downtrend")

    rsi = _rsi(closes["1h"])
    if Decimal("32") <= rsi <= Decimal("52"):
        score += 1
        reasons.append("bearish_rsi_window")

    if _ema(closes["1h"], 12) < _ema(closes["1h"], 26):
        score += 1
        reasons.append("negative_macd_proxy")

    baseline_volume = sum(volumes_15m[-21:-1], Decimal("0")) / Decimal("20")
    volume_ratio = volumes_15m[-1] / baseline_volume if baseline_volume > 0 else Decimal("0")
    if volume_ratio >= Decimal("1.10"):
        score += 1
        reasons.append("volume_confirmation")

    atr_percent = _atr_percent(timeframes["1h"])
    if Decimal("0.20") <= atr_percent <= Decimal("5"):
        score += 1
        reasons.append("tradable_volatility")

    veto = rsi <= Decimal("25") or rsi >= Decimal("70") or atr_percent > Decimal("8")
    if veto:
        reasons.append("short_risk_veto")
    confidence = min(Decimal("1"), Decimal(score) / Decimal("9"))
    return BearishAnalysis(not veto and score >= 7, score, confidence, rsi, atr_percent, volume_ratio, tuple(reasons))
