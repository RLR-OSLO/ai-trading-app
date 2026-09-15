import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("recovery_collect", Path(__file__).with_name("collect_server_evidence.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RecoveryTests(unittest.TestCase):
    def test_exchange_transport_is_get_only_and_rejects_trade_endpoints(self):
        with patch.object(mod, "request_json", return_value={"serverTime": 1}) as call:
            reader = mod.SpotReader({"BINANCE_API_KEY": "dummy-key", "BINANCE_SECRET_KEY": "dummy-secret"})
            for path in ("/api/v3/order", "/api/v3/orderList/oco", "https://example.com"):
                with self.assertRaises(mod.RecoveryError):
                    reader.read(path)
            reader.read("/api/v3/account")
            self.assertTrue(call.call_args.args[0].startswith(mod.SPOT + "/api/v3/account?"))
            self.assertNotIn("payload", call.call_args.kwargs)
            self.assertNotIn("dummy-secret", call.call_args.args[0])

    def test_trade_pagination_never_silently_claims_full_history_at_cap(self):
        class Reader:
            def read(self, path, params):
                self.params = params
                return [{"id": i} for i in range(params["fromId"], params["fromId"] + 1000)]
        reader = Reader()
        with patch.object(mod.time, "sleep"):
            result = mod.history(reader, "SOLUSDC", max_pages=2)
        self.assertFalse(result["pagination_exhausted"])
        self.assertEqual(reader.params["fromId"], 1000)
        self.assertEqual(len(result["rows"]), 2000)

    def test_history_rejects_repeated_page(self):
        class Reader:
            def read(self, path, params):
                return [{"id": i} for i in range(1000)]
        with patch.object(mod.time, "sleep"), self.assertRaises(mod.RecoveryError):
            mod.history(Reader(), "SOLUSDC")

    def test_other_users_state_does_not_expand_owner_history(self):
        class Reader:
            def __init__(self, env):
                pass
            def read(self, path, params=None):
                if path == "/api/v3/account":
                    return {"balances": []}
                return []
        states = {"users/other/live-state.json": {"positions": [{"symbol": "ADAUSDC"}]}}
        with patch.object(mod, "SpotReader", Reader), patch.object(mod.time, "sleep"):
            report = mod.collect({}, states)
        self.assertNotIn("ADAUSDC", report["spot_trades"])
        self.assertFalse(report["margin_futures_verified"])


if __name__ == "__main__":
    unittest.main()
