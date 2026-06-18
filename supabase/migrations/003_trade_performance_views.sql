-- Trade history, cumulative P&L, and equity curve dashboard views.

create or replace view dashboard_trade_history as
select
  p.position_id,
  p.portfolio_type,
  p.ticker,
  p.status,
  p.shares,
  p.entry_date,
  p.exit_date,
  case
    when p.entry_date is not null
      then coalesce(p.exit_date, current_date) - p.entry_date
    else null
  end as days_held,
  p.entry_price,
  p.exit_price,
  p.target_price,
  p.stop_loss,
  p.signal_type,
  p.conviction,
  case
    when p.exit_price is not null and p.entry_price is not null and p.shares is not null
      then round(((p.exit_price - p.entry_price) * p.shares)::numeric, 2)
    else null
  end as realized_pnl_usd,
  case
    when p.exit_price is not null and p.entry_price is not null and p.entry_price > 0
      then round(((p.exit_price - p.entry_price) / p.entry_price * 100)::numeric, 2)
    else null
  end as realized_return_pct,
  case
    when p.status = 'open'
      then null
    when p.exit_price is null
      then 'missing_exit'
    when p.exit_price >= p.entry_price
      then 'win'
    else 'loss'
  end as outcome,
  p.note
from positions p
where p.portfolio_type = 'real'
order by coalesce(p.exit_date, p.entry_date) desc, p.position_id desc;

create or replace view dashboard_cumulative_pnl as
with closed_trades as (
  select
    p.position_id,
    p.ticker,
    p.exit_date,
    round(((p.exit_price - p.entry_price) * p.shares)::numeric, 2) as realized_pnl_usd,
    round(((p.exit_price - p.entry_price) / nullif(p.entry_price, 0) * 100)::numeric, 2) as realized_return_pct
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
    sum(realized_pnl_usd) over (
      order by exit_date, position_id
      rows between unbounded preceding and current row
    ) as cumulative_realized_pnl_usd,
    count(*) over (
      order by exit_date, position_id
      rows between unbounded preceding and current row
    ) as closed_trade_count,
    sum(case when realized_pnl_usd >= 0 then 1 else 0 end) over (
      order by exit_date, position_id
      rows between unbounded preceding and current row
    ) as cumulative_wins
  from closed_trades
)
select
  position_id,
  ticker,
  exit_date,
  realized_pnl_usd,
  realized_return_pct,
  cumulative_realized_pnl_usd,
  closed_trade_count,
  cumulative_wins,
  round((cumulative_wins::numeric / nullif(closed_trade_count, 0) * 100), 2) as cumulative_win_rate_pct
from sequenced
order by exit_date desc, position_id desc;

create or replace view dashboard_daily_realized_pnl as
select
  p.exit_date as trade_date,
  count(*) as closed_trade_count,
  round(sum((p.exit_price - p.entry_price) * p.shares)::numeric, 2) as daily_realized_pnl_usd,
  round(sum(sum((p.exit_price - p.entry_price) * p.shares)) over (
    order by p.exit_date
    rows between unbounded preceding and current row
  )::numeric, 2) as cumulative_realized_pnl_usd
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
realized_by_date as (
  select
    d.run_date,
    coalesce(sum((p.exit_price - p.entry_price) * p.shares), 0) as realized_pnl_usd
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
unrealized_by_date as (
  select
    mp.run_date,
    coalesce(sum((mp.current_price - mp.entry_price) * mp.shares), 0) as unrealized_pnl_usd,
    coalesce(sum(mp.current_price * mp.shares), 0) as monitored_market_value_usd,
    coalesce(sum(mp.entry_price * mp.shares), 0) as monitored_cost_basis_usd
  from monitor_positions mp
  where coalesce(mp.shares, 0) > 0
    and mp.current_price is not null
    and mp.entry_price is not null
  group by mp.run_date
)
select
  d.run_date,
  6700.0::numeric as starting_capital_usd,
  round(r.realized_pnl_usd::numeric, 2) as realized_pnl_usd,
  round(coalesce(u.unrealized_pnl_usd, 0)::numeric, 2) as unrealized_pnl_usd,
  round((r.realized_pnl_usd + coalesce(u.unrealized_pnl_usd, 0))::numeric, 2) as total_pnl_usd,
  round((6700.0 + r.realized_pnl_usd + coalesce(u.unrealized_pnl_usd, 0))::numeric, 2) as estimated_equity_usd,
  round(coalesce(u.monitored_market_value_usd, 0)::numeric, 2) as monitored_market_value_usd,
  round(coalesce(u.monitored_cost_basis_usd, 0)::numeric, 2) as monitored_cost_basis_usd
from monitor_dates d
join realized_by_date r on r.run_date = d.run_date
left join unrealized_by_date u on u.run_date = d.run_date
order by d.run_date desc;

create or replace view dashboard_performance_summary as
with closed_trades as (
  select
    round(((p.exit_price - p.entry_price) * p.shares)::numeric, 2) as pnl,
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
  6700.0::numeric as starting_capital_usd,
  (select count(*) from closed_trades) as closed_trade_count,
  (select count(*) from open_positions) as open_position_count,
  (select round(coalesce(sum(pnl), 0)::numeric, 2) from closed_trades) as cumulative_realized_pnl_usd,
  (select round(coalesce(avg(return_pct), 0)::numeric, 2) from closed_trades) as avg_realized_return_pct,
  (select round((count(*) filter (where pnl >= 0)::numeric / nullif(count(*), 0) * 100), 2) from closed_trades) as win_rate_pct,
  (select round(coalesce(sum((current_price - entry_price) * shares), 0)::numeric, 2) from open_positions) as current_unrealized_pnl_usd,
  (
    select round((6700.0 + coalesce((select sum(pnl) from closed_trades), 0) + coalesce(sum((current_price - entry_price) * shares), 0))::numeric, 2)
    from open_positions
  ) as estimated_current_equity_usd;
