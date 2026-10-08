-- S-519 / T-073 — 前向记录锚定:每天一行,只追加。payload = 前一天全部前向账本行(规范 JSON),
-- digest = SHA-256(payload),ots = {日历: .ots 证明的 base64}。模块:src/data/accounting/anchor.py。
-- S-167 姿态:RLS 开、零 policy、只授 service_role;对外经 /api/v1/proof/anchors 只读。AS APPLIED 2026-10-08(migration s519_forward_anchor)。
create table if not exists public.forward_anchor_daily (
  d            date primary key,
  digest       text not null,
  payload      jsonb not null,
  n_rows       integer not null,
  ots          jsonb not null,
  submitted_at timestamptz not null,
  code_ref     text
);
alter table public.forward_anchor_daily enable row level security;
revoke all on public.forward_anchor_daily from anon, authenticated;
grant select, insert, update, delete on public.forward_anchor_daily to service_role;
