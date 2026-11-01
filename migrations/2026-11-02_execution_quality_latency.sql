-- 2026-11-02 · 执行质量加三段延迟(src/data/execution/exec_quality.py「延迟」):收盘 → 决策(分)、决策 → 回报(秒)、交易所往返(秒)。
-- 中位数;诊断列,不进 forward_anchor_daily 的 payload(anchor.DROP)。
alter table public.execution_quality_daily
  add column if not exists median_close_to_decision_min double precision,
  add column if not exists median_decision_to_fill_s    double precision,
  add column if not exists median_venue_s               double precision;
