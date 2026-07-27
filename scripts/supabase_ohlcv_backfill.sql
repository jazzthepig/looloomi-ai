-- ============================================================================
-- P0 panel extension — Binance deep-history OHLCV backfill (Seth, 2026-07-27)
-- Applied live via MCP (migration ohlcv_binance_deep_backfill_fn). Repo provenance.
--
-- WHY: the 731-day bear-dominated panel was the root cause behind most R46-R94
-- refutations (Minimax feedback P0, lessons #54/#59/#60). Waiting on Mac-side
-- §OHLCV-EXTENSION was passive; this eliminates the wait.
--
-- HOW: Supabase runs in ap-southeast-2 (NOT US) ⇒ api.binance.com is reachable
-- from Postgres itself via the http extension. The DB fetches its own history —
-- no data transits the agent or Railway (which IS geo-blocked for Binance).
--
-- RESULT (2026-07-27): 82,227 rows · 41 symbols · back to 2017-08-17 ·
-- 25 symbols ≥2000 days (multi-cycle: 2018 bear / 2020-21 bull / 2022 bear /
-- 2023-24 recovery / 2025-26 bear). source='binance_hist', idempotent on
-- (symbol, trade_date, source). HYPE/MNT not on Binance spot (0 rows, expected).
-- Re-run anytime:  select backfill_binance_ohlcv('BTC');
-- ============================================================================

create extension if not exists http with schema extensions;

create or replace function backfill_binance_ohlcv(p_symbol text, p_asset_class text default 'Crypto',
                                                  p_start_ms bigint default 1483228800000) -- 2017-01-01
returns int language plpgsql security definer as $$
declare
  cur_ms  bigint := p_start_ms;
  end_ms  bigint := (extract(epoch from now())*1000)::bigint;
  resp    extensions.http_response;
  arr     jsonb;
  n_rows  int := 0;
  batch   int;
begin
  loop
    exit when cur_ms >= end_ms;
    select * into resp from extensions.http_get(
      'https://api.binance.com/api/v3/klines?symbol=' || p_symbol ||
      'USDT&interval=1d&limit=1000&startTime=' || cur_ms::text);
    exit when resp.status <> 200;
    arr := resp.content::jsonb;
    exit when jsonb_typeof(arr) <> 'array' or jsonb_array_length(arr) = 0;
    insert into ohlcv_daily (symbol, asset_class, source, trade_date, open, high, low, close, volume)
    select p_symbol, p_asset_class, 'binance_hist',
           to_timestamp((k->>0)::bigint/1000)::date,
           (k->>1)::numeric, (k->>2)::numeric, (k->>3)::numeric, (k->>4)::numeric, (k->>5)::numeric
    from jsonb_array_elements(arr) k
    on conflict (symbol, trade_date, source) do nothing;
    get diagnostics batch = row_count;
    n_rows := n_rows + batch;
    cur_ms := ((arr->(jsonb_array_length(arr)-1))->>0)::bigint + 86400000;
    exit when jsonb_array_length(arr) < 1000;
  end loop;
  return n_rows;
end $$;
