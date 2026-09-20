import { test } from 'node:test';
import assert from 'node:assert/strict';
import { futuresWallet, walletNumber } from '../lib/trading-wallet.ts';

test('complete numbers retain exponents and signs', () => {
  assert.equal(walletNumber('0E-8'), 0);
  assert.equal(walletNumber('1E-8'), .00000001);
  assert.equal(walletNumber('-12.5'), -12.5);
  for (const raw of [undefined, '', 'unknown', 'NaN', 'Infinity']) assert.equal(walletNumber(raw), null);
});
test('reported availability stays distinct from cash, open orders and position margin', () => {
  const wallet = futuresWallet('futures_wallet_version=v2;futures_total=63.44;futures_available=0E-8;futures_position_margin=0;futures_order_margin=0;futures_value=63.44;futures_status=no_available_margin', true);
  assert.equal(wallet.total, 63.44);
  assert.equal(wallet.available, 0);
  assert.equal(wallet.positionMargin, 0);
  assert.equal(wallet.tradable, 0);
});
test('stale, failed and legacy balances cannot suggest new futures orders', () => {
  for (const [message, fresh] of [['futures_available=60;futures_status=ready',false],['futures_available=unknown;futures_status=read_error',true],['futures_available=60',true]]) {
    assert.equal(futuresWallet(message,fresh).tradable,0);
  }
});
test('shared margin and currencies are shown without adding unrelated cash', () => {
  const wallet = futuresWallet('futures_available=40;futures_status=ready;futures_assets=USDC:63.44,USDT:10', true);
  assert.equal(wallet.tradable,40);
  assert.deepEqual(wallet.assets,[{asset:'USDC',balance:63.44},{asset:'USDT',balance:10}]);
});
