-- S-690 真钱进场过滤(Jazz 10-27「直接应用」):信号日 d 收盘那一刻的规模中性 OI/市值截面。
-- 为什么不是归档:d 的 Binance Vision 归档要到 d+1 约 07:30 UTC 才落库,执行器 00:45 取计划;
-- 滞后一天的截面检验不过(台账 S-690 附记一:差 −0.34R、p 0.063)。所以在 d+1 00:05 UTC 从 CoinGecko Pro
-- 一次拿全(binance_futures 合约的 open_interest_usd + /coins/markets 市值),同一个量换一根管子;
-- 归档落库后逐名回填 p_archive,对不上就停用(oi_leverage.AUDIT_*)。
create table if not exists public.oi_lev_snapshot_daily (
  d            date not null,            -- 信号日(刚收盘的 UTC 日)
  symbol       text not null,            -- Binance U 本位永续的基础名(1000SHIB …),与 deriv_metrics_daily 同
  kind         text not null default 'live',   -- live = 窗口内的正式快照(计划只读这个);probe = 部署后的对照,不进计划
  coin_id      text,
  oi_usd       double precision,
  mcap         double precision,
  last_usd     double precision,         -- 合约最新价(美元)
  cg_px        double precision,         -- CG 现货价;映射校验:|cg_px × mult / last_usd − 1| ≤ 5%
  mult         integer,
  in_cs        boolean not null,
  why_out      text,
  p            double precision,         -- 快照截面的规模中性分位
  n_cs         integer,
  snap_at      timestamptz not null,
  p_archive    double precision,         -- 同一天 Binance 归档版截面的 p(oi_leverage.cross_section,与研究 SQL 同口径)
  n_archive    integer,
  audited_at   timestamptz,
  primary key (d, symbol, kind)
);
alter table public.oi_lev_snapshot_daily enable row level security;
grant select on public.oi_lev_snapshot_daily to anon;
drop policy if exists lane_read on public.oi_lev_snapshot_daily;
create policy lane_read on public.oi_lev_snapshot_daily for select to anon using (true);

alter table public.r_ticket_oi_tags add column if not exists p_live double precision;
alter table public.r_ticket_oi_tags add column if not exists high_live boolean;
