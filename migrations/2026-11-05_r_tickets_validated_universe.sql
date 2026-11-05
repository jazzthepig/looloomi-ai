-- S-730(2026-11-05 06:07 UTC):R-v2 的宇宙收回到验证过的那批名字(binance_hist 面板符号 ∩ 加密永续),序列仍是 perp_bv_daily。
-- 同日 02:25 的 r_tickets_perp_source 把宇宙一并扩到了全部 coin 永续 —— 没有预注册的策略变更;T-238 v2 显示扩出来的票 2026-08 后
-- 123 张合计 −24.9R、10-19 → 11-03 的 8 张全亏。只改 r_tickets_scan 的 uni CTE;r_tickets_nav 不变(按票的 symbol 取 perp_bv_daily 收盘)。
-- 已通过 Supabase MCP 施加(migration name: r_tickets_validated_universe)。

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
  with uni as (
    -- S-730(11-05):宇宙 = R-v2 验证过的那批名字(binance_hist 面板里的符号)∩ 加密永续合约;序列用永续(perp_bv_daily)。
    -- 02:25 的版本把宇宙扩到全部 coin 永续(约 650 个,含 2025 年新上的小合约)—— 那是没有预注册的策略变更(T-238 v2:扩出来的
    -- 2026-08 后 123 张票合计 −24.9R),这里收回。宇宙要扩,另立预注册(S-684 已量过全宇宙:仍为正但不显著)。
    select p.symbol from perp_bv_pairs p
    where (p.kind = 'coin' or (p.kind is null and p.dead_from is not null))
      and p.symbol in (select distinct o.symbol from ohlcv_daily o where o.source = 'binance_hist')
  ), pre as (
    select symbol, count(*) n_before from perp_bv_daily
    where symbol in (select symbol from uni) and symbol not in ('USDC','BTCDOM','DEFI') and d < v_from - 560
    group by symbol
  ), b0 as (
    select x.symbol, x.d d, x.o o, x.h h, x.l l, x.c c, x.qv dv,
           row_number() over w + coalesce(p.n_before, 0) rn, lag(x.c) over w pc
    from perp_bv_daily x left join pre p on p.symbol = x.symbol
    where x.symbol in (select symbol from uni) and x.symbol not in ('USDC','BTCDOM','DEFI') and x.c > 0
      and x.d between v_from - 560 and p_to
    window w as (partition by x.symbol order by x.d)
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
