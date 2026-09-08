from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TradingConfig:
    starting_capital_nok: Decimal
    symbols: tuple[str, ...]
    preferred_quote_assets: tuple[str, ...]
    risk_per_trade: Decimal
    daily_loss_limit: Decimal
    hard_drawdown_limit: Decimal
    starting_reserve: Decimal
    weekly_profit_lock: Decimal
    max_open_positions: int
    spot_only: bool = True
    withdrawals_allowed: bool = False
    leverage_allowed: bool = False


DEFAULT_CONFIG = TradingConfig(
    starting_capital_nok=Decimal("6000"),
    symbols=("BTC", "ETH", "SOL", "BNB", "XRP"),
    preferred_quote_assets=("USDC", "USDT"),
    risk_per_trade=Decimal("0.005"),
    daily_loss_limit=Decimal("0.02"),
    hard_drawdown_limit=Decimal("0.08"),
    starting_reserve=Decimal("0.20"),
    weekly_profit_lock=Decimal("0.25"),
    max_open_positions=3,
)
