import hashlib
import hmac
import unittest
from decimal import Decimal

from trader.binance import BinanceCredentials, BinanceError, BinanceSpotClient
from trader.worker import configured_pairs, readiness_check


class BinanceClientTests(unittest.TestCase):
    def test_signature_matches_hmac_sha256(self) -> None:
        params = {"symbol": "BTCUSDC", "timestamp": 1234567890}
        expected_query = "symbol=BTCUSDC&timestamp=1234567890"
        expected_signature = hmac.new(
            b"secret", expected_query.encode(), hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            BinanceSpotClient.sign_query(params, "secret"),
            f"{expected_query}&signature={expected_signature}",
        )

    def test_live_order_lock_is_closed_by_default(self) -> None:
        client = BinanceSpotClient()
        with self.assertRaisesRegex(BinanceError, "safety lock"):
            client.place_spot_order(
                symbol="BTCUSDC",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("0.001"),
                live_trading_enabled=False,
            )

    def test_protective_oco_uses_current_spot_order_list_endpoint(self) -> None:
        class CaptureClient(BinanceSpotClient):
            def __init__(self):
                super().__init__(BinanceCredentials("api", "secret"))
                self.request = None

            def _request(self, method, path, params=None, *, signed=False):
                self.request = (method, path, params, signed)
                return {"orderListId": 1, "orders": [{"orderId": 2}, {"orderId": 3}]}

        client = CaptureClient()
        client.place_protective_oco_sell(
            symbol="BTCUSDC",
            quantity=Decimal("0.001"),
            target_price=Decimal("80000"),
            stop_price=Decimal("76000"),
            live_trading_enabled=True,
        )
        method, path, params, signed = client.request
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/v3/orderList/oco")
        self.assertTrue(signed)
        self.assertEqual(params["side"], "SELL")
        self.assertEqual(params["aboveType"], "LIMIT_MAKER")
        self.assertEqual(params["belowType"], "STOP_LOSS")

    def test_default_pair_allowlist(self) -> None:
        self.assertEqual(
            configured_pairs(),
            ("BTCUSDC", "ETHUSDC", "SOLUSDC", "BNBUSDC", "XRPUSDC"),
        )

    def test_readiness_uses_signed_account_check_when_configured(self) -> None:
        class ReadyClient:
            credentials = BinanceCredentials("api", "secret")

            def server_time(self):
                return 1

            def exchange_info(self, symbols):
                return {"symbols": [{"symbol": symbol} for symbol in symbols]}

            def account(self):
                return {"canTrade": False}

        self.assertTrue(readiness_check(ReadyClient()))


if __name__ == "__main__":
    unittest.main()
