-- S-529 / T-078 — 每个 CIS 信号的归因:为什么出(支柱贡献)、出了之后怎样(同类 / 相对 / BTC β)。
-- 一行 = 一次信号变化(symbol, d)。v_cis_signal_daily 补上分数、等级、五个支柱(列加在末尾,旧读者不受影响)。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s529_signal_attribution)。
create table if not exists public.cis_signal_attribution (
  symbol           text not null,
  d                date not null,
  asset_class      text,
  grp              text not null,
  signal           text not null,
  prev_signal      text,
  prev_d           date,
  score            double precision,
  prev_score       double precision,
  grade            text,
  d_score          double precision,
  contrib          jsonb,
  contrib_residual double precision,
  top_driver       text,
  weights          text,
  pre30_ret        double precision,
  pre30_rel        double precision,
  beta_btc         double precision,
  btc_below_ma50   boolean,
  matured_7        boolean,
  ret_7            double precision,
  univ_7           double precision,
  rel_7            double precision,
  btc_7            double precision,
  alpha_7          double precision,
  matured_30       boolean,
  ret_30           double precision,
  univ_30          double precision,
  rel_30           double precision,
  btc_30           double precision,
  alpha_30         double precision,
  note             text,
  code_ref         text,
  computed_at      timestamptz not null,
  primary key (symbol, d)
);
create index if not exists cis_signal_attribution_d on public.cis_signal_attribution (d);
alter table public.cis_signal_attribution enable row level security;
revoke all on public.cis_signal_attribution from anon, authenticated;
grant select, insert, update, delete on public.cis_signal_attribution to service_role;

create or replace view public.v_cis_signal_daily with (security_invoker = true) as
select distinct on (symbol, (recorded_at at time zone 'UTC')::date)
       symbol, asset_class, (recorded_at at time zone 'UTC')::date as d, signal, score,
       grade, pillar_f, pillar_m, pillar_o, pillar_s, pillar_a
from public.cis_scores
order by symbol, (recorded_at at time zone 'UTC')::date, recorded_at desc;
revoke all on public.v_cis_signal_daily from anon, authenticated;
grant select on public.v_cis_signal_daily to service_role;

-- S-529 补(10-09,migration s529b_signal_attribution_held):51% 的信号变化 3 天内变回原档(边界来回跳)。
-- 记下一次变化的日期与档位、这一档维持了几天、是否 3 天内变回 —— 事后才知道,归因里标明。
alter table public.cis_signal_attribution add column if not exists next_d date;
alter table public.cis_signal_attribution add column if not exists next_signal text;
alter table public.cis_signal_attribution add column if not exists held_days integer;
alter table public.cis_signal_attribution add column if not exists reverted_3d boolean;
