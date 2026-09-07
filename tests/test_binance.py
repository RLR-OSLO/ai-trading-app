import hashlib
import hmac
import unittest
from decimal import Decimal

from trader.binance import BinanceError, BinanceSpotClient
from trader.worker import configured_pairs


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

    def test_default_pair_allowlist(self) -> None:
        self.assertEqual(
            configured_pairs(),
            ("BTCUSDC", "ETHUSDC", "SOLUSDC", "BNBUSDC", "XRPUSDC"),
        )


if __name__ == "__main__":
    unittest.main()
