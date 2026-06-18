-- Fix dashboard_open_positions so old watchlist-like monitor rows do not
-- masquerade as current position prices.

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
