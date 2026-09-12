from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from trader import derivatives_live as shorts
from trader import portfolio_live as spot
from trader import worker
from trader.binance import BinanceError
from tests.test_portfolio_live import FakeClient


def limits():
    return spot.PortfolioLimits.from_values('200', '25', '1', '2', '5',
        max_trades=80, cooldown=30, max_positions=3)


def position(path, **kwargs):
    pos = spot.Position('BTCUSDC', '0.25', '100', '25', 1, **kwargs)
    spot.save_state(path, spot.PortfolioState(day=spot._today(), positions=[pos]))
    return pos


def test_profit_guard_survives_restart_and_realizes_reversal(tmp_path, monkeypatch):
    monkeypatch.setenv('EXCHANGE_PROTECTION_ENABLED', 'false')
    path = tmp_path / 'state.json'
    position(path)
    client = FakeClient()
    client.price = D('100.65')  # below 2% full trailing activation
    spot.run_portfolio_cycle(client, {}, path, limits(), allow_new_entries=False)
    assert client.live_sells == 0
    assert D(spot.load_state(path).positions[0].peak_price) == D('100.65')
    client.price = D('100.34')
    result = spot.run_portfolio_cycle(client, {}, path, limits(), allow_new_entries=False)
    assert 'reason=profit_guard' in result
    assert client.live_sells == 1


def test_profit_guard_does_not_block_hard_stop_or_require_profit(tmp_path, monkeypatch):
    monkeypatch.setenv('EXCHANGE_PROTECTION_ENABLED', 'false')
    path = tmp_path / 'state.json'
    position(path)
    client = FakeClient()
    client.price = D('98')
    result = spot.run_portfolio_cycle(client, {}, path, limits(), allow_new_entries=False)
    assert 'reason=hard_stop' in result
    assert client.live_sells == 1


def test_trailing_profit_floor_covers_acquisition_cost(tmp_path, monkeypatch):
    monkeypatch.setenv('EXCHANGE_PROTECTION_ENABLED', 'false')
    path = tmp_path / 'state.json'
    pos = position(path, stop_fraction='0.10', target_fraction='0.008')
    state = spot.load_state(path)
    state.positions[0].quote_spent = '25.025'  # acquisition fee in basis
    spot.save_state(path, state)
    client = FakeClient()
    client.price = D('100.9')
    spot.run_portfolio_cycle(client, {}, path, limits(), allow_new_entries=False)
    trailing = spot.load_state(path).positions[0]
    assert D(trailing.trailing_stop_price) >= D('100.1') * D('1.0035')
    assert D(trailing.trailing_stop_price) < client.price


def test_losing_exit_requires_pause_and_new_signal_even_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('EXCHANGE_PROTECTION_ENABLED', 'false')
    path = tmp_path / 'state.json'
    position(path)
    state = spot.load_state(path)
    with patch.object(spot.time, 'time', return_value=1000):
        spot._finalize_sell(state, path, state.positions[0], D('.25'), D('24.85'), limits(), None)
    client = FakeClient()
    with patch.object(spot.time, 'time', return_value=1901):
        spot.run_portfolio_cycle(client, {'BTCUSDC': True}, path, limits())
        assert client.live_buys == 0  # old signal still on
        spot.run_portfolio_cycle(client, {}, path, limits())
        assert 'BTCUSDC' in spot.load_state(path).reentry_blocks
        spot.run_portfolio_cycle(client, {'BTCUSDC': False}, path, limits())
        spot.run_portfolio_cycle(client, {'BTCUSDC': True}, path, limits())
        assert client.live_buys == 1


def test_negative_signal_does_not_shorten_loss_pause(tmp_path):
    path = tmp_path / 'state.json'
    spot.save_state(path, spot.PortfolioState(day=spot._today(),
        reentry_blocks={'BTCUSDC': {'until': 1900, 'signal_reset': False}}))
    client = FakeClient()
    with patch.object(spot.time, 'time', return_value=1100):
        spot.run_portfolio_cycle(client, {'BTCUSDC': False}, path, limits())
        spot.run_portfolio_cycle(client, {'BTCUSDC': True}, path, limits())
    assert client.live_buys == 0


@pytest.mark.parametrize('reasons,expected', [
    (('15m_trend', '1h_trend', 'risk_veto'), False),
    (('1h_trend',), False),
    (('15m_trend', '1h_trend'), True),
])
def test_scalp_cannot_bypass_higher_timeframe_risk_veto(reasons, expected):
    analysis = SimpleNamespace(score=7, reasons=reasons, volume_ratio_15m=D('1.2'))
    scalp = SimpleNamespace(signal=True, score=7)
    bearish = SimpleNamespace(score=1, reasons=())
    client = SimpleNamespace(klines=lambda *a, **k: [[], []])
    news = SimpleNamespace(score=lambda: SimpleNamespace(blocks_new_positions=False, score=0, fresh_headlines=0))
    with patch.object(worker, 'analyze_market', return_value=analysis), \
         patch.object(worker, 'analyze_scalp', return_value=scalp), \
         patch.object(worker, 'analyze_bearish_market', return_value=bearish), \
         patch.object(worker, 'bullish_btc_regime', return_value=False), \
         patch.object(worker, 'bullrun_candidate', return_value=False):
        signals, *_ = worker.market_scan(client, news, ('BTCUSDC',), 'extreme')
    assert signals['BTCUSDC'] is expected


def test_failed_short_open_is_not_retried_next_cycle(tmp_path):
    path = tmp_path / 'short.json'
    settings = {'short_enabled': True, 'futures_enabled': True, 'risk_profile': 'extreme'}
    with patch.object(shorts, '_open_futures', side_effect=BinanceError('Margin is insufficient.')) as opening:
        with pytest.raises(BinanceError):
            shorts.run_short_cycle(None, {'BTCUSDC': True}, {}, settings, path)
        assert shorts.run_short_cycle(None, {'BTCUSDC': True}, {}, settings, path) == 'short_cooldown'
        assert opening.call_count == 1


def test_short_cooldown_does_not_skip_management_of_existing_position(tmp_path):
    path = tmp_path / 'short.json'
    pos = shorts.ShortPosition('futures', 'BTCUSDC', '.001', '100', '.1', 1, '.015', '.03')
    shorts.save_state(path, shorts.DerivativesState(day=shorts._today(), position=pos, cooldown_until=99999999999))
    fake = SimpleNamespace(position_risk=lambda **k: [{'positionAmt': '-.001'}], ticker_price=lambda s: D('102'))
    with patch.object(shorts, 'BinanceFuturesClient', return_value=fake), \
         patch.object(shorts, '_close_futures', return_value='closed') as close:
        assert shorts.run_short_cycle(None, {}, {}, {}, path) == 'closed'
        assert close.call_args.args[3] == 'hard_stop'
