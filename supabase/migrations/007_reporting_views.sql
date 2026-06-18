-- Report-ready views for Supabase Table Editor / SQL Editor.
-- These views intentionally use simple columns so they are easy to scan.

create or replace view report_summary_cards as
with perf as (
  select *
  from dashboard_performance_summary
),
alerts as (
  select
    count(*) filter (where status = 'open' and severity = 'HIGH') as high_alerts,
    count(*) filter (where status = 'open' and severity = 'MEDIUM') as medium_alerts
  from monitor_alerts
),
watch_alerts as (
  select
    count(*) filter (where status = 'open' and severity = 'HIGH') as high_watch_alerts,
    count(*) filter (where status = 'open' and severity = 'MEDIUM') as medium_watch_alerts
  from watchlist_alerts
),
watch as (
  select
    count(*) filter (where status = 'active') as active_watchlist,
    count(*) filter (where pipeline_status = 'decision_queued') as decision_waiting,
    count(*) filter (where pipeline_status = 'research_queued') as research_waiting
  from watchlist_items
)
select 10 as sort_order, '資産' as section, '推定資産' as item, assets_usd::text as value, '開始資金 + 確定損益 + 保有中損益' as memo from perf
union all
select 20, '損益', '累計損益', total_profit_usd::text, '決済済み取引の累計損益' from perf
union all
select 30, '損益', '保有中損益', open_profit_usd::text, 'open position の含み損益' from perf
union all
select 40, '取引', '勝率', win_rate_pct::text || '%', '決済済み取引ベース' from perf
union all
select 50, '取引', '決済済み', closed_trades::text, 'closed trades' from perf
union all
select 60, '取引', '保有中', open_positions::text, 'open positions' from perf
union all
select 70, 'アラート', '保有HIGH', high_alerts::text, 'portfolio monitor の未対応HIGH' from alerts
union all
select 80, 'アラート', '保有MEDIUM', medium_alerts::text, 'portfolio monitor の未対応MEDIUM' from alerts
union all
select 90, '監視リスト', '監視中', active_watchlist::text, 'active watchlist items' from watch
union all
select 100, '監視リスト', '判断待ち', decision_waiting::text, 'decision_queued' from watch
union all
select 110, '監視リスト', '調査待ち', research_waiting::text, 'research_queued' from watch
union all
select 120, '監視リスト', 'WL HIGH', high_watch_alerts::text, 'watchlist monitor の未対応HIGH' from watch_alerts
union all
select 130, '監視リスト', 'WL MEDIUM', medium_watch_alerts::text, 'watchlist monitor の未対応MEDIUM' from watch_alerts
order by sort_order;

create or replace view report_action_list as
select
  10 as sort_order,
  'portfolio' as source,
  alert_date as date,
  ticker,
  severity,
  alert_type as type,
  message,
  case
    when alert_type in ('STOP_LOSS', 'TARGET_REACHED', 'SHARP_DROP') then '/decision --mode exit --ticker ' || ticker
    else 'check position'
  end as next_step,
  status
from monitor_alerts
where status = 'open'
union all
select
  20,
  'watchlist',
  alert_date,
  ticker,
  severity,
  alert_type,
  message,
  next_step,
  status
from watchlist_alerts
where status = 'open'
union all
select
  30,
  'decision_request',
  requested_at::date,
  ticker,
  'HIGH',
  request_type,
  reason,
  case
    when request_type like 'exit%' then '/decision --mode exit --ticker ' || ticker
    else '/decision'
  end,
  status
from decision_requests
where status = 'pending'
order by
  case severity when 'HIGH' then 1 when 'MEDIUM' then 2 else 3 end,
  date desc,
  sort_order,
  ticker;

create or replace view report_assets_by_day as
select
  date,
  assets_usd,
  total_profit_usd as profit_usd,
  closed_profit_usd,
  open_profit_usd,
  open_value_usd
from dashboard_equity_curve
order by date desc;

create or replace view report_profit_by_month as
select
  to_char(date_trunc('month', date), 'YYYY-MM') as month,
  round(sum(profit_usd)::numeric, 2) as profit_usd,
  count(*) as trade_days,
  max(total_profit_usd) as total_profit_usd,
  max(assets_usd) as assets_usd
from dashboard_daily_realized_pnl
group by date_trunc('month', date)
order by month desc;

create or replace view report_trades_simple as
select
  sell_date as date,
  ticker,
  result,
  profit_usd,
  return_pct,
  days,
  buy_price,
  sell_price,
  reason_type,
  confidence,
  memo
from dashboard_trade_history
where status = 'closed'
order by date desc, ticker;

create or replace view report_open_positions_simple as
select
  ticker,
  shares,
  entry_price as buy_price,
  current_price,
  pnl_pct as return_pct,
  round(((current_price - entry_price) * shares)::numeric, 2) as profit_usd,
  target_price,
  stop_loss as stop_price,
  last_monitored_at as checked_date,
  note as memo
from dashboard_open_positions
order by ticker;

create or replace view report_watchlist_simple as
select
  ticker,
  simple_status as status,
  stage,
  score,
  latest_flag,
  checked_date,
  memo
from dashboard_watchlist
order by
  case simple_status
    when 'needs_action' then 1
    when 'in_portfolio' then 2
    when 'speculative' then 3
    else 9
  end,
  score desc nulls last,
  ticker;

create or replace view report_latest_monitor as
select
  run_date as date,
  position_count as positions,
  alert_count as alerts,
  high_alert_count as high_alerts,
  created_at
from monitor_runs
order by run_date desc, created_at desc
limit 20;
