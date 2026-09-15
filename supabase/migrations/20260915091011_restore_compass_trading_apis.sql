alter table public.bot_settings add column execution_authorized boolean not null default false;

create table trading_auth.account_mappings (
 legacy_user_id uuid primary key,
 user_id uuid not null unique references auth.users(id),
 evidence_id uuid not null references public.trading_recovery_uploads(id)
);
create table trading_auth.exchange_connections (
 user_id uuid primary key references auth.users(id) on delete cascade,
 kind text not null check(kind in ('server_env','vault')),
 key_id uuid references vault.secrets(id),
 secret_id uuid references vault.secrets(id),
 updated_at timestamptz not null default now(),
 check((kind='vault' and key_id is not null and secret_id is not null) or
       (kind='server_env' and key_id is null and secret_id is null))
);
alter table trading_auth.account_mappings enable row level security;
alter table trading_auth.exchange_connections enable row level security;
revoke all on trading_auth.account_mappings,trading_auth.exchange_connections from public,anon,authenticated;

create table public.exchange_fills (
 user_id uuid not null references auth.users(id),
 symbol text not null,
 exchange_trade_id bigint not null,
 order_id bigint not null,
 side text not null check(side in ('BUY','SELL')),
 quantity numeric not null,
 price numeric not null,
 quote_quantity numeric not null,
 commission numeric not null,
 commission_asset text not null,
 executed_at timestamptz not null,
 source_upload_id uuid not null references public.trading_recovery_uploads(id),
 primary key(user_id,symbol,exchange_trade_id)
);
create index exchange_fills_user_time on public.exchange_fills(user_id,executed_at desc);
create table public.trading_opening_positions (
 user_id uuid not null references auth.users(id),
 symbol text not null,
 quantity numeric not null check(quantity>0),
 quote_spent numeric not null check(quote_spent>0),
 captured_at timestamptz not null,
 source_upload_id uuid not null references public.trading_recovery_uploads(id),
 primary key(user_id,symbol)
);
do $block$
declare t text;
begin
 foreach t in array array['exchange_fills','trading_opening_positions'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant select on public.%I to authenticated',t);
  execute format('grant all on public.%I to service_role',t);
  execute format($p$create policy own_member_read on public.%I for select to authenticated
    using(user_id=(select auth.uid()) and exists(select 1 from public.internal_app_memberships m join public.internal_apps a on a.id=m.app_id where m.user_id=(select auth.uid()) and a.slug='ai-trading-app'))$p$,t);
 end loop;
 foreach t in array array['bot_settings','trades','bot_events','trade_directives','user_access','exchange_fills','trading_opening_positions'] loop
  execute format($p$create policy trading_requires_mfa on public.%I as restrictive for all to authenticated
    using((select auth.jwt()->>'aal')='aal2') with check((select auth.jwt()->>'aal')='aal2')$p$,t);
 end loop;
end;$block$;

-- Permission helpers run as the caller, preserving existing membership RLS.
create function trading_auth.can_operate() returns boolean language sql stable set search_path='' as $f$
 select auth.uid() is not null and auth.jwt()->>'aal'='aal2' and exists(
  select 1 from public.internal_app_memberships m join public.internal_apps a on a.id=m.app_id
  join public.trading_account_recovery r on r.user_id=m.user_id
  where m.user_id=auth.uid() and a.slug='ai-trading-app' and m.role in ('editor','admin') and r.completed_at is not null
 );$f$;
revoke all on function trading_auth.can_operate() from public,anon;
grant usage on schema trading_auth to authenticated,service_role;
grant execute on function trading_auth.can_operate() to authenticated;
grant insert(user_id,bot_enabled,live_trading_enabled,risk_profile,quote_asset,trade_cap_usdc,order_size_usdc,stop_loss_percent,take_profit_percent,max_daily_loss_usdc,short_enabled,futures_enabled,leverage,daily_loss_reset_at,updated_at),
 update(user_id,bot_enabled,live_trading_enabled,risk_profile,quote_asset,trade_cap_usdc,order_size_usdc,stop_loss_percent,take_profit_percent,max_daily_loss_usdc,short_enabled,futures_enabled,leverage,daily_loss_reset_at,updated_at)
 on public.bot_settings to authenticated;
create policy own_ready_settings_insert on public.bot_settings for insert to authenticated with check(user_id=auth.uid() and trading_auth.can_operate());
create policy own_ready_settings_update on public.bot_settings for update to authenticated using(user_id=auth.uid() and trading_auth.can_operate()) with check(user_id=auth.uid() and trading_auth.can_operate());

create function trading_auth.authorize_execution() returns trigger language plpgsql set search_path='' as $f$
begin
 if new.bot_enabled and new.live_trading_enabled and current_user='authenticated' then
  if not trading_auth.can_operate() then raise exception 'Trading recovery and MFA must be complete'; end if;
  new.execution_authorized:=true;
 end if;
 return new;
end;$f$;
revoke all on function trading_auth.authorize_execution() from public,anon,authenticated;
create trigger authorize_execution before insert or update on public.bot_settings for each row execute function trading_auth.authorize_execution();

grant insert(user_id,symbol,direction,mode,requested_notional,leverage),update(status,result) on public.trade_directives to authenticated;
grant usage on sequence public.trade_directives_id_seq to authenticated;
create policy own_ready_directive_insert on public.trade_directives for insert to authenticated with check(user_id=auth.uid() and trading_auth.can_operate());
create policy own_ready_directive_cancel on public.trade_directives for update to authenticated using(user_id=auth.uid() and status='pending' and trading_auth.can_operate()) with check(user_id=auth.uid() and status='cancelled' and trading_auth.can_operate());

create function trading_auth.exchange_status() returns table(configured boolean) language sql stable security definer set search_path='' as $f$
 select exists(select 1 from trading_auth.exchange_connections c where c.user_id=auth.uid())
 where auth.uid() is not null and auth.jwt()->>'aal'='aal2' and exists(
  select 1 from public.internal_app_memberships m join public.internal_apps a on a.id=m.app_id
  where m.user_id=auth.uid() and a.slug='ai-trading-app');$f$;
create function public.exchange_setup_status() returns table(configured boolean) language sql set search_path='' as $f$ select * from trading_auth.exchange_status();$f$;
revoke all on function trading_auth.exchange_status(),public.exchange_setup_status() from public,anon;
grant execute on function trading_auth.exchange_status(),public.exchange_setup_status() to authenticated;

create function trading_auth.save_exchange(p_api_key text,p_api_secret text) returns void language plpgsql security definer set search_path='' as $f$
declare uid uuid:=auth.uid(); c trading_auth.exchange_connections;
begin
 if uid is null or coalesce(auth.jwt()->>'aal','')<>'aal2' or not exists(
  select 1 from public.internal_app_memberships m join public.internal_apps a on a.id=m.app_id
  where m.user_id=uid and a.slug='ai-trading-app' and m.role in ('editor','admin')) then
  raise exception 'App membership and MFA required' using errcode='42501';
 end if;
 if length(trim(p_api_key))<16 or length(trim(p_api_secret))<16 or length(p_api_key)>512 or length(p_api_secret)>512 then raise exception 'Invalid credential format'; end if;
 perform pg_advisory_xact_lock(hashtextextended(uid::text,0));
 select * into c from trading_auth.exchange_connections where user_id=uid;
 if c.kind='server_env' then raise exception 'Existing server connection must be migrated by an operator before replacement'; end if;
 if c.key_id is null then
  c.key_id:=vault.create_secret(trim(p_api_key),'ai-trading:'||uid::text||':key');
  c.secret_id:=vault.create_secret(trim(p_api_secret),'ai-trading:'||uid::text||':secret');
 else
  perform vault.update_secret(c.key_id,trim(p_api_key));
  perform vault.update_secret(c.secret_id,trim(p_api_secret));
 end if;
 insert into trading_auth.exchange_connections(user_id,kind,key_id,secret_id) values(uid,'vault',c.key_id,c.secret_id)
 on conflict(user_id) do update set key_id=excluded.key_id,secret_id=excluded.secret_id,updated_at=now();
end;$f$;
create function public.save_binance_credentials(p_api_key text,p_api_secret text) returns void language sql set search_path='' as $f$ select trading_auth.save_exchange(p_api_key,p_api_secret);$f$;
revoke all on function trading_auth.save_exchange(text,text),public.save_binance_credentials(text,text) from public,anon;
grant execute on function trading_auth.save_exchange(text,text),public.save_binance_credentials(text,text) to authenticated;

create function trading_auth.service_accounts() returns table(user_id uuid,api_key text,api_secret text) language sql stable security definer set search_path='' as $f$
 select c.user_id,k.decrypted_secret,s.decrypted_secret from trading_auth.exchange_connections c
 join vault.decrypted_secrets k on k.id=c.key_id join vault.decrypted_secrets s on s.id=c.secret_id
 where c.kind='vault' and exists(select 1 from public.internal_app_memberships m join public.internal_apps a on a.id=m.app_id where m.user_id=c.user_id and a.slug='ai-trading-app' and m.role in ('editor','admin'));
$f$;
create function public.service_trading_accounts() returns table(user_id uuid,api_key text,api_secret text) language sql set search_path='' as $f$ select * from trading_auth.service_accounts();$f$;
revoke all on function trading_auth.service_accounts(),public.service_trading_accounts() from public,anon,authenticated;
grant execute on function trading_auth.service_accounts(),public.service_trading_accounts() to service_role;

create function trading_auth.register_server(p_legacy_user_id uuid,p_user_id uuid) returns void language plpgsql security definer set search_path='' as $f$
begin
 if not exists(select 1 from trading_auth.account_mappings where legacy_user_id=p_legacy_user_id and user_id=p_user_id) then raise exception 'Unverified account mapping'; end if;
 if exists(select 1 from trading_auth.exchange_connections where user_id=p_user_id and kind<>'server_env') then raise exception 'Existing vault account must not be overwritten'; end if;
 insert into trading_auth.exchange_connections(user_id,kind) values(p_user_id,'server_env') on conflict(user_id) do update set updated_at=now();
end;$f$;
create function public.service_register_trading_server(p_legacy_user_id uuid,p_user_id uuid) returns void language sql set search_path='' as $f$ select trading_auth.register_server(p_legacy_user_id,p_user_id);$f$;
revoke all on function trading_auth.register_server(uuid,uuid),public.service_register_trading_server(uuid,uuid) from public,anon,authenticated;
grant execute on function trading_auth.register_server(uuid,uuid),public.service_register_trading_server(uuid,uuid) to service_role;
notify pgrst,'reload schema';
