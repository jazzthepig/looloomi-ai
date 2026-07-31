#!/usr/bin/env bash
# verify_post_p0_fix.sh — post-deploy validation for the S-92 connection-leak fix
#
# Covers the two lessons written into REFUTATION_LEDGER.md by this commit:
#   Lesson #68 : a health check that cannot fail is not a health check
#                (it manufactures false reassurance)
#   Lesson #69 : a client-side timeout without a matching server-side timeout
#                is not a timeout — it is a connection leak with a reassuring
#                log line
#
# Three checks:
#   [1] GET /health                              — exercises Lesson #68
#   [2] GET /api/v1/cis/universe?limit=1         — exercises bounded single-flight lock
#   [3] 5× repeated GET /api/v1/cis/universe     — exercises Lesson #69 implicitly
#                                                  (no hang under repeated load)
#
# Lane: scripts/ (Seth/Austin). Run on Mac after Mac-side commit + push +
# Supabase project restart + SQL apply (see handoff post-commit ①②③).
# Does NOT touch Supabase itself — only the public Railway surface.

set -u

BASE="${BASE:-https://web-production-0cdf76.up.railway.app}"
CURL_TIMEOUT="${CURL_TIMEOUT:-10}"
LATENCY_BUDGET_S="${LATENCY_BUDGET_S:-5}"
CALLS="${CALLS:-5}"

# colors (auto-disabled if stdout is not a TTY)
if [ -t 1 ]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  YELLOW='\033[0;33m'
  NC='\033[0m'
else
  GREEN='' RED='' YELLOW='' NC=''
fi

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

ok()    { printf "${GREEN}PASS${NC}  %s\n" "$1"; PASS_COUNT=$((PASS_COUNT+1)); }
warn()  { printf "${YELLOW}WARN${NC}  %s\n" "$1"; WARN_COUNT=$((WARN_COUNT+1)); }
fail()  { printf "${RED}FAIL${NC}  %s\n" "$1"; FAIL_COUNT=$((FAIL_COUNT+1)); }

require_tools() {
  local missing=0
  for tool in curl jq bc; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "missing required tool: $tool" >&2
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || { echo "install missing tools and retry" >&2; exit 2; }
}

# gt "1.234" "5.0" → "1" if 1.234 > 5.0 else "0"
gt() { [ "$(echo "$1 > $2" | bc)" = "1" ]; }

# fetch URL → echoes "<status>\n<time_s>\n<body>"; empty status means curl errored
# Two-curl pattern: one for status+time metadata (-w), one writes body to tmpfile.
# Avoids parsing pitfalls of "single line with embedded meta markers".
http_get() {
  local url="$1" tmpfile meta status time_s body
  tmpfile=$(mktemp -t vpf.XXXXXX) || return 1
  meta=$(curl -sm"$CURL_TIMEOUT" -o "$tmpfile" -w '%{http_code}|%{time_total}' "$url" 2>&1) || {
    rm -f "$tmpfile"; return 1
  }
  status=${meta%%|*}
  time_s=${meta##*|}
  body=$(cat "$tmpfile")
  rm -f "$tmpfile"
  printf '%s\n%s\n' "$status" "$time_s"
  printf '%s' "$body"
}

# ──────────────────────────────────────────────────────────────────────────
require_tools

echo "== P0 verification (S-92 connection-leak fix) =="
echo "BASE=${BASE}"
echo "LATENCY_BUDGET_S=${LATENCY_BUDGET_S}  CALLS=${CALLS}  CURL_TIMEOUT=${CURL_TIMEOUT}s"
echo

# ── [1] /health — Lesson #68 ──────────────────────────────────────────────
echo "[1/3] GET /health — Lesson #68 (must reflect real breaker state, not hardcoded healthy)"
RAW=$(http_get "${BASE}/health") || {
  fail "curl /health failed (network down?); raw: $RAW"
  exit 1
}
STATUS=$(echo "$RAW" | sed -n '1p')
TIME_S=$(echo "$RAW" | sed -n '2p')
BODY=$(echo "$RAW" | sed -n '3,$p')
if [ "$STATUS" != "200" ]; then
  fail "/health status=${STATUS:-curl-error} (expected 200)"
else
  if ! echo "$BODY" | jq . >/dev/null 2>&1; then
    fail "/health returned non-JSON body (Lesson #68 regression: hardcoded?)"
    echo "  body (first 200 chars): $(printf '%s' "$BODY" | head -c 200)"
  else
    DL=$(echo "$BODY" | jq -r '.data_layer // empty')
    if [ -z "$DL" ] || [ "$DL" = "null" ]; then
      warn "/health 200 + JSON but .data_layer is missing — pre-fix code path?"
      echo "  body (first 200 chars): $(printf '%s' "$BODY" | head -c 200)"
    else
      BREAKER=$(echo "$BODY" | jq -r '.data_layer.breaker // empty')
      if [ -z "$BREAKER" ] || [ "$BREAKER" = "null" ]; then
        warn "/health .data_layer present but .breaker field missing — store.py landed but main.py observer did not?"
        echo "  data_layer: $DL"
      else
        # NOTE: '// empty' filters out BOTH null AND false — so we use
        # '| tostring' to coerce false/true to "false"/"true" before the
        # fallback. Otherwise an open=false system would WARN forever.
        BOPEN=$(echo "$BODY" | jq -r '.data_layer.breaker.open | tostring')
        BFAILS=$(echo "$BODY" | jq -r '.data_layer.breaker.consecutive_failures // empty')
        BTRIPS=$(echo "$BODY" | jq -r '.data_layer.breaker.lifetime_trips // empty')
        if [ "$BOPEN" = "false" ]; then
          ok "/health status=200 time=${TIME_S}s breaker.open=false consecutive_failures=${BFAILS} lifetime_trips=${BTRIPS}"
        elif [ "$BOPEN" = "true" ]; then
          warn "/health breaker.open=true consecutive_failures=${BFAILS} lifetime_trips=${BTRIPS} — Lesson #68 reports real state (good), but real state is tripped"
        else
          warn "/health breaker exists but .open field is empty/non-boolean: ${BREAKER}"
        fi
      fi
    fi
  fi
fi
echo

# ── [2] /api/v1/cis/universe?limit=1 — single-flight lock bounded ─────────
echo "[2/3] GET /api/v1/cis/universe?limit=1 — bounded single-flight lock"
RAW=$(http_get "${BASE}/api/v1/cis/universe?limit=1") || {
  fail "curl /cis/universe failed (network down?); raw: $RAW"
  exit 1
}
STATUS=$(echo "$RAW" | sed -n '1p')
TIME_S=$(echo "$RAW" | sed -n '2p')
BODY=$(echo "$RAW" | sed -n '3,$p')
if [ "$STATUS" != "200" ]; then
  fail "/cis/universe status=${STATUS:-curl-error} (expected 200)"
else
  if ! echo "$BODY" | jq . >/dev/null 2>&1; then
    fail "/cis/universe returned non-JSON body"
  else
    if echo "$BODY" | jq -e '.universe | length > 0' >/dev/null 2>&1; then
      COUNT=$(echo "$BODY" | jq -r '.universe | length')
      if gt "$TIME_S" "$LATENCY_BUDGET_S"; then
        warn "/cis/universe status=200 time=${TIME_S}s universe_size=${COUNT} — exceeds ${LATENCY_BUDGET_S}s budget; single-flight lock may still be vulnerable (P0 partial fix?)"
      else
        ok "/cis/universe status=200 time=${TIME_S}s universe_size=${COUNT}"
      fi
    else
      fail "/cis/universe 200 + JSON but .universe is empty (data layer OK but no rows?)"
    fi
  fi
fi
echo

# ── [3] 5× repeated calls — Lesson #69 (no hang under repeated load) ─────
echo "[3/3] ${CALLS}× repeated GET /api/v1/cis/universe?limit=1 — Lesson #69 (no hang under repeated load)"
TIMES=()
ERRORS=0
for i in $(seq 1 "$CALLS"); do
  RAW=$(http_get "${BASE}/api/v1/cis/universe?limit=1") || { ERRORS=$((ERRORS+1)); continue; }
  STATUS=$(echo "$RAW" | sed -n '1p')
  TIME_S=$(echo "$RAW" | sed -n '2p')
  if [ "$STATUS" = "200" ]; then
    TIMES+=("$TIME_S")
  else
    ERRORS=$((ERRORS+1))
  fi
done

if [ "$ERRORS" -gt 0 ]; then
  fail "${ERRORS}/${CALLS} repeated calls failed (curl or non-200)"
fi

if [ "${#TIMES[@]}" -gt 0 ]; then
  printf "  per-call: "
  for t in "${TIMES[@]}"; do printf "%.3fs " "$t"; done
  echo

  # stats (use bc for decimals)
  MAX=0
  SUM=0
  for t in "${TIMES[@]}"; do
    [ -z "$t" ] && continue
    if gt "$t" "$MAX"; then MAX="$t"; fi
    SUM=$(echo "$SUM + $t" | bc)
  done
  N=${#TIMES[@]}
  if [ "$N" -gt 0 ]; then
    AVG=$(echo "scale=3; $SUM / $N" | bc)
    printf "  max=%.3fs  avg=%.3fs  n=%d\n" "$MAX" "$AVG" "$N"
    if gt "$MAX" "$LATENCY_BUDGET_S"; then
      warn "max ${MAX}s exceeds ${LATENCY_BUDGET_S}s budget across ${N} calls — single-flight lock vulnerable"
    else
      ok "all ${N} calls returned within ${MAX}s (budget ${LATENCY_BUDGET_S}s)"
    fi
  fi
fi
echo

# ── Summary ──────────────────────────────────────────────────────────────
TOTAL=$((PASS_COUNT + FAIL_COUNT + WARN_COUNT))
echo "== Summary: ${PASS_COUNT} pass / ${WARN_COUNT} warn / ${FAIL_COUNT} fail (${TOTAL} checks) =="

# Hard rule for human eyes: if breaker.state = open OR errors > 0, exit non-zero
# (so this script can be chained in CI / cron / alert paths)
if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "exit=1 (one or more FAIL — investigate before treating deploy as healthy)"
  exit 1
fi
if [ "$WARN_COUNT" -gt 0 ]; then
  echo "exit=0 (no FAIL, but ${WARN_COUNT} WARN — review)"
  exit 0
fi
echo "exit=0 (clean)"
