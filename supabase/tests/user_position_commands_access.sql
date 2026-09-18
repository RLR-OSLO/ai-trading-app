-- Run as database owner. All fixtures are uncommitted and rolled back; workers
-- cannot see or execute them. Existing users/settings are never modified.
begin;
select set_config('test.command_user_a', (select user_id::text from public.trading_account_recovery where completed_at is not null order by user_id limit 1), true);
select set_config('test.command_user_b', (select user_id::text from public.trading_account_recovery where completed_at is not null order by user_id offset 1 limit 1), true);
select set_config('test.command_id', gen_random_uuid()::text, true);
insert into public.trading_position_snapshots(user_id, engine)
values (current_setting('test.command_user_a')::uuid, 'access-test'), (current_setting('test.command_user_b')::uuid, 'access-test')
on conflict (user_id) do update set engine = excluded.engine;

set local role authenticated;
select set_config('request.jwt.claims', jsonb_build_object('sub', current_setting('test.command_user_a'), 'role', 'authenticated', 'aal', 'aal2')::text, true);
do $test$
begin
  assert trading_auth.can_operate(), 'Fixture user must be an approved app operator';
  assert (select count(*) from public.trading_position_snapshots) = 1, 'Snapshot crossed account boundary';
  insert into public.trading_commands(id, user_id, action, symbol, mode, position_key, quantity)
  values (current_setting('test.command_id')::uuid, auth.uid(), 'CLOSE', 'TESTUSDC', 'SPOT', 'SPOT:TESTUSDC:1', 1);
  begin
    insert into public.trading_commands(user_id, action, symbol, mode, position_key, quantity)
    values (auth.uid(), 'CLOSE', 'TESTUSDC', 'SPOT', 'SPOT:TESTUSDC:1', 1);
    raise exception 'Duplicate active command was accepted';
  exception when unique_violation then null; end;
  begin
    insert into public.trading_commands(user_id, action, symbol, mode, position_key, quantity)
    values (current_setting('test.command_user_b')::uuid, 'CLOSE', 'TESTUSDC', 'SPOT', 'SPOT:TESTUSDC:1', 1);
    raise exception 'Cross-account command was accepted';
  exception when insufficient_privilege then null; end;
  begin
    update public.trading_commands set status = 'executed' where id = current_setting('test.command_id')::uuid;
    raise exception 'Client marked a command executed';
  exception when insufficient_privilege then null; end;
  begin
    update public.trading_commands set symbol = 'ETHUSDC' where id = current_setting('test.command_id')::uuid;
    raise exception 'Client changed an accepted command';
  exception when insufficient_privilege then null; end;
  update public.trading_commands set status = 'cancelled' where id = current_setting('test.command_id')::uuid;
  assert (select status from public.trading_commands where id = current_setting('test.command_id')::uuid) = 'cancelled';
end;
$test$;

set local role postgres;
update public.trading_commands set status = 'processing' where id = current_setting('test.command_id')::uuid;
set local role authenticated;
do $test$
declare changed integer;
begin
  update public.trading_commands set status = 'cancelled' where id = current_setting('test.command_id')::uuid;
  get diagnostics changed = row_count;
  assert changed = 0, 'A processing order was cancelled by the client';
end;
$test$;

select set_config('request.jwt.claims', jsonb_build_object('sub', current_setting('test.command_user_b'), 'role', 'authenticated', 'aal', 'aal2')::text, true);
do $test$
begin
  assert (select count(*) from public.trading_commands where id = current_setting('test.command_id')::uuid) = 0, 'Other account can read order';
  assert (select count(*) from public.trading_position_snapshots) = 1, 'Other account can read snapshot';
end;
$test$;

select set_config('request.jwt.claims', jsonb_build_object('sub', current_setting('test.command_user_a'), 'role', 'authenticated', 'aal', 'aal1')::text, true);
do $test$
begin
  assert (select count(*) from public.trading_commands) = 0, 'MFA-less session can read commands';
  assert (select count(*) from public.trading_position_snapshots) = 0, 'MFA-less session can read positions';
  begin
    insert into public.trading_commands(user_id, action, symbol, mode, requested_notional)
    values (auth.uid(), 'PRIORITY_OPEN', 'TESTUSDC', 'SPOT', 5);
    raise exception 'MFA-less session submitted command';
  exception when insufficient_privilege then null; end;
end;
$test$;

select set_config('request.jwt.claims', jsonb_build_object('sub', gen_random_uuid(), 'role', 'authenticated', 'aal', 'aal2')::text, true);
do $test$
begin
  assert (select count(*) from public.trading_commands) = 0, 'Unapproved third user can read commands';
  assert (select count(*) from public.trading_position_snapshots) = 0, 'Unapproved third user can read positions';
  begin
    insert into public.trading_commands(user_id, action, symbol, mode, requested_notional)
    values (auth.uid(), 'PRIORITY_OPEN', 'TESTUSDC', 'SPOT', 5);
    raise exception 'Unapproved third user submitted command';
  exception when insufficient_privilege then null; end;
end;
$test$;
rollback;
select 'PASS: account isolation, MFA, cancellation race, duplicate command, immutable request; all fixtures rolled back' as result;
