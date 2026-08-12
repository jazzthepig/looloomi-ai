-- ============================================================================
-- C5 R77 forward episode attribution — 2026-08-12 (Seth, per §C5-SHIP-SPEC)
-- ============================================================================
-- Per §C5-SHIP-SPEC 2026-08-12:
--   Episode = VDB-similarity cluster of consecutive days. Boundary =
--   cosine_distance(vec[t], vec[t-1]) > BOUNDARY_THRESHOLD (default 0.30).
--   MIN_EPISODE_DAYS=5 (align with C2 dwell=5).
--
-- DEPENDS ON D2 push backfill (Minimax-A): the r77_fwd_5d_alpha_pct label
-- must be present per day for episode-level attribution to bind. Before D2
-- ships, episode rows can land with alpha_count=0 (verdict still computable
-- but not gate-clearing).
--
-- Two tables:
--   r77_forward_episodes       — per-episode rows for the forward 60d window
--   r77_forward_episodes_meta  — event log (episode_zero_alphas, gate_stalled,
--                                verdict_emitted)
-- ============================================================================

-- ── 1. Forward 60d episode attribution (C5 ship 2026-09-15 → Day 60 2026-11-14) ─
create table if not exists r77_forward_episodes (
  episode_id           text            primary key,        -- uuid4 from cluster_episodes
  mark_date            date            not null,           -- start_date of episode
  end_date             date            not null,
  inception_id         text            not null,           -- 'c5_episode_v1'
  n_days               int             not null,
  max_daily_distance   double precision,
  mean_daily_distance  double precision,
  regime_centroid      jsonb,                              -- 12-dim mean per-dim vector
  n_neighbors          int             default 0,          -- VDB k=20 placeholder
  episode_t_pooled     double precision,                   -- one-sample t vs 0 of r77 fwd alpha
  episode_sign         int,                                -- +1, -1, 0
  mean_daily_alpha     double precision,
  alpha_count          int             default 0,          -- r77 fwd alphas available
  void_reason          text,
  created_at           timestamptz     not null    default now()
);

create index if not exists idx_r77_forward_episodes_incarnation
    on r77_forward_episodes (inception_id, mark_date desc)
 where void_reason is null;

comment on table r77_forward_episodes is
  'C5 R77 forward episode attribution (per §C5-SHIP-SPEC 2026-08-12). Each row '
  'is one VDB-similarity cluster from the live 60d forward window. Forward '
  '60d evaluation 2026-10-08 reads this to compute episode-conditional t-stat.';

-- ── 2. C5 event log ──────────────────────────────────────────────────────────
create table if not exists r77_forward_episodes_meta (
  event_id             bigserial       primary key,
  mark_date            date            not null,
  inception_id         text            not null,
  event_type           text            not null,           -- episode_zero_alphas | gate_stalled | verdict_emitted
  n_episodes           int,
  positive_count       int,
  negative_count       int,
  pooled_t_mean        double precision,
  verdict              text,                               -- C5_EPISODES_CLEAR | C5_INSUFFICIENT_EPISODES | C5_HETEROGENEOUS_REGIME
  reason               text,
  meta                 jsonb          default '{}'::jsonb,
  created_at           timestamptz     not null    default now()
);

create index if not exists idx_r77_forward_episodes_meta_incarnation
    on r77_forward_episodes_meta (inception_id, mark_date desc);
create index if not exists idx_r77_forward_episodes_meta_event_type
    on r77_forward_episodes_meta (event_type, mark_date desc);

comment on table r77_forward_episodes_meta is
  'Event log for C5 R77 forward episode layer. Why: per S-123, fixes that '
  'do not log are fixes that get re-introduced. Records zero-alphas episodes, '
  'gate stalls, and verdict emissions.';

-- ── 3. RLS — same posture as beta_core_nav_q (anon read blocked) ────────────
alter table r77_forward_episodes      enable row level security;
alter table r77_forward_episodes_meta enable row level security;

-- ── 4. verification — run BEFORE seeding any rows ────────────────────────────
-- (a) tables exist with expected columns:
--     \d r77_forward_episodes
--     \d r77_forward_episodes_meta
--
-- (b) RLS is ON:
--     select relname, relrowsecurity from pg_class
--      where relname in ('r77_forward_episodes', 'r77_forward_episodes_meta');
--
-- (c) anon read FAILS:
--     set role anon;
--     select count(*) from r77_forward_episodes;   -- expect: permission denied
--     reset role;
--
-- 60-day gate from C5 ship day: 2026-09-15 + 60 days = 2026-11-14.