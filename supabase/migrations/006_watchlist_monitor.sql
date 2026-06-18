-- Mechanical watchlist monitoring for GitHub Actions.

create table if not exists watchlist_monitor_runs (
  run_id text primary key,
  run_date date not null,
  item_count integer not null default 0,
  alert_count integer not null default 0,
  decision_needed_count integer not null default 0,
  research_needed_count integer not null default 0,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists watchlist_monitor_items (
  id uuid primary key default gen_random_uuid(),
  run_id text not null references watchlist_monitor_runs(run_id) on delete cascade,
  run_date date not null,
  ticker text not null,
  price numeric,
  change_pct numeric,
  reference_price numeric,
  ref_change_pct numeric,
  rsi numeric,
  macd_hist numeric,
  ema20 numeric,
  days_until_earnings integer,
  last_score numeric,
  flags text[] not null default '{}',
  action text not null default 'watch',
  next_step text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, ticker)
);

create table if not exists watchlist_alerts (
  alert_id text primary key,
  run_id text references watchlist_monitor_runs(run_id) on delete set null,
  alert_date date not null,
  ticker text not null,
  alert_type text not null,
  severity text not null,
  message text,
  next_step text,
  status text not null default 'open',
  notified_at timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_watchlist_monitor_items_ticker_date on watchlist_monitor_items (ticker, run_date desc);
create index if not exists idx_watchlist_alerts_date on watchlist_alerts (alert_date desc);
create index if not exists idx_watchlist_alerts_status on watchlist_alerts (status);

create or replace function enqueue_watchlist_alert_notification()
returns trigger
language plpgsql
as $$
begin
  if new.severity in ('HIGH', 'MEDIUM')
     and coalesce(new.raw_payload ->> 'suppress_automation', 'false') <> 'true' then
    insert into notifications (
      notification_id,
      source_table,
      source_id,
      channel,
      severity,
      status,
      payload
    )
    values (
      'watchlist_alert:' || new.alert_id || ':slack',
      'watchlist_alerts',
      new.alert_id,
      'slack',
      new.severity,
      'pending',
      jsonb_build_object(
        'ticker', new.ticker,
        'alert_type', new.alert_type,
        'severity', new.severity,
        'message', new.message,
        'next_step', new.next_step,
        'alert_date', new.alert_date
      )
    )
    on conflict (source_table, source_id, channel) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_watchlist_alert_notification on watchlist_alerts;
create trigger trg_watchlist_alert_notification
after insert on watchlist_alerts
for each row execute function enqueue_watchlist_alert_notification();

create or replace view dashboard_watchlist_monitor_latest as
select
  i.run_date as date,
  i.ticker,
  i.price,
  i.change_pct,
  i.ref_change_pct,
  i.rsi,
  i.last_score as score,
  i.flags,
  i.action,
  i.next_step
from watchlist_monitor_items i
join (
  select ticker, max(run_date) as run_date
  from watchlist_monitor_items
  group by ticker
) latest on latest.ticker = i.ticker and latest.run_date = i.run_date
order by
  case
    when i.action = 'decision_needed' then 1
    when i.action = 'research_needed' then 2
    when i.action = 'review_needed' then 3
    else 9
  end,
  i.last_score desc nulls last,
  i.ticker;

create or replace view dashboard_watchlist_alerts as
select
  alert_date as date,
  ticker,
  severity,
  alert_type,
  message,
  next_step,
  status,
  notified_at
from watchlist_alerts
order by alert_date desc, created_at desc;
