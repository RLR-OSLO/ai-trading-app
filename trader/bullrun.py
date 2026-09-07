from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class MarketRegime(StrEnum):
    BEAR = "bear"
    NEUTRAL = "neutral"
    BULL = "bull"
    STRONG_BULL = "strong_bull"


@dataclass(frozen=True)
class ScaleOutTarget:
    reward_multiple: Decimal
    fraction_of_original_position: Decimal


@dataclass(frozen=True)
class BullrunExitPlan:
    scale_out_targets: tuple[ScaleOutTarget, ...]
    runner_fraction: Decimal
    trailing_atr_multiple: Decimal
    exit_on_higher_timeframe_trend_failure: bool = True


def exit_plan_for_regime(regime: MarketRegime) -> BullrunExitPlan:
    if regime is MarketRegime.STRONG_BULL:
        return BullrunExitPlan(
            scale_out_targets=(
                ScaleOutTarget(Decimal("2"), Decimal("0.20")),
                ScaleOutTarget(Decimal("4"), Decimal("0.15")),
            ),
            runner_fraction=Decimal("0.65"),
            trailing_atr_multiple=Decimal("3.5"),
        )
    if regime is MarketRegime.BULL:
        return BullrunExitPlan(
            scale_out_targets=(
                ScaleOutTarget(Decimal("2"), Decimal("0.25")),
                ScaleOutTarget(Decimal("3"), Decimal("0.25")),
            ),
            runner_fraction=Decimal("0.50"),
            trailing_atr_multiple=Decimal("2.5"),
        )
    return BullrunExitPlan(
        scale_out_targets=(ScaleOutTarget(Decimal("2"), Decimal("0.50")),),
        runner_fraction=Decimal("0.50"),
        trailing_atr_multiple=Decimal("2"),
    )


def validate_exit_plan(plan: BullrunExitPlan) -> None:
    allocated = plan.runner_fraction + sum(
        (target.fraction_of_original_position for target in plan.scale_out_targets),
        start=Decimal("0"),
    )
    if allocated != Decimal("1"):
        raise ValueError(f"Exit plan allocations total {allocated}, expected 1")
    if plan.trailing_atr_multiple <= 0:
        raise ValueError("Trailing ATR multiple must be positive")

