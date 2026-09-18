# Execution integrity and visible activity

This release fixes observed order-format failures, missing reporting and account-level risk accounting. It does not establish a profitable strategy or change account activation, leverage, credentials, membership, MFA or recovery authorization.

## Changes

- Spot quote amounts use the symbol's quote precision, round down and use fixed decimal notation for both test and real requests.
- Position accounting uses terminal exchange statuses and executed quantities. Terminal partial fills retain the remaining position; ambiguous replies stay pending and are queried before another order.
- Short entries and closes checkpoint their client order ID before submission. Exchange-triggered exits require a confirmed executed order and fill price before recording profit or removing a position.
- Each account's existing atomic state contains a reporting outbox. Retry preserves the execution ID and original timestamp. The additive database unique index `(user_id, execution_key)` prevents duplicate reporting in Compass.
- Spot and short entries share the configured notional cap and realized daily loss limit. Opposite positions in the same symbol are excluded. Reporting/reconciliation backlog blocks new entries while existing exits continue.
- A missing short symbol in the rotating market list is no longer treated as a confirmed reversal. Existing hard stops, targets and trailing rules remain.
- Existing positions are checked before candle, news and history dependencies. Spot and short protection checks are isolated from one another. Recovery-locked accounts still perform no position mutations or orders. This does not protect against an unavailable exchange, unavailable settings or a stopped process.
- The BTC regime uses actual BTC candles even when BTC is absent from the rotating list. Expired priority instructions are expired first; execution attribution requires the requested symbol.
- The dashboard exposes latest bot trade, heartbeat, completed-cycle status and relevant errors near the top. Polling is 15 seconds and on focus. Unsaved settings and changes during a fetch are preserved. Queries explicitly filter by account in addition to existing RLS/MFA policies.
- The result display distinguishes recorded P&L from fully reconciled net P&L. The 0.10% fee example is explicitly an assumption.

## Verification

Local validation: 116 Python tests, six Node activity tests and a Next production build. New tests cover amount precision, terminal partial fills, unknown responses, reporting retry, combined caps/losses, opposite-symbol exclusion, account-separated outboxes, short reconciliation, recovery authorization and candle outages during protection. No test submits a live order.

Production database verification used read-only transactions with authenticated JWT claims to test cross-account denial, an unknown future account and the existing MFA requirement. No account settings or membership records were changed. The nullable execution key migration preserves old rows and old worker compatibility.

## Deployment boundaries

The existing GitHub Actions Vercel workflow publishes the dashboard on main. It does not deploy the Python worker. The worker release identifier is `execution-integrity-v4`; deployment is only confirmed when an account heartbeat reports this version and successful cycle evidence follows.

The active systemd service uses an override pointing to a versioned Compass checkout. An old `/opt/ai-trading-app` checkout is not evidence of the active release. Do not run a recovery installer or replace account state to update code.

For a server rollout, first inspect the active unit/override and process command, back up each existing account state and the service override, and stage this commit in a separate checkout. Preserve all existing environment files, per-user state paths, credentials and manager configuration. Stop the manager before switching the override; never run two managers against the same account. Restart using the established service and verify each existing account independently. Check pending order IDs and reporting outboxes before declaring success.

Rollback must retain the current state and resolve any pending orders/reports. The old engine does not understand the new derivatives pending-order fields; a blind rollback while those fields are populated can lose reconciliation evidence. Do not restore an old position snapshot after trades have occurred.

## Remaining strategy work

Profitability still needs actual commission, funding and borrow-interest reconciliation, representative historical validation with spread/slippage, walk-forward evaluation and an observed forward-testing period. A small positive gross sample is insufficient. Capital concentration and leverage remain bounded by each account's existing settings. No broader leverage or entry-threshold expansion is included in this repair.

The existing history reader's 1,000-row recovery limit and per-process polling architecture also remain limitations to address before scaling trading volume. Local trailing protection depends on the process and exchange being reachable.
