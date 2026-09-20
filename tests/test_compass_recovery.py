from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from trader import worker
from trader.reporting import SupabaseReporter, supabase_headers


class CompassRecoveryTests(unittest.TestCase):
    def test_secret_key_is_not_used_as_a_jwt(self):
        self.assertEqual(supabase_headers("sb_secret_dummy")["apikey"], "sb_secret_dummy")
        self.assertNotIn("Authorization", supabase_headers("sb_secret_dummy"))
        self.assertEqual(supabase_headers("legacy")["Authorization"], "Bearer legacy")

    def test_recovery_lock_requires_exact_boolean_authorization(self):
        reporter = SupabaseReporter("https://nsqsqupucxgrkwotegof.supabase.co", "dummy", "user")
        for settings in (None, {}, {"execution_authorized": False}, {"execution_authorized": "true"}):
            self.assertTrue(worker.recovery_execution_blocked(reporter, settings))
        self.assertFalse(worker.recovery_execution_blocked(reporter, {"execution_authorized": True}))

    def test_recovery_cycle_reports_but_never_touches_positions_or_orders(self):
        reporter = MagicMock()
        reporter.is_compass = True
        reporter.get_settings.return_value = {"bot_enabled": False, "live_trading_enabled": False, "execution_authorized": False, "quote_asset": "USDC"}
        reporter.get_recent_trades.return_value = []
        analysis = SimpleNamespace(score=0, confidence=Decimal(0), reasons=[], signal=False)
        scan = ({"BTCUSDC": False}, {"BTCUSDC": False}, {"BTCUSDC": analysis}, {"BTCUSDC": analysis}, {"BTCUSDC": analysis}, {"BTCUSDC": "swing"}, "test=1")
        client = MagicMock()
        client._request.return_value = [{"symbol": "BTCUSDC", "price": "100"}]
        with patch.object(worker, "build_client", return_value=client), \
             patch.object(worker.SupabaseReporter, "from_env", return_value=reporter), \
             patch.object(worker, "readiness_check", return_value=True), \
             patch.object(worker, "active_pairs", return_value=("BTCUSDC",)), \
             patch.object(worker, "free_quote_balance", return_value=Decimal(0)), \
             patch.object(worker, "market_scan", return_value=scan), \
             patch.object(worker, "binance_account_summary", return_value=("",Decimal(0),Decimal(0),"","")), \
             patch.object(worker, "futures_wallet_summary", return_value=worker.FuturesWallet("USDC", total=Decimal(0), available=Decimal(0))), \
             patch.object(worker, "recover_positions_from_trade_history") as recover, \
             patch.object(worker, "run_portfolio_cycle") as spot, \
             patch.object(worker, "run_short_cycle") as short, \
             patch.object(worker, "save_state") as save, \
             patch.object(worker.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                worker.main()
        recover.assert_not_called()
        spot.assert_not_called()
        short.assert_not_called()
        save.assert_not_called()
        reporter.get_pending_directive.assert_not_called()
        self.assertIn("recovery_locked=True", reporter.record_event.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
