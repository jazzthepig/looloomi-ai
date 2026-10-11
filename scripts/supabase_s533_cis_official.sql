-- S-533 / T-080 — 正式 CIS:统一标准的日终序列,每天一批,只追加(Jazz 10-11 批准)。
-- 写进去之后不能改、不能删(触发器):后来修订的数据不回改已经发布的信号;要改只能出新版本(code_ref)。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-11(migration s533_cis_official)。
create table if not exists public.cis_official_daily (
  symbol                text not null,
  d                     date not null,
  asset_class           text,
  cis_score             double precision,
  regime_adjusted_score double precision,
  grade                 text,
  signal                text,
  watch                 text,
  pct                   double precision,
  pillar_f              double precision,
  pillar_m              double precision,
  pillar_o              double precision,
  pillar_s              double precision,
  pillar_a              double precision,
  regime                text,
  inputs                jsonb,
  missing               text[],
  code_ref              text not null,
  published_at          timestamptz not null,
  primary key (symbol, d)
);
create index if not exists cis_official_daily_d on public.cis_official_daily (d);
alter table public.cis_official_daily enable row level security;
revoke all on public.cis_official_daily from anon, authenticated;
grant select, insert on public.cis_official_daily to service_role;

create or replace function public.cis_official_daily_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'cis_official_daily is append-only: % on (%, %) refused', tg_op, old.symbol, old.d;
end $$;
drop trigger if exists cis_official_daily_no_change on public.cis_official_daily;
create trigger cis_official_daily_no_change before update or delete on public.cis_official_daily
  for each row execute function public.cis_official_daily_immutable();
