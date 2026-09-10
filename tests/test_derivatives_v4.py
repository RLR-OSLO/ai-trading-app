from decimal import Decimal

import pytest

from trader.binance import BinanceCredentials, BinanceError
from trader.derivatives import BinanceFuturesClient, BinanceMarginClient


CREDS = BinanceCredentials("key", "secret")


def test_futures_algo_protection_requires_live_lock():
    client = BinanceFuturesClient(CREDS)
    with pytest.raises(BinanceError):
        client.close_algo(
            symbol="BTCUSDT",
            side="BUY",
            order_type="STOP_MARKET",
            trigger_price=Decimal("100"),
            live_trading_enabled=False,
        )


def test_futures_algo_uses_2026_algo_endpoint(monkeypatch):
    seen = {}

    def fake_request(self, method, path, params=None, *, signed=False):
        seen.update({"method": method, "path": path, "params": params, "signed": signed})
        return {"algoId": 123}

    monkeypatch.setattr(BinanceFuturesClient, "_request", fake_request)
    client = BinanceFuturesClient(CREDS)
    result = client.close_algo(
        symbol="BTCUSDT",
        side="BUY",
        order_type="STOP_MARKET",
        trigger_price=Decimal("101"),
        live_trading_enabled=True,
    )
    assert result["algoId"] == 123
    assert seen["path"] == "/fapi/v1/algoOrder"
    assert seen["params"]["closePosition"] == "true"
    assert seen["params"]["workingType"] == "MARK_PRICE"


def test_margin_short_oco_is_buy_and_auto_repay(monkeypatch):
    seen = {}

    def fake_request(self, method, path, params=None, *, signed=False):
        seen.update({"method": method, "path": path, "params": params, "signed": signed})
        return {"orderListId": 77}

    monkeypatch.setattr(BinanceMarginClient, "_request", fake_request)
    client = BinanceMarginClient(credentials=CREDS)
    result = client.protective_short_oco(
        symbol="BTCUSDT",
        quantity=Decimal("0.001"),
        take_profit_price=Decimal("90"),
        stop_price=Decimal("110"),
        live_trading_enabled=True,
    )
    assert result["orderListId"] == 77
    assert seen["path"] == "/sapi/v1/margin/order/oco"
    assert seen["params"]["side"] == "BUY"
    assert seen["params"]["sideEffectType"] == "AUTO_REPAY"
