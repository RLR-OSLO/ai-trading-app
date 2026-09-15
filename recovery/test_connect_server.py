import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

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

    @unittest.skipUnless(os.geteuid() == 0, "isolated root-filesystem simulation")
    def test_missing_heartbeat_restores_env_and_service_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            def mapped(value):
                raw = str(value)
                if raw.startswith(("/root", "/opt", "/etc", "/var/lib")):
                    return sandbox / raw.lstrip("/")
                return Path(value)
            backup = mapped("/root/ai-trading-recovery-test")
            backup.mkdir(parents=True)
            mapped("/opt").mkdir()
            state = mapped("/var/lib/ai-trading-app/live-state.json")
            state.parent.mkdir(parents=True)
            state.write_text('{"positions":[]}')
            old_id = "00000000-0000-0000-0000-000000000001"
            new_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
            original = f"APP_USER_ID={old_id}\nBINANCE_API_KEY=dummy\nBINANCE_SECRET_KEY=dummy\nLIVE_STATE_PATH={state}\nSUPABASE_URL=old\n".encode()
            env = mapped("/etc/ai-trading-app.env")
            env.parent.mkdir(parents=True)
            env.write_bytes(original)
            (backup / "report.json").write_text(json.dumps({"legacy_user_id": old_id, "local_states": {"live-state.json": {"positions": []}}}))
            secret = backup / "compass-server-key"
            secret.write_text("sb_secret_dummy")
            secret.chmod(0o600)
            args = SimpleNamespace(backup=backup, revision="a" * 40, user_id=new_id, email="test@example.invalid")
            real_mkdtemp = tempfile.mkdtemp
            def isolated_mkdtemp(**kwargs):
                return real_mkdtemp(**{**kwargs, "dir": mapped(kwargs["dir"])})
            commands = []
            def run(*command):
                commands.append(command)
                return "a" * 40 if "rev-parse" in command else ""
            def api(url, headers=None, payload=None):
                if "/admin/users/" in url:
                    return {"email": args.email, "email_confirmed_at": "2026-01-01", "identities": [{"provider": "google"}]}
                if "/bot_settings?" in url:
                    return [{"bot_enabled": False, "live_trading_enabled": False, "execution_authorized": False}]
                return None
            with patch.object(mod, "Path", side_effect=mapped), patch.object(mod.tempfile, "mkdtemp", side_effect=isolated_mkdtemp), patch.object(mod.argparse.ArgumentParser, "parse_args", return_value=args), patch.object(mod, "run", side_effect=run), patch.object(mod, "api", side_effect=api), patch.object(mod, "exchange_read", return_value={"balances": []}), patch.object(mod.time, "monotonic", side_effect=[0, 151]):
                with self.assertRaisesRegex(mod.Stop, "Ingen bekreftet rapport"):
                    mod.main()
            self.assertEqual(env.read_bytes(), original)
            self.assertEqual(state.read_text(), '{"positions":[]}')
            self.assertFalse(mapped("/etc/systemd/system/ai-trading-app.service.d/40-compass.conf").exists())
            self.assertEqual(commands[-1], ("systemctl", "start", "ai-trading-app"))


if __name__ == "__main__":
    unittest.main()
