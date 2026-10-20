-- 2026-10-21 · R-v2 money NAV: one read-only kernel for the forward book and the replay (ledger S-638).
--
-- r_tickets_nav(p_tickets, p_f, p_cap, p_from, p_to, p_compound, p_equity0) marks a set of R tickets to market at every
-- UTC daily close and returns the equity curve. It does not decide tickets — r_tickets_scan does (forward), or the
-- research SQL docs/research/r_v2_tickets.sql does (replay); both hand the same jsonb shape to this function:
--   [{"id", "symbol", "signal_d", "entry_d", "exit_d" (null = still open), "entry_px", "stop_px", "exit_px"}, ...]
-- Rules (S-638, written before any f was run):
--   units    = p_f × equity(close of entry_d − 1) / (entry − stop)   (p_compound = false ⇒ p_equity0 instead; check only)
--   cost     = 0.2% × entry notional at entry and again at exit  (= the 0.4% × entry / (entry − stop) in the R formula)
--   cap      = on entry day d, tickets already taken with entry_d < d and exit_d ≥ d (or still open) occupy a slot;
--              a new ticket is taken only while occupied + taken-today < p_cap; same day ⇒ signal_d, then symbol
--   mark     = each held symbol's latest binance_hist close on or before the day
--   no gross-notional cap (perps); gross / equity is reported. Funding is NOT charged here (coverage: S-638).
-- Read-only: temp tables only. Forward use: r_tickets_nav_paper(p_f, p_cap) below.

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
                      where x.source = 'binance_hist' and x.symbol = k.symbol and x.trade_date <= g.t::date
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

-- The forward book: the paper tickets as they stand, from the book's first forward day (2026-10-19, the first day
-- r_tickets_scan processed) through r_tickets_state.last_d.
create or replace function public.r_tickets_nav_paper(p_f double precision, p_cap int default 10,
                                                      p_from date default '2026-10-19')
returns table(d date, equity double precision, realized double precision, unrealized double precision,
              open_n int, gross double precision, taken int, skipped int, closed int)
language sql
volatile
security invoker
set search_path = public
as $fn$
  select * from r_tickets_nav(
    (select coalesce(jsonb_agg(jsonb_build_object(
        'id', t.ticket_id, 'symbol', t.symbol, 'signal_d', t.signal_d, 'entry_d', t.entry_d, 'exit_d', t.exit_d,
        'entry_px', t.entry_px, 'stop_px', t.stop_px, 'exit_px', t.exit_px)), '[]'::jsonb)
     from r_tickets_paper t where t.status in ('open', 'closed') and t.entry_d is not null),
    p_f, p_cap, p_from,
    (select last_d from r_tickets_state where id = 1),
    true, 1.0)
$fn$;

revoke all on function public.r_tickets_nav(jsonb, double precision, int, date, date, boolean, double precision) from public, anon, authenticated;
revoke all on function public.r_tickets_nav_paper(double precision, int, date) from public, anon, authenticated;
