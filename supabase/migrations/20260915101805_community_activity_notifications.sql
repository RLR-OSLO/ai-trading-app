create table public.trading_community_activity (
 id bigint generated always as identity primary key,
 actor_id uuid not null references auth.users(id),
 actor_name text not null,
 kind text not null check(kind in ('chat','idea_created','idea_completed','idea_reopened')),
 item_id bigint not null,
 preview text not null,
 created_at timestamptz not null default now()
);
create index trading_community_activity_actor on public.trading_community_activity(actor_id);
alter table public.trading_community_activity enable row level security;
revoke all on public.trading_community_activity from public,anon,authenticated;
grant select on public.trading_community_activity to authenticated;
grant all on public.trading_community_activity to service_role;
create policy member_read on public.trading_community_activity for select to authenticated using((select trading_auth.is_community_member()));
create table trading_auth.community_activity_reads (
 user_id uuid not null references auth.users(id) on delete cascade,
 activity_id bigint not null references public.trading_community_activity(id) on delete cascade,
 primary key(user_id,activity_id)
);
create index community_activity_reads_activity on trading_auth.community_activity_reads(activity_id);
alter table trading_auth.community_activity_reads enable row level security;
revoke all on trading_auth.community_activity_reads from public,anon,authenticated;
-- Private table is accessed only through guarded, caller-specific functions.
create function trading_auth.capture_community_activity() returns trigger
language plpgsql security definer set search_path='' as $f$
declare category text; actor text;
begin
 if auth.uid() is null or not trading_auth.is_community_member() then raise exception 'Approved membership and MFA required' using errcode='42501'; end if;
 if tg_table_name='trading_chat_messages' then category:='chat';
 elsif tg_op='INSERT' then category:='idea_created';
 elsif new.done is not distinct from old.done then return new;
 else category:=case when new.done then 'idea_completed' else 'idea_reopened' end;
 end if;
 select split_part(email,'@',1) into actor from auth.users where id=auth.uid();
 insert into public.trading_community_activity(actor_id,actor_name,kind,item_id,preview)
 values(auth.uid(),actor,category,new.id,left(new.body,240));
 return new;
end;$f$;
revoke all on function trading_auth.capture_community_activity() from public,anon,authenticated;
create trigger community_chat_activity after insert on public.trading_chat_messages for each row execute function trading_auth.capture_community_activity();
create trigger community_idea_activity after insert or update on public.trading_development_ideas for each row execute function trading_auth.capture_community_activity();

create function trading_auth.unread_community_activity()
returns table(id bigint,actor_name text,kind text,item_id bigint,preview text,created_at timestamptz,total_unread bigint)
language plpgsql stable security definer set search_path='' as $f$
begin
 if auth.uid() is null or not trading_auth.is_community_member() then raise exception 'Approved membership and MFA required' using errcode='42501'; end if;
 return query select a.id,a.actor_name,a.kind,a.item_id,a.preview,a.created_at,count(*) over()
 from public.trading_community_activity a
 where a.actor_id<>auth.uid() and not exists(select 1 from trading_auth.community_activity_reads r where r.user_id=auth.uid() and r.activity_id=a.id)
 order by a.id desc limit 50;
end;$f$;
create function trading_auth.mark_community_activity_read(p_ids bigint[]) returns void
language plpgsql security definer set search_path='' as $f$
begin
 if auth.uid() is null or not trading_auth.is_community_member() then raise exception 'Approved membership and MFA required' using errcode='42501'; end if;
 if coalesce(cardinality(p_ids),0)>50 then raise exception 'At most 50 activity items'; end if;
 insert into trading_auth.community_activity_reads(user_id,activity_id)
 select auth.uid(),a.id from public.trading_community_activity a where a.id=any(p_ids) and a.actor_id<>auth.uid()
 on conflict do nothing;
end;$f$;
create function public.unread_community_activity()
returns table(id bigint,actor_name text,kind text,item_id bigint,preview text,created_at timestamptz,total_unread bigint)
language sql set search_path='' as $f$ select * from trading_auth.unread_community_activity();$f$;
create function public.mark_community_activity_read(p_ids bigint[]) returns void
language sql set search_path='' as $f$ select trading_auth.mark_community_activity_read(p_ids);$f$;
revoke all on function trading_auth.unread_community_activity(),trading_auth.mark_community_activity_read(bigint[]),public.unread_community_activity(),public.mark_community_activity_read(bigint[]) from public,anon;
grant execute on function trading_auth.unread_community_activity(),trading_auth.mark_community_activity_read(bigint[]),public.unread_community_activity(),public.mark_community_activity_read(bigint[]) to authenticated;
