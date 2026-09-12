# Exit guard v3

This change addresses repeated entries on an unchanged signal and gaps in spot
profit protection. It is a behaviour correction, not evidence of a profitable
strategy. Unit tests validate execution rules; out-of-sample performance remains
unverified.

## Behaviour

- Swing entries require both 15-minute and hourly rising trends in addition to
  the existing score and risk veto.
- Scalp entries must respect the 15-minute trend and higher-timeframe risk veto.
  The existing 0.6% scalp hard stop is retained. Stops are not widened on existing
  positions and leverage and capital settings are unchanged.
- Following a spot sale, the same symbol needs a signal observed off and a pause
  before it can be bought again: 15 minutes after a loss, 5 minutes otherwise.
  A symbol missing from a rotating universe does not count as an off signal.
  These blocks survive worker restarts and daily loss resets.
- Spot positions retain their observed high from every management cycle. After
  reaching 0.6% above the larger of entry price and allocated acquisition cost,
  a reversal to 0.35% above that basis triggers a market exit. This operates before
  the full trend trail activates and permits winners to continue rising.
- The 0.35% floor also bounds the ordinary trailing stop. This is a configured
  execution buffer, not an exact net fee calculation. Gaps, fees and slippage can
  still produce a loss. Existing hard stops remain active.
- A timer alone no longer exits an underwater scalp. The existing profitable
  timeout and hard stops still apply.
- Short exits, exchange-detected closures and failed short opens have a 5-minute
  pause before new entries. Open positions are still managed during this pause.
- Execution results, including exit reasons, are recorded in bot_events.
  Heartbeats include `engine=exit-guard-v3` to verify the running backend.

## Existing accounting and remaining limitations

The earlier partial-sale cost-basis fix remains intact. Historical database
records are not rewritten from price differences alone: exchange fills and
commissions are needed for an authoritative net-P&L reconciliation. Existing
futures records can also omit fees and exchange-side closure P&L.

Market scans and balance/news reads precede position management in the existing
worker loop. The guard uses sampled prices, not a continuous exchange-side stop;
it cannot capture a peak missed between samples. This patch does not claim to
resolve that architecture or convert losing entries into profitable trades.

## Deployment verification

The backend runs on DigitalOcean. A dashboard deployment does not update it.
From an existing clean backend checkout, fast-forward to the tested main commit,
run the Python suite, then restart `ai-trading-app.service`. Do not run historical
upgrade scripts or reset state files. Verify a new heartbeat with the engine
marker and use `spot_execution` / `short_execution` events for exit diagnosis.

Validation: `python -m pytest -q` (77 passing tests at authoring).
