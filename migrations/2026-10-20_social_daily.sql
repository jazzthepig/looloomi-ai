-- 2026-10-20 · external social / attention data (Santiment social volume, Sharpe mindshare) — ledger S-628 / S-629.
--
-- Why these four tables: the narrative A/B (S-625 → S-626) needs an attention series that is NOT derived from price.
-- Santiment's free key gives ~1 year of daily social volume, never the last 30 days (rolling) — so we must store it
-- or it walks out of the window. Sharpe gives only the current token snapshot (no token history) — so the forward
-- arm exists only if we snapshot it every day. Writer: Railway `_social_ingest_loop` (src/data/market/social_ingest.py).
-- Lanes read with the publishable key (anon, lane_read policy); writes stay with the secret key.

create table if not exists public.santiment_slug_map (
  symbol        text primary key,          -- binance_hist symbol
  slug          text,                      -- null = no Santiment project matched (kept so we don't retry daily)
  ticker        text,
  marketcap_usd double precision,
  n_candidates  int not null default 0,    -- >1 = ticker collision, resolved by largest market cap (S-628 rule)
  note          text,
  mapped_at     timestamptz not null default now()
);

create table if not exists public.social_daily (
  source     text not null,                -- 'santiment'
  symbol     text not null,                -- binance_hist symbol
  metric     text not null,                -- social_volume_total / sentiment_weighted_total
  d          date not null,                -- UTC day the value describes
  value      double precision,
  slug       text,
  fetched_at timestamptz not null default now(),
  primary key (source, symbol, metric, d)
);

create table if not exists public.sharpe_mindshare_snap (
  snap_d          date not null,           -- UTC date of the provider's as_of
  win             text not null,           -- request window: now / 7d
  token_id        text not null,           -- CoinGecko id
  symbol          text,
  name            text,
  mindshare_pct   double precision,
  sentiment_pct   double precision,
  social_score    double precision,
  watchlist_users double precision,
  delta24h        double precision,
  delta7d         double precision,
  price           double precision,
  market_cap      double precision,
  price_change24h double precision,
  narrative_ids   text[],
  as_of           timestamptz,
  fetched_at      timestamptz not null default now(),
  primary key (snap_d, win, token_id)
);

create table if not exists public.sharpe_narrative_mindshare (
  snapshot_at        timestamptz not null,
  narrative_id       text not null,
  mindshare_pct      double precision,
  watchlist_users    double precision,
  token_count        int,
  total_social_score double precision,
  fetched_at         timestamptz not null default now(),
  primary key (snapshot_at, narrative_id)
);

do $$
declare t text;
begin
  foreach t in array array['santiment_slug_map','social_daily','sharpe_mindshare_snap','sharpe_narrative_mindshare']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;

-- One call tells the writer what to fetch: the universe, the slug map, and how far each series already goes.
-- STABLE + SECURITY INVOKER; only the secret key (service_role) may call it.
create or replace function public.social_ingest_plan()
returns jsonb language sql stable security invoker set search_path = public as $$
  with u as (
    select symbol from ohlcv_daily
    where source = 'binance_hist' and trade_date >= current_date - 400 and symbol not in ('USDC','BTCDOM','DEFI')
    group by symbol
  ), l as (
    select symbol, metric, max(d) last_d, max(fetched_at) last_fetch
    from social_daily where source = 'santiment' group by symbol, metric
  )
  select jsonb_build_object(
    'universe',         (select coalesce(jsonb_agg(symbol order by symbol), '[]'::jsonb) from u),
    'map',              (select coalesce(jsonb_object_agg(symbol, slug), '{}'::jsonb) from santiment_slug_map),
    'map_built_at',     (select max(mapped_at) from santiment_slug_map),
    'last',             (select coalesce(jsonb_object_agg(symbol || '|' || metric, last_d), '{}'::jsonb) from l),
    'last_fetch',       (select max(last_fetch) from l),
    'sharpe_last_snap', (select max(snap_d) from sharpe_mindshare_snap),
    'sharpe_last_narr', (select max(snapshot_at) from sharpe_narrative_mindshare)
  );
$$;
revoke all on function public.social_ingest_plan() from public, anon, authenticated;
grant execute on function public.social_ingest_plan() to service_role;
