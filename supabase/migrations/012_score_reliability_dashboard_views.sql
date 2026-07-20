-- Views for the local score reliability dashboard.
-- Keep the browser dashboard thin: SQL owns the metric definitions.

drop view if exists score_reliability_summary;
drop view if exists score_reliability_score_scatter;
drop view if exists score_reliability_return_distribution;
drop view if exists score_reliability_suggestions;
drop view if exists score_reliability_maturity;
drop view if exists score_reliability_factor_latest;
drop view if exists score_reliability_threshold_latest;
drop view if exists score_reliability_threshold_history;
drop view if exists score_reliability_horizon_latest;
drop view if exists score_reliability_horizon_history;

create or replace view score_reliability_horizon_history as
select
  r.validation_date,
  h.horizon,
  nullif(regexp_replace(h.horizon, '\D', '', 'g'), '')::integer as horizon_weeks,
  h.sample_count,
  h.spearman_rho,
  h.p_value,
  h.label
from validation_horizon_ic h
join validation_runs r on r.validation_id = h.validation_id;

create or replace view score_reliability_horizon_latest as
select *
from score_reliability_horizon_history
where validation_date = (select max(validation_date) from validation_runs)
order by horizon_weeks;

create or replace view score_reliability_threshold_history as
select
  r.validation_date,
  t.horizon,
  nullif(regexp_replace(t.horizon, '\D', '', 'g'), '')::integer as horizon_weeks,
  t.passed_avg_return_pct,
  t.rejected_avg_return_pct,
  t.passed_avg_return_pct - t.rejected_avg_return_pct as spread_return_pct
from validation_threshold_comparison t
join validation_runs r on r.validation_id = t.validation_id;

create or replace view score_reliability_threshold_latest as
select *
from score_reliability_threshold_history
where validation_date = (select max(validation_date) from validation_runs)
order by horizon_weeks;

create or replace view score_reliability_factor_latest as
select
  r.validation_date,
  f.factor,
  f.horizon,
  nullif(regexp_replace(f.horizon, '\D', '', 'g'), '')::integer as horizon_weeks,
  f.sample_count,
  f.spearman_rho,
  case
    when f.sample_count < 30 then '判断保留'
    when f.spearman_rho >= 0.30 then '強い: 配点引き上げ候補'
    when f.spearman_rho >= 0.15 then '有効: 配点維持'
    when f.spearman_rho > 0 then '弱い: 補助扱い'
    else '弱い/逆効果: 配点引き下げ候補'
  end as judgement,
  case
    when f.factor = 'fundamentals' and f.spearman_rho >= 0.20 then 'BUY根拠として重視'
    when f.factor in ('technical', 'catalyst') and f.spearman_rho < 0.10 then '単独の買い理由にしない'
    when f.factor = 'sentiment' and f.spearman_rho >= 0.15 then '補助材料として使う'
    else '継続監視'
  end as action
from validation_factor_ic f
join validation_runs r on r.validation_id = f.validation_id
where r.validation_date = (select max(validation_date) from validation_runs);

create or replace view score_reliability_summary as
with latest_run as (
  select *
  from validation_runs
  where validation_date = (select max(validation_date) from validation_runs)
),
metrics as (
  select
    r.validation_id,
    r.validation_date,
    r.period_start,
    r.period_end,
    r.snapshot_count,
    r.passed_threshold_count,
    r.rejected_threshold_count,
    w4.spearman_rho as week4_ic,
    w4.sample_count as week4_sample_count,
    w4.p_value as week4_p_value,
    w8.spearman_rho as week8_ic,
    w8.sample_count as week8_sample_count,
    w8.p_value as week8_p_value,
    t4.spread_return_pct as week4_threshold_spread,
    t8.spread_return_pct as week8_threshold_spread
  from latest_run r
  left join score_reliability_horizon_history w4
    on w4.validation_date = r.validation_date and w4.horizon = 'week4'
  left join score_reliability_horizon_history w8
    on w8.validation_date = r.validation_date and w8.horizon = 'week8'
  left join score_reliability_threshold_history t4
    on t4.validation_date = r.validation_date and t4.horizon = 'week4'
  left join score_reliability_threshold_history t8
    on t8.validation_date = r.validation_date and t8.horizon = 'week8'
)
select
  *,
  case
    when week4_ic >= 0.20 and week4_threshold_spread > 0 then '使える: 4週目線の候補選別に有効'
    when week8_ic >= 0.20 and week8_threshold_spread > 0 then '条件付きで使える: 長めの保有期間では有効'
    when week4_threshold_spread > 0 then '足切りには使える: ランキング精度は弱い'
    else '要見直し: スコア閾値または配点の再検証が必要'
  end as overall_judgement,
  case
    when snapshot_count < 30 then '判断保留: 検証データを蓄積'
    when week4_ic >= 0.20 and week4_threshold_spread > 0 then 'score>=7.0を候補順位付けに使う'
    when week4_threshold_spread > 0 then 'score>=7.0を足切りに使い、順位付けは補助扱い'
    else '次回/reviewで配点と閾値を見直す'
  end as recommended_action
from metrics;

create or replace view score_reliability_suggestions as
select
  r.validation_date,
  s.suggestion_order,
  s.suggestion
from validation_calibration_suggestions s
join validation_runs r on r.validation_id = s.validation_id
where r.validation_date = (select max(validation_date) from validation_runs)
order by s.suggestion_order;

create or replace view score_reliability_maturity as
with observations as (
  select 1 as horizon_weeks, 'week1' as horizon, week1 as week_data from score_snapshots
  union all select 2, 'week2', week2 from score_snapshots
  union all select 3, 'week3', week3 from score_snapshots
  union all select 4, 'week4', week4 from score_snapshots
  union all select 5, 'week5', week5 from score_snapshots
  union all select 6, 'week6', week6 from score_snapshots
  union all select 7, 'week7', week7 from score_snapshots
  union all select 8, 'week8', week8 from score_snapshots
)
select
  horizon_weeks,
  horizon,
  count(*) as total_observations,
  count(*) filter (where nullif(week_data->>'target_date', '')::date <= current_date) as matured_count,
  count(*) filter (where week_data->>'return_pct' is not null) as fetched_count,
  round(
    count(*) filter (where week_data->>'return_pct' is not null)::numeric
    / nullif(count(*), 0) * 100,
    1
  ) as fetched_pct,
  case
    when count(*) filter (where week_data->>'return_pct' is not null) >= 50 then '十分'
    when count(*) filter (where week_data->>'return_pct' is not null) >= 30 then '最低限OK'
    else '判断保留'
  end as judgement
from observations
where week_data is not null
group by horizon_weeks, horizon
order by horizon_weeks;

create or replace view score_reliability_return_distribution as
with observations as (
  select 1 as horizon_weeks, 'week1' as horizon, (week1->>'return_pct')::numeric as return_pct from score_snapshots
  union all select 2, 'week2', (week2->>'return_pct')::numeric from score_snapshots
  union all select 3, 'week3', (week3->>'return_pct')::numeric from score_snapshots
  union all select 4, 'week4', (week4->>'return_pct')::numeric from score_snapshots
  union all select 5, 'week5', (week5->>'return_pct')::numeric from score_snapshots
  union all select 6, 'week6', (week6->>'return_pct')::numeric from score_snapshots
  union all select 7, 'week7', (week7->>'return_pct')::numeric from score_snapshots
  union all select 8, 'week8', (week8->>'return_pct')::numeric from score_snapshots
)
select
  horizon_weeks,
  horizon,
  round(return_pct, 2) as return_pct
from observations
where return_pct is not null
  and abs(return_pct) <= 100
order by horizon_weeks, return_pct;

create or replace view score_reliability_score_scatter as
select
  ticker,
  scored_at,
  round(score::numeric, 2) as score,
  passed_threshold,
  macro_regime,
  sector_etf,
  round((week4->>'return_pct')::numeric, 2) as week4_return_pct,
  round((week4->>'alpha_spy_pct')::numeric, 2) as week4_alpha_spy_pct,
  round((week4->>'alpha_qqq_pct')::numeric, 2) as week4_alpha_qqq_pct,
  round((week4->>'alpha_sector_pct')::numeric, 2) as week4_alpha_sector_pct
from score_snapshots
where score is not null
  and score > 6
  and week4->>'return_pct' is not null
  and abs((week4->>'return_pct')::numeric) <= 100
order by score, week4_return_pct;
