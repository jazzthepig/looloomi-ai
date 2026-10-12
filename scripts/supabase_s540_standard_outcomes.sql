-- S-540 — 档位历史表现(track record / edge map)只从正式序列算。
-- 之前:refresh_signal_track_record 读 cis_scores(实时引擎),refresh_signal_edge_map 读 signal_outcomes_unified
-- (旧 signal_outcomes + 信号日志)—— 资产页旁边的「同档历史」(归因,正式序列)与档位表现页是两套数。
-- 现在两个函数都从 cis_standard_outcomes 聚合:每个 (名字, 日) 在正式序列上的 30 日结果
-- (已发布优先,之前是同标准按时点重建;每行 provenance)。函数名不变 —— 调它们的调度(Railway / Mac)不用改。
-- AS APPLIED 2026-10-12(migration s540_standard_outcomes)。
create table if not exists public.cis_standard_outcomes (
  symbol          text not null,
  d               date not null,
  asset_class     text,
  grp             text,
  signal          text,
  grade           text,
  provenance      text,
  bench           text,
  a_ret           double precision,
  b_ret           double precision,
  alpha           double precision,
  bench_trail_30d double precision,
  panel_fwd_30d   double precision,
  panel_trail_30d double precision,
  computed_at     timestamptz not null default now(),
  primary key (symbol, d)
);
alter table public.cis_standard_outcomes enable row level security;
revoke all on public.cis_standard_outcomes from anon, authenticated;
grant select, insert, update on public.cis_standard_outcomes to service_role;

create or replace function public.refresh_signal_track_record()
 returns integer
 language plpgsql
 security definer
 set search_path to 'public', 'pg_temp'
as $function$
declare n_rows int;
begin
  insert into signal_track_record (signal, grade, n, avg_alpha_pct, alpha_win_pct, avg_abs_return_pct, lookback_days, basis)
  select signal, grade, count(*),
         round(avg(alpha * 100)::numeric, 2),
         round(100.0 * count(*) filter (where alpha > 0) / count(*), 1),
         round(avg(a_ret * 100)::numeric, 2),
         30,
         'official daily-close series (published + point-in-time reconstruction of the same standard); 30d vs BTC (crypto) / SPY (traditional)'
  from cis_standard_outcomes
  where alpha is not null and signal is not null
  group by signal, grade;
  get diagnostics n_rows = row_count;
  return n_rows;
end $function$;

create or replace function public.refresh_signal_edge_map()
 returns integer
 language plpgsql
 set search_path to 'public', 'extensions', 'pg_temp'
as $function$
declare n_rows int;
begin
    with rows_btc as (
        select 'btc'::text as benchmark, o.signal, o.alpha * 100 as alpha, o.a_ret * 100 as a_ret,
               case when o.bench_trail_30d < -0.15 then '1_deep_off'
                    when o.bench_trail_30d < -0.05 then '2_off'
                    when o.bench_trail_30d <  0.05 then '3_neutral'
                    when o.bench_trail_30d <  0.15 then '4_on'
                    else '5_deep_on' end as risk_band
        from cis_standard_outcomes o
        where o.grp = 'crypto' and o.bench_trail_30d is not null and o.alpha is not null
    ),
    rows_panel as (
        select 'panel_ew'::text as benchmark, o.signal, (o.a_ret - o.panel_fwd_30d) * 100 as alpha, o.a_ret * 100 as a_ret,
               case when o.panel_trail_30d < -0.15 then '1_deep_off'
                    when o.panel_trail_30d < -0.05 then '2_off'
                    when o.panel_trail_30d <  0.05 then '3_neutral'
                    when o.panel_trail_30d <  0.15 then '4_on'
                    else '5_deep_on' end as risk_band
        from cis_standard_outcomes o
        where o.grp = 'crypto' and o.panel_fwd_30d is not null and o.panel_trail_30d is not null
    ),
    all_rows as (select * from rows_btc union all select * from rows_panel)
    insert into signal_edge_map
        (benchmark, signal, risk_band, n, avg_alpha_pct, alpha_win_pct, avg_abs_return_pct, computed_at)
    select benchmark, signal, risk_band, count(*),
           round(avg(alpha)::numeric, 2),
           round(100.0 * count(*) filter (where alpha > 0) / count(*), 1),
           round(avg(a_ret)::numeric, 2),
           now()
    from all_rows
    where signal is not null and risk_band is not null
    group by benchmark, signal, risk_band
    on conflict (benchmark, signal, risk_band) do update
        set n                  = excluded.n,
            avg_alpha_pct      = excluded.avg_alpha_pct,
            alpha_win_pct      = excluded.alpha_win_pct,
            avg_abs_return_pct = excluded.avg_abs_return_pct,
            computed_at        = excluded.computed_at;
    get diagnostics n_rows = row_count;
    return n_rows;
end
$function$;
revoke all on function public.refresh_signal_track_record() from public, anon, authenticated;
revoke all on function public.refresh_signal_edge_map() from public, anon, authenticated;
grant execute on function public.refresh_signal_track_record() to service_role;
grant execute on function public.refresh_signal_edge_map() to service_role;
