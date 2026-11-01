-- 2026-11-02 · T-082 B:我们真能下单的场所的盘口深度(src/data/market/venue_depth.py)。每天 UTC 00 / 08 / 16 一批,只追加。
-- 表结构按 T-085(lane-c)交接 §6.1,去掉 CEX 才有的 24h 成交字段,加覆盖范围与粒度(HL l2Book 每边只给 20 档)。
create table if not exists public.venue_depth_snapshots (
  id                   bigserial primary key,
  fetched_utc          timestamptz not null,
  venue                text not null,
  symbol               text not null,
  ex_symbol            text not null,
  mid                  double precision,
  spread_bps           double precision,
  depth_1pct_bid_usd   double precision,
  depth_1pct_ask_usd   double precision,
  depth_2pct_bid_usd   double precision,
  depth_2pct_ask_usd   double precision,
  covered_bid_pct      double precision,
  covered_ask_pct      double precision,
  granularity          text,
  code_ref             text not null,
  created_at           timestamptz not null default now(),
  unique (fetched_utc, venue, symbol)
);
create index if not exists venue_depth_snapshots_symbol_ts on public.venue_depth_snapshots (symbol, fetched_utc);
alter table public.venue_depth_snapshots enable row level security;
revoke all on public.venue_depth_snapshots from anon, authenticated;
