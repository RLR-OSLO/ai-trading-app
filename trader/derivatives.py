from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
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
    """Cross-margin client. No transfer or withdrawal methods are exposed."""

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

    def protective_short_oco(
        self,
        *,
        symbol: str,
        quantity: Decimal,
        take_profit_price: Decimal,
        stop_price: Decimal,
        live_trading_enabled: bool,
        list_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Protect a short: BUY lower for profit, BUY higher for stop, then auto-repay debt."""
        if not live_trading_enabled:
            raise BinanceError("Margin live-trading safety lock is disabled")
        if quantity <= 0 or take_profit_price <= 0 or stop_price <= 0:
            raise ValueError("Margin OCO values must be positive")
        if take_profit_price >= stop_price:
            raise ValueError("Short take-profit must be below stop price")
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": "BUY",
            "quantity": format(quantity, "f"),
            "price": format(take_profit_price, "f"),
            "stopPrice": format(stop_price, "f"),
            "newOrderRespType": "FULL",
            "sideEffectType": "AUTO_REPAY",
            "autoRepayAtCancel": "true",
        }
        if list_client_order_id:
            params["listClientOrderId"] = list_client_order_id
        return self._request("POST", "/sapi/v1/margin/order/oco", params, signed=True)

    def query_order_list(self, *, order_list_id: int) -> dict[str, Any]:
        return self._request("GET", "/sapi/v1/margin/orderList", {"orderListId": order_list_id}, signed=True)

    def cancel_order_list(self, *, symbol: str, order_list_id: int) -> dict[str, Any]:
        return self._request("DELETE", "/sapi/v1/margin/orderList", {"symbol": symbol, "orderListId": order_list_id}, signed=True)


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

    def quantity_for_notional(self, *, symbol: str, notional: Decimal) -> Decimal:
        info = self.exchange_info_all()
        row = next((x for x in info.get("symbols", []) if x.get("symbol") == symbol), None)
        if row is None:
            raise BinanceError(f"Futures symbol unavailable: {symbol}")
        lot = next((x for x in row.get("filters", []) if x.get("filterType") == "MARKET_LOT_SIZE"), None)
        if lot is None:
            lot = next((x for x in row.get("filters", []) if x.get("filterType") == "LOT_SIZE"), None)
        if lot is None:
            raise BinanceError(f"Futures lot-size filter missing: {symbol}")
        price = self.ticker_price(symbol)
        step = Decimal(str(lot["stepSize"]))
        minimum = Decimal(str(lot.get("minQty", "0")))
        qty = (notional / price / step).to_integral_value(rounding=ROUND_DOWN) * step
        if qty < minimum:
            raise BinanceError(f"Futures quantity below minimum for {symbol}")
        precision = int(row.get("quantityPrecision", max(0, -step.normalize().as_tuple().exponent)))
        quantum = Decimal("1").scaleb(-precision)
        return qty.quantize(quantum, rounding=ROUND_DOWN)

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
            if "-4046" in str(exc) or "-4175" in str(exc):
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

    def close_algo(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        trigger_price: Decimal,
        live_trading_enabled: bool,
        client_algo_id: str | None = None,
    ) -> dict[str, Any]:
        """Exchange-side close-all STOP_MARKET or TAKE_PROFIT_MARKET using the 2026 Algo service."""
        if not live_trading_enabled:
            raise BinanceError("Futures live-trading safety lock is disabled")
        if side not in {"BUY", "SELL"}:
            raise ValueError("Futures algo side must be BUY or SELL")
        if order_type not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
            raise ValueError("Unsupported futures close algo type")
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "triggerPrice": format(trigger_price, "f"),
            "closePosition": "true",
            "workingType": "MARK_PRICE",
            "priceProtect": "true",
        }
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id
        return self._request("POST", "/fapi/v1/algoOrder", params, signed=True)

    def cancel_algo(self, *, algo_id: int, live_trading_enabled: bool) -> dict[str, Any]:
        if not live_trading_enabled:
            raise BinanceError("Futures live-trading safety lock is disabled")
        return self._request("DELETE", "/fapi/v1/algoOrder", {"algoId": algo_id}, signed=True)


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
