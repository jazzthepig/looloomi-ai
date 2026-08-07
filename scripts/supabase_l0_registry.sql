-- ============================================================================
-- L0 REGISTRY — identity must precede everything.
-- Contract: docs/DATA_ARCHITECTURE.md.  APPLIED 2026-08-07 (migration l0_asset_registry).
--
-- Jazz: "先做架构,再补充数据源,现在很多细节都不对的" — and the details being wrong
-- was measurable, not a feeling:
--   A1  symbol coverage differs per table (ohlcv 65 / cis 76 / vectors 72), 1 orphan.
--   A2  24 symbols carried MULTIPLE asset_class values, because class was stored on the
--       OBSERVATION row, where it actually recorded the data SOURCE.
--   A3  and source determines candle convention: rows with >1% open/prev_close gap were
--       31.3% under 'Crypto' but 73.7% / 79.5% / 83.5% under 'L1' / 'L2' / 'DeFi'.
--       So `where asset_class='Crypto'` was a SOURCE filter wearing a class filter's
--       clothes — that is how the S-106 first cut produced a fake +12.30 "overnight
--       return" by splicing two bar conventions and reading the seam as structure.
--   A4  no way to answer "who was in the panel on date D", so survivorship bias was
--       present in every backtest AND unmeasurable.
--
-- Jazz also: "我们是强筛选展示,但是我们跟踪要足够广" — tracking and investing are
-- different objects. Three universes, because statistics must be computed on the broad
-- one: three separate analyses on 2026-08-07 died of sample size (N_eff 3.1 / n=20 /
-- 13 episodes) and every one of them was computed on the investable set.
-- ============================================================================

create table if not exists assets (
  asset_id     text primary key,          -- canonical, stable, venue-independent
  symbol       text not null unique,
  name         text,
  class        text,                      -- THE ONLY place class lives. On an observation row it is a P0.
  listed_at    date,
  delisted_at  date,                      -- non-null = dead. Never deleted: the graveyard is the asset.
  created_at   timestamptz default now()
);

-- SOL / SOLUSDT / a CoinGecko id are ALIASES, not identities.
create table if not exists asset_aliases (
  asset_id     text not null references assets(asset_id) on delete cascade,
  venue        text not null,
  venue_symbol text not null,
  primary key (venue, venue_symbol)
);
create index if not exists idx_alias_asset on asset_aliases (asset_id);

-- Point-in-time membership, interval form. `reason` is kept because WHY something left
-- (liquidity, delisting, compliance) is research material, not bookkeeping.
create table if not exists universe_membership (
  asset_id   text not null references assets(asset_id) on delete cascade,
  universe   text not null check (universe in ('coverage','investable','display')),
  valid_from date not null,
  valid_to   date,
  reason     text,
  primary key (asset_id, universe, valid_from)
);
create index if not exists idx_membership_lookup on universe_membership (universe, valid_from, valid_to);

alter table assets              enable row level security;   -- S-94
alter table asset_aliases       enable row level security;
alter table universe_membership enable row level security;
revoke all on assets, asset_aliases, universe_membership from anon;

-- ---------------------------------------------------------------------------
-- Population. Class conflicts are resolved by row-weighted majority AND RECORDED —
-- silently flattening 24 conflicts would destroy the evidence that the old model
-- was broken, which is the only reason anyone would trust the new one.
-- ---------------------------------------------------------------------------
with src  as (select symbol, asset_class, count(*) n from ohlcv_daily group by 1,2),
     nc   as (select symbol, count(*) n_classes from src group by symbol),
     win  as (select distinct on (symbol) symbol, asset_class from src order by symbol, n desc, asset_class),
     life as (select symbol, min(trade_date) t0, max(trade_date) t1 from ohlcv_daily group by symbol)
insert into assets (asset_id, symbol, class, listed_at, delisted_at, name)
select w.symbol, w.symbol, w.asset_class, l.t0,
       -- a series that stopped >30d before the PANEL's max is dead, not merely stale
       case when l.t1 < (select max(trade_date) from ohlcv_daily) - 30 then l.t1 end,
       case when nc.n_classes>1 then 'class resolved by majority from '||nc.n_classes||' conflicting labels' end
from win w join life l using (symbol) join nc using (symbol)
on conflict (asset_id) do nothing;

insert into assets (asset_id, symbol, class, name)
select distinct symbol, symbol, null, 'cis_scores only - no price history (A1 orphan)'
from cis_scores where symbol not in (select asset_id from assets)
on conflict do nothing;

insert into asset_aliases (asset_id, venue, venue_symbol)
select asset_id, 'binance_perp', symbol||'USDT' from assets where class is not null
on conflict do nothing;

insert into universe_membership (asset_id, universe, valid_from, valid_to, reason)
select asset_id, 'coverage', listed_at, delisted_at,
       case when delisted_at is not null then 'series ended' else 'has price history' end
from assets where listed_at is not null
on conflict do nothing;

-- investable starts at CIS inception, NOT at listing: claiming membership before we
-- could score it would backfill a decision we never made (I2).
insert into universe_membership (asset_id, universe, valid_from, valid_to, reason)
select a.asset_id, 'investable',
       greatest(a.listed_at, (select min(d)::date from signal_outcomes)), a.delisted_at,
       'in CIS scoring set'
from assets a
where a.asset_id in (select distinct symbol from cis_scores) and a.listed_at is not null
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- VERIFY (this is the whole point — A1/A2/A4 must go to zero / become answerable):
--   A1: select count(*) from (
--         select symbol from cis_scores union select symbol from funding_history
--         union select symbol from asset_embeddings union select symbol from ohlcv_daily
--         except select asset_id from assets) q;                        -- expect 0
--   A2: select count(*) from (select asset_id from assets
--         group by asset_id having count(distinct class)>1) q;          -- expect 0
--   A4: select count(*) from universe_membership where universe='coverage'
--         and valid_from <= DATE '2024-06-15'
--         and (valid_to is null or valid_to > DATE '2024-06-15');       -- expect >0
--       the same query with universe='investable' must return 0 for that date —
--       CIS scoring began 2025-05-03, and a non-zero answer would mean we had
--       backfilled an investment decision into a period where none existed.
-- Measured on apply: A1 0 · A2 0 · A4 74 coverage / 0 investable on 2024-06-15.
