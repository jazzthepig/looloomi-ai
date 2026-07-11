-- experiment_runs — Qlib-style run memory (positive-results twin of REFUTATION_LEDGER.md)
-- One row per backtest / sleeve / signal / portfolio / audit run. Written by
-- src/research/validation/experiment_recorder.py. See reports/LOOP_VS_OSS_2026-07-10.md.

create table if not exists experiment_runs (
    run_id            text primary key,
    ts                timestamptz not null default now(),
    kind              text not null,          -- backtest | sleeve | signal | portfolio | audit
    hypothesis        text not null,          -- what we tested (one sentence)
    universe          text,                   -- e.g. "24 majors" / "SwingOverlayV7"
    verdict           text not null,          -- certified | candidate | null | refuted | false_alarm | exploratory
    -- metrics
    sharpe            double precision,
    ic                double precision,
    dsr               double precision,
    corr_to_book      double precision,
    max_dd_pct        double precision,
    total_return_pct  double precision,
    n_obs             integer,
    -- provenance
    cost_bps          double precision,
    "window"          text,           -- quoted: `window` is a reserved word in Postgres
    params            jsonb default '{}'::jsonb,
    notes             text default '',
    ledger_ref        text                    -- e.g. "R7" when also in REFUTATION_LEDGER.md
);

create index if not exists idx_experiment_runs_verdict on experiment_runs (verdict);
create index if not exists idx_experiment_runs_kind    on experiment_runs (kind);
create index if not exists idx_experiment_runs_dsr     on experiment_runs (dsr desc);

-- The capital shortlist: certified runs clearing the DSR bar.
--   select hypothesis, universe, sharpe, dsr from experiment_runs
--   where verdict = 'certified' and dsr >= 0.95 order by dsr desc;
