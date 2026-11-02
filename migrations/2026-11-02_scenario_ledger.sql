-- 2026-11-02 · 情景台账(src/data/evaluation/scenario_ledger.py):事前写下的命题,只追加;打分另表、可重算。
-- 触发器:写入时间与 d 用库的时间(客户端给的不算);结算日必须晚于写下那天;UPDATE / DELETE 一律拒绝。
create table if not exists public.scenario_ledger (
  id          text primary key,
  d           date not null,
  written_at  timestamptz not null default now(),
  author      text not null,
  scenario    text not null,
  statement   text not null,
  variable    text not null,
  op          text not null check (op in ('between', 'gt', 'lt')),
  lo          double precision,
  hi          double precision,
  prob        double precision not null check (prob >= 0 and prob <= 1),
  horizon_d   date not null,
  code_ref    text not null
);
create index if not exists scenario_ledger_horizon on public.scenario_ledger (horizon_d);

create or replace function public.scenario_ledger_guard() returns trigger language plpgsql as $$
begin
  if tg_op <> 'INSERT' then
    raise exception 'scenario_ledger is append-only: % refused (a forecast written cannot be changed or removed)', tg_op;
  end if;
  new.written_at := now();
  new.d := (now() at time zone 'utc')::date;
  if new.horizon_d <= new.d then
    raise exception 'scenario_ledger: horizon_d % must be after the day it is written (%)', new.horizon_d, new.d;
  end if;
  if new.op = 'between' and (new.lo is null or new.hi is null or new.lo > new.hi) then
    raise exception 'scenario_ledger: between needs lo <= hi';
  end if;
  if new.op = 'gt' and new.lo is null then raise exception 'scenario_ledger: gt needs lo'; end if;
  if new.op = 'lt' and new.hi is null then raise exception 'scenario_ledger: lt needs hi'; end if;
  return new;
end $$;
drop trigger if exists scenario_ledger_guard on public.scenario_ledger;
create trigger scenario_ledger_guard before insert or update or delete on public.scenario_ledger
  for each row execute function public.scenario_ledger_guard();

create table if not exists public.scenario_scores (
  id          text primary key references public.scenario_ledger(id),
  scored_at   timestamptz not null default now(),
  observed    double precision,
  outcome     boolean,
  brier       double precision,
  note        text,
  code_ref    text not null
);
alter table public.scenario_ledger enable row level security;
alter table public.scenario_scores enable row level security;
revoke all on public.scenario_ledger from anon, authenticated;
revoke all on public.scenario_scores from anon, authenticated;
