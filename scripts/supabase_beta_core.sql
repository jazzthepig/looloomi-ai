-- ============================================================================
-- Layer-① Beta Core NAV — the benchmark every strategy is measured against.
-- Spec: docs/BETA_CORE_SPEC.md · Hierarchy: docs/HIGH_DIM_ONTOLOGY.md §5b
-- Seth, 2026-07-27. NOT YET APPLIED (Supabase was timing out) — Minimax applies
-- this as the first step of M-WO-A, then writes the NAV rows.
--
-- "Beat" now means beat THIS curve, never 0. Both lanes write the same shape.
-- ============================================================================
create table if not exists beta_core_nav (
  d                date not null,
  variant          text not null,   -- ew_0bps | ew_10bps | cw_0bps | cw_10bps | live_ew | live_cw
  nav              double precision not null,
  n_holdings       int,
  turnover         double precision,  -- fraction traded that day (rebalance days only)
  cost_bps_applied double precision,
  meta             jsonb default '{}'::jsonb,  -- delisted/zeroed contributors, cap breaches, notes
  primary key (d, variant)
);
create index if not exists beta_core_nav_variant_idx on beta_core_nav (variant, d);

comment on table beta_core_nav is
  'Layer-1 beta core NAV per docs/BETA_CORE_SPEC.md — long-only, fully invested, PIT-eligible panel. '
  'THE benchmark: every sleeve reports total_return vs the cw_10bps variant, then excess. '
  'Delisted/zeroed assets MUST be carried at -100%, never silently dropped (meta records them).';

-- ── Central risk allocator audit trail (docs/RISK_ALLOCATOR_SPEC.md §9) ──────
-- NOT YET APPLIED (Supabase timing out 2026-07-27) — apply together with the table above.
create table if not exists risk_allocations (
  d                 date not null,
  pod_id            text not null,
  risk_share        double precision,   -- share of the portfolio VOL budget (not capital)
  capital_pct       double precision,   -- = risk_share / vol_i, normalized
  vol_used          double precision,   -- rolling 90d realized vol (PIT)
  conviction        double precision,   -- evidence-grade factor (§2)
  capacity_f        double precision,
  diversification_f double precision,
  exposure_cap      double precision,   -- from layer-0 regime override
  trigger           text,               -- monthly | dd_ladder | regime_switch | corr_breach | capacity
  prev_share        double precision,
  meta              jsonb default '{}'::jsonb,
  primary key (d, pod_id)
);
create index if not exists risk_allocations_pod_idx on risk_allocations (pod_id, d);

comment on table risk_allocations is
  'Central risk allocator audit trail. Every reallocation records its INPUTS (conviction/capacity/'
  'diversification/vol) and trigger — no discretionary override without a traceable input change.';
