alter table public.bot_settings
 add column ignore_rsi_high_veto boolean not null default false,
 add column ignore_rsi_low_veto boolean not null default false,
 add column ignore_atr_veto boolean not null default false;
grant update(ignore_rsi_high_veto,ignore_rsi_low_veto,ignore_atr_veto) on public.bot_settings to authenticated;

create function trading_auth.is_community_member() returns boolean
language sql stable set search_path='' as $f$
 select auth.uid() is not null and auth.jwt()->>'aal'='aal2' and exists(
  select 1 from public.internal_app_memberships m join public.internal_apps a on a.id=m.app_id
  where m.user_id=auth.uid() and a.slug='ai-trading-app'
 );
$f$;
revoke all on function trading_auth.is_community_member() from public,anon;
grant execute on function trading_auth.is_community_member() to authenticated;

create table public.trading_chat_messages (
 id bigint generated always as identity primary key,
 user_id uuid not null default auth.uid() references auth.users(id),
 author_name text not null default '',
 body text not null check(char_length(btrim(body)) between 1 and 2000),
 created_at timestamptz not null default now()
);
create table public.trading_development_ideas (
 id bigint generated always as identity primary key,
 user_id uuid not null default auth.uid() references auth.users(id),
 author_name text not null default '',
 body text not null check(char_length(btrim(body)) between 1 and 1000),
 done boolean not null default false,
 completed_by uuid references auth.users(id),
 completed_at timestamptz,
 created_at timestamptz not null default now()
);
create index trading_chat_messages_user on public.trading_chat_messages(user_id);
create index trading_development_ideas_user on public.trading_development_ideas(user_id);
create index trading_development_ideas_completed_by on public.trading_development_ideas(completed_by);
create index trading_development_ideas_open on public.trading_development_ideas(done,id);
alter table public.trading_chat_messages enable row level security;
alter table public.trading_development_ideas enable row level security;
revoke all on public.trading_chat_messages,public.trading_development_ideas from public,anon,authenticated;
grant select on public.trading_chat_messages,public.trading_development_ideas to authenticated;
grant insert(body) on public.trading_chat_messages,public.trading_development_ideas to authenticated;
grant update(done) on public.trading_development_ideas to authenticated;
grant usage on sequence public.trading_chat_messages_id_seq,public.trading_development_ideas_id_seq to authenticated;
grant all on public.trading_chat_messages,public.trading_development_ideas to service_role;
grant usage on sequence public.trading_chat_messages_id_seq,public.trading_development_ideas_id_seq to service_role;
create policy member_read on public.trading_chat_messages for select to authenticated using((select trading_auth.is_community_member()));
create policy member_write on public.trading_chat_messages for insert to authenticated with check(user_id=(select auth.uid()) and (select trading_auth.is_community_member()));
create policy member_read on public.trading_development_ideas for select to authenticated using((select trading_auth.is_community_member()));
create policy member_write on public.trading_development_ideas for insert to authenticated with check(user_id=(select auth.uid()) and (select trading_auth.is_community_member()));
create policy member_complete on public.trading_development_ideas for update to authenticated using((select trading_auth.is_community_member())) with check((select trading_auth.is_community_member()));

-- Only the database supplies authorship and completion attribution.
create function trading_auth.stamp_community_author() returns trigger
language plpgsql security definer set search_path='' as $f$
begin
 if auth.uid() is null or not trading_auth.is_community_member() then raise exception 'Approved membership and MFA required' using errcode='42501'; end if;
 new.user_id:=auth.uid();
 select split_part(email,'@',1) into new.author_name from auth.users where id=auth.uid();
 new.body:=btrim(new.body);
 return new;
end;$f$;
revoke all on function trading_auth.stamp_community_author() from public,anon,authenticated;
create trigger stamp_chat_author before insert on public.trading_chat_messages for each row execute function trading_auth.stamp_community_author();
create trigger stamp_idea_author before insert on public.trading_development_ideas for each row execute function trading_auth.stamp_community_author();
create function trading_auth.stamp_idea_completion() returns trigger
language plpgsql set search_path='' as $f$
begin
 if new.done is distinct from old.done then
  new.completed_by:=case when new.done then auth.uid() else null end;
  new.completed_at:=case when new.done then now() else null end;
 end if;
 return new;
end;$f$;
revoke all on function trading_auth.stamp_idea_completion() from public,anon,authenticated;
create trigger stamp_completion before update on public.trading_development_ideas for each row execute function trading_auth.stamp_idea_completion();

-- Existing workers already publish bullrun candidates. Persist one alert per coin
-- per 30 minutes, including while the dashboard is closed. No trading writes.
create index bot_events_bullrun_recent on public.bot_events(user_id,created_at desc) where event_type='bullrun_alert';
create function trading_auth.capture_bullrun_alert() returns trigger
language plpgsql set search_path='' as $f$
declare candidates text; coin text;
begin
 if new.event_type <> 'heartbeat' then return new; end if;
 candidates:=substring(new.message from '(?:^|;)bullrun=([^;]+)');
 if candidates is null or candidates='none' then return new; end if;
 perform pg_advisory_xact_lock(hashtextextended(new.user_id::text||':bullrun',0));
 foreach coin in array string_to_array(candidates,',') loop
  if coin ~ '^[A-Z0-9]{3,24}$' and not exists(
   select 1 from public.bot_events e where e.user_id=new.user_id and e.event_type='bullrun_alert'
   and e.created_at >= new.created_at-interval '30 minutes' and e.message='symbol='||coin
  ) then
   insert into public.bot_events(user_id,level,event_type,message,created_at)
   values(new.user_id,'info','bullrun_alert','symbol='||coin,new.created_at);
  end if;
 end loop;
 return new;
end;$f$;
revoke all on function trading_auth.capture_bullrun_alert() from public,anon,authenticated;
create trigger capture_bullrun after insert on public.bot_events for each row execute function trading_auth.capture_bullrun_alert();
