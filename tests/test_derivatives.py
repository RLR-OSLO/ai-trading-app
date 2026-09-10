from decimal import Decimal

import pytest

from trader.binance import BinanceCredentials, BinanceError
from trader.derivatives import BinanceFuturesClient, BinanceMarginClient, capability_snapshot


CREDS = BinanceCredentials("key", "secret")


def test_margin_order_requires_live_lock():
    client = BinanceMarginClient(credentials=CREDS)
    with pytest.raises(BinanceError):
        client.market_order(symbol="BTCUSDT", side="SELL", quantity=Decimal("0.001"), live_trading_enabled=False)


def test_futures_order_requires_live_lock():
    client = BinanceFuturesClient(CREDS)
    with pytest.raises(BinanceError):
        client.market_order(symbol="BTCUSDT", side="SELL", quantity=Decimal("0.001"), live_trading_enabled=False)


def test_futures_leverage_is_capped():
    client = BinanceFuturesClient(CREDS)
    with pytest.raises(ValueError):
        client.set_leverage(symbol="BTCUSDT", leverage=4, live_trading_enabled=True)


def test_capability_snapshot_maps_account_and_api_flags(monkeypatch):
    def fake_request(self, method, path, params=None, *, signed=False):
        if path == "/sapi/v1/account/info":
            return {"isMarginEnabled": True, "isFutureEnabled": True}
        if path == "/sapi/v1/account/apiRestrictions":
            return {
                "enableMargin": True,
                "enableSpotAndMarginTrading": True,
                "enableFutures": True,
                "enableWithdrawals": False,
                "ipRestrict": True,
            }
        raise AssertionError(path)

    monkeypatch.setattr(BinanceMarginClient, "_request", fake_request)
    status = capability_snapshot(CREDS)
    assert status.margin_ready is True
    assert status.futures_ready is True
    assert status.withdrawals_enabled is False
    assert status.ip_restricted is True
