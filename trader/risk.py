from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from .config import TradingConfig


MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class RiskBudget:
    active_capital: Decimal
    protected_reserve: Decimal
    max_loss_per_trade: Decimal
    max_daily_loss: Decimal
    hard_drawdown_amount: Decimal


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_DOWN)


def build_risk_budget(equity: Decimal, config: TradingConfig) -> RiskBudget:
    if equity <= 0:
        raise ValueError("Equity must be positive")

    reserve = money(equity * config.starting_reserve)
    return RiskBudget(
        active_capital=money(equity - reserve),
        protected_reserve=reserve,
        max_loss_per_trade=money(equity * config.risk_per_trade),
        max_daily_loss=money(equity * config.daily_loss_limit),
        hard_drawdown_amount=money(equity * config.hard_drawdown_limit),
    )


def position_notional_for_stop(
    equity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    config: TradingConfig,
) -> Decimal:
    """Return quote-currency notional whose stop loss equals the risk budget."""
    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("For a long position, stop must be between zero and entry")

    stop_distance_fraction = (entry_price - stop_price) / entry_price
    risk_amount = equity * config.risk_per_trade
    raw_notional = risk_amount / stop_distance_fraction
    active_capital = equity * (Decimal("1") - config.starting_reserve)
    per_position_cap = active_capital / Decimal(config.max_open_positions)
    return money(min(raw_notional, per_position_cap))


def should_pause_for_drawdown(
    current_equity: Decimal,
    high_water_mark: Decimal,
    config: TradingConfig,
) -> bool:
    if high_water_mark <= 0:
        raise ValueError("High-water mark must be positive")
    drawdown = (high_water_mark - current_equity) / high_water_mark
    return drawdown >= config.hard_drawdown_limit


def profit_to_lock(realized_weekly_profit: Decimal, config: TradingConfig) -> Decimal:
    if realized_weekly_profit <= 0:
        return Decimal("0.00")
    return money(realized_weekly_profit * config.weekly_profit_lock)

