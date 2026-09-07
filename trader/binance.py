from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class BinanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    secret_key: str

    def validate(self) -> None:
        if not self.api_key or not self.secret_key:
            raise ValueError("Binance API credentials are required")


class BinanceSpotClient:
    """Minimal Spot client. It intentionally exposes no withdrawal methods."""

    def __init__(
        self,
        credentials: BinanceCredentials | None = None,
        base_url: str = "https://api.binance.com",
        timeout_seconds: int = 10,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def sign_query(params: dict[str, Any], secret_key: str) -> str:
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = False,
    ) -> Any:
        request_params = dict(params or {})
        headers = {"Accept": "application/json"}

        if signed:
            if self.credentials is None:
                raise BinanceError("Signed request requires credentials")
            self.credentials.validate()
            request_params.setdefault("timestamp", int(time.time() * 1000))
            request_params.setdefault("recvWindow", 5000)
            query = self.sign_query(request_params, self.credentials.secret_key)
            headers["X-MBX-APIKEY"] = self.credentials.api_key
        else:
            query = urllib.parse.urlencode(request_params)

        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"

        request = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise BinanceError(f"Binance HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise BinanceError(f"Binance connection failed: {exc.reason}") from exc

    def server_time(self) -> int:
        response = self._request("GET", "/api/v3/time")
        return int(response["serverTime"])

    def exchange_info(self, symbols: tuple[str, ...]) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v3/exchangeInfo",
            {"symbols": json.dumps(list(symbols), separators=(",", ":"))},
        )

    def klines(self, symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
        return self._request(
            "GET",
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account", signed=True)

    def ticker_price(self, symbol: str) -> Decimal:
        response = self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})
        return Decimal(str(response["price"]))

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        response = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
        symbols = response.get("symbols", [])
        if len(symbols) != 1:
            raise BinanceError(f"Symbol unavailable: {symbol}")
        return symbols[0]

    def test_market_buy(self, *, symbol: str, quote_quantity: Decimal) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v3/order/test",
            {"symbol": symbol, "side": "BUY", "type": "MARKET", "quoteOrderQty": format(quote_quantity, "f")},
            signed=True,
        )

    def market_buy_by_quote(self, *, symbol: str, quote_quantity: Decimal, live_trading_enabled: bool) -> dict[str, Any]:
        if not live_trading_enabled:
            raise BinanceError("Live trading safety lock is disabled")
        return self._request(
            "POST",
            "/api/v3/order",
            {"symbol": symbol, "side": "BUY", "type": "MARKET", "quoteOrderQty": format(quote_quantity, "f"), "newOrderRespType": "FULL"},
            signed=True,
        )

    def place_spot_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        live_trading_enabled: bool,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not live_trading_enabled:
            raise BinanceError("Live trading safety lock is disabled")
        if side not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL")

        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": format(quantity, "f"),
            "newOrderRespType": "FULL",
        }
        params.update(extra or {})
        return self._request("POST", "/api/v3/order", params, signed=True)
