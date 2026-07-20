alter table if exists score_snapshots
  add column if not exists week5 jsonb,
  add column if not exists week6 jsonb,
  add column if not exists week7 jsonb,
  add column if not exists week8 jsonb;
