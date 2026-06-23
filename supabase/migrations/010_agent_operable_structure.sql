-- Agent-operable structure.
-- Adds canonical task queue, position event history, and lineage columns without
-- breaking the existing file-first workflow.

alter table investment_proposals
  add column if not exists research_candidate_id text references research_candidates(candidate_id) on delete set null;

alter table positions
  add column if not exists proposal_id text references investment_proposals(proposal_id) on delete set null;

create index if not exists idx_investment_proposals_research_candidate
  on investment_proposals(research_candidate_id);

create index if not exists idx_positions_proposal
  on positions(proposal_id);

create table if not exists workflow_tasks (
  task_id text primary key,
  ticker text,
  task_type text not null check (
    task_type in (
      'research',
      'decision',
      'exit_review',
      'risk_review',
      'position_update',
      'manual_review',
      'notification',
      'reflection'
    )
  ),
  priority text not null default 'normal' check (priority in ('urgent', 'high', 'normal', 'low')),
  status text not null default 'open' check (status in ('open', 'in_progress', 'blocked', 'done', 'dismissed')),
  command text,
  title text,
  detail text,
  source_table text,
  source_id text,
  source_run_id text,
  due_date date,
  resolved_at timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source_table, source_id, task_type)
);

create index if not exists idx_workflow_tasks_status_priority
  on workflow_tasks(status, priority, created_at desc);
create index if not exists idx_workflow_tasks_ticker
  on workflow_tasks(ticker);
create index if not exists idx_workflow_tasks_source
  on workflow_tasks(source_table, source_id);

create table if not exists position_events (
  event_id text primary key,
  position_id text references positions(position_id) on delete cascade,
  ticker text not null,
  portfolio_type text not null default 'real' check (portfolio_type in ('real', 'paper')),
  event_type text not null check (
    event_type in (
      'entry',
      'exit',
      'partial_exit',
      'stop_update',
      'target_update',
      'stage_update',
      'note_update',
      'sync'
    )
  ),
  event_date date not null default current_date,
  shares_delta numeric,
  price numeric,
  stop_loss numeric,
  target_price numeric,
  reason text,
  source_table text,
  source_id text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (position_id, event_type, event_date, source_table, source_id)
);

create index if not exists idx_position_events_position_date
  on position_events(position_id, event_date desc);
create index if not exists idx_position_events_ticker_date
  on position_events(ticker, event_date desc);

drop trigger if exists trg_workflow_tasks_touch_updated_at on workflow_tasks;
create trigger trg_workflow_tasks_touch_updated_at
before update on workflow_tasks
for each row execute function touch_updated_at();

create or replace function task_priority_from_severity(severity text)
returns text
language sql
immutable
as $$
  select case upper(coalesce(severity, ''))
    when 'HIGH' then 'urgent'
    when 'MEDIUM' then 'high'
    when 'LOW' then 'low'
    else 'normal'
  end
$$;

create or replace function task_type_from_monitor_alert(alert_type text)
returns text
language sql
immutable
as $$
  select case upper(coalesce(alert_type, ''))
    when 'STOP_LOSS' then 'exit_review'
    when 'STOP_BREACH' then 'exit_review'
    when 'TARGET_REACHED' then 'exit_review'
    when 'STAGE1_HIT' then 'position_update'
    when 'STAGE2_HIT' then 'position_update'
    when 'SHARP_DROP' then 'risk_review'
    when 'SIGNIFICANT_DRAWDOWN' then 'risk_review'
    else 'manual_review'
  end
$$;

create or replace function task_type_from_watchlist_alert(alert_type text)
returns text
language sql
immutable
as $$
  select case upper(coalesce(alert_type, ''))
    when 'WATCHLIST_DECISION_NEEDED' then 'decision'
    when 'WATCHLIST_RESEARCH_NEEDED' then 'research'
    else 'manual_review'
  end
$$;

create or replace function enqueue_workflow_task_from_monitor_alert()
returns trigger
language plpgsql
as $$
declare
  resolved_type text;
  resolved_command text;
begin
  if coalesce(new.raw_payload ->> 'suppress_automation', 'false') = 'true' then
    return new;
  end if;

  resolved_type := task_type_from_monitor_alert(new.alert_type);
  resolved_command := case
    when resolved_type = 'exit_review' then '/decision --mode exit --ticker ' || new.ticker
    when resolved_type = 'risk_review' then '/monitor'
    when resolved_type = 'position_update' then '/monitor'
    else null
  end;

  insert into workflow_tasks (
    task_id,
    ticker,
    task_type,
    priority,
    status,
    command,
    title,
    detail,
    source_table,
    source_id,
    source_run_id,
    due_date,
    raw_payload
  )
  values (
    'task:monitor_alert:' || new.alert_id,
    new.ticker,
    resolved_type,
    task_priority_from_severity(new.severity),
    'open',
    resolved_command,
    new.alert_type || ' for ' || new.ticker,
    new.message,
    'monitor_alerts',
    new.alert_id,
    new.run_id,
    new.alert_date,
    new.raw_payload
  )
  on conflict (source_table, source_id, task_type) do update set
    priority = excluded.priority,
    status = case when workflow_tasks.status in ('done', 'dismissed') then workflow_tasks.status else excluded.status end,
    command = excluded.command,
    title = excluded.title,
    detail = excluded.detail,
    source_run_id = excluded.source_run_id,
    due_date = excluded.due_date,
    raw_payload = excluded.raw_payload;

  return new;
end;
$$;

drop trigger if exists trg_monitor_alert_workflow_task on monitor_alerts;
create trigger trg_monitor_alert_workflow_task
after insert on monitor_alerts
for each row execute function enqueue_workflow_task_from_monitor_alert();

create or replace function enqueue_workflow_task_from_watchlist_alert()
returns trigger
language plpgsql
as $$
declare
  resolved_type text;
begin
  if coalesce(new.raw_payload ->> 'suppress_automation', 'false') = 'true' then
    return new;
  end if;

  resolved_type := task_type_from_watchlist_alert(new.alert_type);

  insert into workflow_tasks (
    task_id,
    ticker,
    task_type,
    priority,
    status,
    command,
    title,
    detail,
    source_table,
    source_id,
    source_run_id,
    due_date,
    raw_payload
  )
  values (
    'task:watchlist_alert:' || new.alert_id,
    new.ticker,
    resolved_type,
    task_priority_from_severity(new.severity),
    'open',
    new.next_step,
    new.alert_type || ' for ' || new.ticker,
    new.message,
    'watchlist_alerts',
    new.alert_id,
    new.run_id,
    new.alert_date,
    new.raw_payload
  )
  on conflict (source_table, source_id, task_type) do update set
    priority = excluded.priority,
    status = case when workflow_tasks.status in ('done', 'dismissed') then workflow_tasks.status else excluded.status end,
    command = excluded.command,
    title = excluded.title,
    detail = excluded.detail,
    source_run_id = excluded.source_run_id,
    due_date = excluded.due_date,
    raw_payload = excluded.raw_payload;

  return new;
end;
$$;

drop trigger if exists trg_watchlist_alert_workflow_task on watchlist_alerts;
create trigger trg_watchlist_alert_workflow_task
after insert on watchlist_alerts
for each row execute function enqueue_workflow_task_from_watchlist_alert();

create or replace function record_position_entry_event()
returns trigger
language plpgsql
as $$
begin
  insert into position_events (
    event_id,
    position_id,
    ticker,
    portfolio_type,
    event_type,
    event_date,
    shares_delta,
    price,
    stop_loss,
    target_price,
    reason,
    source_table,
    source_id,
    raw_payload
  )
  values (
    'position_event:' || new.position_id || ':entry',
    new.position_id,
    new.ticker,
    new.portfolio_type,
    'entry',
    coalesce(new.entry_date, current_date),
    new.shares,
    new.entry_price,
    new.stop_loss,
    new.target_price,
    new.signal_type,
    'positions',
    new.position_id,
    new.raw_payload
  )
  on conflict (event_id) do nothing;
  return new;
end;
$$;

drop trigger if exists trg_position_entry_event on positions;
create trigger trg_position_entry_event
after insert on positions
for each row execute function record_position_entry_event();

create or replace function record_position_update_event()
returns trigger
language plpgsql
as $$
begin
  if old.status is distinct from new.status and new.status = 'closed' then
    insert into position_events (
      event_id,
      position_id,
      ticker,
      portfolio_type,
      event_type,
      event_date,
      shares_delta,
      price,
      stop_loss,
      target_price,
      reason,
      source_table,
      source_id,
      raw_payload
    )
    values (
      'position_event:' || new.position_id || ':exit',
      new.position_id,
      new.ticker,
      new.portfolio_type,
      'exit',
      coalesce(new.exit_date, current_date),
      -1 * coalesce(old.shares, new.shares),
      new.exit_price,
      new.stop_loss,
      new.target_price,
      new.note,
      'positions',
      new.position_id,
      new.raw_payload
    )
    on conflict (event_id) do update set
      event_date = excluded.event_date,
      shares_delta = excluded.shares_delta,
      price = excluded.price,
      stop_loss = excluded.stop_loss,
      target_price = excluded.target_price,
      reason = excluded.reason,
      raw_payload = excluded.raw_payload;
  end if;

  if old.stop_loss is distinct from new.stop_loss then
    insert into position_events (
      event_id,
      position_id,
      ticker,
      portfolio_type,
      event_type,
      event_date,
      stop_loss,
      target_price,
      reason,
      source_table,
      source_id,
      raw_payload
    )
    values (
      'position_event:' || new.position_id || ':stop:' || md5(coalesce(new.updated_at::text, now()::text)),
      new.position_id,
      new.ticker,
      new.portfolio_type,
      'stop_update',
      current_date,
      new.stop_loss,
      new.target_price,
      new.note,
      'positions',
      new.position_id,
      new.raw_payload
    )
    on conflict do nothing;
  end if;

  if old.target_price is distinct from new.target_price then
    insert into position_events (
      event_id,
      position_id,
      ticker,
      portfolio_type,
      event_type,
      event_date,
      stop_loss,
      target_price,
      reason,
      source_table,
      source_id,
      raw_payload
    )
    values (
      'position_event:' || new.position_id || ':target:' || md5(coalesce(new.updated_at::text, now()::text)),
      new.position_id,
      new.ticker,
      new.portfolio_type,
      'target_update',
      current_date,
      new.stop_loss,
      new.target_price,
      new.note,
      'positions',
      new.position_id,
      new.raw_payload
    )
    on conflict do nothing;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_position_update_event on positions;
create trigger trg_position_update_event
after update on positions
for each row execute function record_position_update_event();

create or replace view agent_task_queue as
select
  task_id,
  priority,
  status,
  task_type,
  ticker,
  command,
  title,
  detail,
  source_table,
  source_id,
  source_run_id,
  due_date,
  created_at,
  updated_at
from workflow_tasks
where status in ('open', 'in_progress', 'blocked')
order by
  case priority
    when 'urgent' then 1
    when 'high' then 2
    when 'normal' then 3
    else 4
  end,
  due_date nulls last,
  created_at;

create or replace view agent_position_state as
select
  p.position_id,
  p.portfolio_type,
  p.ticker,
  p.status,
  p.shares,
  p.entry_price,
  p.entry_date,
  p.exit_price,
  p.exit_date,
  p.target_price,
  p.stop_loss,
  p.exit_stage,
  p.conviction,
  p.signal_type,
  p.proposal_id,
  ip.research_candidate_id,
  mp.current_price,
  mp.pnl_pct,
  mp.run_date as last_monitor_date,
  (
    select count(*)
    from workflow_tasks wt
    where wt.ticker = p.ticker
      and wt.status in ('open', 'in_progress', 'blocked')
  ) as open_task_count
from positions p
left join investment_proposals ip on ip.proposal_id = p.proposal_id
left join lateral (
  select *
  from monitor_positions mp
  where mp.ticker = p.ticker
    and mp.run_date >= coalesce(p.entry_date, mp.run_date)
  order by mp.run_date desc, mp.created_at desc
  limit 1
) mp on true;

create or replace view agent_research_decision_lineage as
select
  rc.candidate_id,
  rc.run_id as research_run_id,
  rc.run_date as research_date,
  rc.ticker,
  rc.score,
  rc.conviction as research_conviction,
  rc.action as research_action,
  ip.proposal_id,
  ip.run_id as decision_run_id,
  ip.action as decision_action,
  ip.conviction as decision_conviction,
  ip.human_decision,
  p.position_id,
  p.status as position_status,
  p.entry_date,
  p.exit_date,
  p.entry_price,
  p.exit_price
from research_candidates rc
left join investment_proposals ip
  on ip.research_candidate_id = rc.candidate_id
left join positions p
  on p.proposal_id = ip.proposal_id
order by rc.run_date desc, rc.score desc nulls last, rc.ticker;
