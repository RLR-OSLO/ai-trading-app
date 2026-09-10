from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .binance import BinanceCredentials, BinanceError, BinanceSpotClient


@dataclass(frozen=True)
class DerivativesCapability:
    margin_account_enabled: bool
    futures_account_enabled: bool
    api_margin_enabled: bool
    api_futures_enabled: bool
    withdrawals_enabled: bool
    ip_restricted: bool

    @property
    def margin_ready(self) -> bool:
        return self.margin_account_enabled and self.api_margin_enabled and not self.withdrawals_enabled

    @property
    def futures_ready(self) -> bool:
        return self.futures_account_enabled and self.api_futures_enabled and not self.withdrawals_enabled


class BinanceMarginClient(BinanceSpotClient):
    """Cross-margin client. No withdrawal or transfer methods are exposed."""

    def account_info(self) -> dict[str, Any]:
        return self._request("GET", "/sapi/v1/account/info", signed=True)

    def api_restrictions(self) -> dict[str, Any]:
        return self._request("GET", "/sapi/v1/account/apiRestrictions", signed=True)

    def margin_account(self) -> dict[str, Any]:
        return self._request("GET", "/sapi/v1/margin/account", signed=True)

    def max_borrowable(self, *, asset: str, isolated_symbol: str | None = None) -> Decimal:
        params: dict[str, Any] = {"asset": asset}
        if isolated_symbol:
            params["isolatedSymbol"] = isolated_symbol
        row = self._request("GET", "/sapi/v1/margin/maxBorrowable", params, signed=True)
        return Decimal(str(row.get("amount", "0")))

    def market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        live_trading_enabled: bool,
        auto_borrow_repay: bool = True,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        if not live_trading_enabled:
            raise BinanceError("Margin live-trading safety lock is disabled")
        if side not in {"BUY", "SELL"}:
            raise ValueError("Margin side must be BUY or SELL")
        if quantity <= 0:
            raise ValueError("Margin quantity must be positive")
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": format(quantity, "f"),
            "newOrderRespType": "FULL",
            "sideEffectType": "AUTO_BORROW_REPAY" if auto_borrow_repay else "NO_SIDE_EFFECT",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._request("POST", "/sapi/v1/margin/order", params, signed=True)


class BinanceFuturesClient(BinanceSpotClient):
    """USD-M futures client with explicit live lock and no transfer/withdrawal methods."""

    def __init__(self, credentials: BinanceCredentials, timeout_seconds: int = 10) -> None:
        super().__init__(credentials=credentials, base_url="https://fapi.binance.com", timeout_seconds=timeout_seconds)

    def server_time(self) -> int:
        response = self._request("GET", "/fapi/v1/time")
        return int(response["serverTime"])

    def exchange_info_all(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v2/account", signed=True)

    def position_risk(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/fapi/v2/positionRisk", params, signed=True)

    def ticker_price(self, symbol: str) -> Decimal:
        row = self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        return Decimal(str(row["price"]))

    def set_leverage(self, *, symbol: str, leverage: int, live_trading_enabled: bool) -> dict[str, Any]:
        if not live_trading_enabled:
            raise BinanceError("Futures live-trading safety lock is disabled")
        if not 1 <= leverage <= 3:
            raise ValueError("Futures leverage safety range is 1x-3x")
        return self._request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)

    def set_isolated_margin(self, *, symbol: str, live_trading_enabled: bool) -> dict[str, Any] | None:
        if not live_trading_enabled:
            raise BinanceError("Futures live-trading safety lock is disabled")
        try:
            return self._request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"}, signed=True)
        except BinanceError as exc:
            # Binance returns -4046 when margin type is already set; that state is safe.
            if "-4046" in str(exc):
                return None
            raise

    def market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        live_trading_enabled: bool,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        if not live_trading_enabled:
            raise BinanceError("Futures live-trading safety lock is disabled")
        if side not in {"BUY", "SELL"}:
            raise ValueError("Futures side must be BUY or SELL")
        if quantity <= 0:
            raise ValueError("Futures quantity must be positive")
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": format(quantity, "f"),
            "newOrderRespType": "RESULT",
            "reduceOnly": "true" if reduce_only else "false",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._request("POST", "/fapi/v1/order", params, signed=True)


def capability_snapshot(credentials: BinanceCredentials) -> DerivativesCapability:
    client = BinanceMarginClient(credentials=credentials)
    account = client.account_info()
    restrictions = client.api_restrictions()
    return DerivativesCapability(
        margin_account_enabled=bool(account.get("isMarginEnabled")),
        futures_account_enabled=bool(account.get("isFutureEnabled")),
        api_margin_enabled=bool(restrictions.get("enableMargin")) and bool(restrictions.get("enableSpotAndMarginTrading")),
        api_futures_enabled=bool(restrictions.get("enableFutures")),
        withdrawals_enabled=bool(restrictions.get("enableWithdrawals")),
        ip_restricted=bool(restrictions.get("ipRestrict")),
    )
