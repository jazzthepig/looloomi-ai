#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# s284_push.sh — Mac-side push for S-284 (2026-09-04 audit fixes).
# Wraps scripts/push_session.sh with today's specific paths + subject + body.
#
# Two-commit flow:
#   C1 — 11 isolated paths (H/I/J/K/O/F tests + E docs + preflight registration)
#        one: src/api/main.py is MIXED with another session's changes;
#             do NOT `git add -A` — use `git add -p` then run scripts/push_session.sh
#             with PUSH_PATHS="src/api/main.py" PUSH_SUBJECT="..." PUSH_BODY="..."
#             to push C2.
#
# Before running, ensure preflight green and dirty tree matches expectation.
#
# Usage:
#   bash scripts/s284_push.sh          # full push (C1 + C2 if main.py clean)
#   DRY_RUN=1 bash scripts/s284_push.sh # show plan, do nothing
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

DRY_RUN="${DRY_RUN:-0}"
[ "$DRY_RUN" = "1" ] && PUSH_DRY_RUN=1 || PUSH_DRY_RUN=0
export PUSH_DRY_RUN

echo "═══ S-284 push (2026-09-04) ═══"

# ── Commit 1: 11 isolated paths ─────────────────────────────────────────────
PUSH_PATHS="paper_trading/__init__.py \
paper_trading/spec_runner.py \
src/data/cis/cis_provider.py \
src/data/signals/track_record.py \
src/research/paper_books/daily_runner.py \
tests/test_track_record_measures.py \
tests/test_display_score_dp.py \
scripts/preflight.sh \
PROJECT_STATE.md \
CLAUDE.md \
REFUTATION_LEDGER.md"

PUSH_REFUSE_DIRTY="scripts/lesson_enforcement_baseline.txt \
src/api/routers/trading.py \
src/data/signals/beta_core_paper.py"

PUSH_SESSION_TAG="S-284"

PUSH_SUBJECT="fix(paper-trading): 8 audit fixes +决策 ticket (S-284)"

PUSH_BODY="H/I/J/K/O/F/B/E 落 PROJECT_STATE §IN-FLIGHT,与 OpenAPI 同事变更完全分离:

  H paper_trading/__init__.py        填 __version__ + __all__ 16 项
  I  paper_books/daily_runner.py     删 if False 死代码
  J  spec_runner.Decision.as_payload 加 verdict_kind 字段 (S-207 SKIPPED vs BLOCKED 分桶)
  K  spec_runner 退役 survivors_only_lag1_book_bookB (S-249 双名字漂移 hazard)
  O  cis_provider.display_score       DISPLAY_SCORE_DP=1 抽出常量
                                       + 新单测 tests/test_display_score_dp.py
  F  track_record.MIN_MEASURABLE      30 → 12 + why_hidden JSON
  E  PROJECT_STATE.md + CLAUDE.md      OPEN RISKS §0c 决策 ticket
                                       (A fold vs B acknowledge paper_books/)

preflight: stage 3 registered test_display_score_dp + test_track_record_measures"

export PUSH_PATHS PUSH_REFUSE_DIRTY PUSH_SESSION_TAG PUSH_SUBJECT PUSH_BODY

bash scripts/push_session.sh

# ── Commit 2: B fix on src/api/main.py (manual git add -p required) ──────
echo ""
echo "═══ Commit 2: B fix on src/api/main.py ═══"
if git diff --quiet -- src/api/main.py && git diff --cached --quiet -- src/api/main.py; then
  echo "src/api/main.py is clean — B fix already in C1 or pushed separately."
  echo "✅ S-284 push done (C1 only)."
  exit 0
fi

echo "src/api/main.py has UNSTED hunks (S-263 valuation point + my B fix)."
echo ""
echo "Manual flow required — push_session.sh refuses mixed-hunk files:"
echo "  1. git add -p src/api/main.py"
echo "     → y on hunks with 'regime_quorum_block' / 'regime_quorum' / 'B fix (2026-09-04)'"
echo "     → n on hunks with '_sleep_until_utc' / '_NAV_VALUATION_POINT_UTC' / S-263"
echo "  2. Then run:"
cat <<'EOF'
     PUSH_PATHS="src/api/main.py" \
     PUSH_REFUSE_DIRTY="scripts/lesson_enforcement_baseline.txt src/api/routers/trading.py src/data/signals/beta_core_paper.py" \
     PUSH_SESSION_TAG="S-284" \
     PUSH_SUBJECT='feat(api): expose LAST_REGIME_QUORUM on /health (S-284 B fix)' \
     PUSH_BODY='S-263 写到模块层 dict 但全 repo 0 reader —— 「不可观测即不存在」,S-244 redux。
今天把 dict 同步到 /health.data_layer.regime_quorum:
  - 空 dict = 还没读过历史(消费者须区分)
  - 有 verdict 键 = 读过了,裁决 ok/thin/COLLAPSED/frozen/no_baseline

不破坏 /health 的 I/O-free 契约(只读 in-process dict,不发任何请求)。
让 OPEN RISKS §0 的 VERIFY 命令真能交叉对照这个 endpoint。' \
     bash scripts/push_session.sh
EOF
echo ""
echo "After C2:  curl -sm15 https://web-production-0cdf76.up.railway.app/health | jq .data_layer.regime_quorum"
echo "  期望: 非空对象(若 hot reload 后还没跑过 history,可能仍是空 dict {})"