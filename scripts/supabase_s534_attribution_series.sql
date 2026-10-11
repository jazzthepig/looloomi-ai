-- S-534 / T-080 — 归因跟着正式序列走:一张表两条序列,不覆盖、不删。
--   standard   = 统一标准日终序列(cis_rebuild_daily v1.1 的按时点重建 + cis_official_daily 的已发布),对外默认
--   live_mixed = 10-10 及以前实际对外发布过的实时信号(v_cis_signal_daily,T1/T2 一天一个来源)—— 冻结在 10-10,只让结果到期
-- 档位按同组分位定之后,换档可能不是自己的分数变了、而是同组别人变了 → 记 pct / prev_pct,归因里两样都看得见。
-- AS APPLIED 2026-10-11(migration s534_attribution_series)。
alter table public.cis_signal_attribution add column if not exists series text not null default 'live_mixed';
alter table public.cis_signal_attribution add column if not exists pct double precision;
alter table public.cis_signal_attribution add column if not exists prev_pct double precision;
alter table public.cis_signal_attribution drop constraint if exists cis_signal_attribution_pkey;
alter table public.cis_signal_attribution add constraint cis_signal_attribution_pkey primary key (symbol, d, series);
