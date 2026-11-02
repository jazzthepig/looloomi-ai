-- 2026-11-02 · 偏离(src/data/execution/overlays.py):规则是零假设,打破是实验(Jazz 11-02)。
-- overlays / overlay_events 只追加(写入时间由库定;起始日不早于写下那天;UPDATE / DELETE 拒绝);overlay_daily 每天一行记录基线 vs 偏离后。
create table if not exists public.overlays (
  id          text primary key,
  d           date not null,
  created_at  timestamptz not null default now(),
  author      text not null,
  source      text not null check (source in ('scenario', 'jazz', 'opportunity', 'seth')),
  thesis      text not null,
  scenario_id text,
  crypto_mult double precision check (crypto_mult is null or (crypto_mult >= 0 and crypto_mult <= 3)),
  gold_pp     double precision check (gold_pp is null or abs(gold_pp) <= 10),
  equity_pp   double precision check (equity_pp is null or abs(equity_pp) <= 10),
  starts_d    date not null,
  ends_d      date not null,
  exit_rule   text not null,
  code_ref    text not null,
  check (ends_d >= starts_d and ends_d - starts_d <= 90),
  check (crypto_mult is not null or gold_pp is not null or equity_pp is not null)
);
create or replace function public.overlays_guard() returns trigger language plpgsql as $$
begin
  if tg_op <> 'INSERT' then
    raise exception '% is append-only: % refused (withdraw = insert an overlay_events cancel row)', tg_table_name, tg_op;
  end if;
  if tg_table_name = 'overlays' then
    new.created_at := now();
    new.d := (now() at time zone 'utc')::date;
    if new.starts_d < new.d then
      raise exception 'overlays: starts_d % is before the day it is written (%)', new.starts_d, new.d;
    end if;
  else
    new.at := now();
  end if;
  return new;
end $$;
drop trigger if exists overlays_guard on public.overlays;
create trigger overlays_guard before insert or update or delete on public.overlays
  for each row execute function public.overlays_guard();

create table if not exists public.overlay_events (
  id          bigserial primary key,
  overlay_id  text not null references public.overlays(id),
  at          timestamptz not null default now(),
  kind        text not null check (kind in ('cancel')),
  reason      text not null,
  author      text not null
);
drop trigger if exists overlay_events_guard on public.overlay_events;
create trigger overlay_events_guard before insert or update or delete on public.overlay_events
  for each row execute function public.overlays_guard();

create table if not exists public.overlay_daily (
  d               date primary key,
  ids             text[] not null default '{}',
  capital_usd     double precision,
  x1v_base_usd    double precision,
  x1v_usd         double precision,
  gold_base_usd   double precision,
  gold_usd        double precision,
  equity_base_usd double precision,
  equity_usd      double precision,
  clipped         text[] not null default '{}',
  code_ref        text not null,
  computed_at     timestamptz not null default now()
);
alter table public.overlays enable row level security;
alter table public.overlay_events enable row level security;
alter table public.overlay_daily enable row level security;
revoke all on public.overlays from anon, authenticated;
revoke all on public.overlay_events from anon, authenticated;
revoke all on public.overlay_daily from anon, authenticated;
