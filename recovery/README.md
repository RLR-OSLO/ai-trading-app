# Compass trading recovery

Google login through Compass Internal is deployed and confirmed by the owner.
The trading dashboard remains gated until recovery is complete.

`supabase/migrations/20260915085750_prepare_compass_trading_recovery.sql` adds
the storage contract used by the existing worker/dashboard. This is schema
reconstruction, not restoration of deleted records. Trading is disabled by
default and authenticated writes remain revoked. RLS isolates each app member;
the evidence-upload table is service-only. Existing Hallkart tables are untouched.

## Server evidence collection

Run `collect_server_evidence.py` on the existing trading server with
`--expected-legacy-id <verified APP_USER_ID> --upload`.

The script:

- Copies the existing env file and local state into a new root-only directory.
- Reads Binance Spot balances, open orders and available fills with GET only.
- Paginates up to 5,000 fills per examined symbol and marks truncation/errors.
  Examined pairs include the original five assets in USDC/USDT, owner state,
  open orders and current holdings. This is not a complete search across every
  Binance market, nor does it inspect Margin/Futures.
- Keeps other users' state separate from the owner's Binance response. A local
  user directory by itself is not proof of that user's email or account.
- Saves a local report, then optionally uploads to the service-only recovery
  table after a server key is entered at a hidden terminal prompt.
- Keeps the validated Compass key in the root-only backup folder for a later
  migration. No credential values are logged or included in the uploaded report.

It does not change active env, modify live state, restart a service, change
orders, submit trades or unlock recovery. Snapshots are captured per file while
the existing process continues running, not as an atomic account checkpoint.

## Still required after collection

1. Verify available fills/balances against local positions and protective orders.
   Inspect Margin/Futures separately. Keep missing history explicitly marked;
   do not turn local positions into fabricated trades or P&L.
2. Confirm old UUID ownership for each account, then map it to the new confirmed
   Google identity. Never reuse the owner's keys for another user.
3. Restore encrypted credential storage and the exchange RPCs, administration,
   MFA and checked client write permissions. These are not yet restored by the
   storage preparation migration.
4. Prepare the server environment change with a rollback copy, preserving state
   paths and existing open positions. Do not silently enable trading with newly
   generated default settings.
5. Verify current reporting and account isolation before marking recovery done.

Validation: transactional SQL tests check ownership, anonymous denial, blocked
client writes, disabled trading defaults and service-only uploads. Python tests
check allowed read paths, pagination and separation of other users' state.
