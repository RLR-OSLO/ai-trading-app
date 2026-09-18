-- Additive: preserve existing records, account permissions, MFA and RLS.
alter table public.trades add column execution_key text;
create unique index trades_user_execution_key on public.trades(user_id, execution_key);
notify pgrst, 'reload schema';
