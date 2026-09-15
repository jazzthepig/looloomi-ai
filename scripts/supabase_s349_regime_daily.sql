-- S-349 · 已于 2026-09-15 经 MCP 应用到生产 · 记录副本,非待跑文件
-- migration name: s349_regime_daily_fingerprint_and_meditations
--
-- 为什么:HIGH_DIM_ONTOLOGY §5 的 `Regime 指纹 12d` 标着「已算未入库」三个月,
-- 同时 meditations/ 的 83 篇每日判读被 0 行代码读过。两个为彼此而生的东西没见过面。
-- 不进 pgvector:§4「sparse+few → jsonb + NaN-aware 共享维余弦」,且 0 补齐是错误度量。
-- I1 在这里的形态:没测到的维度,**键不存在**,不是 0。
create table if not exists public.regime_daily (
    d date primary key,
    features jsonb not null,
    regime_db text,
    n_universe integer,
    meditation text,
    meditation_regime text,
    created_at timestamptz not null default now()
);
alter table public.regime_daily enable row level security;
grant select on public.regime_daily to anon;
grant select, insert, update, delete on public.regime_daily to authenticated;
grant select, insert, update, delete on public.regime_daily to service_role;

insert into public.regime_daily (d, features, regime_db, n_universe)
select c.recorded_at::date,
       jsonb_strip_nulls(jsonb_build_object(
         'avg_cis', round(avg(c.score)::numeric,3),
         'pct_out', round((count(*) filter (where c.signal like '%OUTPERFORM%'))::numeric/nullif(count(*),0),4),
         'pct_under', round((count(*) filter (where c.signal like '%UNDER%'))::numeric/nullif(count(*),0),4),
         'avg_pillar_f', round(avg(c.pillar_f)::numeric,3),
         'avg_pillar_m', round(avg(c.pillar_m)::numeric,3),
         'avg_pillar_o', round(avg(c.pillar_o)::numeric,3),
         'avg_pillar_s', round(avg(c.pillar_s)::numeric,3),
         'avg_pillar_a', round(avg(c.pillar_a)::numeric,3),
         'avg_las', round(avg(c.las)::numeric,3),
         'avg_conf', round(avg(c.confidence)::numeric,3),
         'score_disp', round(stddev_samp(c.score)::numeric,3))),
       mode() within group (order by c.macro_regime),
       count(distinct c.symbol)
from public.cis_scores c
where c.recorded_at is not null
group by c.recorded_at::date
on conflict (d) do nothing;
-- 实测落地:474 天 · 全部带 regime_db · 平均 10.83 维(最少 6,那是真的只测到 6)
