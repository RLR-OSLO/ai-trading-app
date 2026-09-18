-- User-confirmed orders are independent of autonomous bot activation.
-- No account settings, credentials, balances or existing directives are changed.
create table public.trading_commands (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  action text not null check (action in ('CLOSE', 'PRIORITY_OPEN')),
  symbol text not null check (symbol ~ '^[A-Z0-9]{3,24}$'),
  mode text not null check (mode in ('SPOT', 'MARGIN', 'FUTURES')),
  position_key text check (length(position_key) between 1 and 128),
  quantity numeric check (quantity > 0 and quantity <= 1e20),
  requested_notional numeric check (requested_notional >= 5 and requested_notional <= 1e9),
  leverage integer not null default 1 check (leverage between 1 and 20),
  status text not null default 'pending' check (status in ('pending', 'processing', 'executed', 'rejected', 'expired', 'cancelled')),
  result text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '15 minutes',
  check ((action = 'CLOSE' and position_key is not null and quantity is not null and requested_notional is null)
      or (action = 'PRIORITY_OPEN' and position_key is null and quantity is null and requested_notional is not null)),
  check (mode = 'FUTURES' or leverage = 1)
);
create index trading_commands_account_history on public.trading_commands(user_id, created_at desc);
create unique index trading_commands_one_active_target on public.trading_commands(user_id, action, mode, symbol)
  where status in ('pending', 'processing');
create unique index trading_commands_one_processing_account on public.trading_commands(user_id)
  where status = 'processing';
alter table public.trading_commands enable row level security;
revoke all on public.trading_commands from public, anon, authenticated;
grant all on public.trading_commands to service_role;
grant select on public.trading_commands to authenticated;
grant insert (id, user_id, action, symbol, mode, position_key, quantity, requested_notional, leverage)
  on public.trading_commands to authenticated;
grant update (status) on public.trading_commands to authenticated;
create policy commands_own_read on public.trading_commands for select to authenticated
  using (user_id = (select auth.uid()) and trading_auth.can_operate());
create policy commands_own_submit on public.trading_commands for insert to authenticated
  with check (user_id = (select auth.uid()) and trading_auth.can_operate());
create policy commands_own_cancel on public.trading_commands for update to authenticated
  using (user_id = (select auth.uid()) and status = 'pending' and trading_auth.can_operate())
  with check (user_id = (select auth.uid()) and status = 'cancelled' and trading_auth.can_operate());

create table public.trading_position_snapshots (
  user_id uuid primary key references auth.users(id) on delete cascade,
  positions jsonb not null default '[]'::jsonb check (jsonb_typeof(positions) = 'array'),
  engine text not null,
  updated_at timestamptz not null default now()
);
alter table public.trading_position_snapshots enable row level security;
revoke all on public.trading_position_snapshots from public, anon, authenticated;
grant all on public.trading_position_snapshots to service_role;
grant select on public.trading_position_snapshots to authenticated;
create policy positions_own_read on public.trading_position_snapshots for select to authenticated
  using (user_id = (select auth.uid()) and trading_auth.can_operate());
