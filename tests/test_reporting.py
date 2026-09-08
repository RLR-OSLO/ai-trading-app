import json
import os
import unittest
from unittest.mock import MagicMock, patch

from trader.reporting import SupabaseReporter


class ReportingTests(unittest.TestCase):
    def test_reporter_is_optional_without_server_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(SupabaseReporter.from_env())

    @patch("urllib.request.urlopen")
    def test_trade_payload_is_scoped_to_configured_user(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = response
        urlopen.return_value = response
        reporter = SupabaseReporter("https://example.supabase.co", "secret", "user-id")
        reporter.record_trade({"symbol": "BTCUSDC", "side": "BUY", "quantity": "0.1", "entry_price": "10", "exit_price": None, "pnl": None})
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["user_id"], "user-id")
        self.assertEqual(body["mode"], "live")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")

    @patch("urllib.request.urlopen")
    def test_settings_are_read_for_configured_user(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps([{"bot_enabled": True, "live_trading_enabled": True}]).encode("utf-8")
        urlopen.return_value = response
        reporter = SupabaseReporter("https://example.supabase.co", "secret", "user-id")
        settings = reporter.get_settings()
        request = urlopen.call_args.args[0]
        self.assertTrue(settings["live_trading_enabled"])
        self.assertIn("user_id=eq.user-id", request.full_url)


if __name__ == "__main__":
    unittest.main()
