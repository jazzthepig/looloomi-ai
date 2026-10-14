-- T-098 / S-577 — World50 的两张数据表。模块 src/data/universe/world50_data.py;周更循环 _world50_history_loop。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-14(migration t098_world50_data)。

-- 候选的历史市值(周频,USD)—— 按时点排名选成分用。来源:EODHD historical-market-cap(公司);贵金属 / 加密另算。
create table if not exists public.world50_mcap_weekly (
  key          text not null,           -- world50.CANDIDATES 的 key(= ohlcv_daily.symbol)
  d            date not null,
  mcap_usd     double precision not null,
  source       text not null,
  recorded_at  timestamptz not null default now(),
  primary key (key, d, source)
);
create index if not exists world50_mcap_weekly_d on public.world50_mcap_weekly (d);
alter table public.world50_mcap_weekly enable row level security;
revoke all on public.world50_mcap_weekly from anon, authenticated;
grant select, insert, update, delete on public.world50_mcap_weekly to service_role;

-- 每个候选在链上可持有的形式(代币化股票 / ETF / 商品)的快照 —— 资格判断用。来源 CoinGecko Pro /rwas/markets。
-- 一行 = 某天看到的一个代币化 RWA;key 为空 = 没对上任何候选(留着,方便查漏配)。原生加密不进这张表(本身就在链上)。
create table if not exists public.world50_onchain_forms (
  as_of            date not null,
  token_id         text not null,       -- CoinGecko RWA id(/rwas/markets 的 id)
  key              text,                -- 对上的候选;对不上为 null
  symbol           text,
  name             text,
  category         text,                -- 'rwa:' || asset_type(stock / etf / commodity)
  issuer           text,                -- /rwas/markets?issuer= 反查的发行方 id,多家用 | 连;查不到为 null
  match_rule       text,                -- 怎么对上的(便于复查)
  price_usd        double precision,
  mcap_usd         double precision,
  volume_24h_usd   double precision,
  recorded_at      timestamptz not null default now(),
  primary key (as_of, token_id)
);
create index if not exists world50_onchain_forms_key on public.world50_onchain_forms (key, as_of);
alter table public.world50_onchain_forms enable row level security;
revoke all on public.world50_onchain_forms from anon, authenticated;
grant select, insert, update, delete on public.world50_onchain_forms to service_role;
