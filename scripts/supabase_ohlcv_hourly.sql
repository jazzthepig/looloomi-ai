-- ============================================================================
-- ohlcv_hourly — the panel that made S-106 testable.
--
-- WHY: Jazz, 2026-08-07 — "even 24/7 has an early and a late session; the middle
-- is just AMM liquidity management." That is untestable on daily bars. Worse, the
-- obvious daily proxy is actively misleading: decomposing daily returns into
-- overnight (open/prev_close) vs intraday is meaningless for a continuously
-- traded asset. Measured: crypto median |open/prev_close - 1| = 0.00004, while
-- the sparsely-populated L1/L2/DeFi rows show 2.5-4.8% — a candle-convention
-- artifact (the S-103 `spread_kind` finding again), not market structure. An
-- earlier cut of this analysis was thrown out for exactly that reason.
--
-- WHAT IT CARRIES AND WHY: quote_volume, trades and taker_buy_base are here
-- because the question is WHEN liquidity and aggression concentrate, not only
-- what price did. taker_buy_base is what showed the session structure lives in
-- volume and volatility but NOT in direction (flat 48.1-49.4% across all 24h).
--
-- APPLIED 2026-08-07 via Supabase migrations `ohlcv_hourly_panel` and
-- `backfill_binance_hourly_fn`. This file is the reviewable copy of record —
-- scripts/supabase_strategy_records.sql sat unapplied for 12 days precisely
-- because a file and an applied migration are different things.
-- ============================================================================

create table if not exists ohlcv_hourly (
  symbol      text        not null,
  asset_class text        not null default 'Crypto',
  ts          timestamptz not null,          -- bar OPEN time, UTC
  open        double precision,
  high        double precision,
  low         double precision,
  close       double precision,
  volume      double precision,
  quote_volume     double precision,          -- USDT notional: the liquidity axis
  trades           integer,                   -- activity independent of trade size
  taker_buy_base   double precision,          -- aggressor split: direction of pressure
  source      text        not null default 'binance_hist',
  primary key (symbol, ts, source)            -- multi-source by construction (Lesson #76)
);

create index if not exists idx_ohlcv_hourly_ts     on ohlcv_hourly (ts desc);
create index if not exists idx_ohlcv_hourly_sym_ts on ohlcv_hourly (symbol, ts desc);

alter table ohlcv_hourly enable row level security;   -- S-94
revoke all on ohlcv_hourly from anon;

create or replace function backfill_binance_hourly(
    p_symbol text,
    p_start_ms bigint default null,      -- null -> resume from what we already have
    p_max_batches int default 40         -- bounded: an unbounded loop inside a
) returns int language plpgsql security definer as $$   -- request is the S-103 class
declare
  -- MUST match interval=1h. scripts/supabase_ohlcv_backfill.sql hardcodes
  -- 86400000 for daily; copying that constant here would advance the cursor 24x
  -- per batch and silently drop 23 of every 24 hours. Bind the step to the
  -- interval, never to the neighbouring function.
  step_ms constant bigint := 3600000;
  cur_ms  bigint;
  end_ms  bigint := (extract(epoch from now())*1000)::bigint;
  resp    extensions.http_response;
  arr     jsonb;
  n_rows  int := 0;
  batch   int;
  i       int := 0;
begin
  if p_start_ms is null then
    select coalesce((extract(epoch from max(ts))*1000)::bigint + step_ms,
                    (extract(epoch from now() - interval '400 days')*1000)::bigint)
      into cur_ms from ohlcv_hourly where symbol = p_symbol;
  else
    cur_ms := p_start_ms;
  end if;

  loop
    exit when cur_ms >= end_ms or i >= p_max_batches;
    i := i + 1;
    select * into resp from extensions.http_get(
      'https://api.binance.com/api/v3/klines?symbol=' || p_symbol ||
      'USDT&interval=1h&limit=1000&startTime=' || cur_ms::text);
    exit when resp.status <> 200;
    arr := resp.content::jsonb;
    exit when jsonb_typeof(arr) <> 'array' or jsonb_array_length(arr) = 0;

    insert into ohlcv_hourly (symbol, ts, open, high, low, close, volume,
                              quote_volume, trades, taker_buy_base, source)
    select p_symbol,
           to_timestamp((k->>0)::bigint/1000.0),
           (k->>1)::double precision, (k->>2)::double precision,
           (k->>3)::double precision, (k->>4)::double precision,
           (k->>5)::double precision, (k->>7)::double precision,
           (k->>8)::int,             (k->>9)::double precision,
           'binance_hist'
    from jsonb_array_elements(arr) k
    on conflict (symbol, ts, source) do nothing;
    get diagnostics batch = row_count;
    n_rows := n_rows + batch;

    cur_ms := ((arr->(jsonb_array_length(arr)-1))->>0)::bigint + step_ms;
    exit when jsonb_array_length(arr) < 1000;
  end loop;
  return n_rows;
end $$;

-- `from public` is load-bearing: CREATE FUNCTION grants EXECUTE to PUBLIC and
-- anon only INHERITS it, so revoking from anon alone succeeds and changes nothing.
revoke all on function backfill_binance_hourly(text, bigint, int) from public, anon, authenticated;

-- VERIFY after any backfill — a silently-skipping cursor is the failure mode this
-- table was most at risk of, and it is invisible in a row count alone:
--   select count(*) bars,
--          count(*) filter (where ts - prev <> interval '1 hour') gaps
--   from (select ts, lag(ts) over (partition by symbol order by ts) prev
--         from ohlcv_hourly where symbol='BTC') q;   -- gaps must be 0
