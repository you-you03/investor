-- Investor Supabase schema
-- Apply this file in the Supabase SQL editor.
-- Personal-use MVP: RLS is intentionally not enabled in this first migration.

create extension if not exists pgcrypto;

create table if not exists positions (
  position_id text primary key,
  portfolio_type text not null default 'real' check (portfolio_type in ('real', 'paper')),
  ticker text not null,
  shares numeric,
  entry_price numeric,
  entry_date date,
  proposal_date date,
  exit_price numeric,
  exit_date date,
  status text not null default 'open',
  target_price numeric,
  stop_loss numeric,
  note text,
  signal_type text,
  conviction text,
  hypothesis_id text,
  exit_stage text,
  mae_pct numeric,
  mfe_pct numeric,
  mfe_capture_pct numeric,
  rule_adherence_score numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_positions_ticker on positions (ticker);
create index if not exists idx_positions_status on positions (status);
create index if not exists idx_positions_portfolio_type on positions (portfolio_type);

create table if not exists watchlist_items (
  ticker text primary key,
  added_at date,
  source text,
  last_research_run_id text,
  last_score numeric,
  reference_price numeric,
  reason text,
  status text,
  last_monitor_flag text,
  last_monitor_date date,
  consecutive_drops integer,
  pipeline_status text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_watchlist_status on watchlist_items (status);
create index if not exists idx_watchlist_pipeline_status on watchlist_items (pipeline_status);

create table if not exists monitor_runs (
  run_id text primary key,
  run_date date not null,
  position_count integer not null default 0,
  alert_count integer not null default 0,
  high_alert_count integer not null default 0,
  market_news jsonb not null default '{}'::jsonb,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_monitor_runs_run_date on monitor_runs (run_date desc);

create table if not exists monitor_positions (
  id uuid primary key default gen_random_uuid(),
  run_id text not null references monitor_runs(run_id) on delete cascade,
  run_date date not null,
  ticker text not null,
  shares numeric,
  entry_price numeric,
  current_price numeric,
  target_price numeric,
  stop_loss numeric,
  pnl_pct numeric,
  change_pct numeric,
  note text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, ticker)
);

create index if not exists idx_monitor_positions_ticker_date on monitor_positions (ticker, run_date desc);

create table if not exists monitor_alerts (
  alert_id text primary key,
  run_id text references monitor_runs(run_id) on delete set null,
  alert_date date not null,
  ticker text not null,
  alert_type text not null,
  severity text not null,
  message text,
  current_price numeric,
  entry_price numeric,
  unrealized_pnl_pct numeric,
  stop_loss numeric,
  target_price numeric,
  status text not null default 'open',
  notified_at timestamptz,
  acknowledged_at timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_monitor_alerts_date on monitor_alerts (alert_date desc);
create index if not exists idx_monitor_alerts_status on monitor_alerts (status);
create index if not exists idx_monitor_alerts_severity on monitor_alerts (severity);

create table if not exists decision_requests (
  request_id text primary key,
  source_alert_id text references monitor_alerts(alert_id) on delete set null,
  ticker text not null,
  request_type text not null,
  reason text,
  status text not null default 'pending',
  requested_at timestamptz not null default now(),
  resolved_at timestamptz,
  raw_payload jsonb not null default '{}'::jsonb
);

create index if not exists idx_decision_requests_status on decision_requests (status);
create index if not exists idx_decision_requests_ticker on decision_requests (ticker);

create table if not exists decision_runs (
  run_id text primary key,
  run_date date not null,
  candidates_evaluated text[] not null default '{}',
  buy_decisions text[] not null default '{}',
  pass_decisions text[] not null default '{}',
  hold_cash_decisions text[] not null default '{}',
  buy_count integer not null default 0,
  pass_count integer not null default 0,
  hold_cash_count integer not null default 0,
  no_trade_week boolean not null default false,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_decision_runs_run_date on decision_runs (run_date desc);

create table if not exists investment_proposals (
  proposal_id text primary key,
  run_id text references decision_runs(run_id) on delete cascade,
  ticker text not null,
  action text,
  conviction text,
  position_size_usd numeric,
  shares_suggested numeric,
  entry_price_range text,
  target_price numeric,
  stop_loss numeric,
  signal_type text,
  rationale text,
  human_decision text not null default 'pending',
  slack_sent boolean not null default false,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_investment_proposals_run on investment_proposals (run_id);
create index if not exists idx_investment_proposals_ticker on investment_proposals (ticker);

create table if not exists research_runs (
  run_id text primary key,
  run_date date not null,
  candidate_count integer not null default 0,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_research_runs_run_date on research_runs (run_date desc);

create table if not exists research_candidates (
  candidate_id text primary key,
  run_id text not null references research_runs(run_id) on delete cascade,
  run_date date not null,
  ticker text not null,
  action text,
  conviction text,
  score numeric,
  entry_price numeric,
  entry_price_range text,
  target_price numeric,
  stop_loss numeric,
  signal_type text,
  rationale text,
  outcome_status text,
  outcome_type text,
  realized_return_pct numeric,
  alpha_pct numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, ticker)
);

create index if not exists idx_research_candidates_ticker on research_candidates (ticker);
create index if not exists idx_research_candidates_score on research_candidates (score desc);

create table if not exists score_snapshots (
  snapshot_id text primary key,
  run_id text,
  scored_at date,
  ticker text not null,
  company_name text,
  score numeric,
  rank_in_run integer,
  total_scored_in_run integer,
  price_at_score numeric,
  passed_threshold boolean,
  macro_regime text,
  sector_etf text,
  week1 jsonb,
  week2 jsonb,
  week3 jsonb,
  week4 jsonb,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_score_snapshots_ticker on score_snapshots (ticker);
create index if not exists idx_score_snapshots_scored_at on score_snapshots (scored_at desc);

create table if not exists trade_journal_entries (
  trade_id text primary key,
  ticker text,
  signal_type text,
  conviction text,
  hold_days integer,
  pnl_pct numeric,
  mae_pct numeric,
  mfe_pct numeric,
  mfe_capture_pct numeric,
  rule_adherence_score numeric,
  decision_quality numeric,
  outcome_quality numeric,
  would_take_again boolean,
  what_i_missed text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists market_news_sources (
  source_id text primary key,
  source_type text,
  value text,
  label text,
  status text,
  last_checked_at timestamptz,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists market_news_items (
  item_id text primary key,
  source_id text references market_news_sources(source_id) on delete set null,
  title text,
  url text,
  publisher text,
  published_at timestamptz,
  selected_for_monitor boolean,
  summary text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_market_news_items_published_at on market_news_items (published_at desc);

create table if not exists job_runs (
  job_run_id text primary key,
  job_name text not null,
  status text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  message text,
  raw_payload jsonb not null default '{}'::jsonb
);

create index if not exists idx_job_runs_name_started on job_runs (job_name, started_at desc);

create table if not exists notifications (
  notification_id text primary key,
  source_table text not null,
  source_id text not null,
  channel text not null default 'slack',
  severity text,
  status text not null default 'pending',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  error text,
  unique (source_table, source_id, channel)
);

create index if not exists idx_notifications_status on notifications (status);

create or replace function touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_positions_touch_updated_at on positions;
create trigger trg_positions_touch_updated_at
before update on positions
for each row execute function touch_updated_at();

drop trigger if exists trg_watchlist_touch_updated_at on watchlist_items;
create trigger trg_watchlist_touch_updated_at
before update on watchlist_items
for each row execute function touch_updated_at();

create or replace function enqueue_monitor_alert_notification()
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
      'monitor_alert:' || new.alert_id || ':slack',
      'monitor_alerts',
      new.alert_id,
      'slack',
      new.severity,
      'pending',
      jsonb_build_object(
        'ticker', new.ticker,
        'alert_type', new.alert_type,
        'severity', new.severity,
        'message', new.message,
        'current_price', new.current_price,
        'unrealized_pnl_pct', new.unrealized_pnl_pct,
        'alert_date', new.alert_date
      )
    )
    on conflict (source_table, source_id, channel) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_monitor_alert_notification on monitor_alerts;
create trigger trg_monitor_alert_notification
after insert on monitor_alerts
for each row execute function enqueue_monitor_alert_notification();

create or replace function enqueue_decision_request_from_alert()
returns trigger
language plpgsql
as $$
begin
  if new.alert_type in ('STOP_LOSS', 'TARGET_REACHED', 'SHARP_DROP')
     and coalesce(new.raw_payload ->> 'suppress_automation', 'false') <> 'true' then
    insert into decision_requests (
      request_id,
      source_alert_id,
      ticker,
      request_type,
      reason,
      status,
      raw_payload
    )
    values (
      'alert:' || new.alert_id,
      new.alert_id,
      new.ticker,
      case
        when new.alert_type = 'TARGET_REACHED' then 'exit_or_raise_target'
        when new.alert_type = 'STOP_LOSS' then 'exit_review'
        else 'risk_review'
      end,
      new.message,
      'pending',
      new.raw_payload
    )
    on conflict (request_id) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_decision_request_from_alert on monitor_alerts;
create trigger trg_decision_request_from_alert
after insert on monitor_alerts
for each row execute function enqueue_decision_request_from_alert();

create or replace view dashboard_open_positions as
select
  p.position_id,
  p.ticker,
  p.shares,
  p.entry_price,
  p.entry_date,
  p.target_price,
  p.stop_loss,
  p.conviction,
  p.signal_type,
  p.note,
  mp.current_price,
  case
    when mp.current_price is not null and p.entry_price is not null and p.entry_price > 0
      then round(((mp.current_price - p.entry_price) / p.entry_price * 100)::numeric, 2)
    else null
  end as pnl_pct,
  mp.run_date as last_monitored_at
from positions p
left join lateral (
  select *
  from monitor_positions mp
  where mp.ticker = p.ticker
    and mp.run_date >= p.entry_date
    and coalesce(mp.shares, 0) > 0
  order by mp.run_date desc, mp.created_at desc
  limit 1
) mp on true
where p.status = 'open'
  and p.portfolio_type = 'real'
order by p.ticker;

create or replace view dashboard_recent_alerts as
select
  alert_date,
  ticker,
  severity,
  alert_type,
  message,
  current_price,
  unrealized_pnl_pct,
  status,
  notified_at,
  created_at
from monitor_alerts
order by alert_date desc, created_at desc
limit 100;

create or replace view dashboard_monitor_runs as
select
  run_date,
  position_count,
  alert_count,
  high_alert_count,
  created_at
from monitor_runs
order by run_date desc, created_at desc;

create or replace view dashboard_decision_queue as
select
  requested_at,
  ticker,
  request_type,
  reason,
  status,
  source_alert_id
from decision_requests
where status = 'pending'
order by requested_at desc;

create or replace view dashboard_score_alpha as
select
  ticker,
  scored_at,
  score,
  macro_regime,
  sector_etf,
  (week3 ->> 'alpha_pct')::numeric as week3_alpha_pct,
  (week4 ->> 'alpha_pct')::numeric as week4_alpha_pct,
  passed_threshold
from score_snapshots
order by scored_at desc, score desc;
