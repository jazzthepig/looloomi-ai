-- ============================================================================
-- M-WO-D2 — risk_meter_history() (H4 unlock)
-- Seth+Minimax, 2026-08-02. Per MINIMAX_SYNC §P0-CIS-UNIVERSE work order:
--   The risk meter has code (src/data/market/risk_meter.py::build_risk_meter)
--   and NO persisted output, so it cannot enter any backtest. Persist daily.
--
-- D2: one row per day. band (low/elevated/high) + score (0..1) + components
--     jsonb (top_risk_contributors + interpretation). The Risk Meter is the
--     judgment→behavior link in ARCHITECTURE 大象无形; without this table,
--     there is no way to know whether the haircuts WERE applied historically.
-- ============================================================================

create table if not exists risk_meter_history (
  d           date          primary key,
  regime      text,
  band        text          not null check (band in ('low', 'elevated', 'high')),
  score       numeric(5,3) not null check (score >= 0 and score <= 1),
  long_gross  numeric(8,4),
  interpretation text,
  components  jsonb,        -- top_risk_contributors + any future per-symbol breakdown
  computed_at timestamptz   default now()
);

create index if not exists risk_meter_history_d_idx
  on risk_meter_history (d desc);

create index if not exists risk_meter_history_band_d_idx
  on risk_meter_history (band, d desc);

comment on table risk_meter_history is
  'M-WO-D2 daily Risk Meter snapshot. band = low/elevated/high (the three '
  'states of the 0..1 needle); score = weighted out-of-circle fragility of '
  'the long book. components jsonb carries the top 5 risk contributors from '
  'src/data/market/risk_meter.py::portfolio_risk_meter so the backtest can '
  'attribute the haircut to specific symbols.';

-- ── Idempotent daily upsert ──────────────────────────────────────────────────
-- Mac T1 calls this once per day after build_risk_meter() runs on the live
-- universe snapshot. The whole-meter result is one row, so a single RPC.
create or replace function upsert_risk_meter_history(
  p_d              date,
  p_regime         text,
  p_band           text,
  p_score          numeric,
  p_long_gross     numeric,
  p_interpretation text,
  p_components     jsonb
)
returns int
language plpgsql
as $$
declare
  v_count int;
begin
  if p_band not in ('low', 'elevated', 'high') then
    raise exception 'risk_meter band must be low/elevated/high, got %', p_band;
  end if;
  if p_score < 0 or p_score > 1 then
    raise exception 'risk_meter score must be 0..1, got %', p_score;
  end if;

  insert into risk_meter_history
    (d, regime, band, score, long_gross, interpretation, components)
  values
    (p_d, p_regime, p_band, p_score, p_long_gross, p_interpretation, p_components)
  on conflict (d) do update set
    regime         = excluded.regime,
    band           = excluded.band,
    score          = excluded.score,
    long_gross     = excluded.long_gross,
    interpretation = excluded.interpretation,
    components     = excluded.components,
    computed_at    = now();

  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

comment on function upsert_risk_meter_history is
  'M-WO-D2: idempotent daily upsert. Called by Mac T1 once per day. Returns '
  'affected row count (always 1 unless an unrelated bug fires).';

-- ── Convenience view: high-band days (the tradeable signal) ──────────────────
-- Days when the long book was crowded. For a backtest that asks "what would
-- have happened if I had followed the meter" — this is the entry-side filter.
create or replace view risk_meter_history_high_days as
select d, regime, score, long_gross, interpretation, components
  from risk_meter_history
  where band = 'high'
  order by d desc;

comment on view risk_meter_history_high_days is
  'M-WO-D2: high-band days. A backtest that respects the meter skips opens '
  '(or applies the HAIRCUT) on these days; the regime/regime_alignment context '
  'in components is what tells us whether the high band was regime-correct '
  '(risk-off) or regime-unusual (risk-on with crowded longs — the actual '
  'fragility signal).';

-- ── Verification queries ─────────────────────────────────────────────────────
-- 1. Band distribution since start:
--    select band, count(*) from risk_meter_history group by band;
-- 2. Latest reading:
--    select * from risk_meter_history order by d desc limit 1;
-- 3. "How often was the meter right?" (compare band at t vs forward 5d return):
--    select band, count(*), avg((components->>'avg_fwd_5d')::numeric)
--      from risk_meter_history
--      where d < current_date - interval '5 days'
--      group by band;
