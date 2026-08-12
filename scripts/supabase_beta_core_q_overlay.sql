-- ============================================================================
-- C2 ⓠ regime override overlay — 2026-08-12 (Seth, per §C2-SHIP-SPEC)
-- ============================================================================
-- Per §C2-SHIP-SPEC §3: C2 ⓠ overlay = PARALLEL 60-day clock to the ① book.
-- The ① baseline (beta_core_nav) keeps accumulating WITHOUT reset.
-- LP compares two curves: beta_core_nav (no ⓠ) + beta_core_nav_q (with ⓠ).
--
-- ⓠ = §RETURN_HIERARCHY ⓪ OVERRIDE:凌驾 ①②③④ 四层:
--   gross_total[t] = beta_capture_gross[t] × q_override[t]
--   q_override ∈ {0.0, 0.5, 1.0, 1.3}, default 1.0
--
-- Why a NEW table (not a column on beta_core_nav):
--   1. ⓠ overlay is TEMPORARY (60-day evaluation). Adding a column would
--      permanently bloat the canonical benchmark table.
--   2. The graveyard is the asset: if ⓠ is killed, the table lives on
--      with inception_id='c2_q_killed_<reason>', so the failed overlay
--      is queryable, not erased.
--   3. Schema drift on beta_core_nav would corrupt the cand comp. Keeping
--      ⓠ in a separate table preserves the C1 baseline's stability.
--
-- ORDER OF OPERATIONS — DO NOT REORDER:
--   1. deploy this migration (apply to Supabase, Railway auto-pushes)
--   2. deploy /internal/beta-core-clock-q endpoint (separate delivery)
--   3. deploy C2 ⓠ hook on beta_core_paper.py (last; writes start here)
-- ============================================================================

-- ── 1. inception_id stamp (parallel to beta_core_nav.reinception) ─────────────
-- Frozen at migration time. NO env-var override. Per S-123: a NAV that can
-- be reset from a dashboard proves nothing.
-- 2026-09-15 = C2 ship target; 60-day clock = 2026-11-14 (per §C2-SHIP-SPEC §3).

-- ── 2. ⓠ overlay curve (mirrors beta_core_nav shape) ────────────────────────
create table if not exists beta_core_nav_q (
  mark_date           date            not null,
  inception_id        text            not null,   -- e.g. 'c2_q_v1'
  q_override          double precision not null,  -- the {0.0, 0.5, 1.0, 1.3} multiplier
  vdb_distance        double precision,           -- 12-dim VDB match distance (NaN → baseline)
  enter_q_zero_thr    double precision,           -- ENTER threshold at this mark
  exit_q_zero_thr     double precision,           -- EXIT threshold (enter - hysteresis_gap)
  baseline_gross      double precision,           -- gross from ① book (pre-ⓠ)
  gross_total         double precision,           -- = baseline_gross × q_override
  nav                 double precision not null,  -- compounded from previous
  benchmark_nav       double precision not null,  -- ① baseline NAV (copied, not re-computed)
  daily_return        double precision,           -- nav[t] / nav[t-1] - 1
  excess_return       double precision,           -- daily_return - beta_core_nav.daily_return
  void_reason         text,                       -- graveyard marker
  note                text,
  primary key (mark_date, inception_id)
);

create index if not exists idx_beta_core_nav_q_incarnation
    on beta_core_nav_q (inception_id, mark_date desc)
 where void_reason is null;

comment on table beta_core_nav_q is
  'C2 ⓠ regime override overlay (per §C2-SHIP-SPEC 2026-08-12). PARALLEL 60-day '
  'clock to the ① benchmark. LP compares beta_core_nav (no ⓠ) vs beta_core_nav_q '
  '(with ⓠ). Default q_override=1.0 means no behavioral difference from baseline. '
  'VDB failure → q_override=1.0 (NEVER 0.0 per §C2-SHIP-SPEC §4). '
  'Frozen on archival: keep void_reason so the killed overlay is queryable.';

-- ── 3. ⓠ event log (graveyard for failures / hysteresis extensions / fixes) ───
create table if not exists beta_core_nav_q_meta (
  event_id            bigserial       primary key,
  mark_date           date            not null,
  inception_id        text            not null,
  event_type          text            not null,   -- vdb_failure | dwell_extension | q_override_fix | hysteresis_widened
  q_override          double precision,           -- the value at event time
  vdb_distance        double precision,           -- VDB distance at event time (NaN ok)
  reason              text,                       -- human-readable explanation
  meta                jsonb          default '{}'::jsonb,
  created_at          timestamptz     not null    default now()
);

create index if not exists idx_beta_core_nav_q_meta_incarnation
    on beta_core_nav_q_meta (inception_id, mark_date desc);
create index if not exists idx_beta_core_nav_q_meta_event_type
    on beta_core_nav_q_meta (event_type, mark_date desc);

comment on table beta_core_nav_q_meta is
  'Event log for C2 ⓠ overlay. Every vdb_failure, dwell_extension, q_override_fix '
  'records a row. WHY: per S-123 lesson, a fix that does not log its existence is a '
  'fix that the next agent re-introduces. FreezE events are recorded, not hidden.';

-- ── 4. RLS — same posture as beta_core_nav (anon read blocked, service_role write) ──
-- DO NOT apply blanket SELECT to anon. cis_scores was world-readable and unflagged
-- (Lesson #71). Default posture: deny anon select on this new table too.
alter table beta_core_nav_q  enable row level security;
alter table beta_core_nav_q_meta enable row level security;

-- Service_role writes (no explicit policy — service_role bypasses RLS by default).
-- Authenticated reads limited to owner/service_role; anon blocked.

-- ── 5. verification — run BEFORE seeding any rows ────────────────────────────
-- (a) tables exist with the expected columns:
--     \d beta_core_nav_q
--     \d beta_core_nav_q_meta
--
-- (b) RLS is ON:
--     select relname, relrowsecurity from pg_class
--      where relname in ('beta_core_nav_q', 'beta_core_nav_q_meta');
--     expect relrowsecurity = true for both
--
-- (c) anon read FAILS (per I1 + Lesson #71):
--     set role anon;
--     select count(*) from beta_core_nav_q;    -- expect: permission denied
--     reset role;
--
-- (d) service_role reads:
--     select count(*) from beta_core_nav_q;    -- expect: 0 (no rows yet)
--
-- ── 6. Mac-side: do NOT clear Redis ──────────────────────────────────────────
-- ⓠ overlay has its own state key (to be added in beta_core_paper.py ⓠ hook).
-- Clearing the ① baseline state key would corrupt the live 60-day clock.
-- Per the §C1-SHIP-SPEC §5 (`beta_core_nav` baseline does NOT reset on ⓠ overlay).
--
-- 60-day gate from the first C2 ⓠ ship day: 2026-09-15 + 60 days = 2026-11-14.
