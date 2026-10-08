-- S-512 / T-067 — 风格指数按时点、在更宽的历史宇宙上重算(src/data/style/pit.py)。
-- style_universe_broad     在 Binance 现货上市过的币(含已下架)映射到 CoinGecko 之后的分类;成分是**今天的分类**
-- style_index_pit_daily    与 style_index_daily 同列 + n_not_in_today_lists(当天成员里不在今天分类前 40 名单上的个数)
-- style_pit_coverage_daily 每天:宇宙里有市值的币合计 / CoinGecko 全市场市值 —— 看不见的那部分有多大
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s512_style_pit)。
create table if not exists public.style_universe_broad (
  symbol      text not null,
  coin_id     text not null,
  categories  jsonb,
  tier_base   text,
  sectors     jsonb,
  source      text not null,
  fetched_d   date not null,
  recorded_at timestamptz not null default now(),
  primary key (symbol, coin_id)
);
create table if not exists public.style_index_pit_daily (
  d           date not null,
  style       text not null,
  weighting   text not null check (weighting in ('cap','equal')),
  dimension   text,
  ret         double precision not null,
  level       double precision not null,
  n_members   integer not null,
  n_dropped   integer not null default 0,
  n_not_in_today_lists integer,
  top_member  text,
  top_weight  double precision,
  members     jsonb,
  basis       text not null,
  code_ref    text,
  computed_at timestamptz not null default now(),
  primary key (d, style, weighting)
);
create table if not exists public.style_pit_coverage_daily (
  d             date primary key,
  universe_mcap double precision,
  total_mcap    double precision,
  coverage      double precision,
  n_universe    integer,
  n_not_in_today_lists integer,
  code_ref      text,
  computed_at   timestamptz not null default now()
);
alter table public.style_universe_broad     enable row level security;
alter table public.style_index_pit_daily    enable row level security;
alter table public.style_pit_coverage_daily enable row level security;
revoke all on public.style_universe_broad, public.style_index_pit_daily, public.style_pit_coverage_daily from anon, authenticated;
grant select, insert, update, delete on public.style_universe_broad, public.style_index_pit_daily, public.style_pit_coverage_daily to service_role;
