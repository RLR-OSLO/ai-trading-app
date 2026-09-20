from decimal import Decimal as D
from unittest.mock import Mock, patch

import pytest

from trader.futures_wallet import parse_futures_wallet, read_futures_wallet, funded_notional
from trader.derivatives import BinanceFuturesClient
from trader.binance import BinanceCredentials, BinanceError
from trader import derivatives_live as engine, worker


def account(available='40', **kwargs):
    return {'multiAssetsMargin': False, 'canTrade': True, 'totalWalletBalance': '999', 'availableBalance': '999',
            'assets': [{'asset': 'USDC', 'walletBalance': '63.44', 'availableBalance': available,
                        'positionInitialMargin': '20', 'openOrderInitialMargin': '3.44'}], **kwargs}


def test_single_asset_uses_selected_currency_not_top_level_usdt():
    wallet = parse_futures_wallet(account(), 'USDC')
    assert wallet.total == D('63.44') and wallet.available == D(40)
    assert wallet.position_margin == D(20) and wallet.order_margin == D('3.44')
    assert wallet.status == 'ready'


def test_shared_usd_margin_used_even_if_quote_asset_available_is_zero():
    raw = account('0', multiAssetsMargin=True, totalWalletBalance='101', availableBalance='50',
                  totalPositionInitialMargin='40', totalOpenOrderInitialMargin='11')
    wallet = parse_futures_wallet(raw, 'USDC', D('1.01'))
    assert wallet.total == D(100) and wallet.available == D(50)/D('1.01')
    assert wallet.mode == 'multi' and wallet.status == 'ready'


def test_shared_margin_requires_verified_conversion_not_one_to_one_guess():
    client = Mock()
    client.account.return_value = account('0', multiAssetsMargin=True)
    client.asset_index.return_value = {'index': '0.99'}
    wallet = read_futures_wallet(client, 'USDC')
    assert wallet.available == D(999)/D('.99')
    client.asset_index.assert_called_once_with('USDC')
    assert parse_futures_wallet(client.account.return_value, 'USDC').available is None


def test_zero_quote_does_not_borrow_other_currency_availability():
    raw = account(assets=[{'asset': 'USDT', 'walletBalance': '63', 'availableBalance': '60'}])
    wallet = parse_futures_wallet(raw, 'USDC')
    assert wallet.total == 0 and wallet.available == 0 and wallet.assets == {'USDT': '63'}
    assert wallet.status == 'no_quote_collateral'


@pytest.mark.parametrize('available', ['0', '0E-8', None, 'NaN', 'Infinity'])
def test_wallet_and_withdrawable_balance_never_invent_available_margin(available):
    raw = account(available)
    raw['assets'][0]['maxWithdrawAmount'] = '100'
    wallet = parse_futures_wallet(raw, 'USDC')
    assert funded_notional(wallet, D(250), 1) == 0
    assert wallet.available == (D(0) if available in ('0', '0E-8') else None)


def test_exchange_disabled_or_missing_mode_is_not_tradable():
    assert funded_notional(parse_futures_wallet(account(canTrade=False), 'USDC'), D(250), 1) == 0
    assert parse_futures_wallet(account(multiAssetsMargin=None), 'USDC').available is None


def test_account_fetch_failure_is_unknown_not_zero():
    with patch.object(worker, 'BinanceFuturesClient') as factory:
        factory.return_value.account.side_effect = BinanceError('denied')
        wallet = worker.futures_wallet_summary(BinanceCredentials('test','test'), 'USDC')
    assert wallet.available is None and wallet.total is None and wallet.status == 'read_error'
    assert 'futures_available=unknown' in wallet.heartbeat()


@pytest.mark.parametrize('multi,leverage,requested,expected', [(False,1,'250','39.20'),(True,1,'250','39.20'),(False,3,'250','117.60'),(False,3,'25','25')])
def test_entry_is_funded_without_raising_user_notional(tmp_path, multi, leverage, requested, expected):
    client = Mock()
    client.account.return_value = account(multiAssetsMargin=multi, availableBalance='40')
    client.asset_index.return_value = {'index':'1'}
    client.quantity_for_notional.return_value = D('.1')
    path = tmp_path/'short.json'
    state = engine.DerivativesState(day=engine._today())
    with patch.object(engine, 'BinanceFuturesClient', return_value=client), patch.object(engine, '_complete_short_open', return_value='opened'):
        assert engine._open_futures(None,'ETHUSDC',D(requested),leverage,D('.02'),D('.04'),state,path,None) == 'opened'
    assert client.quantity_for_notional.call_args.kwargs['notional'] == D(expected)
    assert state.pending_open['leverage'] == leverage
    assert client.set_isolated_margin.call_count == (0 if multi else 1)
    assert client.market_order.call_count == 1


def test_zero_margin_sends_no_order_and_creates_no_pending_order(tmp_path):
    client = Mock()
    client.account.return_value = account('0')
    state = engine.DerivativesState(day=engine._today())
    with patch.object(engine, 'BinanceFuturesClient', return_value=client):
        result = engine._open_futures(None,'ETHUSDC',D(250),1,D('.02'),D('.04'),state,tmp_path/'short.json',None)
    assert result == 'futures_margin_in_use'
    assert state.pending_open is None
    client.market_order.assert_not_called()
    client.set_leverage.assert_not_called()


def test_order_minimum_is_checked_after_quantity_rounding():
    client = BinanceFuturesClient(BinanceCredentials('test','test'))
    client.exchange_info_all = lambda: {'symbols':[{'symbol':'BTCUSDC','quantityPrecision':3,'filters':[
        {'filterType':'MARKET_LOT_SIZE','stepSize':'.001','minQty':'.001'},
        {'filterType':'MIN_NOTIONAL','notional':'100'}]}]}
    client.ticker_price = lambda symbol: D(80000)
    with pytest.raises(BinanceError, match='notional below minimum'):
        client.quantity_for_notional(symbol='BTCUSDC',notional=D(110))
