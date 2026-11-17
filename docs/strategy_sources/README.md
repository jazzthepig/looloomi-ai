# Committed strategy-vector sources (`docs/strategy_sources/`)

**Why this directory exists.** The strategy vector used to be rebuildable only on
Jazz's Mac. `scripts/backfill_strategies.py` mined R-entries out of
`./REFUTATION_LEDGER.md` (never committed) and filled their measured
dimensions out of `./reports/**/REPORT.md` (committed nowhere — `.gitignore`
line 47). On a clean machine both are simply not there, so
`tests/test_strategy_vector_smoke` measured *this machine's stale artefact*
instead of the code: S-500 found 14 red checks on a clean box while the
07-21 `_data/strategy_records.json` on the Mac still passed. That is card
**T-056**.

**The rule.** Every source the pipeline mines is committed here, and the
precedence is fixed:

| what | live file wins | committed copy | explicit override |
|---|---|---|---|
| R-entries | `./REFUTATION_LEDGER.md` | `REFUTATION_LEDGER.snapshot.md` | `--ledger PATH` |
| § experiment blocks | `./MINIMAX_SYNC.md` | `docs/MINIMAX_SYNC.md` | `--sync PATH` |
| measured dimensions | `./reports/**/REPORT.md` | `sidecars/<topic>/<date>/REPORT.md` | `--sidecar-dir PATH` (repeatable) |

A live file always wins. The committed copies are **fallbacks, not the source
of truth** — the ledger grows every day, and the snapshot is a dated artefact
that says so in its own header. Nothing here is a rewrite of a source: the
snapshot copies the R-entry sections verbatim, and each sidecar is a
byte-for-byte copy of the report that was mined.

## What is in here

- `REFUTATION_LEDGER.snapshot.md` — every level-2 section of the live ledger
  whose header starts with `## R`, copied verbatim and cut at the next level-2
  heading (the prose between R-entries — S-### lessons, aggregate lesson
  lists, the §LEDGER-RECONCILIATION-MAP — is not part of any R-entry body).
  93 sections, ~400 KB.
- `sidecars/<topic>/<date>/REPORT.md` — the mined experiment reports. Each
  record that carries a `sidecar:` tag points at the file that filled its
  dimensions; the tag path is relative to the repo root.

## Refreshing

```bash
# re-cut the ledger snapshot from the live ledger (Mac side)
python3 scripts/backfill_strategies.py --export-snapshot

# commit a new sidecar (copy the report, keep the reports/<topic>/<date> shape)
cp reports/<topic>/<date>/REPORT.md docs/strategy_sources/sidecars/<topic>/<date>/REPORT.md
```

Both steps are ordinary file copies — no numbers are retyped, so the committed
store cannot drift away from the report it claims to hold.

## Reading the result

`python3 scripts/backfill_strategies.py --write` prints which source file each
source came from, so a run says outright whether it read the live ledger or the
snapshot:

```
  source files:
    REFUTATION_LEDGER            docs/strategy_sources/REFUTATION_LEDGER.snapshot.md
    MINIMAX_SYNC                 docs/MINIMAX_SYNC.md
```

If a record's dimensions look thin, the sidecar for that R-entry is probably
not committed yet — the record still carries whatever the ledger body said,
and nothing is invented to fill the gap.
