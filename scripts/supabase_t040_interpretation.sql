-- T-040 解读层:每天一行(相似日 → 之后 30 天各风格分布 → 角度一致性),30 天后写回实际结果。S-167 姿态。
create table if not exists public.market_interpretation_daily (
  d date primary key,
  angles jsonb not null,        -- {style|macro|micro: {analogs: [[日期, 相似度]…], fwd: {键: {median,p25,p75,p_up,n}}}}
  pooled jsonb,                 -- 三个角度的相似日合在一起的分布
  agreement jsonb,              -- 两两角度对「各风格相对大币」方向的一致比例
  realized jsonb,               -- d 之后 30 天的实际结果(走完才有)
  narrative text,
  code_ref text,
  computed_at timestamptz not null default now());
alter table public.market_interpretation_daily enable row level security;
revoke all on public.market_interpretation_daily from anon, authenticated;
grant select, insert, update, delete on public.market_interpretation_daily to service_role;
