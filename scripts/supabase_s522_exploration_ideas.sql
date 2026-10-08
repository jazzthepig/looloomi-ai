-- S-522 / T-074 — 探索仓的入口:机会提交,只追加。模块 src/data/exploration/ideas.py;
-- 每天的前向锚(forward_anchor_daily)把当天的提交一起锚定。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s522_exploration_ideas)。
create table if not exists public.exploration_ideas (
  id           bigint generated always as identity primary key,
  d            date not null,
  submitted_at timestamptz not null,
  asset        text not null,
  chain        text,
  contract     text,
  thesis       text not null,
  source       text,
  submitted_by text not null,
  horizon      text not null,
  status       text not null default 'open'
);
create index if not exists exploration_ideas_d on public.exploration_ideas (d);
alter table public.exploration_ideas enable row level security;
revoke all on public.exploration_ideas from anon, authenticated;
grant select, insert, update, delete on public.exploration_ideas to service_role;
