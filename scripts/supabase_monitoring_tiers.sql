-- ============================================================================
-- Monitoring tiers — "we do not need to watch that many assets, short term" (Jazz).
-- APPLIED 2026-08-08 (migrations monitoring_tiers_per_feed, feeds_respect_monitoring_tiers).
--
-- THE MEASUREMENT THAT MOVED THE ANSWER. The instinct was to monitor fewer assets.
-- Measured cost per feed says the constraint is FREQUENCY, not count:
--     daily   @687 =    42 MB/yr    affordable
--     funding @687 =   237 MB/yr    too much
--     hourly  @687 = 1,096 MB/yr    exhausts a 500 MB tier in ~2 months
--     hourly  @24  =    38 MB/yr    affordable
--
-- So the rule is **broad at low frequency, narrow at high frequency** — which is
-- also what the research needs. Survivorship is only measurable on a WIDE daily
-- panel (S-111: 25.1pp/yr, invisible until the dead were included), while the
-- intraday question (S-106) was always about a handful of names.
--
-- HOURLY WAS THEN TIGHTENED FURTHER, from "admissible" to "actually consumed".
-- Nothing reads hourly today: the ① book is daily and the S-106 study is finished.
-- Gating it to the investable set (74) would have cost 118 MB/yr for zero readers.
-- **A feed whose consumer list is empty is a subscription nobody cancelled.** It is
-- now the ① book's own 24 holdings, 38 MB/yr.
--
-- AND THE DEAD NEED NOTHING. 126 delisted assets carry false on every feed: their
-- history is complete by definition. A monitoring list built from "assets we have"
-- rather than "assets still trading" polls the graveyard forever.
--
-- RESULT: 98 MB/yr total against 1,375 MB/yr unbounded.
-- ============================================================================

alter table assets add column if not exists monitor_daily   boolean not null default false;
alter table assets add column if not exists monitor_hourly  boolean not null default false;
alter table assets add column if not exists monitor_funding boolean not null default false;

-- DAILY: everything still listed (561). 34 MB/yr is the cheapest insurance we own —
-- it is what keeps survivorship measurable GOING FORWARD rather than only in hindsight.
update assets set monitor_daily = (delisted_at is null);

-- FUNDING: the investable set (74). Our only persisted anchor series, 26 MB/yr.
update assets set monitor_funding = false;
update assets a set monitor_funding = true
where a.delisted_at is null and exists (
  select 1 from universe_membership m where m.asset_id = a.asset_id
    and m.universe = 'investable' and m.valid_to is null);

-- HOURLY: the ① book's holdings only (24). Set by CONSUMPTION, not admissibility.
update assets set monitor_hourly = false;
update assets set monitor_hourly = true
where delisted_at is null and asset_id in
  ('BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT','LTC','TRX',
   'ATOM','NEAR','APT','ARB','OP','SUI','UNI','AAVE','INJ','FIL','ETC','BCH');

create index if not exists idx_assets_monitor on assets (monitor_daily, monitor_hourly, monitor_funding);

-- ---------------------------------------------------------------------------
-- The flags are ENFORCED, not advisory. `backfill_binance_hourly` and
-- `backfill_binance_funding` (see supabase_ohlcv_hourly.sql /
-- supabase_funding_history.sql) each open with:
--
--     if not exists (select 1 from assets
--                    where asset_id = p_symbol and monitor_<feed>) then
--       return -2;
--     end if;
--
-- The sentinel is DISTINCT on purpose:
--     -1 = unaddressable (no venue alias)
--     -2 = not monitored for this feed
--      0 = monitored and addressable, nothing new to fetch
-- Collapsing -2 into 0 would let "we chose not to watch this" read as "the market
-- has no data here" — the same conflation that turned a source seam into a market
-- fact in S-106, in the storage domain instead of the analysis one.
--
-- VERIFY (the gate must FIRE, and be distinguishable):
--   select backfill_binance_hourly('AGIX');   -- -2, a delisted name
--   select backfill_binance_funding('AGIX');  -- -2
--   select backfill_binance_hourly('BTC');    -- >= 0, an ① holding
--   select count(*) from assets where not monitor_hourly;   -- 663 now refused
--
-- WHEN TO WIDEN A FEED: only when a named consumer exists. "We might want it later"
-- is what took hourly to 687 assets in the first place; the data is refetchable in
-- minutes, so the option costs nothing to leave unexercised.
