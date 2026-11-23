# Strategy-vector sources (`docs/strategy_sources/`) — local only

**Nothing in this directory except this README is in the repository.**

The strategy vector is built by `scripts/backfill_strategies.py` from two
private sources: the experiment ledger (`./REFUTATION_LEDGER.md`) and the
experiment reports that back individual entries. This repository is public and
those sources are not (decision of 2026-10-07, restated 2026-11-23), so the
files the pipeline reads live only on the maintainers' machine and are
gitignored:

| what | live file wins | local stored copy | explicit override |
|---|---|---|---|
| ledger entries | `./REFUTATION_LEDGER.md` | `docs/strategy_sources/REFUTATION_LEDGER.snapshot.md` | `--ledger PATH` |
| measured dimensions | `./reports/**/REPORT.md` | `docs/strategy_sources/sidecars/<topic>/<date>/REPORT.md` | `--sidecar-dir PATH` (repeatable) |

A live file always wins; the stored copies are fallbacks. Lane and merge
worktrees see the same files through symlinks to the main working directory
(`scripts/setup_lane_worktrees.sh`, `scripts/seth_bot/seth_bot.py`).

## History

Between 2026-11-18 and 2026-11-23 the snapshot and five reports were committed
here (card T-056) so that a clean machine could rebuild the vector. That solved
a real problem — a clean checkout measured a stale local artefact instead of the
code — with the wrong trade: it published private research text. They were
untracked on 2026-11-23. The guards that should have stopped it
(`tests/test_private_docs_untracked.py`, `scripts/check_pr_scope.py`, the commit
bot's deny list) matched four exact file names; they now also refuse this
directory, any tracked file named after the private documents, and any tracked
text that carries the ledger's entry headings in bulk.

## Consequence on a clean machine

`python3 scripts/backfill_strategies.py --write` finds no ledger and says so.
`tests/test_strategy_vector_smoke` runs only where `_data/strategy_records.json`
exists (`scripts/preflight.sh`), i.e. on the machine that has the sources. CI
does not rebuild the vector.

## Refreshing (machine with the sources)

```bash
python3 scripts/backfill_strategies.py --export-snapshot
cp reports/<topic>/<date>/REPORT.md docs/strategy_sources/sidecars/<topic>/<date>/REPORT.md
```

Both are plain file copies; neither result is committed.
