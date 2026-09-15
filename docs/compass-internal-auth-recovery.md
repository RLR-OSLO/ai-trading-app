# Compass Internal authentication recovery

The former Supabase endpoint is unavailable. Compass Internal is the replacement
auth project (`nsqsqupucxgrkwotegof`). The frontend supports both configurations
so the repair can be verified on its preview branch before production switches.

## Applied database preparation

The following migrations are recorded in Compass Internal:

- `prepare_ai_trading_invited_access`: a separate application membership and
  private email invitations. Only a confirmed Google identity can claim an
  invitation. Invitation addresses are kept out of the public repository.
- `gate_trading_access_until_account_recovery`: a row-isolated recovery record.
  Authenticated clients can only read their own status and cannot mark recovery
  complete. Signup provisions invited users with recovery still pending.

Shared-project membership does not automatically grant access to this app.
The existing Hallkart application and its memberships remain independent.

## Remaining rollout steps

1. In Compass Internal Auth URL Configuration, add the production origin
   `https://ai-trading-app-mocha.vercel.app` to Redirect URLs. Add the exact repair
   preview origin for testing. Preserve the existing Site URL and Hallkart URLs.
2. Verify Google sign-in on the preview with an invited account. It should show
   the signed-in recovery message. An unapproved account must remain pending.
3. Set production `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` to Compass Internal and deploy this
   change after the redirect is configured. Only the publishable key belongs
   in the frontend.
4. Recover the original account schema, records, settings, credentials and MFA
   requirements from an available backup or the trading server. Map each old
   worker UUID to its verified new Google identity; do not match by display name
   or confuse a work email with a personal Google account. Reconcile existing
   positions and worker state before starting any newly configured worker.
5. Restore and verify all existing dashboard APIs, account isolation and server
   reporting. Only then may an operator set the matching recovery row's
   `completed_at`. A missing row or timestamp always keeps the dashboard closed.

This change restores the authentication path; it does not recreate deleted
trading history, exchange credentials or MFA factors. Logging in does not start
a new trading worker or submit orders.

## Verification

- TypeScript compilation and the production frontend build.
- Transactional database checks: a confirmed invited Google identity provisions
  membership and pending recovery; an unconfirmed identity does not; clients
  cannot update recovery status; each client only sees its own recovery record.
- Test identities and invitations are rolled back after the checks.
