-- S-535 / T-080 — v1.1 的档位缓冲有缺陷,永远不得进正式表。
-- ±10 个百分位的缓冲放在 90 / 10 分位的门槛上 = 进入「前 10%」要求分位 ≥ 1.0、进入「后 10%」要求 < 0 ——
-- 两个极端档只在序列第一天出现,之后永远进不去(10-10 的重建:0 个 STRONG OUTPERFORM、0 个 UNDERWEIGHT;MKR 分位 0.02 仍是 UNDERPERFORM)。
-- 表只追加、主键 (symbol, d):错的一批写进去就改不回来,所以在库里直接拒绝 v1.1 的行;v1.2 起外侧门槛缓冲封顶 5。
-- AS APPLIED 2026-10-11 14:4x UTC(migration s535_official_refuse_v1_1),在第一批正式发布之前。
alter table public.cis_official_daily add constraint cis_official_daily_not_v1_1 check (code_ref <> 'cis-standard-v1.1');
