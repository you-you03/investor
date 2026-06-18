-- Read-only queries for Supabase Reports / Charts.
-- Do not paste migration files into Reports. Reports only accepts SELECT.

-- Summary cards / table
select
  section,
  item,
  value,
  memo
from report_summary_cards
order by sort_order;

-- Action list
select
  source,
  date,
  ticker,
  severity,
  type,
  message,
  next_step,
  status
from report_action_list;

-- Assets over time. Good for line chart:
-- X axis: date
-- Y axis: assets_usd
select
  date,
  assets_usd,
  profit_usd,
  closed_profit_usd,
  open_profit_usd,
  open_value_usd
from report_assets_by_day
order by date;

-- Monthly profit. Good for bar chart:
-- X axis: month
-- Y axis: profit_usd
select
  month,
  profit_usd,
  total_profit_usd,
  assets_usd,
  trade_days
from report_profit_by_month
order by month;

-- Closed trades table
select
  date,
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
from report_trades_simple
order by date desc, ticker;

-- Open positions table
select
  ticker,
  shares,
  buy_price,
  current_price,
  return_pct,
  profit_usd,
  target_price,
  stop_price,
  checked_date,
  memo
from report_open_positions_simple
order by ticker;

-- Watchlist table
select
  ticker,
  status,
  stage,
  score,
  latest_flag,
  checked_date,
  memo
from report_watchlist_simple;
