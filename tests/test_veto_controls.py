from decimal import Decimal as D
from unittest.mock import patch
import pytest
from trader.analysis import analyze_market, entry_vetoes
from trader.directional import analyze_bearish_market
from trader.worker import market_scan
from tests.test_analysis import straight_candles
from types import SimpleNamespace
from trader.scalping import analyze_scalp

@pytest.mark.parametrize('rsi,atr,expected',[(75,8,('rsi_high',)),(35,8,('rsi_low',)),(50,'8.001',('atr',)),('74.99',8,()),('35.01',8,())])
def test_exact_veto_boundaries(rsi,atr,expected):
    assert entry_vetoes(D(str(rsi)),D(str(atr)))==expected


def test_one_override_does_not_disable_other_vetoes():
    assert entry_vetoes(D(90),D(9),{'ignore_rsi_high_veto':True})==('atr',)
    for value in ('true',1,None,False):
        assert entry_vetoes(D(90),D(1),{'ignore_rsi_high_veto':value})==('rsi_high',)


def test_overheated_trend_requires_explicit_override_and_preserves_score():
    frames={interval:straight_candles(D(1)) for interval in ('15m','1h','4h')}
    strict=analyze_market(frames)
    relaxed=analyze_market(frames,{'ignore_rsi_high_veto':True})
    assert not strict.signal and relaxed.signal
    assert strict.score==relaxed.score
    assert 'risk_veto' not in relaxed.reasons
    assert 'short_risk_veto' in analyze_bearish_market(frames).reasons


def test_scan_applies_override_to_long_signals_and_reports_actual_policy():
    client=SimpleNamespace(klines=lambda *a,**k:straight_candles(D(1),count=101))
    news=SimpleNamespace(score=lambda:SimpleNamespace(blocks_new_positions=False,score=0,fresh_headlines=0))
    with patch('trader.worker.analyze_scalp',return_value=SimpleNamespace(signal=False,score=0)):
        strict=market_scan(client,news,('BTCUSDC',),'normal')
        relaxed=market_scan(client,news,('BTCUSDC',),'normal',{'ignore_rsi_high_veto':True})
    assert not strict[0]['BTCUSDC'] and relaxed[0]['BTCUSDC']
    assert not relaxed[1]['BTCUSDC']
    assert 'veto_ignored=rsi_high;' in relaxed[-1]
    assert 'indicators=BTCUSDC:100.00:' in relaxed[-1]


def test_upgrade_refuses_any_activated_account():
    from recovery.update_compass_server import require_unactivated
    safe={'bot_enabled':False,'live_trading_enabled':False,'execution_authorized':False}
    require_unactivated([safe])
    for flag in safe:
        with pytest.raises(RuntimeError):
            require_unactivated([safe,{**safe,flag:True}])
    with pytest.raises(RuntimeError):
        require_unactivated([])


@pytest.mark.parametrize('rsi,atr,override', [(25,1,'rsi_low'),(70,1,'rsi_high'),(45,'8.01','atr')])
def test_short_override_disables_only_selected_rule(rsi, atr, override):
    assert entry_vetoes(D(str(rsi)), D(str(atr)), short=True) == (override,)
    assert entry_vetoes(D(str(rsi)), D(str(atr)), {'ignore_'+override+'_veto': True}, short=True) == ()
    assert entry_vetoes(D(20), D(9), {'ignore_rsi_low_veto': True}, short=True) == ('atr',)


def test_short_override_reaches_entry_signal_and_does_not_leak_to_other_accounts():
    client = SimpleNamespace(klines=lambda *a, **k: straight_candles(D('-.1'), count=101))
    news = SimpleNamespace(score=lambda: SimpleNamespace(blocks_new_positions=False, score=0, fresh_headlines=0))
    strict = market_scan(client, news, ('BTCUSDC',), 'extreme', {})
    relaxed = market_scan(client, news, ('BTCUSDC',), 'extreme', {'ignore_rsi_low_veto': True})
    third = market_scan(client, news, ('BTCUSDC',), 'extreme', {})
    assert not strict[1]['BTCUSDC'] and relaxed[1]['BTCUSDC'] and not third[1]['BTCUSDC']
    assert strict[3]['BTCUSDC'].score == relaxed[3]['BTCUSDC'].score == 7
    assert 'short_risk_veto' not in relaxed[3]['BTCUSDC'].reasons
    assert 'veto_controls=v2;short_threshold=7;' in relaxed[-1]


def test_ignoring_short_veto_does_not_lower_signal_threshold():
    frames = {i: straight_candles(D('-.1')) for i in ('15m','1h','4h')}
    frames['4h'] = straight_candles(D('.1'))
    analysis = analyze_bearish_market(frames, {'ignore_rsi_low_veto': True})
    assert 'short_risk_veto' not in analysis.reasons
    assert analysis.score < 7 and not analysis.signal


def test_scalp_high_rsi_override_keeps_price_move_limit():
    frames = {i: straight_candles(D('.1')) for i in ('1m','5m')}
    strict = analyze_scalp(frames)
    relaxed = analyze_scalp(frames, veto_overrides={'ignore_rsi_high_veto': True})
    assert not strict.signal and relaxed.signal and strict.score == relaxed.score
    frames['1m'][-1][4] = str(D(frames['1m'][-1][4]) * D('1.04'))
    assert not analyze_scalp(frames, veto_overrides={'ignore_rsi_high_veto': True}).signal
