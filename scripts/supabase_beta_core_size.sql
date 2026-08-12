-- ============================================================================
-- C3 conviction-size 2D table — 2026-08-12 (Seth, per §C3-SHIP-SPEC)
-- ============================================================================
-- Per §C3-SHIP-SPEC 2026-08-12:
--   size[t] = lookup_2d(regime_band, signal_band) × q_override[t]
--   size[t] ∈ [0, 1.3] (clipped)
--
-- DEPENDS ON C2: q_override comes from the C2 ⓠ layer. Without C2 the size
-- hook degrades to q_override=1.0 (size = table lookup only).
--
-- Two tables:
--   beta_core_nav_size       — the size-adjusted NAV curve (parallel to ①)
--   beta_core_nav_size_meta  — event log (size_lookup_failure, drift_audit, cell_flip)
-- ============================================================================

-- ── 1. ⓠ size-adjusted curve (mirrors beta_core_nav shape) ─────────────────
create table if not exists beta_core_nav_size (
  mark_date           date            not null,
  inception_id        text            not null,   -- 'c3_size_v1'
  regime_band         int             not null,   -- 1..5 (VDB distance quantile)
  signal_band         int             not null,   -- 1..5 (signal strength quantile)
  raw_table_size      double precision not null,  -- pre-clip from 2D table
  q_override          double precision not null,  -- from C2 ⓠ layer
  size_final          double precision not null,  -- clipped to [0, 1.3]
  clipped             boolean         not null,   -- True if clip engaged
  signal_strength     double precision,           -- 0.5 × R62 + 0.5 × VDB
  vdb_distance        double precision,           -- raw VDB distance
  nav                 double precision not null,  -- ① x size[t] NAV
  benchmark_nav       double precision not null,  -- ① baseline NAV (hold-the-panel)
  daily_return        double precision,           -- nav[t] / nav[t-1] - 1
  excess_return       double precision,           -- daily_return - beta_core_nav.daily_return
  void_reason         text,
  note                text,
  primary key (mark_date, inception_id)
);

create index if not exists idx_beta_core_nav_size_incarnation
    on beta_core_nav_size (inception_id, mark_date desc)
 where void_reason is null;

comment on table beta_core_nav_size is
  'C3 conviction-size 2D table (per §C3-SHIP-SPEC 2026-08-12). PARALLEL 60-day '
  'clock. size[t] = 2D_table[regime_band, signal_band] × q_override, clipped [0, 1.3]. '
  'LP compares ① (no size) vs C3 (size-banded). C3 depends on C2 q_override; '
  'without C2 live, q_override defaults to 1.0 (table-only effect).';

-- ── 2. ⓠ size event log (drift audit / cell flip / size_lookup_failure) ─────
create table if not exists beta_core_nav_size_meta (
  event_id            bigserial       primary key,
  mark_date           date            not null,
  inception_id        text            not null,
  event_type          text            not null,   -- size_lookup_failure | drift_audit | cell_flip | table_dead_zone
  regime_band         int,
  signal_band         int,
  size_final          double precision,
  drift_pct           double precision,           -- for drift_audit events
  flips_in_window     int,                        -- for cell_flip events
  reason              text,
  meta                jsonb          default '{}'::jsonb,
  created_at          timestamptz     not null    default now()
);

create index if not exists idx_beta_core_nav_size_meta_incarnation
    on beta_core_nav_size_meta (inception_id, mark_date desc);
create index if not exists idx_beta_core_nav_size_meta_event_type
    on beta_core_nav_size_meta (event_type, mark_date desc);

comment on table beta_core_nav_size_meta is
  'Event log for C3 size layer. Day 30 drift_audit, Day 45 cell_flip, and '
  'size_lookup_failure events are recorded. WHY: per S-123, fixes that '
  'do not log are fixes that get re-introduced.';

-- ── 3. RLS — same posture as beta_core_nav_q (anon read blocked) ────────────
alter table beta_core_nav_size      enable row level security;
alter table beta_core_nav_size_meta enable row level security;

-- ── 4. verification — run BEFORE seeding any rows ────────────────────────────
-- (a) tables exist with expected columns:
--     \d beta_core_nav_size
--     \d beta_core_nav_size_meta
--
-- (b) RLS is ON:
--     select relname, relrowsecurity from pg_class
--      where relname in ('beta_core_nav_size', 'beta_core_nav_size_meta');
--
-- (c) anon read FAILS:
--     set role anon;
--     select count(*) from beta_core_nav_size;   -- expect: permission denied
--     reset role;
--
-- 60-day gate from C3 ship day: 2026-09-10 + 60 days = 2026-11-09.
