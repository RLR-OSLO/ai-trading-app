-- Run inside a transaction and roll back. These existing accounts are fixtures only.
set local role authenticated;
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal2"}';
insert into public.trading_chat_messages(body) values('TRANSACTION TEST shared message');
insert into public.trading_development_ideas(body) values('TRANSACTION TEST shared idea');
do $t$begin
 if not exists(select 1 from public.trading_chat_messages where body='TRANSACTION TEST shared message' and author_name='rudirorstad') then raise exception 'Author stamp failed'; end if;
 begin
  insert into public.trading_chat_messages(body,user_id) values('Spoof','94f7835b-aac2-4ec5-8048-5d1ac78ace51');
  raise exception 'Spoof was permitted';
 exception when insufficient_privilege then null; end;
end;$t$;
set local request.jwt.claims='{"sub":"94f7835b-aac2-4ec5-8048-5d1ac78ace51","role":"authenticated","aal":"aal2"}';
do $t$begin
 if not exists(select 1 from public.trading_chat_messages where body='TRANSACTION TEST shared message') then raise exception 'Approved user cannot read chat'; end if;
end;$t$;
update public.trading_development_ideas set done=true where body='TRANSACTION TEST shared idea';
do $t$begin
 if not exists(select 1 from public.trading_development_ideas where body='TRANSACTION TEST shared idea' and done and completed_by=auth.uid() and completed_at is not null) then raise exception 'Completion failed'; end if;
end;$t$;
update public.trading_development_ideas set done=false where body='TRANSACTION TEST shared idea';
set local request.jwt.claims='{"sub":"2fa670f9-62d3-47f8-bdc3-ab868e7557a9","role":"authenticated","aal":"aal2"}';
do $t$begin
 if exists(select 1 from public.trading_chat_messages) or exists(select 1 from public.trading_development_ideas) then raise exception 'Other app user sees community'; end if;
 begin
  insert into public.trading_chat_messages(body) values('Blocked outsider'); raise exception 'Outsider wrote chat';
 exception when insufficient_privilege then null; end;
end;$t$;
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal1"}';
do $t$begin
 if exists(select 1 from public.trading_chat_messages) then raise exception 'MFA bypass'; end if;
end;$t$;
set local request.jwt.claims='{"sub":"fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3","role":"authenticated","aal":"aal2"}';
update public.bot_settings set ignore_rsi_high_veto=true where user_id=auth.uid();
do $t$begin
 if not exists(select 1 from public.bot_settings where user_id=auth.uid() and ignore_rsi_high_veto and not bot_enabled and not live_trading_enabled and not execution_authorized) then raise exception 'Veto change modified trading authorization'; end if;
 begin
  update public.bot_settings set execution_authorized=true where user_id=auth.uid(); raise exception 'Authorization forge allowed';
 exception when insufficient_privilege then null; end;
end;$t$;
reset role;
insert into public.bot_events(user_id,level,event_type,message) values
('fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3','info','heartbeat','bullrun=TESTCOINUSDC;'),
('fa1ee1d5-78ec-4b08-9ec7-d6ec7b0842b3','info','heartbeat','bullrun=TESTCOINUSDC;');
do $t$begin
 if (select count(*) from public.bot_events where event_type='bullrun_alert' and message='symbol=TESTCOINUSDC')<>1 then raise exception 'Alert dedup failed'; end if;
end;$t$;
select 'Community membership, MFA, authorship, completion, veto isolation and alert dedup passed' as result;
