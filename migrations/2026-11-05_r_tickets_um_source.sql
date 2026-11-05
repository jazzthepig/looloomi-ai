-- S-718(2026-11-05,Jazz 拍板):R-v2 交易永续、宇宙按定义是 Binance U 本位永续在册 ⇒ 票的扫描与盯市改读 `binance_um_hist`
-- (永续日线:存档到 2026-08-08 + `um_bridge_fill()` 从 perp_bv_daily 续写)。函数体与 2026-10-20 / 10-21 的版本逐字相同,只换源标签。
-- 背景:S-698(10-30)把 binance_hist 修成现货量之后,R-v2 在现货量序列上是 600 张 / 197R,验证过的 770 张 / 372R 是永续量(T-237)。
-- r_tickets_paper 当时 0 行、无持仓 ⇒ 切换无需迁移状态。已通过 Supabase MCP 施加(migration name: r_tickets_um_source)。
-- 续写函数 um_bridge_fill 见同日 migration um_bridge_fill。

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
    where source = 'binance_um_hist' and symbol not in ('USDC','BTCDOM','DEFI') and trade_date < v_from - 560
    group by symbol
  ), b0 as (
    select x.symbol, x.trade_date d, x.open o, x.high h, x.low l, x.close c, x.close * x.volume dv,
           row_number() over w + coalesce(p.n_before, 0) rn, lag(x.close) over w pc
    from ohlcv_daily x left join pre p on p.symbol = x.symbol
    where x.source = 'binance_um_hist' and x.symbol not in ('USDC','BTCDOM','DEFI')
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

create or replace function public.r_tickets_nav(
  p_tickets jsonb,
  p_f double precision,
  p_cap int default 10,
  p_from date default null,
  p_to date default null,
  p_compound boolean default true,
  p_equity0 double precision default 1.0)
returns table(d date, equity double precision, realized double precision, unrealized double precision,
              open_n int, gross double precision, taken int, skipped int, closed int)
language plpgsql
volatile
security invoker
set search_path = public
as $fn$
#variable_conflict use_column
declare
  v_from date; v_to date; v_e date;
  v_eq_prev double precision;
  v_occ int; v_k int;
  r record;
begin
  if p_f is null or p_f <= 0 or p_f > 0.5 then raise exception 'r_tickets_nav: p_f % out of (0, 0.5]', p_f; end if;
  if p_cap is null or p_cap < 1 then raise exception 'r_tickets_nav: p_cap % < 1', p_cap; end if;

  drop table if exists _nv_tk;
  drop table if exists _nv_path;
  create temp table _nv_tk on commit drop as
  select t->>'id' id, t->>'symbol' symbol, (t->>'signal_d')::date signal_d, (t->>'entry_d')::date entry_d,
         nullif(t->>'exit_d', '')::date exit_d, (t->>'entry_px')::float8 entry_px, (t->>'stop_px')::float8 stop_px,
         nullif(t->>'exit_px', '')::float8 exit_px,
         null::text state, 0::float8 units
  from jsonb_array_elements(coalesce(p_tickets, '[]'::jsonb)) t
  where (t->>'entry_d') is not null and (t->>'entry_px')::float8 > (t->>'stop_px')::float8;
  v_from := coalesce(p_from, (select min(entry_d) from _nv_tk));
  v_to := coalesce(p_to, (now() at time zone 'utc')::date - 1);
  if v_from is null or v_from > v_to then return; end if;
  delete from _nv_tk k where k.entry_d < v_from or k.entry_d > v_to;
  update _nv_tk k set exit_d = null, exit_px = null where k.exit_d > v_to;   -- not exited yet as of p_to
  create index on _nv_tk (entry_d);
  analyze _nv_tk;

  -- per-unit value of every ticket on every held calendar day before its exit: latest close on or before the day,
  -- less the entry, less the entry cost already paid (the exit cost is paid on the exit day, inside the realised value)
  create temp table _nv_path on commit drop as
  select k.id, g.t::date t, m.c - k.entry_px - 0.002 * k.entry_px u, m.c mark
  from _nv_tk k
  cross join lateral generate_series(k.entry_d, coalesce(k.exit_d - 1, v_to), interval '1 day') g(t)
  cross join lateral (select x.close c from ohlcv_daily x
                      where x.source = 'binance_um_hist' and x.symbol = k.symbol and x.trade_date <= g.t::date
                      order by x.trade_date desc limit 1) m;
  create index on _nv_path (t);
  analyze _nv_path;

  -- the only path-dependent step: who is taken, and at what size, walking entry days in order
  for v_e in select distinct k.entry_d from _nv_tk k order by 1 loop
    select p_equity0
           + coalesce((select sum(k.units * (k.exit_px - k.entry_px - 0.004 * k.entry_px)) from _nv_tk k
                       where k.state = 'taken' and k.exit_d <= v_e - 1), 0)
           + coalesce((select sum(k.units * p.u) from _nv_path p join _nv_tk k on k.id = p.id
                       where p.t = v_e - 1 and k.state = 'taken'), 0)
      into v_eq_prev;
    select count(*) into v_occ from _nv_tk k
      where k.state = 'taken' and k.entry_d < v_e and (k.exit_d is null or k.exit_d >= v_e);
    v_k := 0;
    for r in select k.id, k.entry_px, k.stop_px from _nv_tk k where k.entry_d = v_e order by k.signal_d, k.symbol loop
      if v_occ + v_k < p_cap then
        update _nv_tk k set state = 'taken',
               units = p_f * (case when p_compound then v_eq_prev else p_equity0 end) / (r.entry_px - r.stop_px)
          where k.id = r.id;
        v_k := v_k + 1;
      else
        update _nv_tk k set state = 'skipped' where k.id = r.id;
      end if;
    end loop;
  end loop;

  return query
  with days as (select g::date t from generate_series(v_from, v_to, interval '1 day') g),
  rz as (select x.t, coalesce(sum(k.units * (k.exit_px - k.entry_px - 0.004 * k.entry_px)), 0) rv, count(k.id) nx
         from days x left join _nv_tk k on k.state = 'taken' and k.exit_d = x.t group by x.t),
  op as (select p.t, sum(k.units * (p.mark - k.entry_px)) unr, sum(k.units * 0.002 * k.entry_px) ec,
                sum(k.units * p.mark) gr, count(*) n
         from _nv_path p join _nv_tk k on k.id = p.id and k.state = 'taken' group by p.t),
  ent as (select x.t, count(*) filter (where k.state = 'taken') nt, count(*) filter (where k.state = 'skipped') ns
          from days x left join _nv_tk k on k.entry_d = x.t group by x.t)
  select x.t,
         p_equity0 + sum(rz.rv) over w + coalesce(op.unr, 0) - coalesce(op.ec, 0),
         sum(rz.rv) over w - coalesce(op.ec, 0),
         coalesce(op.unr, 0),
         coalesce(op.n, 0)::int,
         coalesce(op.gr, 0) / nullif(p_equity0 + sum(rz.rv) over w + coalesce(op.unr, 0) - coalesce(op.ec, 0), 0),
         (sum(ent.nt) over w)::int, (sum(ent.ns) over w)::int, (sum(rz.nx) over w)::int
  from days x join rz on rz.t = x.t join ent on ent.t = x.t left join op on op.t = x.t
  window w as (order by x.t)
  order by x.t;

  drop table if exists _nv_tk;
  drop table if exists _nv_path;
end
$fn$;
