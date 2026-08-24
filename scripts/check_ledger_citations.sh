#!/usr/bin/env bash
# Every S-number cited in code must exist as a ledger heading (S-206).
#
# WHY. Jazz, 2026-08-24:「你发生错误的时候没有和我们项目资料进行核实,然后就自己
# 主观臆断了。」This script is the smallest checkable instance of that complaint.
#
# Measured the same day: nine S-numbers — S-197 through S-205 — were cited as
# authority in production code and in preflight's own stage banners, and NOT ONE
# of them existed in REFUTATION_LEDGER.md. `hyperliquid_collector.py` says "see
# S-204"; there was no S-204. preflight printed "✓ pod aggregator guards
# (S-197)"; there was no S-197. CLAUDE.md rule #7 says claim the heading BEFORE
# writing the body. Nine bodies, zero headings.
#
# The failure is not bookkeeping. A citation is a promise that the reasoning was
# written down somewhere a future reader can audit it. Nine dangling citations
# means nine decisions whose justification exists only in a docstring written by
# the same author, in the same hour, with no independent record — which is the
# exact shape of "assert, then treat the assertion as verified".
#
# A grep cannot check whether a diagnosis is correct. It CAN check whether the
# diagnosis was ever written to the place we agreed diagnoses live. That is a
# narrow property, and it is the one that failed nine times.
set -uo pipefail

cd "$(dirname "$0")/.."
LEDGER="REFUTATION_LEDGER.md"

[[ -f "$LEDGER" ]] || { echo "  ✗ $LEDGER not found — cannot verify citations"; exit 1; }

# Headings only. `## S-186 / S-187 — ...` claims BOTH numbers, so scan the whole
# heading line rather than anchoring one number to one line.
CLAIMED=$(grep -E '^#{2,3} .*S-[0-9]+' "$LEDGER" | grep -oE 'S-[0-9]+' | sort -u)

# Citations in code. Excludes build artefacts and vendored trees — a vendored
# licence file matching `S-201` is not a citation of ours (measured: it does).
CITED=$(grep -rhoE '\bS-[0-9]+\b' src/ scripts/ tests/ docs/ 2>/dev/null \
          --include='*.py' --include='*.sh' --include='*.sql' --include='*.md' \
          --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=node_modules \
          --exclude='check_ledger_citations.sh' \
        | sort -u)

DANGLING=$(comm -13 <(echo "$CLAIMED") <(echo "$CITED"))

# ── The pre-existing debt, frozen ────────────────────────────────────────────
# 30 numbers were already dangling when this check was written. Backfilling them
# from memory is the very error being fixed — I would be reconstructing a
# diagnosis I no longer have the evidence for, and it would read identically to
# one I did verify. So they are FROZEN, listed by number, and the baseline may
# only SHRINK: writing the real entry removes the line. A number not in the
# baseline fails immediately, so the debt cannot grow while it is being paid.
BASELINE="scripts/ledger_citation_baseline.txt"
if [[ -f "$BASELINE" ]]; then
  FROZEN=$(grep -oE '^S-[0-9]+' "$BASELINE" | sort -u)
  # A baseline line whose entry now EXISTS is stale — force its removal, or the
  # file becomes the permanent amnesty that every such list turns into.
  STALE=$(comm -12 <(echo "$FROZEN") <(echo "$CLAIMED"))
  if [[ -n "$STALE" ]]; then
    echo "  ✗ $BASELINE still lists numbers that now HAVE entries — delete these lines:"
    echo "$STALE" | sed 's/^/      /'
    exit 1
  fi
  DANGLING=$(comm -13 <(echo "$FROZEN") <(echo "$DANGLING"))
fi

if [[ -n "$DANGLING" ]]; then
  n=$(echo "$DANGLING" | wc -l | tr -d ' ')
  echo "  ✗ $n S-number(s) cited in code with NO ledger entry:"
  for s in $DANGLING; do
    where=$(grep -rlE "\b$s\b" src/ scripts/ tests/ docs/ 2>/dev/null \
              --include='*.py' --include='*.sh' --include='*.sql' --include='*.md' \
              --exclude-dir=__pycache__ --exclude-dir=.venv \
              --exclude='check_ledger_citations.sh' | head -2 | tr '\n' ' ')
    echo "      $s  ← $where"
  done
  echo "  Rule #7: claim the heading in $LEDGER BEFORE writing the body."
  exit 1
fi

echo "  ✓ every cited S-number has a ledger entry ($(echo "$CITED" | wc -l | tr -d ' ') citations)"
