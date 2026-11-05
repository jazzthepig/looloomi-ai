-- 2026-11-06 · prediction_markets: market-implied probabilities next to ours (Polymarket Gamma /events, one page per tag).
create table if not exists public.prediction_markets (
  d            date not null,
  venue        text not null,
  market_id    text not null,
  tag          text,
  event_slug   text,
  event_title  text,
  question     text,
  item         text,
  p_yes        double precision not null,
  volume_24h   double precision,
  liquidity    double precision,
  end_date     timestamptz,
  fetched_at   timestamptz not null default now(),
  primary key (d, venue, market_id)
);
alter table public.prediction_markets enable row level security;
grant select on public.prediction_markets to anon;
drop policy if exists lane_read on public.prediction_markets;
create policy lane_read on public.prediction_markets for select to anon using (true);
