-- 2026-11-23 · 行情快照(src/data/market/market_snapshot.py,S-908):取回来的全宇宙行情落一份,只追加。
-- 起因:全宇宙行情(价 / 市值 / 量 / 流通 / 总量 / 上限)与全市场市值的即时值此前只进缓存、从不落表 ——
-- CoinGecko 一停,「总量」「上限」「BTC 占比」就没有任何库内来源(S-900 / S-906)。
-- symbol = 我们自己的代码;全市场那一行 symbol = '_GLOBAL'(market_cap = 总市值,btc_dominance 只有这一行有)。
-- 触发器:只许 INSERT;d 由库按 ts 的 UTC 日填(客户端给的不算)。
create table if not exists public.market_snapshot (
  ts                 timestamptz      not null,
  d                  date             not null,
  source             text             not null check (source in ('coinmarketcap', 'coingecko_markets')),
  symbol             text             not null,
  vendor_id          text,
  name               text,
  price              double precision,
  market_cap         double precision,
  volume_24h         double precision,
  circulating_supply double precision,
  total_supply       double precision,
  max_supply         double precision,
  pct_24h            double precision,
  pct_7d             double precision,
  btc_dominance      double precision,
  source_ts          timestamptz,
  identity           text,
  primary key (source, symbol, ts)
);
create index if not exists market_snapshot_source_ts on public.market_snapshot (source, ts desc);
create index if not exists market_snapshot_d on public.market_snapshot (d, source);

create or replace function public.market_snapshot_guard() returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op <> 'INSERT' then
    raise exception 'market_snapshot is append-only: % refused', tg_op;
  end if;
  new.d := (new.ts at time zone 'utc')::date;
  return new;
end $$;
drop trigger if exists market_snapshot_guard on public.market_snapshot;
create trigger market_snapshot_guard before insert or update or delete on public.market_snapshot
  for each row execute function public.market_snapshot_guard();

-- 读:跟其它研究数据表同一套(`lane_read`)—— 这张表存在的理由就是让研究读库、不再打 API。写:只有服务端 key。
alter table public.market_snapshot enable row level security;
revoke all on public.market_snapshot from anon, authenticated;
grant select on public.market_snapshot to anon;
drop policy if exists lane_read on public.market_snapshot;
create policy lane_read on public.market_snapshot for select to anon using (true);
