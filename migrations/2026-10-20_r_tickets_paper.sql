-- 2026-10-20 · R-v2 paper book: one kernel for replay and forward (docs/TRADING_LAYER_V2.md).
--
-- r_tickets_scan(p_to, p_from) walks UTC days in order and runs the ticket state machine that the research SQL
-- (docs/research/s610_breakout_sim.sql + ledger S-620(a) / S-627) computes in one shot:
--   signal  = deep-drawdown base breakout on day t (S-610 R arm, unchanged)
--   gate    = majors cap index above its 200-day mean on day t, else the ticket is logged as 'blocked'
--   entry   = open of the next bar; stop = entry − 2.5 × ATR14[t]; void if stop <= 0
--   exit    = low <= stop ⇒ at stop (at the open if it gapped through, except on the entry bar);
--             close < SMA20 ⇒ next bar's open; 120 bars held ⇒ that bar's close; no bar for 10 days ⇒ last close
--   no overlap: a symbol with a pending / open ticket takes no new signal
--   R = (exit − entry)/(entry − stop) − 0.4% × entry/(entry − stop)
-- Run forward by the Railway loop (one completed UTC day at a time); run historically inside a transaction
-- that is rolled back, to check it against the research SQL. Writes only these two tables.

create table if not exists public.r_tickets_paper (
  ticket_id    text primary key,
  symbol       text not null,
  signal_d     date not null,
  gate_open    boolean not null,
  atr14        double precision not null,
  status       text not null check (status in ('pending','open','closed','void','blocked')),
  entry_d      date,
  entry_px     double precision,
  stop_px      double precision,
  bars_held    integer not null default 0,
  exit_flag    boolean not null default false,
  exit_d       date,
  exit_px      double precision,
  exit_reason  text check (exit_reason in ('stop','sma20','time','no_data')),
  r_mult       double precision,
  rule_version text not null default 'r_v2_k2.5_gate200',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists r_tickets_paper_status_idx on public.r_tickets_paper (status, symbol);
create index if not exists r_tickets_paper_signal_idx on public.r_tickets_paper (signal_d);
alter table public.r_tickets_paper enable row level security;

create table if not exists public.r_tickets_state (
  id          integer primary key default 1 check (id = 1),
  last_d      date not null,
  last_run_at timestamptz not null default now(),
  last_result jsonb
);
alter table public.r_tickets_state enable row level security;

create or replace function public.r_tickets_scan(p_to date, p_from date default null)
returns jsonb
language plpgsql
security invoker
set search_path = public
as $fn$
declare
  v_from date;
  v_d date;
  v_last_done date;
  v_n_bars int;
  v_prev_bars int;
  v_gate_known boolean;
  v_new int := 0; v_blocked int := 0; v_filled int := 0; v_void int := 0; v_closed int := 0; v_k int; v_k2 int;
  v_stop_reason text := null;
begin
  if p_to >= (now() at time zone 'utc')::date then
    raise exception 'r_tickets_scan: p_to % is not a completed UTC day', p_to;
  end if;
  -- one scan at a time: a client that times out and retries must not run the same day twice
  if not pg_try_advisory_xact_lock(hashtext('r_tickets_scan')) then
    return jsonb_build_object('ok', false, 'busy', true, 'reason', 'another r_tickets_scan is running');
  end if;
  v_from := coalesce(p_from, (select last_d + 1 from r_tickets_state where id = 1), p_to);
  if v_from > p_to then
    return jsonb_build_object('ok', true, 'reason', 'up to date', 'last_d', p_to);
  end if;

  drop table if exists _rt_bars;
  drop table if exists _rt_gate;
  create temp table _rt_bars on commit drop as
  -- only the last ~560 days are windowed (the longest lookback is 365 + 120 rows); listing age still counts every
  -- earlier row, so `rn` is the same row number the research SQL uses
  with pre as (
    select symbol, count(*) n_before from ohlcv_daily
    where source = 'binance_hist' and symbol not in ('USDC','BTCDOM','DEFI') and trade_date < v_from - 560
    group by symbol
  ), b0 as (
    select x.symbol, x.trade_date d, x.open o, x.high h, x.low l, x.close c, x.close * x.volume dv,
           row_number() over w + coalesce(p.n_before, 0) rn, lag(x.close) over w pc
    from ohlcv_daily x left join pre p on p.symbol = x.symbol
    where x.source = 'binance_hist' and x.symbol not in ('USDC','BTCDOM','DEFI')
      and x.trade_date between v_from - 560 and p_to
    window w as (partition by x.symbol order by x.trade_date)
  ), f as (
    select *,
      avg(c) over (partition by symbol order by rn rows between 19 preceding and current row) sma20,
      avg(c) over (partition by symbol order by rn rows between 199 preceding and current row) sma200,
      avg(greatest(h-l, abs(h-coalesce(pc,c)), abs(l-coalesce(pc,c)))) over (partition by symbol order by rn rows between 13 preceding and current row) atr14,
      avg(dv) over (partition by symbol order by rn rows between 29 preceding and current row) adv30,
      avg(dv) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) adv40p,
      max(h) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) hh40,
      min(l) over (partition by symbol order by rn rows between 40 preceding and 1 preceding) ll40,
      c / max(c) over (partition by symbol order by rn rows between 365 preceding and current row) dd
    from b0
  ), f2 as (
    select f.*, min(dd) over (partition by symbol order by rn rows between 120 preceding and current row) mindd120 from f
  )
  select symbol, d, o, h, l, c, coalesce(sma20, c) sma20, atr14,
         (rn >= 220 and adv30 >= 5e6 and mindd120 <= 0.5 and (hh40 - ll40) / nullif(hh40, 0) <= 0.40
          and c > hh40 and c > sma200 and dv >= 2 * adv40p) sig
  from f2 where d >= v_from - 15;
  create index on _rt_bars (d, symbol);
  create index on _rt_bars (symbol, d);
  analyze _rt_bars;

  create temp table _rt_gate on commit drop as
  select d, (n < 200 or lvl > sma) gate_open from (
    select d, lvl, avg(lvl) over (order by d rows between 199 preceding and current row) sma,
           count(*) over (order by d rows between 199 preceding and current row) n
    from (select d, exp(sum(ln(1 + ret)) over (order by d)) lvl
          from style_index_pit_daily where style = 'majors' and weighting = 'cap' and ret > -0.95 and d <= p_to) z
  ) g where d >= v_from - 15;

  v_last_done := v_from - 1;
  for v_d in select generate_series(v_from, p_to, interval '1 day')::date loop
    -- data-completeness guards: never process a day whose inputs are not there yet
    select count(*) into v_n_bars from _rt_bars where d = v_d;
    select count(*) into v_prev_bars from _rt_bars where d = v_d - 1;
    select exists (select 1 from _rt_gate where d = v_d) into v_gate_known;
    if v_n_bars < greatest(20, 0.8 * v_prev_bars) then
      v_stop_reason := format('only %s bars on %s (previous day %s)', v_n_bars, v_d, v_prev_bars); exit;
    end if;
    if not v_gate_known and v_d > '2020-07-18' then v_stop_reason := format('majors index missing on %s', v_d); exit; end if;

    -- 1. yesterday's SMA20 exits fill at today's open
    with x as (
      update r_tickets_paper t set status = 'closed', exit_d = v_d, exit_px = b.o, exit_reason = 'sma20',
             r_mult = (b.o - t.entry_px) / (t.entry_px - t.stop_px) - 0.004 * t.entry_px / (t.entry_px - t.stop_px), updated_at = now()
      from _rt_bars b where t.status = 'open' and t.exit_flag and b.symbol = t.symbol and b.d = v_d returning 1)
    select count(*) into v_k from x; v_closed := v_closed + v_k;

    -- 2. pending tickets fill at today's open
    with x as (
      update r_tickets_paper t set status = case when b.o - 2.5 * t.atr14 > 0 then 'open' else 'void' end,
             entry_d = v_d, entry_px = b.o, stop_px = b.o - 2.5 * t.atr14, updated_at = now()
      from _rt_bars b where t.status = 'pending' and b.symbol = t.symbol and b.d = v_d returning t.status)
    select count(*) filter (where status = 'open'), count(*) filter (where status = 'void') into v_k, v_k2 from x;
    v_filled := v_filled + v_k; v_void := v_void + v_k2;

    -- 3. open tickets on today's bar: count it, then stop > SMA20 flag > time
    update r_tickets_paper t set bars_held = t.bars_held + 1
      from _rt_bars b where t.status = 'open' and not t.exit_flag and b.symbol = t.symbol and b.d = v_d;
    with x as (
      update r_tickets_paper t set status = 'closed', exit_d = v_d, exit_reason = 'stop',
             exit_px = case when v_d > t.entry_d and b.o <= t.stop_px then b.o else t.stop_px end,
             r_mult = ((case when v_d > t.entry_d and b.o <= t.stop_px then b.o else t.stop_px end) - t.entry_px) / (t.entry_px - t.stop_px)
                      - 0.004 * t.entry_px / (t.entry_px - t.stop_px), updated_at = now()
      from _rt_bars b where t.status = 'open' and not t.exit_flag and b.symbol = t.symbol and b.d = v_d and b.l <= t.stop_px returning 1)
    select count(*) into v_k from x; v_closed := v_closed + v_k;
    update r_tickets_paper t set exit_flag = true, updated_at = now()
      from _rt_bars b where t.status = 'open' and not t.exit_flag and b.symbol = t.symbol and b.d = v_d and b.c < b.sma20;
    with x as (
      update r_tickets_paper t set status = 'closed', exit_d = v_d, exit_px = b.c, exit_reason = 'time',
             r_mult = (b.c - t.entry_px) / (t.entry_px - t.stop_px) - 0.004 * t.entry_px / (t.entry_px - t.stop_px), updated_at = now()
      from _rt_bars b where t.status = 'open' and not t.exit_flag and b.symbol = t.symbol and b.d = v_d and t.bars_held >= 120 returning 1)
    select count(*) into v_k from x; v_closed := v_closed + v_k;

    -- 3b. a symbol that stopped printing bars: close at its last close after 10 days
    with lastbar as (
      select t.ticket_id, lb.d, lb.c from r_tickets_paper t
      cross join lateral (select d, c from _rt_bars b where b.symbol = t.symbol and b.d <= v_d order by d desc limit 1) lb
      where t.status = 'open' and lb.d < v_d - 9
    ), x as (
      update r_tickets_paper t set status = 'closed', exit_d = l.d, exit_px = l.c, exit_reason = 'no_data',
             r_mult = (l.c - t.entry_px) / (t.entry_px - t.stop_px) - 0.004 * t.entry_px / (t.entry_px - t.stop_px), updated_at = now()
      from lastbar l where t.ticket_id = l.ticket_id returning 1)
    select count(*) into v_k from x; v_closed := v_closed + v_k;

    -- 4. today's signals: pending if the gate is open, logged as blocked otherwise
    with x as (
      insert into r_tickets_paper (ticket_id, symbol, signal_d, gate_open, atr14, status)
      select b.symbol || ':' || v_d, b.symbol, v_d, coalesce(g.gate_open, true), b.atr14,
             case when coalesce(g.gate_open, true) then 'pending' else 'blocked' end
      from _rt_bars b left join _rt_gate g on g.d = v_d
      where b.d = v_d and b.sig and b.atr14 > 0
        and not exists (select 1 from r_tickets_paper t where t.symbol = b.symbol and t.status in ('pending','open'))
      on conflict (ticket_id) do nothing
      returning status)
    select count(*) filter (where status = 'pending'), count(*) filter (where status = 'blocked') into v_k, v_k2
      from x;
    v_new := v_new + v_k; v_blocked := v_blocked + v_k2;
    v_last_done := v_d;
  end loop;

  drop table if exists _rt_bars;
  drop table if exists _rt_gate;
  if v_last_done >= v_from then
    insert into r_tickets_state (id, last_d, last_run_at) values (1, v_last_done, now())
      on conflict (id) do update set last_d = excluded.last_d, last_run_at = excluded.last_run_at;
  end if;
  return jsonb_build_object(
    'ok', v_stop_reason is null, 'from', v_from, 'to', p_to, 'last_done', v_last_done, 'stopped', v_stop_reason,
    'new_pending', v_new, 'blocked', v_blocked, 'filled', v_filled, 'closed', v_closed, 'void', v_void,
    'open_now', (select count(*) from r_tickets_paper where status = 'open'),
    'pending_now', (select count(*) from r_tickets_paper where status = 'pending'));
end
$fn$;

revoke all on function public.r_tickets_scan(date, date) from public, anon, authenticated;
