import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from deploy import update_active_worker as update


def service_files(tmp_path):
    root, backup = tmp_path / "state", tmp_path / "backup"
    root.mkdir()
    backup.mkdir()
    state = root / "live-state.json"
    state.write_text(json.dumps({"positions": [{"symbol": "ETHUSDC", "quantity": "0.12"}], "trades_today": 14}))
    other = root / "users" / "second-user" / "live-state.json"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps({"positions": [], "trades_today": 4}))
    override = tmp_path / "40-compass.conf"
    original = b"[Service]\nWorkingDirectory=/opt/ai-trading-compass-old\nExecStart=\nExecStart=/usr/bin/python3 -m trader.manager\n"
    override.write_bytes(original)
    replacement = update.rewrite_working_directory(original, Path("/opt/ai-trading-compass-new"))
    return root, backup, override, original, replacement


@pytest.mark.parametrize("field", update.PENDING_FIELDS)
def test_pending_orders_and_reports_block_update(field):
    with pytest.raises(update.Stop, match="Uavklart"):
        update.require_settled({"live-state.json": json.dumps({field: "pending"}).encode()})


def test_open_positions_are_preserved_and_do_not_block_software_update():
    update.require_settled({"live-state.json": b'{"positions":[{"symbol":"ETHUSDC","quantity":"1"}]}'} )


def test_state_reader_includes_all_users_and_rejects_links(tmp_path):
    root, *_ = service_files(tmp_path)
    assert set(update.read_states(root)) == {"live-state.json", "users/second-user/live-state.json"}
    (root / "linked").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(update.Stop, match="Symbolsk"):
        update.read_states(root)


def test_config_rewrite_changes_only_working_directory():
    source = b"[Service]\nWorkingDirectory=/opt/ai-trading-compass-old\nExecStart=\nExecStart=/usr/bin/python3 -m trader.manager\nEnvironment=EXISTING_FLAG=1\n"
    assert update.rewrite_working_directory(source, Path("/opt/ai-trading-compass-new")) == source.replace(b"compass-old", b"compass-new")
    with pytest.raises(update.Stop):
        update.rewrite_working_directory(source + b"WorkingDirectory=/unexpected\n", Path("/opt/ai-trading-compass-new"))
    with pytest.raises(update.Stop):
        update.rewrite_working_directory(source, Path("/tmp/unsafe"))


def test_switch_backs_up_both_users_and_never_rewrites_their_state(tmp_path):
    root, backup, override, original, replacement = service_files(tmp_path)
    before = update.read_states(root)
    callback = Mock()
    with patch.object(update, "run") as run, patch.object(update, "property_value", side_effect=["0", "inactive"]):
        update.switch_service(override, replacement, root, backup, callback)
    assert update.read_states(root) == before
    for name, raw in before.items():
        assert (backup / "state" / name).read_bytes() == raw
    assert (backup / "40-compass.conf").read_bytes() == original
    assert override.read_bytes() == replacement
    assert [call.args for call in run.call_args_list] == [
        ("systemctl", "stop", update.SERVICE), ("systemctl", "daemon-reload"), ("systemctl", "start", update.SERVICE)]
    callback.assert_called_once()


def test_pending_order_after_stop_restores_old_code_without_restoring_state(tmp_path):
    root, backup, override, original, replacement = service_files(tmp_path)
    state = root / "live-state.json"
    pending = b'{"pending_action":"BUY:BTCUSDC","pending_client_order_id":"original"}'

    def command(*args):
        if args[:2] == ("systemctl", "stop"):
            state.write_bytes(pending)
        return ""

    with patch.object(update, "run", side_effect=command) as run, \
         patch.object(update, "property_value", side_effect=["0", "inactive"]):
        with pytest.raises(update.Stop, match="Uavklart"):
            update.switch_service(override, replacement, root, backup, Mock())
    assert override.read_bytes() == original
    assert state.read_bytes() == pending
    assert run.call_args.args == ("systemctl", "start", update.SERVICE)


def test_external_change_before_start_aborts_without_overwriting_accounts(tmp_path):
    root, backup, override, original, replacement = service_files(tmp_path)
    before = update.read_states(root)
    with patch.object(update, "run"), patch.object(update, "property_value", side_effect=["0", "inactive"]):
        with pytest.raises(update.Stop, match="Kontoinnstillingene"):
            update.switch_service(override, replacement, root, backup,
                lambda: update.require_unchanged_settings([{"live": False}], [{"live": True}]))
    assert override.read_bytes() == original
    assert update.read_states(root) == before


def test_no_blind_rollback_after_new_process_could_have_run(tmp_path):
    root, backup, override, original, replacement = service_files(tmp_path)
    changed = b'{"pending_open":{"client_id":"preserve-exchange-evidence"}}'

    def command(*args):
        if args[:2] == ("systemctl", "start"):
            (root / "live-state.json").write_bytes(changed)
            raise update.Stop("start failed after fork")
        return ""

    with patch.object(update, "run", side_effect=command) as run, \
         patch.object(update, "property_value", side_effect=["0", "inactive"]):
        with pytest.raises(update.Stop, match="after fork"):
            update.switch_service(override, replacement, root, backup, Mock())
    assert override.read_bytes() == replacement
    assert (root / "live-state.json").read_bytes() == changed
    assert sum(call.args[:2] == ("systemctl", "start") for call in run.call_args_list) == 1


def event(uid, kind, message="", stamp="2026-09-18T14:30:00+00:00"):
    return {"user_id": uid, "event_type": kind, "message": message, "created_at": stamp}


def test_health_requires_both_accounts_new_engine_and_completed_live_cycle():
    rows = [event("owner", "heartbeat", "engine=execution-integrity-v4;recovery_locked=True"),
            event("second", "heartbeat", "engine=execution-integrity-v4;recovery_locked=False")]
    expected = {"owner": False, "second": True}
    assert not update.health_ready(rows, expected)
    rows.append(event("second", "cycle_status", "spot=paused_trade_limit;short=short_disabled"))
    assert update.health_ready(rows, expected)
    rows.append(event("second", "trading_cycle_error", "error", "2026-09-18T14:30:01+00:00"))
    assert not update.health_ready(rows, expected)
    rows.append(event("second", "cycle_status", "spot=no_signal", "2026-09-18T14:30:02+00:00"))
    assert update.health_ready(rows, expected)


def test_old_heartbeat_or_changed_authorization_cannot_pass_health():
    assert not update.health_ready([event("owner", "heartbeat", "engine=exit-guard-v3;recovery_locked=True")], {"owner": False})
    assert not update.health_ready([event("owner", "heartbeat", "engine=execution-integrity-v4;recovery_locked=False")], {"owner": False})
    assert not update.health_ready([], {})


def test_database_access_is_read_only_and_modern_key_is_not_jwt():
    response = Mock()
    response.read.return_value = b"[]"
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    with patch.object(update.urllib.request, "urlopen", return_value=response) as request:
        assert update.api_read("/rest/v1/bot_settings?select=*", "sb_secret_test_only") == []
    sent = request.call_args.args[0]
    assert sent.method == "GET"
    assert sent.data is None
    assert sent.get_header("Authorization") is None
