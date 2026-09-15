# Community, bullrun alerts and entry veto controls

Approved AI Trading App members with MFA share the chat and development list at the bottom of the dashboard. Other Compass apps have no access. Authenticated clients can insert only message/idea text and update only an idea's completed flag. Database triggers supply authorship and completion identity. Ideas and messages persist; completed ideas can be shown and reopened. The open page refreshes community data every five seconds and offers older chat history.

Bullrun alerts are persisted from the existing worker heartbeat using a database trigger. Each account receives at most one alert per coin per thirty minutes. The browser polls recent alerts every fifteen seconds. Optional browser notifications require permission and an open app; there is no background web push, email or SMS. An alert is a strategy candidate, not an executed trade. Normal news, account, capital and execution checks can still prevent entry.

Three independent, per-account long-entry overrides default to false:

- RSI 1h >= 75: overbought veto.
- RSI 1h <= 35: weak/oversold veto.
- ATR 1h > 8 percent: volatility veto.

Only literal boolean true overrides a rule. They apply to long spot/scalp/bullrun risk vetoes, including prioritized long directives through the existing signal check. They do not change scores, trend checks, short RSI boundaries (25/70), bullrun's separate ATR candidate range (0.35–6 percent), stop-loss, daily loss, size, leverage or position limits. Saving a veto setting cannot grant execution authorization or start trading.

The worker emits `veto_controls=v1`, `veto_ignored` and `indicators` in its heartbeat. Dashboard boxes show actual server policy, not merely unsynchronized form values. Missing/unscanned/stale data is labeled as unavailable. Only the current scanned market set has RSI/ATR data. Other price charts remain available as before.

## Deployment

Apply `20260915095909_community_alerts_veto_controls.sql` before the new worker. It is additive and compatible with the previous worker. Vercel deploys the UI from main. The DigitalOcean worker requires a separate pinned revision update.

`recovery/update_compass_server.py --revision <reviewed_commit>` updates the previously recovered server, preserving its environment file and position files. It stages a separate checkout, backs up state and the current systemd override, switches code, and waits for a fresh reporting-only heartbeat with veto telemetry. It restores the previous override on failure without overwriting position data. It deliberately refuses to run if any account has already been authorized for trading; activated production accounts require a maintenance procedure suited to their current positions. Do not use the old recovery connector or deploy/install.sh for this update.

## Validation

Python tests cover thresholds, independent overrides, fail-closed values, real candle analysis, full scan policy/telemetry, existing execution protections and upgrade preconditions. SQL tests in `supabase/tests/community_veto_access.sql` run transactionally with rollback against existing test identities and cover member sharing, outsider denial, MFA, author spoof denial, completion identity, isolated settings and alert deduplication. Do not commit test data. Production frontend build passes. Local browser preview was blocked by the environment; visual and interactive browser verification is not claimed.
