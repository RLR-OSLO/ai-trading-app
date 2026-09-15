set local role authenticated;
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal2"}';
insert into public.trading_chat_messages(body) values('NOTICE_TEST message');
insert into public.trading_development_ideas(body) values('NOTICE_TEST idea');
do $t$begin
 if exists(select 1 from public.unread_community_activity() where preview like 'NOTICE_TEST%') then raise exception 'Own actions should not notify'; end if;
end;$t$;
set local request.jwt.claims='{"sub":"94f7835b-aac2-4ec5-8048-5d1ac78ace51","role":"authenticated","aal":"aal2"}';
do $t$begin
 if (select count(*) from public.unread_community_activity() where preview like 'NOTICE_TEST%')<>2 then raise exception 'New message/idea missing'; end if;
end;$t$;
select public.mark_community_activity_read(array(select id from public.unread_community_activity() where preview like 'NOTICE_TEST%'));
update public.trading_development_ideas set done=true where body='NOTICE_TEST idea';
update public.trading_development_ideas set done=false where body='NOTICE_TEST idea';
-- Saving the same checkbox state should not add another event.
update public.trading_development_ideas set done=false where body='NOTICE_TEST idea';
do $t$begin
 if exists(select 1 from public.unread_community_activity() where preview like 'NOTICE_TEST%') then raise exception 'Read state or own-update filter failed'; end if;
end;$t$;
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal2"}';
do $t$begin
 if (select count(*) from public.unread_community_activity() where preview='NOTICE_TEST idea')<>2 then raise exception 'Completion/reopen events missing or duplicated'; end if;
 if not exists(select 1 from public.unread_community_activity() where preview='NOTICE_TEST idea' and kind='idea_completed') then raise exception 'Completion missing'; end if;
 if not exists(select 1 from public.unread_community_activity() where preview='NOTICE_TEST idea' and kind='idea_reopened') then raise exception 'Reopen missing'; end if;
 begin
  insert into public.trading_community_activity(actor_id,actor_name,kind,item_id,preview) values(auth.uid(),'spoof','chat',1,'forged');
  raise exception 'Forged activity allowed';
 exception when insufficient_privilege then null; end;
end;$t$;
select public.mark_community_activity_read(array(select id from public.unread_community_activity() where preview like 'NOTICE_TEST%'));
set local request.jwt.claims='{"sub":"94f7835b-aac2-4ec5-8048-5d1ac78ace51","role":"authenticated","aal":"aal2"}';
insert into public.trading_chat_messages(body) values('NOTICE_TEST later message');
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal2"}';
do $t$begin
 if not exists(select 1 from public.unread_community_activity() where preview='NOTICE_TEST later message') then raise exception 'Later event accidentally marked read'; end if;
end;$t$;
set local request.jwt.claims='{"sub":"2fa670f9-62d3-47f8-bdc3-ab868e7557a9","role":"authenticated","aal":"aal2"}';
do $t$begin
 begin
  perform public.unread_community_activity(); raise exception 'Other app can read notices';
 exception when insufficient_privilege then null; end;
 begin
  perform public.mark_community_activity_read(array[1::bigint]); raise exception 'Other app can mark read';
 exception when insufficient_privilege then null; end;
end;$t$;
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal1"}';
do $t$begin
 begin
  perform public.unread_community_activity(); raise exception 'MFA bypass';
 exception when insufficient_privilege then null; end;
end;$t$;
reset role;
select 'Notification creation, independent read state, later arrivals, own-action exclusion, MFA and membership checks passed' result;
