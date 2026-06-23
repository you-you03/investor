-- Persist score validation report metrics in Supabase.
-- These tables store the structured contents of reports/validation/validation_YYYY-MM-DD.md.

create table if not exists validation_runs (
  validation_id text primary key,
  validation_date date not null,
  period_start date,
  period_end date,
  snapshot_count integer not null default 0,
  passed_threshold_count integer not null default 0,
  rejected_threshold_count integer not null default 0,
  report_path text,
  report_markdown text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_validation_runs_date on validation_runs(validation_date desc);

create table if not exists validation_horizon_ic (
  validation_id text references validation_runs(validation_id) on delete cascade,
  horizon text not null,
  sample_count integer not null default 0,
  spearman_rho numeric,
  p_value numeric,
  label text,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, horizon)
);

create table if not exists validation_score_buckets (
  validation_id text references validation_runs(validation_id) on delete cascade,
  bucket_label text not null,
  bucket_order integer not null,
  sample_count integer not null default 0,
  week1_avg_return_pct numeric,
  week2_avg_return_pct numeric,
  week3_avg_return_pct numeric,
  week4_avg_return_pct numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, bucket_label)
);

create table if not exists validation_conviction_spy_matrix (
  validation_id text references validation_runs(validation_id) on delete cascade,
  horizon text not null,
  conviction text not null,
  spy_bucket_label text not null,
  sample_count integer not null default 0,
  avg_return_pct numeric,
  spy_min_pct numeric,
  spy_max_pct numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, horizon, conviction, spy_bucket_label)
);

create table if not exists validation_horizon_conviction_summary (
  validation_id text references validation_runs(validation_id) on delete cascade,
  horizon text not null,
  conviction text not null,
  sample_count integer not null default 0,
  avg_return_pct numeric,
  median_return_pct numeric,
  avg_alpha_spy_pct numeric,
  avg_alpha_qqq_pct numeric,
  avg_alpha_sector_pct numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, horizon, conviction)
);

create table if not exists validation_best_horizons (
  validation_id text references validation_runs(validation_id) on delete cascade,
  conviction text not null,
  best_return_horizon text,
  best_return_pct numeric,
  best_return_sample_count integer,
  best_spy_alpha_horizon text,
  best_spy_alpha_pct numeric,
  best_spy_alpha_sample_count integer,
  best_sector_alpha_horizon text,
  best_sector_alpha_pct numeric,
  best_sector_alpha_sample_count integer,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, conviction)
);

create table if not exists validation_regime_summary (
  validation_id text references validation_runs(validation_id) on delete cascade,
  regime text not null,
  sample_count integer not null default 0,
  avg_return_pct numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, regime)
);

create table if not exists validation_factor_ic (
  validation_id text references validation_runs(validation_id) on delete cascade,
  factor text not null,
  horizon text not null,
  sample_count integer not null default 0,
  spearman_rho numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, factor, horizon)
);

create table if not exists validation_threshold_comparison (
  validation_id text references validation_runs(validation_id) on delete cascade,
  horizon text not null,
  passed_avg_return_pct numeric,
  rejected_avg_return_pct numeric,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (validation_id, horizon)
);

create table if not exists validation_calibration_suggestions (
  suggestion_id text primary key,
  validation_id text references validation_runs(validation_id) on delete cascade,
  suggestion_order integer not null,
  suggestion text not null,
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

drop trigger if exists trg_validation_runs_touch_updated_at on validation_runs;
create trigger trg_validation_runs_touch_updated_at
before update on validation_runs
for each row execute function touch_updated_at();
