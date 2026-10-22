-- 2026-10-22 · CIS v2 影子加状态层与档位(S-669;Jazz 10-22:加密影子满 20 天即切、个股不给档位)。
--   state   v2_state.state_for 的结果:趋势标签、30 日动量与 7 日资金费(只给数值)、市场情绪 —— 描述,不是预测
--   pct     加密组内按 v2 分数的分位(平均名次 ÷ 人数);个股为空
--   signal  加密档位(与 v1 同一套滞回 pct_step,接前一天 v2 的档);个股为空(不给档位)
--   watch   滞回缓冲带内的标记
-- 加列不改已有行(表是只追加的,触发器拦的是改删,不拦加列)。
alter table public.cis_v2_daily add column if not exists state jsonb;
alter table public.cis_v2_daily add column if not exists pct double precision;
alter table public.cis_v2_daily add column if not exists signal text;
alter table public.cis_v2_daily add column if not exists watch text;
alter table public.cis_v2_daily drop constraint if exists cis_v2_daily_signal_enum;
alter table public.cis_v2_daily add constraint cis_v2_daily_signal_enum check (
  signal is null or signal in ('UNDERWEIGHT', 'UNDERPERFORM', 'NEUTRAL', 'OUTPERFORM', 'STRONG OUTPERFORM'));
alter table public.cis_v2_daily drop constraint if exists cis_v2_daily_no_equity_bands;
alter table public.cis_v2_daily add constraint cis_v2_daily_no_equity_bands check (grp = 'crypto' or signal is null);
