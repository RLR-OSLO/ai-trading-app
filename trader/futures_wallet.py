"""Read exchange margin availability without treating cash or withdrawals as margin."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


def number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass
class FuturesWallet:
    quote: str
    total: Decimal | None = None
    available: Decimal | None = None
    position_margin: Decimal | None = None
    order_margin: Decimal | None = None
    mode: str = "unknown"
    status: str = "read_error"
    assets: dict[str, str] = field(default_factory=dict)

    def heartbeat(self) -> str:
        values = {"wallet_version": "v2", "quote": self.quote, "total": self.total,
                  "available": self.available, "position_margin": self.position_margin,
                  "order_margin": self.order_margin, "margin_mode": self.mode,
                  "status": self.status, "assets": ",".join(f"{k}:{v}" for k, v in self.assets.items()) or "none"}
        return ";".join(f"futures_{key}={format(value, 'f') if isinstance(value, Decimal) else value if value is not None else 'unknown'}"
                        for key, value in values.items())


def parse_futures_wallet(account: dict, quote: str, quote_usd: Decimal | None = None) -> FuturesWallet:
    wallet = FuturesWallet(quote=quote, status="balance_unavailable")
    rows = account.get("assets")
    if not isinstance(rows, list):
        return wallet
    for row in rows:
        asset = str(row.get("asset", ""))
        balance = number(row.get("walletBalance"))
        if asset.isalnum() and balance is not None and balance != 0:
            wallet.assets[asset] = format(balance, "f")
    selected = next((r for r in rows if r.get("asset") == quote), None)
    multi = account.get("multiAssetsMargin")
    # v2 includes the mode. Never guess whether top-level USD/USDT values
    # represent the selected settlement asset when that mode is missing.
    if multi is True:
        wallet.mode = "multi"
        if quote_usd is None or not quote_usd.is_finite() or quote_usd <= 0:
            return wallet
        source, divisor = account, quote_usd
        fields = ("totalWalletBalance", "availableBalance", "totalPositionInitialMargin", "totalOpenOrderInitialMargin")
    elif multi is False:
        wallet.mode = "single"
        if selected is None:
            wallet.status = "no_quote_collateral"
            wallet.total = wallet.available = Decimal("0")
            return wallet
        source, divisor = selected, Decimal("1")
        fields = ("walletBalance", "availableBalance", "positionInitialMargin", "openOrderInitialMargin")
    else:
        return wallet
    for key, attr in zip(fields, ("total", "available", "position_margin", "order_margin")):
        value = number(source.get(key))
        setattr(wallet, attr, value / divisor if value is not None else None)
    if wallet.available is not None:
        wallet.available = max(Decimal("0"), wallet.available)
    if account.get("canTrade") is False:
        wallet.status = "trading_disabled"
    elif account.get("canTrade") is not True or wallet.available is None:
        wallet.status = "balance_unavailable"
    elif wallet.available > 0:
        wallet.status = "ready"
    elif wallet.position_margin and wallet.position_margin > 0 or wallet.order_margin and wallet.order_margin > 0:
        wallet.status = "margin_in_use"
    elif wallet.mode == "single" and wallet.total == 0 and wallet.assets:
        wallet.status = "no_quote_collateral"
    else:
        wallet.status = "no_available_margin"
    return wallet


def read_futures_wallet(client, quote: str) -> FuturesWallet:
    account = client.account()
    quote_usd = None
    if account.get("multiAssetsMargin") is True:
        index = client.asset_index(quote)
        quote_usd = number(index.get("index"))
    return parse_futures_wallet(account, quote, quote_usd)


def funded_notional(wallet: FuturesWallet, requested: Decimal, leverage: int) -> Decimal:
    if wallet.status != "ready" or wallet.available is None:
        return Decimal("0")
    # Leave room for entry fees/slippage; leverage never increases the user's
    # requested notional or capital cap. It only changes required collateral.
    return max(Decimal("0"), min(requested, wallet.available * leverage * Decimal("0.98")))
