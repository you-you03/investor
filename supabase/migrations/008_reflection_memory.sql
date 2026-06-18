-- Full reflection memory for Codex-driven review loops.
-- Goal: historical decisions, outcomes, reports, and future reflections all live in Supabase.

create table if not exists daily_lite_runs (
  run_id text primary key,
  run_date date not null,
  position_count integer not null default 0,
  position_alert_count integer not null default 0,
  watchlist_count integer not null default 0,
  research_candidate_count integer not null default 0,
  pending_action_count integer not null default 0,
  report_path text,
  macro_context jsonb not null default '{}'::jsonb,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists daily_lite_actions (
  action_id text primary key,
  run_id text references daily_lite_runs(run_id) on delete cascade,
  run_date date not null,
  ticker text,
  action_type text,
  command text,
  detail text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_daily_lite_actions_run on daily_lite_actions(run_id);
create index if not exists idx_daily_lite_actions_ticker on daily_lite_actions(ticker);

create table if not exists watchlist_research_runs (
  run_id text primary key,
  run_date date not null,
  result_count integer not null default 0,
  escalate_count integer not null default 0,
  remove_count integer not null default 0,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists watchlist_research_results (
  result_id text primary key,
  run_id text references watchlist_research_runs(run_id) on delete cascade,
  run_date date not null,
  ticker text not null,
  action text,
  new_score numeric,
  flag text,
  note text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, ticker)
);

create index if not exists idx_watchlist_research_results_ticker on watchlist_research_results(ticker);

create table if not exists report_artifacts (
  artifact_id text primary key,
  report_type text not null,
  report_date date,
  title text,
  path text not null unique,
  content_markdown text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_report_artifacts_type_date on report_artifacts(report_type, report_date desc);

create table if not exists reflection_runs (
  reflection_id text primary key,
  reflection_date date not null default current_date,
  scope text not null,
  period_start date,
  period_end date,
  trigger_source text,
  summary text,
  conclusion text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists reflection_findings (
  finding_id text primary key,
  reflection_id text references reflection_runs(reflection_id) on delete cascade,
  ticker text,
  finding_type text not null,
  severity text,
  title text not null,
  evidence text,
  recommendation text,
  status text not null default 'open',
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_reflection_findings_ticker on reflection_findings(ticker);
create index if not exists idx_reflection_findings_status on reflection_findings(status);

create table if not exists codex_memory_events (
  event_id text primary key,
  event_date date not null default current_date,
  event_type text not null,
  ticker text,
  source_table text,
  source_id text,
  summary text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_codex_memory_events_type_date on codex_memory_events(event_type, event_date desc);
create index if not exists idx_codex_memory_events_ticker on codex_memory_events(ticker);

drop trigger if exists trg_report_artifacts_touch_updated_at on report_artifacts;
create trigger trg_report_artifacts_touch_updated_at
before update on report_artifacts
for each row execute function touch_updated_at();

create or replace view report_decision_performance as
with proposal_rows as (
  select
    rc.run_id,
    rc.run_date,
    rc.ticker,
    rc.action,
    rc.conviction,
    rc.score,
    rc.signal_type,
    rc.outcome_status,
    rc.outcome_type,
    rc.realized_return_pct,
    rc.alpha_pct,
    case
      when rc.realized_return_pct is null then null
      when rc.realized_return_pct >= 0 then 'win'
      else 'loss'
    end as result
  from research_candidates rc
  where rc.action is not null
)
select
  ticker,
  run_date,
  action,
  conviction as confidence,
  score,
  signal_type as reason_type,
  outcome_status,
  outcome_type,
  realized_return_pct as return_pct,
  alpha_pct,
  result
from proposal_rows
order by run_date desc, ticker;

create or replace view report_reflection_inputs as
select
  'trade' as source,
  coalesce(sell_date, buy_date) as date,
  ticker,
  result as label,
  profit_usd::text as value,
  memo
from dashboard_trade_history
union all
select
  'score',
  scored_at,
  ticker,
  'score=' || coalesce(score::text, '-'),
  coalesce((week3 ->> 'alpha_pct'), '-') as value,
  'week3 alpha'
from score_snapshots
union all
select
  'decision',
  run_date,
  ticker,
  coalesce(action, '-'),
  coalesce(score::text, '-'),
  coalesce(rationale, '')
from research_candidates
order by date desc, source, ticker;

create or replace view report_latest_reflections as
select
  r.reflection_date as date,
  r.scope,
  r.summary,
  r.conclusion,
  count(f.finding_id) filter (where f.status = 'open') as open_findings
from reflection_runs r
left join reflection_findings f on f.reflection_id = r.reflection_id
group by r.reflection_id, r.reflection_date, r.scope, r.summary, r.conclusion
order by r.reflection_date desc, r.created_at desc;
