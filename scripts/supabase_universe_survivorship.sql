-- ============================================================================
-- Universe ingest + delisted-name backfill — DATA_ARCHITECTURE §4 step 4.
-- APPLIED 2026-08-08 (migrations l0_universe_ingest_with_survivorship,
-- backfill_daily_by_venue_symbol).
--
-- WHY. `universe_membership` held only the 75 assets we happened to have data for,
-- all of them alive. The problem with a survivorship filter is not that it flatters
-- results — it is that the flattery is UNMEASURABLE, because the dead are simply
-- absent. This makes them present.
--
-- WHAT WAS AVAILABLE ALL ALONG. fapi/exchangeInfo returns more than "what trades
-- today": 526 TRADING PERPETUAL, and **126 SETTLING** — symbols being delisted right
-- now, i.e. exactly the population a current-liquidity screen erases. We had not
-- looked at that field in two months.
--
-- SECOND FIX, quieter and broader. `onboardDate` is the TRUE listing date, whereas
-- `assets.listed_at` had been the date OUR COLLECTION began — a collection artifact
-- wearing a listing date's clothes, which dated every membership interval wrong.
--
-- MEASURED CONSEQUENCE (S-111):
--   survivorship rate  : 302 assets alive on 2024-06-15, 63 dead today = 20.9%
--   panel 2024-01..2026-08, equal weight, PIT (a dying name stays until it dies):
--       with the dead     -211.1% cumulative log over 943 days (136 names avg)
--       survivors only    -146.3%                              ( 39 names avg)
--       overstatement      +64.8pp / 2.58y = **25.1 percentage points per year**
--   The largest tier effect we ever chased was ~3%/yr. The bias is 8x larger than
--   the signal. This is the same error class as S-103 (benchmarked against BTC):
--   there the benchmark had the wrong ASSET, here it has the wrong MEMBERSHIP.
--   Neither was an analysis mistake; both were "compared to what".
--
-- The forward book is NOT affected: from today membership is recorded point-in-time,
-- so beta_core_nav is survivorship-free from its first mark.
-- ============================================================================

create or replace function ingest_binance_universe() returns table(action text, n bigint)
language plpgsql security definer as $$
declare resp extensions.http_response; arr jsonb;
begin
  select * into resp from extensions.http_get('https://fapi.binance.com/fapi/v1/exchangeInfo');
  if resp.status <> 200 then return query select 'http_error'::text, resp.status::bigint; return; end if;
  arr := resp.content::jsonb -> 'symbols';

  create temp table _u on commit drop as
  select k->>'baseAsset' base, k->>'symbol' perp, k->>'status' status,
         to_timestamp((k->>'onboardDate')::bigint/1000.0)::date onboard
  from jsonb_array_elements(arr) k
  where k->>'symbol' like '%USDT'
    and k->>'contractType' = 'PERPETUAL'          -- TRADIFI_PERPETUAL is a different product
    and k->>'status' in ('TRADING','SETTLING');   -- PENDING has never traded

  -- class stays NULL rather than guessed: class lives in L0, and inventing one here
  -- would recreate exactly the defect L0 was built to remove.
  insert into assets (asset_id, symbol, class, listed_at, name)
  select base, base, null, min(onboard), 'binance perp universe ingest 2026-08-08'
  from _u group by base on conflict (asset_id) do nothing;

  update assets a set listed_at = u.onboard
  from (select base, min(onboard) onboard from _u group by base) u
  where a.asset_id = u.base and (a.listed_at is null or u.onboard < a.listed_at);

  update assets a set delisted_at = current_date
  from (select base from _u where status='SETTLING'
        except select base from _u where status='TRADING') s
  where a.asset_id = s.base and a.delisted_at is null;

  insert into asset_aliases (asset_id, venue, venue_symbol)
  select base, 'binance_perp', perp from _u on conflict (venue, venue_symbol) do nothing;

  insert into universe_membership (asset_id, universe, valid_from, valid_to, reason)
  select a.asset_id, 'coverage', a.listed_at, a.delisted_at,
         case when a.delisted_at is not null then 'binance SETTLING (delisting)'
              else 'binance perp, trading' end
  from assets a where a.asset_id in (select base from _u) and a.listed_at is not null
  on conflict (asset_id, universe, valid_from) do nothing;

  return query select 'assets_total'::text, (select count(*) from assets)
    union all select 'delisted_recorded', (select count(*) from assets where delisted_at is not null)
    union all select 'coverage_members',  (select count(*) from universe_membership where universe='coverage');
end $$;

-- Addressed by VENUE SYMBOL, not by base||'USDT'. The old backfill concatenated, which
-- is the identity confusion L0 exists to remove: for 1000WHY / 1000X / AI16Z the venue
-- returns 400, and a 400 is indistinguishable from "this asset has no history".
create or replace function backfill_daily_for_asset(p_asset text, p_max_batches int default 12)
returns int language plpgsql security definer as $$
declare
  vsym text; cur_ms bigint; end_ms bigint := (extract(epoch from now())*1000)::bigint;
  resp extensions.http_response; arr jsonb; n_rows int := 0; batch int; i int := 0; last_t bigint;
begin
  select venue_symbol into vsym from asset_aliases
   where asset_id = p_asset and venue = 'binance_perp' limit 1;
  if vsym is null then return -1; end if;   -- -1, not 0, so "unaddressable" never reads as "no data"

  select coalesce((extract(epoch from max(trade_date))*1000)::bigint + 86400000, 1483228800000)
    into cur_ms from ohlcv_daily where asset_id = p_asset and source = 'binance_hist';

  loop
    exit when cur_ms >= end_ms or i >= p_max_batches;
    i := i + 1;
    select * into resp from extensions.http_get(
      'https://fapi.binance.com/fapi/v1/klines?symbol=' || vsym ||
      '&interval=1d&limit=1000&startTime=' || cur_ms::text);
    exit when resp.status <> 200;
    arr := resp.content::jsonb;
    exit when jsonb_typeof(arr) <> 'array' or jsonb_array_length(arr) = 0;

    insert into ohlcv_daily (symbol, asset_id, asset_class, source, trade_date,
                             open, high, low, close, volume)
    select p_asset, p_asset, 'Crypto', 'binance_hist',
           to_timestamp((k->>0)::bigint/1000)::date,
           (k->>1)::real, (k->>2)::real, (k->>3)::real, (k->>4)::real, (k->>5)::real
    from jsonb_array_elements(arr) k
    on conflict (symbol, trade_date, source) do nothing;
    get diagnostics batch = row_count;
    n_rows := n_rows + batch;

    last_t := ((arr->(jsonb_array_length(arr)-1))->>0)::bigint;
    exit when last_t <= cur_ms;               -- no forward progress ⇒ stop, never spin
    cur_ms := last_t + 86400000;
    exit when jsonb_array_length(arr) < 1000;
  end loop;
  return n_rows;
end $$;

-- `from public` is load-bearing: CREATE FUNCTION grants EXECUTE to PUBLIC and
-- anon only INHERITS it, so revoking from anon alone succeeds and changes nothing.
revoke all on function ingest_binance_universe() from public, anon, authenticated;
revoke all on function backfill_daily_for_asset(text, int) from public, anon, authenticated;

-- Backfill the DEAD first. They are the highest-value rows in the warehouse precisely
-- because every prior study lacked them:
--   select count(*), sum(rows) from (
--     select backfill_daily_for_asset(asset_id, 6) rows from (
--       select asset_id from assets a where a.delisted_at is not null
--         and not exists (select 1 from ohlcv_daily o where o.asset_id=a.asset_id)
--       order by asset_id limit 48) q) r;   -- repeat until sum = 0
--
-- VERIFY the bias is now measurable (this is the point of the whole exercise):
--   with px as (select o.asset_id, o.trade_date d,
--                 ln(o.close/nullif(lag(o.close) over (partition by o.asset_id
--                   order by o.trade_date),0)) lr, (a.delisted_at is not null) dead
--               from ohlcv_daily o join assets a using(asset_id)
--               where o.source='binance_hist' and o.close>0 and o.trade_date>='2024-01-01'),
--        d as (select d, avg(lr) all_n, avg(lr) filter (where not dead) surv
--              from px where lr is not null group by d having count(*)>=20)
--   select round((100*(sum(surv)-sum(all_n))/count(*)*365)::numeric,1) as overstatement_pp_per_yr
--   from d;   -- measured 2026-08-08: 25.1
