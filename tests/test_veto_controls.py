from decimal import Decimal as D
from unittest.mock import patch
import pytest
from trader.analysis import analyze_market, entry_vetoes
from trader.directional import analyze_bearish_market
from trader.worker import market_scan
from tests.test_analysis import straight_candles
from types import SimpleNamespace

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
