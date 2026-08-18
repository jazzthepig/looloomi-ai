#!/usr/bin/env bash
# §NO-DIRECT-SUPABASE step 5 — does anything still write Supabase directly?
#
# Mac-A's rule (2026-08-17, Jazz ↔ Minimax): neither lane writes Supabase
# directly. Every write goes through a Railway endpoint holding service_role.
#
# WHY THE RULE EXISTS, measured: the Mac `.env` carries the ANON key, both
# push RPCs are SECURITY INVOKER, so RLS denies the underlying tables and the
# script logs "push complete" over a write that never happened. Both targets
# were EMPTY on 2026-08-18 — `asset_embeddings_history` 0 rows,
# `risk_meter_history` 0 rows. Never landed a single row, not "stale".
#
# ── THREE-VALUED ON PURPOSE ───────────────────────────────────────────────────
# violations found     → report (or fail, see below)
# clean                → pass
# volume not mounted   → NOT CHECKED, said out loud
#
# The third state is the point. This grep targets the Mac volume, which does not
# exist in the Cowork sandbox or on CI. A guard that silently skips when it
# cannot look reports "clean" from a machine that never checked — the exact
# vacuous-pass hazard documented in S-163, and the same collapse that hid eleven
# missing tables (S-166) and a read-only production (S-168). Not-checked is not
# a pass and must never print like one.
#
# ── STILL INFO-ONLY, DELIBERATELY ─────────────────────────────────────────────
# Per §NO-DIRECT-SUPABASE the sequence is: (1) Mac sweep → (2) wrappers →
# (3) Mac switches its callers → (4) backfill → (5) THIS goes hard-fail.
# Step 2 landed 2026-08-18 (S-169). Step 3 has not. Hard-failing now would block
# every push on a violation that is expected until Minimax switches the callers,
# and a gate that fires on known-and-planned state teaches people to use --no-verify.
#
# FLIPPING IT IS ONE LINE: set STRICT=1 below, or export NO_DIRECT_SUPABASE_STRICT=1.
STRICT="${NO_DIRECT_SUPABASE_STRICT:-0}"

MAC_ROOT="${COMETCLOUD_LOCAL:-/Volumes/CometCloudAI/cometcloud-local}"

PATTERN='httpx\.(post|put|patch)\(.*supabase|httpx\.(post|put|patch)\(.*/rpc/|urllib\.request\..*supabase|requests\.(post|put|patch)\(.*supabase'

echo "── §NO-DIRECT-SUPABASE: direct-write sweep ──"

if [ ! -d "$MAC_ROOT" ]; then
    echo "  ⊘ NOT CHECKED — $MAC_ROOT is not mounted on this machine."
    echo "    This is not a pass. Run preflight on the Mac, where the volume"
    echo "    exists, for this check to mean anything."
    exit 0
fi

HITS=$(grep -rnE "$PATTERN" "$MAC_ROOT" 2>/dev/null | grep -v __pycache__ || true)

if [ -z "$HITS" ]; then
    echo "  ✓ no direct Supabase writes under $MAC_ROOT"
    exit 0
fi

N=$(printf '%s\n' "$HITS" | wc -l | tr -d ' ')
echo "  ⚠ $N direct-write call site(s) still present:"
printf '%s\n' "$HITS" | sed 's|^|      |' | head -20
echo
echo "    Route these through Railway instead — the wrappers exist:"
echo "      POST /internal/asset-vectors-history   (upsert_asset_embeddings_history)"
echo "      POST /internal/risk-meter-history      (upsert_risk_meter_history)"
echo "      POST /internal/research-intake         (experiment_runs, strategy_records)"
echo "      GET  /internal/mac-push/schema         (contract, no auth needed to read)"

if [ "$STRICT" = "1" ]; then
    echo "  🔴 STRICT mode — failing."
    exit 1
fi
echo "  (info-only until §NO-DIRECT-SUPABASE step 3 lands; then set STRICT=1)"
exit 0
