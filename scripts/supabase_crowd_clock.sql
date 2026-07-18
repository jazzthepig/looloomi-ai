-- Crowd Clock log — the falsifiability substrate for the behavioral-phase primitive.
-- One row per UTC day: the phase we read + the inputs that produced it. A later resolver
-- matches each day's phase to the FORWARD 30d asymmetry (does "capitulation" actually
-- precede up-moves? does "euphoria" precede drawdowns?) → REFUTE or keep (Refutation Ledger R22).
-- Until that resolver runs and passes, the Crowd Clock carries NO predictive claim.

create table if not exists crowd_clock_log (
  id                            bigint generated always as identity primary key,
  date                          date not null,
  phase                         text not null,   -- capitulation|accumulation|markup|euphoria|distribution
  confidence                    numeric,          -- separation from the runner-up phase
  angle                         numeric,
  in_fng                        numeric,
  in_btc_chg_30d                numeric,
  in_btc_chg_7d                 numeric,
  in_mean_positioning_pressure  numeric,
  in_cis_dispersion_std         numeric,
  created_at                    timestamptz default now(),
  unique (date)
);

create index if not exists crowd_clock_log_date_idx on crowd_clock_log (date desc);

-- RLS: internal write via service key only; keep anon out (SEC hardening). Public read optional.
alter table crowd_clock_log enable row level security;
