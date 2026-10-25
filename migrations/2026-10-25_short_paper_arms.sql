-- 2026-10-25 · S-683 两条做空纸面前向臂 + 它们要的全宇宙永续日线(Binance Vision,含之后下架的合约)。
--
-- perp_bv_pairs / perp_bv_daily / perp_bv_coverage ← src/data/market/perp_bv_daily.py(_binance_vision_loop 里的一步)
-- short_paper_tickets / short_paper_state / short_paper_money ← src/data/signals/short_paper.py(同一循环的下一步)
-- funding_vision_plan:把做空票的合约并进资金费月档的回补计划(空头的资金费按真实结算记)。
-- 公开数据 / 纸面账本,lane 可读(publishable key = anon,只读);写入只走 Railway 的 secret key。

create table if not exists public.perp_bv_pairs (
  pair       text primary key,
  symbol     text not null,
  first_d    date,
  active     boolean not null default true,
  dead_from  date,
  seen_at    timestamptz not null default now()
);

create table if not exists public.perp_bv_daily (
  pair         text not null,
  symbol       text not null,
  d            date not null,
  o            double precision not null,
  h            double precision not null,
  l            double precision not null,
  c            double precision not null,
  qv           double precision not null,
  recorded_at  timestamptz not null default now(),
  primary key (pair, d)
);
create index if not exists perp_bv_daily_d_idx on public.perp_bv_daily (d);

create or replace view public.perp_bv_coverage as
  select pair, min(d) as min_d, max(d) as max_d, count(*) as n from public.perp_bv_daily group by pair;

create table if not exists public.short_paper_tickets (
  arm            text not null,
  ticket_id      text not null,
  pair           text not null,
  symbol         text not null,
  signal_d       date not null,
  status         text not null check (status in ('pending', 'open', 'closed')),
  listing_d      date,
  entry_d        date,
  entry_px       double precision,
  stop_px        double precision,
  risk           double precision,
  exit_d         date,
  exit_px        double precision,
  why            text,
  gap            boolean,
  hold_days      integer,
  r_price        double precision,
  funding        double precision,
  funding_days   integer,
  r_net          double precision,
  hedge_ret      double precision,
  btc_funding    double precision,
  r_hedged       double precision,
  rule_version   text not null,
  updated_at     timestamptz not null default now(),
  primary key (arm, ticket_id)
);
create index if not exists short_paper_tickets_sym_idx on public.short_paper_tickets (symbol, entry_d);

create table if not exists public.short_paper_state (
  arm             text primary key,
  last_d          date not null,
  inception       date not null,
  rule_version    text not null,
  n_pending       integer not null default 0,
  n_open          integer not null default 0,
  n_closed        integer not null default 0,
  mean_r_closed   double precision,
  judge_on        text,
  drift           integer not null default 0,
  detail          jsonb,
  updated_at      timestamptz not null default now()
);

create table if not exists public.short_paper_money (
  arm           text not null,
  d             date not null,
  nav           double precision not null,
  ret           double precision not null,
  open_n        integer,
  taken         integer,
  skipped       integer,
  f             double precision,
  cap           integer,
  inception     date not null,
  rule_version  text not null,
  recorded_at   timestamptz not null default now(),
  primary key (arm, d)
);

do $$
declare t text;
begin
  foreach t in array array['perp_bv_pairs', 'perp_bv_daily', 'short_paper_tickets', 'short_paper_state', 'short_paper_money'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;
grant select on public.perp_bv_coverage to anon;

-- 资金费月档回补:原来的宇宙(binance_hist)∪ 做空票的合约(从进场月起)。其余逻辑一字不改。
create or replace view public.funding_vision_plan as
 WITH u AS (
         SELECT ohlcv_daily.symbol,
            GREATEST('2020-01-01'::date, date_trunc('month'::text, min(ohlcv_daily.trade_date)::timestamp with time zone)::date) AS start_m
           FROM ohlcv_daily
          WHERE ohlcv_daily.source = 'binance_hist'::text AND (ohlcv_daily.symbol <> ALL (ARRAY['USDC'::text, 'BTCDOM'::text, 'DEFI'::text]))
          GROUP BY ohlcv_daily.symbol
        UNION
         SELECT short_paper_tickets.symbol,
            date_trunc('month'::text, min(short_paper_tickets.entry_d)::timestamp with time zone)::date AS start_m
           FROM short_paper_tickets
          WHERE short_paper_tickets.entry_d IS NOT NULL
          GROUP BY short_paper_tickets.symbol
        ), u1 AS (
         SELECT u.symbol, min(u.start_m) AS start_m FROM u GROUP BY u.symbol
        ), have AS (
         SELECT funding_history.symbol,
            date_trunc('month'::text, (funding_history.funding_time AT TIME ZONE 'utc'::text))::date AS m
           FROM funding_history
          WHERE funding_history.venue = 'binance_perp'::text
          GROUP BY funding_history.symbol, (date_trunc('month'::text, (funding_history.funding_time AT TIME ZONE 'utc'::text))::date)
        ), months AS (
         SELECT u1.symbol,
            g.g::date AS m
           FROM u1
             CROSS JOIN LATERAL generate_series(u1.start_m::timestamp with time zone, (date_trunc('month'::text, (now() AT TIME ZONE 'utc'::text)) - '1 mon'::interval)::date::timestamp with time zone, '1 mon'::interval) g(g)
        )
 SELECT symbol,
    m AS month
   FROM months m
  WHERE NOT (EXISTS ( SELECT 1
           FROM have h
          WHERE h.symbol = m.symbol AND h.m = m.m)) AND NOT (EXISTS ( SELECT 1
           FROM funding_vision_absent a
          WHERE a.symbol = m.symbol AND a.month = m.m));
