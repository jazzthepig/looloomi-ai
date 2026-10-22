-- 2026-10-22 · CIS v2 影子序列(S-668;src/data/cis/v2_shadow.py)。
-- 每天在 v1 正式发布之后,同一个 d 算一遍 v2:分数只留慢维度(规模 / 稳定 / 供给纪律,加密另加 v1 的 F / O),
-- 组 = 加密(CIS 的 25 个)/ 个股(CIS 美股单股 + World50 美股挂牌 / 美元 ADR);宏观 ETF 不打分。
-- 只追加:一个 (symbol, d, code_ref) 只写一次,触发器拒绝改删 —— 影子期的记录就是切换判定的证据。
-- 对外仍是 v1(cis_official_daily);lane 用 publishable key 可读(lane_read)。

create table if not exists public.cis_v2_daily (
  symbol        text not null,
  d             date not null,
  grp           text not null check (grp in ('crypto', 'equity')),
  score         double precision check (score is null or (score >= 0 and score <= 100)),
  n_dims        smallint not null,
  ranks         jsonb not null default '{}'::jsonb,
  raw           jsonb not null default '{}'::jsonb,
  missing       text[] not null default '{}',
  code_ref      text not null,
  published_at  timestamptz not null default now(),
  primary key (symbol, d, code_ref)
);
create index if not exists cis_v2_daily_d_idx on public.cis_v2_daily (d desc);
alter table public.cis_v2_daily enable row level security;

create or replace function public.cis_v2_daily_append_only() returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'cis_v2_daily 只追加:% 不允许', tg_op;
end $$;
drop trigger if exists cis_v2_daily_no_change on public.cis_v2_daily;
create trigger cis_v2_daily_no_change before update or delete on public.cis_v2_daily
  for each row execute function public.cis_v2_daily_append_only();

grant select on public.cis_v2_daily to anon;
drop policy if exists lane_read on public.cis_v2_daily;
create policy lane_read on public.cis_v2_daily for select to anon using (true);
