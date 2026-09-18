import { test } from 'node:test';
import assert from 'node:assert/strict';
import { engineSummary, activityDescription, cycleDescription } from '../lib/trading-activity.ts';

const now = Date.parse('2026-01-01T12:00:00Z');
const heartbeat = { id: 1, event_type: 'heartbeat', level: 'info', message: 'live=True;recovery_locked=False;signals=none', created_at: '2026-01-01T11:59:30Z' };

test('stale heartbeat never claims engine is live', () => {
  assert.equal(engineSummary(heartbeat, [], now + 180_000, true, true).label, 'Utdatert motorstatus');
});
test('recovery lock is explained even when signals exist', () => {
  assert.equal(engineSummary({ ...heartbeat, message: 'live=False;recovery_locked=True;signals=BTCUSDC' }, [], now, true, true).label, 'Kun overvåking');
});
test('an error newer than heartbeat is visible', () => {
  const event = { ...heartbeat, id: 2, event_type: 'trading_cycle_error', level: 'error', message: 'quoteOrderQty error', created_at: '2026-01-01T11:59:40Z' };
  assert.equal(engineSummary(heartbeat, [event], now, true, true).label, 'Feil i siste kontroll');
  assert.match(activityDescription(event), /ikke gjennomført/);
});
test('heartbeat alone is not called a successful trading cycle', () => {
  assert.equal(engineSummary(heartbeat, [], now, true, true).label, 'Motoren sender status');
});
test('completed cycle explains daily loss and separate short setting', () => {
  const event = { ...heartbeat, event_type: 'cycle_status', message: 'spot=paused_daily_loss;short=short_disabled' };
  assert.match(engineSummary(heartbeat, [event], now, true, true).detail, /Daglig tapsgrense/);
  assert.match(activityDescription(event), /Shorting er avslått/);
});
test('unknown future cycle codes remain visible instead of hiding status', () => {
  assert.equal(cycleDescription('new_reason:ETHUSDC'), 'new_reason:ETHUSDC');
});
