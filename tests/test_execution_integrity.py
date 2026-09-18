from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from trader import portfolio_live as spot, derivatives_live as shorts, worker
from trader.binance import BinanceSpotClient, BinanceError
from trader.journal import flush_reports
from tests.test_portfolio_live import FakeClient
from tests.test_exit_guard_v3 import limits, position


@pytest.mark.parametrize('precision,amount,expected', [
    (8, '18.88888888888888888888888888', '18.88888888'),
    (2, '25.009', '25.00'), (8, '1E-7', '0.00000010'), (0, '7.99', '7'),
])
def test_quote_amount_is_rounded_down_identically_for_test_and_live(precision, amount, expected):
    client = BinanceSpotClient()
    with patch.object(client, 'symbol_info', return_value={'quoteAssetPrecision': precision}), \
         patch.object(client, '_request', return_value={}) as request:
        client.test_market_buy(symbol='BTCUSDC', quote_quantity=D(amount))
        test_amount = request.call_args.args[2]['quoteOrderQty']
        client.market_buy_by_quote(symbol='BTCUSDC', quote_quantity=D(amount), live_trading_enabled=True)
        live_amount = request.call_args.args[2]['quoteOrderQty']
        assert test_amount == live_amount == expected
        assert D(live_amount) <= D(amount)


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1', '0'])
def test_invalid_amount_does_not_contact_exchange(amount):
    client = BinanceSpotClient()
    with patch.object(client, '_request') as request:
        with pytest.raises(ValueError):
            client.test_market_buy(symbol='BTCUSDC', quote_quantity=D(amount))
        request.assert_not_called()


def test_partial_market_sell_preserves_unfilled_position(tmp_path):
    path = tmp_path / 'state.json'
    position(path)
    state = spot.load_state(path)
    client = FakeClient()
    records = []
    with patch.object(client, 'place_spot_order', return_value={
        'status': 'EXPIRED', 'executedQty': '.1', 'cummulativeQuoteQty': '10.2'
    }):
        spot._market_sell(client, state, path, state.positions[0], limits(), records.append, 1000, 'trailing_stop')
    state = spot.load_state(path)
    assert D(state.positions[0].quantity) == D('.15')
    assert D(state.positions[0].quote_spent) == D('15')
    assert D(state.realized_pnl) == D('.2')
    assert records[0]['quantity'] == '0.1'


def test_unknown_order_response_is_not_booked_and_no_second_sell_is_sent(tmp_path):
    path = tmp_path / 'state.json'
    position(path)
    state = spot.load_state(path)
    client = FakeClient()
    records = []
    with patch.object(client, 'place_spot_order', return_value={}) as sell:
        result = spot._market_sell(client, state, path, state.positions[0], limits(), records.append, 1000, 'hard_stop')
        assert result == 'pending_exchange_order:SELL:UNKNOWN'
        assert spot.load_state(path).pending_action == 'SELL:BTCUSDC'
        assert not records
        with patch.object(client, 'query_order', create=True, return_value={'status': 'PARTIALLY_FILLED'}):
            spot.run_portfolio_cycle(client, {}, path, limits(), records.append)
        assert sell.call_count == 1


@pytest.mark.parametrize('side,status', [('BUY', 'CANCELED'), ('SELL', 'EXPIRED')])
def test_reconciliation_records_terminal_partial_fills(tmp_path, side, status):
    path = tmp_path / 'state.json'
    if side == 'SELL':
        position(path)
    state = spot.load_state(path)
    state.pending_action = f'{side}:BTCUSDC'
    state.pending_client_order_id = 'existing-order'
    spot.save_state(path, state)
    client = FakeClient()
    records = []
    with patch.object(client, 'query_order', create=True, return_value={
        'status': status, 'executedQty': '.1', 'cummulativeQuoteQty': '10'
    }):
        spot.run_portfolio_cycle(client, {}, path, limits(), records.append)
    assert len(records) == 1
    assert D(records[0]['quantity']) == D('.1')
    assert spot.load_state(path).pending_action is None


def test_reporting_failure_survives_restart_and_blocks_new_entries(tmp_path, monkeypatch):
    monkeypatch.setenv('EXCHANGE_PROTECTION_ENABLED', 'false')
    path = tmp_path / 'state.json'
    position(path)
    state = spot.load_state(path)
    with patch('builtins.print'):
        spot._finalize_sell(state, path, state.positions[0], D('.25'), D('25.1'), limits(),
                            lambda _: (_ for _ in ()).throw(OSError('offline')))
    restarted = spot.load_state(path)
    original_report = dict(restarted.pending_reports[0])
    assert restarted.positions == []
    client = FakeClient()
    result = spot.run_portfolio_cycle(client, {'ETHUSDC': True}, path, limits(), lambda _: (_ for _ in ()).throw(OSError('offline')))
    assert result == 'paused_reporting_backlog'
    assert client.live_buys == 0
    records = []
    restarted = spot.load_state(path)
    assert flush_reports(restarted, path, spot.save_state, records.append)
    assert records == [original_report]
    assert not spot.load_state(path).pending_reports


def test_spot_respects_combined_daily_loss_and_short_capital(tmp_path):
    client = FakeClient()
    result = spot.run_portfolio_cycle(client, {'BTCUSDC': True}, tmp_path / 's.json', limits(), other_realized_pnl=D('-5'))
    assert result == 'paused_daily_loss'
    result = spot.run_portfolio_cycle(client, {'BTCUSDC': True}, tmp_path / 's.json', limits(), other_open_notional=D('199'))
    assert result == 'capital_cap_reached'
    assert client.live_buys == 0


def test_same_symbol_spot_and_short_are_not_opened_together(tmp_path):
    client = FakeClient()
    spot.run_portfolio_cycle(client, {'BTCUSDC': True}, tmp_path / 's.json', limits(), blocked_symbols=frozenset({'BTCUSDC'}))
    assert client.live_buys == 0
    with patch.object(shorts, '_open_margin') as opening:
        shorts.run_short_cycle(None, {'BTCUSDC': True}, {}, {'short_enabled': True}, tmp_path / 'd.json', spot_open_symbols=frozenset({'BTCUSDC'}))
        opening.assert_not_called()


def test_short_cannot_exceed_total_capital_after_spot_allocation(tmp_path):
    with patch.object(shorts, '_open_margin') as opening:
        result = shorts.run_short_cycle(None, {'BTCUSDC': True}, {},
            {'short_enabled': True, 'trade_cap_usdc': 100}, tmp_path / 'd.json', spot_open_notional=D('98'))
        assert result == 'short_notional_below_minimum'
        opening.assert_not_called()


def test_missing_short_signal_is_not_a_reversal_but_stop_still_applies():
    p = shorts.ShortPosition('margin', 'BTCUSDC', '1', '100', '100', 1, '.015', '.03')
    assert shorts._update_short_position(p, D('99.5'), None) is None
    assert shorts._update_short_position(p, D('102'), None) == 'hard_stop'


def test_three_users_keep_distinct_reporting_state(tmp_path):
    keys = set()
    for user in ('user-a', 'user-b', 'user-c'):
        path = tmp_path / user / 'state.json'
        position(path)
        state = spot.load_state(path)
        spot._finalize_sell(state, path, state.positions[0], D('.25'), D('25.1'), limits(), lambda _: (_ for _ in ()).throw(OSError('offline')))
        keys.add(spot.load_state(path).pending_reports[0]['execution_key'])
    assert len(keys) == 3
    state_a = spot.load_state(tmp_path / 'user-a/state.json')
    flush_reports(state_a, tmp_path / 'user-a/state.json', spot.save_state, lambda _: None)
    assert not spot.load_state(tmp_path / 'user-a/state.json').pending_reports
    assert len(spot.load_state(tmp_path / 'user-b/state.json').pending_reports) == 1
    assert len(spot.load_state(tmp_path / 'user-c/state.json').pending_reports) == 1


def test_partial_short_close_preserves_residual_and_books_actual_fill(tmp_path):
    path = tmp_path / 'short.json'
    state = shorts.DerivativesState(day=shorts._today(), position=shorts.ShortPosition(
        'futures', 'BTCUSDC', '1', '100', '100', 1, '.015', '.03'), pending_close_id='same-order')
    records = []
    result = shorts._finalize_short_close(state, path,
        {'status': 'EXPIRED', 'executedQty': '.4', 'cumQuote': '39.2'}, 'test', records.append)
    assert result.startswith('futures_short_closed:')
    saved = shorts.load_state(path)
    assert saved.position.quantity == '0.6'
    assert saved.position.notional == '60.0'
    assert D(saved.realized_pnl) == D('.8')
    assert D(records[0]['quantity']) == D('.4')


def test_exchange_short_close_is_recorded_from_order_not_ticker(tmp_path):
    path = tmp_path / 'short.json'
    p = shorts.ShortPosition('futures', 'BTCUSDC', '1', '100', '100', 1, '.015', '.03', protection_ids=(55,))
    shorts.save_state(path, shorts.DerivativesState(day=shorts._today(), position=p))
    fake = SimpleNamespace(position_risk=lambda **k: [{'positionAmt': '0'}],
        query_algo=lambda **k: {'actualOrderId': '123'},
        query_order_by_id=lambda **k: {'status': 'FILLED', 'executedQty': '1', 'avgPrice': '98'})
    records = []
    with patch.object(shorts, 'BinanceFuturesClient', return_value=fake):
        result = shorts.run_short_cycle(None, {}, {}, {}, path, records.append, allow_new_entries=False)
    assert 'exchange_protection' in result
    assert records[0]['pnl'] == '2'
    assert shorts.load_state(path).position is None


def test_cancelled_margin_protection_does_not_erase_position(tmp_path):
    path = tmp_path / 'short.json'
    p = shorts.ShortPosition('margin', 'BTCUSDC', '1', '100', '100', 1, '.015', '.03', protection_ids=(55,))
    shorts.save_state(path, shorts.DerivativesState(day=shorts._today(), position=p))
    fake = SimpleNamespace(query_order_list=lambda **k: {'listOrderStatus': 'ALL_DONE', 'orders': [{'orderId': 99}]},
        query_order_by_id=lambda **k: {'status': 'CANCELED', 'executedQty': '0'})
    with patch.object(shorts, 'BinanceMarginClient', return_value=fake):
        result = shorts.run_short_cycle(None, {}, {}, {}, path, allow_new_entries=False)
    assert result.startswith('margin_reconciliation_required:')
    assert shorts.load_state(path).position is not None


def test_pending_short_close_is_read_without_sending_second_order(tmp_path):
    path = tmp_path / 'short.json'
    p = shorts.ShortPosition('futures', 'BTCUSDC', '1', '100', '100', 1, '.015', '.03')
    shorts.save_state(path, shorts.DerivativesState(day=shorts._today(), position=p, pending_close_id='original-close'))
    fake = SimpleNamespace(query_order=lambda **k: {'status': 'FILLED', 'executedQty': '1', 'avgPrice': '99'})
    records = []
    with patch.object(shorts, 'BinanceFuturesClient', return_value=fake):
        result = shorts.run_short_cycle(None, {}, {}, {}, path, records.append, allow_new_entries=False)
    assert 'reconciled_close' in result
    assert len(records) == 1
    assert shorts.load_state(path).pending_close_id is None


def test_pending_short_entry_uses_actual_fill_and_existing_leverage(tmp_path):
    path = tmp_path / 'short.json'
    pending = {'mode': 'futures', 'symbol': 'BTCUSDC', 'client_id': 'original-entry', 'stop': '.015', 'target': '.03',
               'leverage': 2, 'opened_at': 100, 'notional': '100'}
    state = shorts.DerivativesState(day=shorts._today(), pending_open=pending)
    shorts.save_state(path, state)
    fake = SimpleNamespace(query_order=lambda **k: {'status': 'EXPIRED', 'executedQty': '.4', 'avgPrice': '100'},
                           close_algo=lambda **k: {'algoId': 44})
    records = []
    with patch.object(shorts, 'BinanceFuturesClient', return_value=fake):
        result = shorts.run_short_cycle(None, {}, {}, {}, path, records.append, allow_new_entries=False)
    assert result.startswith('futures_short_opened:')
    saved = shorts.load_state(path)
    assert saved.position.quantity == '0.4'
    assert saved.position.leverage == 2
    assert saved.pending_open is None
    assert len(records) == 1


def test_protection_checks_short_even_when_spot_check_fails(tmp_path):
    path, short_path = tmp_path / 'spot.json', tmp_path / 'short.json'
    position(path)
    p = shorts.ShortPosition('futures', 'ETHUSDC', '1', '100', '100', 1, '.015', '.03')
    shorts.save_state(short_path, shorts.DerivativesState(day=shorts._today(), position=p))
    client, reporter = MagicMock(), MagicMock()
    reporter.is_compass = True
    with patch.object(worker, 'run_portfolio_cycle', side_effect=OSError('spot unavailable')) as spot_cycle, \
         patch.object(worker, 'run_short_cycle', return_value='futures_short_holding:ETHUSDC') as short_cycle:
        ready = worker.protect_existing_positions(client, reporter, {'execution_authorized': True}, path, short_path)
    assert not ready
    assert spot_cycle.call_args.kwargs['allow_new_entries'] is False
    assert short_cycle.call_args.kwargs['allow_new_entries'] is False
    assert short_cycle.call_args.args[1] == {}  # Missing market data is not a reversal.


def test_candle_outage_does_not_skip_existing_position_protection(tmp_path, monkeypatch):
    path, short_path = tmp_path / 'spot.json', tmp_path / 'short.json'
    monkeypatch.setenv('LIVE_STATE_PATH', str(path))
    monkeypatch.setenv('DERIVATIVES_STATE_PATH', str(short_path))
    position(path)
    reporter, client = MagicMock(), MagicMock()
    reporter.is_compass = True
    reporter.get_settings.return_value = {'execution_authorized': True, 'bot_enabled': True,
                                          'live_trading_enabled': True, 'quote_asset': 'USDC'}
    with patch.object(worker, 'build_client', return_value=client), \
         patch.object(worker.SupabaseReporter, 'from_env', return_value=reporter), \
         patch.object(worker, 'readiness_check', return_value=True), \
         patch.object(worker, 'active_pairs', return_value=('BTCUSDC',)), \
         patch.object(worker, 'free_quote_balance', return_value=D('25')), \
         patch.object(worker, 'recover_positions_from_trade_history', return_value=[]), \
         patch.object(worker, 'learning_factors', return_value={}), \
         patch.object(worker, 'market_scan', side_effect=OSError('candles unavailable')), \
         patch.object(worker, 'run_portfolio_cycle', return_value='sold:BTCUSDC:pnl=1') as protect, \
         patch.object(worker.time, 'sleep', side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            worker.main()
    protect.assert_called_once()
    assert protect.call_args.kwargs['allow_new_entries'] is False
    assert any(call.args[0] == 'spot_execution' for call in reporter.record_event.call_args_list)
