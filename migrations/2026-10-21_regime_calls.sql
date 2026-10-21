-- 2026-10-21 · Jazz ⓪ 开关:人的「何时在场 / 在哪」判断,作为一个被记录、被执行、被记分的输入
-- (docs/HIGH_DIM_ONTOLOGY.md §5b-bis「⓪ 是我们最该建的能力」;Jazz 10-21「高维选战场,低维集中火力」)。
--
-- regime_calls  只追加。每一条是一次完整的判断(不是增量):
--   state       on   = 照常 + 战场名单上的币开 J 票 + 信心档位放大每票风险
--               off  = 不开任何新票(R-v2 与 J 票),已有的照规则走完
--               flat = 不开新票,且所有在持的票下一轮出场
--   conviction  1 / 2 / 3 ⇒ 每票风险 × 1 / 1.5 / 2(主机再守 2 倍上限)
--   battlefield HL 永续币名;on 时每个没有在持 J 票的币开一张 J 票
--   close_coins 这些币的 J 票下一轮出场(人的提前离场,记分时单列)
--   effective_d 从哪个 asof 起管(= 提交时的 UTC 日期;主机每天 00:45 后执行 asof = 前一天的计划)
-- j_tickets     人选的战场、系统管的票:进场 = 次日开盘,止损 = 进场 − 2.5 × ATR14(HL 日线),
--               收盘破 SMA20 次日开盘出 / 120 根到期 —— 与 R-v2 同一套管理,R 同口径(含 0.4% 来回成本);
--               唯一的不同:SMA20 离场要等第一次收盘站上 SMA20 之后才生效(sma_armed),人可能在回调里进场。
-- j_tickets_state  每日推进到哪天(判活:last_d ≥ 前天,且 loop_attempt 里 _r_tickets_paper_loop 带 j_scan)。

create table if not exists public.regime_calls (
  id           bigserial primary key,
  at           timestamptz not null default now(),
  state        text not null check (state in ('on', 'off', 'flat')),
  conviction   smallint not null default 1 check (conviction between 1 and 3),
  battlefield  text[] not null default '{}',
  close_coins  text[] not null default '{}',
  note         text not null default '',
  effective_d  date not null,
  expires_at   timestamptz not null,
  source       text not null default 'jazz',
  check (expires_at > at)
);
create index if not exists regime_calls_at_idx on public.regime_calls (at desc);
alter table public.regime_calls enable row level security;

create table if not exists public.j_tickets (
  ticket_id    text primary key,
  coin         text not null,
  call_id      bigint not null references public.regime_calls (id),
  signal_d     date not null,
  atr14        double precision not null,
  ref_close    double precision not null,
  risk_mult    double precision not null default 1,
  status       text not null check (status in ('pending', 'open', 'closed', 'void')),
  entry_d      date,
  entry_px     double precision,
  stop_px      double precision,
  bars_held    integer not null default 0,
  exit_flag    boolean not null default false,
  sma_armed    boolean not null default false,
  exit_why     text,
  exit_d       date,
  exit_px      double precision,
  exit_reason  text check (exit_reason in ('stop', 'sma20', 'time', 'human', 'flat', 'no_data')),
  r_mult       double precision,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- 人可能在回调里进场(收盘在 SMA20 下面):SMA20 离场在第一次收盘站上 SMA20 之后才生效,之前只有 2.5 ATR 止损
alter table public.j_tickets add column if not exists sma_armed boolean not null default false;
create index if not exists j_tickets_status_idx on public.j_tickets (status, coin);
alter table public.j_tickets enable row level security;

create table if not exists public.j_tickets_state (
  id          integer primary key default 1 check (id = 1),
  last_d      date not null,
  last_run_at timestamptz not null default now(),
  last_result jsonb
);
alter table public.j_tickets_state enable row level security;
