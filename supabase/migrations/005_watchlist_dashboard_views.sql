-- Simple watchlist dashboard views.

create or replace view dashboard_watchlist as
select
  ticker,
  status,
  pipeline_status as stage,
  last_score as score,
  reference_price as ref_price,
  last_monitor_flag as latest_flag,
  last_monitor_date as checked_date,
  case
    when pipeline_status in ('decision_queued', 'research_queued') then 'needs_action'
    when pipeline_status = 'position_open' then 'in_portfolio'
    when last_monitor_flag in ('SPECULATIVE_WATCH') then 'speculative'
    when status = 'active' then 'watch'
    else status
  end as simple_status,
  left(coalesce(reason, ''), 180) as memo
from watchlist_items
where status = 'active'
order by
  case
    when pipeline_status = 'decision_queued' then 1
    when pipeline_status = 'research_queued' then 2
    when pipeline_status = 'position_open' then 3
    else 9
  end,
  last_score desc nulls last,
  ticker;

create or replace view dashboard_watchlist_action_needed as
select *
from dashboard_watchlist
where simple_status = 'needs_action'
order by score desc nulls last, ticker;

create or replace view dashboard_watchlist_summary as
select
  count(*) filter (where status = 'active') as active_count,
  count(*) filter (where pipeline_status = 'decision_queued') as decision_needed,
  count(*) filter (where pipeline_status = 'research_queued') as research_needed,
  count(*) filter (where pipeline_status = 'position_open') as in_portfolio,
  count(*) filter (where last_monitor_flag = 'SPECULATIVE_WATCH') as speculative_count,
  round(avg(last_score) filter (where status = 'active'), 2) as avg_score
from watchlist_items;
