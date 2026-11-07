-- 2026-11-06 · T-082 验收 ②「深度**与场所成交**」—— 11-02 建表时把 24h 成交字段当成 CEX 才有的去掉了,
-- 但 HL 的 metaAndAssetCtxs / spotMetaAndAssetCtxs 每个名字都给 dayNtlVlm(美元名义额,滚动 24h)。
-- 同一批采样顺手带上(永续那一次 metaAndAssetCtxs 是全部名字一次请求;现货那一次本来就在调),不多一个扇出。
-- 有了它,场所口径才有一个和全市场口径同式子的数:场所日成交 × 10% 参与率 × 5 天 ÷ 权重。
alter table public.venue_depth_snapshots
  add column if not exists day_ntl_vlm_usd   double precision,
  add column if not exists open_interest_usd double precision;
