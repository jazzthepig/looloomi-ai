-- ============================================================================
-- funding_history — the first ANCHOR series we have ever persisted.
--
-- WHY (Jazz, 2026-08-07): "a rating changes and then you slowly buy" cannot work,
-- in crypto or in traditional assets. That is the sell-side distribution model:
-- once the upgrade is public everyone knows simultaneously, so the return goes to
-- whoever is fastest. S-106 measured that we are not fastest and structurally
-- cannot be — return is delivered in 0.8% of days and 45.9% of a big day's move
-- lands in a four-hour window. So value mining needs ANCHORS instead.
--
-- THE CRITERION THIS TABLE EXISTS TO SATISFY (S-107):
--   a good anchor's payoff ACCRUES rather than JUMPS — it pays you for holding,
--   not for guessing a moment. Measurable with the S-106 concentration ruler,
--   before spending anything on a return test:
--     funding carry : best 10 days = 14.9% of total, 73.6% of days positive
--     price momentum: best 10 days = 152%  of total, 50.0% of days positive
--
-- AUDIT NOTE that outlived the finding: before this table the warehouse had NO
-- anchor series at all — no funding, no flows, no TVL, no unlocks; all fetched
-- live, never persisted. Every test we had ever run was price predicting price.
--
-- DO NOT SIZE OFF THIS SERIES' SHARPE. Gross Sharpe of the funding stream is
-- 8.75, and it is meaningless: it measures a PAYMENT STREAM, not the P&L of the
-- basis trade, which carries spot-perp basis risk, margin/liquidation tail and
-- two legs of execution — none of which appear here. Carry is smooth; the risk
-- lives in the tail you did not measure. Mean pairwise corr 0.707 across 10
-- assets ⇒ N_eff = 1.36: this is ONE systematic factor (crowd leverage demand),
-- not ten sleeves. Its correct job is as a state variable for exposure timing.
--
-- APPLIED 2026-08-07 via Supabase migration `funding_history_anchor`.
-- ============================================================================

create table if not exists funding_history (
  symbol        text        not null,
  funding_time  timestamptz not null,       -- 3x/day ⇒ the key is the TIMESTAMP, not a date
  funding_rate  double precision not null,  -- per-interval, NOT annualised
  mark_price    double precision,
  venue         text        not null default 'binance_perp',
  primary key (symbol, funding_time, venue)
);

create index if not exists idx_funding_time on funding_history (funding_time desc);
create index if not exists idx_funding_sym  on funding_history (symbol, funding_time desc);

alter table funding_history enable row level security;   -- S-94
revoke all on funding_history from anon;

create or replace function backfill_binance_funding(
    p_symbol text, p_start_ms bigint default null, p_max_batches int default 30
) returns int language plpgsql security definer as $$
declare
  cur_ms bigint; end_ms bigint := (extract(epoch from now())*1000)::bigint;
  resp extensions.http_response; arr jsonb;
  n_rows int := 0; batch int; i int := 0; last_t bigint;
begin
  if p_start_ms is null then
    select coalesce((extract(epoch from max(funding_time))*1000)::bigint + 1,
                    (extract(epoch from now() - interval '900 days')*1000)::bigint)
      into cur_ms from funding_history where symbol = p_symbol;
  else cur_ms := p_start_ms; end if;

  loop
    exit when cur_ms >= end_ms or i >= p_max_batches;
    i := i + 1;
    select * into resp from extensions.http_get(
      'https://fapi.binance.com/fapi/v1/fundingRate?symbol=' || p_symbol ||
      'USDT&limit=1000&startTime=' || cur_ms::text);
    exit when resp.status <> 200;
    arr := resp.content::jsonb;
    exit when jsonb_typeof(arr) <> 'array' or jsonb_array_length(arr) = 0;

    insert into funding_history (symbol, funding_time, funding_rate, mark_price, venue)
    select p_symbol, to_timestamp((k->>'fundingTime')::bigint/1000.0),
           (k->>'fundingRate')::double precision,
           nullif(k->>'markPrice','')::double precision, 'binance_perp'
    from jsonb_array_elements(arr) k
    on conflict (symbol, funding_time, venue) do nothing;
    get diagnostics batch = row_count;
    n_rows := n_rows + batch;

    -- Cursor follows the DATA, not an assumed step. Funding is nominally 8-hourly
    -- but the interval has changed historically for some symbols, so a fixed step
    -- would skip or repeat — a nastier version of the hourly backfill's step_ms
    -- trap, because here the true step is not even constant. The <= guard means
    -- "no forward progress ⇒ stop", so the loop can never spin.
    last_t := ((arr->(jsonb_array_length(arr)-1))->>'fundingTime')::bigint;
    exit when last_t <= cur_ms;
    cur_ms := last_t + 1;
    exit when jsonb_array_length(arr) < 1000;
  end loop;
  return n_rows;
end $$;

-- `from public` is load-bearing: CREATE FUNCTION grants EXECUTE to PUBLIC and
-- anon only INHERITS it, so revoking from anon alone succeeds and changes nothing.
revoke all on function backfill_binance_funding(text, bigint, int) from public, anon, authenticated;

-- VERIFY (the anchor criterion itself, runnable):
--   with f as (select symbol, funding_time::date d, sum(funding_rate) c
--              from funding_history group by 1,2),
--        r as (select f.*, row_number() over (partition by symbol order by c desc) rk,
--                     count(*) over (partition by symbol) n from f)
--   select round((100.0*sum(c) filter (where rk<=10)/sum(c))::numeric,1) pct_from_best_10d,
--          round((100.0*count(*) filter (where c>0)/count(*))::numeric,1) pct_days_positive
--   from r;   -- accrual anchor: low first number, high second. Jump: the reverse.
