-- T-099 / S-581 — World50 的营收原始事实(增长分的输入;EW×(Mom+Growth) 臂)。模块 src/data/universe/world50_data.py 的 refresh_revenue;
-- 周更循环 _world50_history_loop 的 revenue 段。S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-15(migration t099_world50_revenue)。
-- 一行 = SEC companyconcept 的一个期间(一季 80–100 天或一年 350–380 天),同一期间取最早报送;单位原样(外国公司是本币)。
create table if not exists public.world50_revenue (
  key           text not null,          -- world50.CANDIDATES 的 key
  tag           text not null,          -- 'us-gaap:Revenues' / 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax' / … / 'ifrs-full:Revenue'
  unit          text not null,          -- USD / EUR / DKK / TWD …
  period_start  date not null,
  period_end    date not null,
  filed         date not null,          -- 已知日
  revenue       double precision not null,
  accn          text,
  recorded_at   timestamptz not null default now(),
  primary key (key, tag, unit, period_start, period_end)
);
create index if not exists world50_revenue_key_filed on public.world50_revenue (key, filed);
alter table public.world50_revenue enable row level security;
revoke all on public.world50_revenue from anon, authenticated;
grant select, insert, update, delete on public.world50_revenue to service_role;
