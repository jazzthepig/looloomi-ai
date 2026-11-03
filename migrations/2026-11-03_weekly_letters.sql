-- 2026-11-03 · weekly_letters: the scorecard letter (Jazz 11-03 "先 2 再 3"). One row per week_end; markdown + the data it was built from.
create table if not exists public.weekly_letters (
  week_end    date primary key,
  markdown    text not null,
  data        jsonb not null default '{}'::jsonb,
  note        text,
  created_at  timestamptz not null default now()
);
