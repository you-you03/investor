-- Replace performance dashboard views with simpler column names.
-- Keep names SQL-friendly, but avoid finance-heavy wording.

drop view if exists dashboard_performance_summary;
drop view if exists dashboard_equity_curve;
drop view if exists dashboard_daily_realized_pnl;
drop view if exists dashboard_cumulative_pnl;
drop view if exists dashboard_trade_history;

create or replace view dashboard_trade_history as
select
  p.position_id as trade_id,
  p.portfolio_type as type,
  p.ticker,
  p.status,
  p.shares,
  p.entry_date as buy_date,
  p.exit_date as sell_date,
  case
    when p.entry_date is not null
      then coalesce(p.exit_date, current_date) - p.entry_date
    else null
  end as days,
  p.entry_price as buy_price,
  p.exit_price as sell_price,
  p.target_price as target_price,
  p.stop_loss as stop_price,
  p.signal_type as reason_type,
  p.conviction as confidence,
  case
    when p.exit_price is not null and p.entry_price is not null and p.shares is not null
      then round(((p.exit_price - p.entry_price) * p.shares)::numeric, 2)
    else null
  end as profit_usd,
  case
    when p.exit_price is not null and p.entry_price is not null and p.entry_price > 0
      then round(((p.exit_price - p.entry_price) / p.entry_price * 100)::numeric, 2)
    else null
  end as return_pct,
  case
    when p.status = 'open'
      then null
    when p.exit_price is null
      then 'missing_sell_price'
    when p.exit_price >= p.entry_price
      then 'win'
    else 'loss'
  end as result,
  p.note as memo
from positions p
where p.portfolio_type = 'real'
order by coalesce(p.exit_date, p.entry_date) desc, p.position_id desc;

create or replace view dashboard_cumulative_pnl as
with closed_trades as (
  select
    p.position_id,
    p.ticker,
    p.exit_date,
    round(((p.exit_price - p.entry_price) * p.shares)::numeric, 2) as profit_usd,
    round(((p.exit_price - p.entry_price) / nullif(p.entry_price, 0) * 100)::numeric, 2) as return_pct
  from positions p
  where p.portfolio_type = 'real'
    and p.status = 'closed'
    and p.exit_date is not null
    and p.exit_price is not null
    and p.entry_price is not null
    and p.shares is not null
),
sequenced as (
  select
    *,
    sum(profit_usd) over (
      order by exit_date, position_id
      rows between unbounded preceding and current row
    ) as total_profit_usd,
    count(*) over (
      order by exit_date, position_id
      rows between unbounded preceding and current row
    ) as trades_count,
    sum(case when profit_usd >= 0 then 1 else 0 end) over (
      order by exit_date, position_id
      rows between unbounded preceding and current row
    ) as wins_count
  from closed_trades
)
select
  position_id as trade_id,
  ticker,
  exit_date as date,
  profit_usd,
  return_pct,
  total_profit_usd,
  trades_count,
  wins_count,
  round((wins_count::numeric / nullif(trades_count, 0) * 100), 2) as win_rate_pct
from sequenced
order by date desc, trade_id desc;

create or replace view dashboard_daily_realized_pnl as
select
  p.exit_date as date,
  count(*) as trades_closed,
  round(sum((p.exit_price - p.entry_price) * p.shares)::numeric, 2) as profit_usd,
  round(sum(sum((p.exit_price - p.entry_price) * p.shares)) over (
    order by p.exit_date
    rows between unbounded preceding and current row
  )::numeric, 2) as total_profit_usd,
  round((6700.0 + sum(sum((p.exit_price - p.entry_price) * p.shares)) over (
    order by p.exit_date
    rows between unbounded preceding and current row
  ))::numeric, 2) as assets_usd
from positions p
where p.portfolio_type = 'real'
  and p.status = 'closed'
  and p.exit_date is not null
  and p.exit_price is not null
  and p.entry_price is not null
  and p.shares is not null
group by p.exit_date
order by p.exit_date desc;

create or replace view dashboard_equity_curve as
with monitor_dates as (
  select distinct run_date
  from monitor_runs
),
closed_profit_by_date as (
  select
    d.run_date,
    coalesce(sum((p.exit_price - p.entry_price) * p.shares), 0) as closed_profit_usd
  from monitor_dates d
  left join positions p
    on p.portfolio_type = 'real'
   and p.status = 'closed'
   and p.exit_date is not null
   and p.exit_date <= d.run_date
   and p.exit_price is not null
   and p.entry_price is not null
   and p.shares is not null
  group by d.run_date
),
open_profit_by_date as (
  select
    mp.run_date,
    coalesce(sum((mp.current_price - mp.entry_price) * mp.shares), 0) as open_profit_usd,
    coalesce(sum(mp.current_price * mp.shares), 0) as open_value_usd,
    coalesce(sum(mp.entry_price * mp.shares), 0) as open_cost_usd
  from monitor_positions mp
  where coalesce(mp.shares, 0) > 0
    and mp.current_price is not null
    and mp.entry_price is not null
  group by mp.run_date
)
select
  d.run_date as date,
  6700.0::numeric as start_cash_usd,
  round(c.closed_profit_usd::numeric, 2) as closed_profit_usd,
  round(coalesce(o.open_profit_usd, 0)::numeric, 2) as open_profit_usd,
  round((c.closed_profit_usd + coalesce(o.open_profit_usd, 0))::numeric, 2) as total_profit_usd,
  round((6700.0 + c.closed_profit_usd + coalesce(o.open_profit_usd, 0))::numeric, 2) as assets_usd,
  round(coalesce(o.open_value_usd, 0)::numeric, 2) as open_value_usd,
  round(coalesce(o.open_cost_usd, 0)::numeric, 2) as open_cost_usd
from monitor_dates d
join closed_profit_by_date c on c.run_date = d.run_date
left join open_profit_by_date o on o.run_date = d.run_date
order by d.run_date desc;

create or replace view dashboard_performance_summary as
with closed_trades as (
  select
    round(((p.exit_price - p.entry_price) * p.shares)::numeric, 2) as profit_usd,
    round(((p.exit_price - p.entry_price) / nullif(p.entry_price, 0) * 100)::numeric, 2) as return_pct
  from positions p
  where p.portfolio_type = 'real'
    and p.status = 'closed'
    and p.exit_price is not null
    and p.entry_price is not null
    and p.shares is not null
),
open_positions as (
  select *
  from dashboard_open_positions
)
select
  6700.0::numeric as start_cash_usd,
  (select count(*) from closed_trades) as closed_trades,
  (select count(*) from open_positions) as open_positions,
  (select round(coalesce(sum(profit_usd), 0)::numeric, 2) from closed_trades) as total_profit_usd,
  (select round(coalesce(avg(return_pct), 0)::numeric, 2) from closed_trades) as avg_return_pct,
  (select round((count(*) filter (where profit_usd >= 0)::numeric / nullif(count(*), 0) * 100), 2) from closed_trades) as win_rate_pct,
  (select round(coalesce(sum((current_price - entry_price) * shares), 0)::numeric, 2) from open_positions) as open_profit_usd,
  (
    select round((6700.0 + coalesce((select sum(profit_usd) from closed_trades), 0) + coalesce(sum((current_price - entry_price) * shares), 0))::numeric, 2)
    from open_positions
  ) as assets_usd;
