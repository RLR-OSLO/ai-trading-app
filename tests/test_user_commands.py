from copy import deepcopy
from decimal import Decimal as D
from unittest.mock import patch
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from trader import commands, portfolio_live as spot, derivatives_live as short, worker
from trader.reporting import SupabaseReporter
from tests.test_portfolio_live import FakeClient
from tests.test_exit_guard_v3 import position


class Reporter:
    is_compass = True
    user_id = "account-a"

    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.trades = []
        self.fail_ack = False
        self.cancel_on_claim = False

    def get_commands(self):
        return deepcopy([r for r in self.rows if r["status"] in {"pending", "processing"}])

    def claim_command(self, command_id):
        row = next(r for r in self.rows if r["id"] == command_id)
        if self.cancel_on_claim:
            row["status"] = "cancelled"
            return None
        if row["status"] != "pending":
            return None
        row["status"] = "processing"
        return deepcopy(row)

    def command_result(self, command_id, status, result):
        if self.fail_ack and status == "executed":
            raise OSError("database response lost")
        row = next(r for r in self.rows if str(r["id"]) == str(command_id))
        row.update(status=status, result=result)

    def record_trade(self, row):
        self.trades.append(row)

    def record_event(self, *args):
        pass


def request(action="CLOSE", **kwargs):
    return {"id": "command-1", "user_id": "account-a", "action": action,
        "symbol": "BTCUSDC", "mode": "SPOT", "position_key": "SPOT:BTCUSDC:1",
        "quantity": "0.25", "requested_notional": "25", "leverage": 1,
        "status": "pending", "result": None, **kwargs}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXCHANGE_PROTECTION_ENABLED", "false")
    client = FakeClient()
    client.credentials = object()
    settings = {"quote_asset": "USDC", "risk_profile": "normal", "trade_cap_usdc": "200",
        "order_size_usdc": "25", "max_daily_loss_usdc": "5", "bot_enabled": False,
        "live_trading_enabled": False, "execution_authorized": False}
    return client, settings, tmp_path / "spot.json", tmp_path / "short.json"


def run(env, reporter, **kwargs):
    client, settings, sp, dp = env
    return commands.process_commands(client, reporter, settings, sp, dp, **kwargs)


def test_sell_while_automatic_trading_off_only_closes_confirmed_quantity(env):
    client, settings, sp, dp = env
    position(sp)
    reporter = Reporter([request(quantity="0.1")])
    assert run(env, reporter)
    assert client.live_sells == 1
    assert D(spot.load_state(sp).positions[0].quantity) == D(".15")
    assert reporter.rows[0]["status"] == "executed"
    assert settings["execution_authorized"] is False
    assert not run(env, reporter)
    assert client.live_sells == 1


@pytest.mark.parametrize("wrong", ["SPOT:BTCUSDC:2", "SPOT:ETHUSDC:1"])
def test_old_position_button_never_closes_a_replacement_position(env, wrong):
    client, _, sp, _ = env
    position(sp)
    reporter = Reporter([request(position_key=wrong)])
    run(env, reporter)
    assert reporter.rows[0]["status"] == "rejected"
    assert client.live_sells == 0
    assert spot.load_state(sp).positions


def test_lost_completion_reply_retries_receipt_not_trade(env):
    client, _, sp, _ = env
    position(sp)
    reporter = Reporter([request()])
    reporter.fail_ack = True
    run(env, reporter)
    assert client.live_sells == 1
    assert spot.load_state(sp).command_receipts
    reporter.fail_ack = False
    run(env, reporter)
    assert client.live_sells == 1
    assert len(reporter.trades) == 1
    assert reporter.rows[0]["status"] == "executed"


def test_lost_exchange_response_reconciles_original_order_without_resubmission(env):
    client, _, sp, _ = env
    position(sp)
    reporter = Reporter([request()])
    with patch.object(client, "place_spot_order", side_effect=OSError("reply lost")) as order:
        run(env, reporter)
        original = spot.load_state(sp).pending_client_order_id
        with patch.object(client, "query_order", create=True, return_value={
            "status": "FILLED", "executedQty": ".25", "cummulativeQuoteQty": "26"
        }) as query:
            run(env, reporter)
        assert query.call_args.kwargs["orig_client_order_id"] == original
        assert order.call_count == 1
    assert reporter.rows[0]["status"] == "executed"
    assert not spot.load_state(sp).positions


def test_nonterminal_partial_fill_waits_and_terminal_partial_records_actual_fill(env):
    client, _, sp, _ = env
    position(sp)
    reporter = Reporter([request()])
    with patch.object(client, "place_spot_order", return_value={"status": "PARTIALLY_FILLED"}) as order:
        run(env, reporter)
        with patch.object(client, "query_order", create=True, return_value={"status": "PARTIALLY_FILLED"}):
            run(env, reporter)
        assert reporter.rows[0]["status"] == "processing"
        assert not reporter.trades
        with patch.object(client, "query_order", create=True, return_value={
            "status": "EXPIRED", "executedQty": ".1", "cummulativeQuoteQty": "10.1"
        }):
            run(env, reporter)
        assert order.call_count == 1
    assert D(spot.load_state(sp).positions[0].quantity) == D(".15")
    assert reporter.trades[0]["quantity"] == "0.1"
    assert reporter.rows[0]["status"] == "executed"


def test_cancellation_winning_claim_race_submits_nothing(env):
    client, _, sp, _ = env
    position(sp)
    reporter = Reporter([request()])
    reporter.cancel_on_claim = True
    run(env, reporter)
    assert client.live_sells == 0
    assert reporter.rows[0]["status"] == "cancelled"


@pytest.mark.parametrize("active_local", [False, True])
def test_restart_after_claim_before_order_never_blindly_replays(env, active_local):
    client, _, sp, _ = env
    position(sp)
    row = request(status="processing")
    if active_local:
        state = spot.load_state(sp)
        state.active_command = row
        spot.save_state(sp, state)
    reporter = Reporter([row])
    run(env, reporter)
    assert client.live_sells == 0
    assert reporter.rows[0]["status"] == "rejected"


def test_three_accounts_do_not_consume_each_others_commands_or_state(env, tmp_path):
    client, settings, _, _ = env
    for user in ["account-a", "account-b", "account-c"]:
        sp, dp = tmp_path / user / "spot.json", tmp_path / user / "short.json"
        position(sp)
        reporter = Reporter([request(user_id="account-b")])
        reporter.user_id = user
        commands.process_commands(client, reporter, settings, sp, dp)
        assert bool(spot.load_state(sp).positions) == (user != "account-b")
    assert client.live_sells == 1


def test_priority_waits_for_signal_then_buys_exact_requested_amount(env):
    client, _, sp, _ = env
    state = spot.load_state(sp)
    state.trades_today = 1000
    state.cooldown_until = 9999999999
    state.reentry_blocks["BTCUSDC"] = {"until": 9999999999, "signal_reset": False}
    spot.save_state(sp, state)
    reporter = Reporter([request("PRIORITY_OPEN", requested_notional="6")])
    assert not run(env, reporter, signals={"BTCUSDC": False})
    assert reporter.rows[0]["status"] == "pending"
    assert "signal" in reporter.rows[0]["result"]
    with patch.object(client, "market_buy_by_quote", return_value={
        "status": "FILLED", "executedQty": ".06", "cummulativeQuoteQty": "6", "fills": []
    }) as order:
        run(env, reporter, signals={"BTCUSDC": True})
        assert order.call_args.kwargs["quote_quantity"] == D("6")
    assert reporter.rows[0]["status"] == "executed"
    assert spot.load_state(sp).positions[0].user_managed


@pytest.mark.parametrize("change,reason", [({"realized_pnl": "-5"}, "paused_daily_loss"), ({}, "capital_cap_reached")])
def test_user_priority_respects_chosen_loss_and_combined_capital(env, change, reason):
    client, _, sp, dp = env
    state = spot.load_state(sp)
    for key, value in change.items():
        setattr(state, key, value)
    spot.save_state(sp, state)
    if not change:
        short.save_state(dp, short.DerivativesState(day=short._today(), position=short.ShortPosition(
            "futures", "ETHUSDC", "2", "100", "200", 1, ".015", ".03")))
    reporter = Reporter([request("PRIORITY_OPEN")])
    run(env, reporter, signals={"BTCUSDC": True})
    assert client.live_buys == 0
    assert reporter.rows[0]["result"] == reason


def test_new_manual_position_gets_exits_without_enabling_old_recovered_positions(env):
    client, settings, sp, dp = env
    state = spot.load_state(sp)
    state.positions = [spot.Position("BTCUSDC", ".25", "100", "25", 1),
                      spot.Position("ETHUSDC", ".25", "100", "25", 2, user_managed=True)]
    spot.save_state(sp, state)
    client.price = D("90")
    reporter = Reporter([])
    worker.protect_existing_positions(client, reporter, settings, sp, dp)
    assert client.live_sells == 1
    assert [p.symbol for p in spot.load_state(sp).positions] == ["BTCUSDC"]


def test_prioritized_buy_waits_for_same_symbol_position_to_close(env):
    client, _, sp, _ = env
    position(sp)
    reporter = Reporter([request("PRIORITY_OPEN")])
    run(env, reporter, signals={"BTCUSDC": True})
    assert reporter.rows[0]["status"] == "pending"
    assert client.live_buys == client.live_sells == 0


def test_dashboard_auto_trading_has_no_hidden_daily_count_quota(env):
    client, settings, sp, _ = env
    state = spot.load_state(sp)
    state.trades_today = 14
    spot.save_state(sp, state)
    result = spot.run_portfolio_cycle(client, {"BTCUSDC": True}, sp, spot.PortfolioLimits.from_settings(settings))
    assert result.startswith("bought:")
    assert client.live_buys == 1


def test_futures_close_uses_reduce_only_and_preserves_unfilled_quantity(env):
    client, _, _, dp = env
    short.save_state(dp, short.DerivativesState(day=short._today(), position=short.ShortPosition(
        "futures", "BTCUSDC", "1", "100", "100", 1, ".015", ".03")))
    reporter = Reporter([request(mode="FUTURES", position_key="FUTURES:BTCUSDC:1", quantity=".4")])
    with patch.object(short, "BinanceFuturesClient") as factory:
        factory.return_value.market_order.return_value = {"status": "FILLED", "executedQty": ".4", "cumQuote": "39"}
        run(env, reporter)
        assert factory.return_value.market_order.call_args.kwargs["reduce_only"] is True
        assert factory.return_value.market_order.call_args.kwargs["quantity"] == D(".4")
    assert D(short.load_state(dp).position.quantity) == D(".6")
    assert reporter.rows[0]["status"] == "executed"


def test_snapshot_is_from_tracked_positions_not_entire_wallet(env):
    _, _, sp, dp = env
    position(sp)
    assert commands.position_snapshot(sp, dp)[0]["quantity"] == "0.25"
    assert len(commands.position_snapshot(sp, dp)) == 1


def test_stale_margin_close_cannot_create_a_long_position(env):
    _, _, _, dp = env
    short.save_state(dp, short.DerivativesState(day=short._today(), position=short.ShortPosition(
        "margin", "BTCUSDC", "1", "100", "100", 1, ".015", ".03")))
    reporter = Reporter([request(mode="MARGIN", position_key="MARGIN:BTCUSDC:1", quantity="1")])
    with patch.object(short, "BinanceMarginClient") as factory:
        factory.return_value.margin_account.return_value = {"userAssets": [{"asset": "BTC", "netAsset": "0"}]}
        factory.return_value.symbol_info.return_value = FakeClient().symbol_info("BTCUSDC")
        run(env, reporter)
        factory.return_value.market_order.assert_not_called()
    assert reporter.rows[0]["status"] == "rejected"


def test_uncertain_manual_order_does_not_get_relabelled_as_an_automatic_exit(env):
    client, settings, sp, dp = env
    settings["execution_authorized"] = True
    position(sp, user_managed=True)
    state = spot.load_state(sp)
    state.active_command = request()
    spot.save_state(sp, state)
    client.price = D("90")
    assert worker.protect_existing_positions(client, Reporter([]), settings, sp, dp) is False
    assert client.live_sells == 0


def test_claim_uses_owner_status_and_expiry_compare_and_set():
    reporter = SupabaseReporter("https://example.supabase.co", "secret", "account-a")
    with patch("urllib.request.urlopen") as call:
        call.return_value.__enter__.return_value.read.return_value = b'[]'
        assert reporter.claim_command("command-1") is None
        request = call.call_args.args[0]
        filters = parse_qs(urlsplit(request.full_url).query)
        assert filters["user_id"] == ["eq.account-a"]
        assert filters["status"] == ["eq.pending"]
        assert filters["expires_at"] == ["gt.now()"]
        assert json.loads(request.data)["status"] == "processing"
