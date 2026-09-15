import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("connect_server", Path(__file__).with_name("connect_server.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SwitchTests(unittest.TestCase):
    def test_environment_rewrite_preserves_keys_and_risk_configuration(self):
        original = "# keep\nBINANCE_API_KEY=dummy\nLIVE_TRADING_ENABLED=true\nSUPABASE_URL=old\nSUPABASE_URL=duplicate\n"
        actual = mod.rewrite_env(original, {"SUPABASE_URL": mod.COMPASS, "APP_USER_ID": "new"})
        self.assertIn("BINANCE_API_KEY=dummy\n", actual)
        self.assertIn("LIVE_TRADING_ENABLED=true\n", actual)
        self.assertEqual(actual.count("SUPABASE_URL="), 1)
        self.assertEqual(mod.env_values(actual)["APP_USER_ID"], "new")

    def test_exchange_endpoint_allowlist_precedes_network_and_signing(self):
        with patch.object(mod, "api") as api:
            for base, path in [("https://api.binance.com", "/api/v3/order"), ("https://attacker.invalid", "/api/v3/account")]:
                with self.assertRaises(mod.Stop):
                    mod.exchange_read({}, base, path)
            api.assert_not_called()

    def test_atomic_replacement_keeps_requested_mode(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(mod.os, "chown"):
            path = Path(folder) / "test.env"
            path.write_bytes(b"old")
            mod.atomic_write(path, b"replacement", 0o640)
            self.assertEqual(path.read_bytes(), b"replacement")
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
