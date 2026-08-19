#!/usr/bin/env bash
# =============================================================================
# External probe — one command, one line, exit code. (Seth, 2026-07-31)
# =============================================================================
# WHY A SCRIPT AND NOT A PROMPT.
# The first version lived inside a scheduled-task prompt. That is wrong twice
# over: (a) probe logic in a prompt is unreviewed, untestable and un-diffable —
# the same "guard nobody observes" defect this repo keeps rediscovering; and
# (b) it forced the agent to reason through five checks on every run, twelve
# times a day. Here the agent runs ONE command and relays ONE line, so the
# recurring token cost collapses to near zero and the logic lives in git where
# it can be read, changed and blamed.
#
# WHY IT EXISTS AT ALL.
# 2026-07-29 (S-92): the CIS layer was dead 10.4 h and nobody noticed, because
# every watchdog runs INSIDE the process it monitors — when the workers wedged
# on a lock, the monitors wedged with them, and /health returned a hardcoded
# "healthy" throughout. This script deliberately uses nothing but curl: no
# CometCloud MCP, no internal health verdict taken on faith. It must stay
# outside the failure domain — that is its entire value.
#
# USAGE:  bash scripts/external_probe.sh          # human
#         bash scripts/external_probe.sh --quiet  # scheduled: one line only
# EXIT :  0 all green · 1 degraded · 2 CRITICAL (security regression)
# =============================================================================
set -uo pipefail

BASE="${COMET_BASE:-https://web-production-0cdf76.up.railway.app}"
SB="${COMET_SB:-https://soupjamxlfsmgmmtoeok.supabase.co}"
ANON="${COMET_ANON:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNvdXBqYW14bGZzbWdtbXRvZW9rIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3MzMzNjUsImV4cCI6MjA4OTMwOTM2NX0.zvdKO2Obwpb3xIyt7OWzisE9B-W8hAPjOT2zO35vC4I}"

FAILS=(); CRIT=0

# ── 1. liveness + WRITE CAPABILITY ───────────────────────────────────────────
# The writes check was added 2026-08-18 (S-174) because THIS PROBE MISSED THE
# BIGGEST OUTAGE OF THE WEEK. From 08-12 to 08-17 production ran with
# APP_ROLE unset, so the S-149 role gate refused every write to Supabase:
# cis_scores, beta_core_nav and experiment_runs all stop dead on 08-12.
#
# Throughout those five days this probe returned ✅ every three hours — forty
# consecutive green readings over a total write outage — because a read-only
# deployment answers 200 on absolutely everything. `status` was "healthy",
# `data_layer.supabase` was "ok", the universe endpoint served 58 assets, and
# the Mac engine kept pushing and kept getting 200s back. Every check this
# script had was measuring the read path.
#
# **A probe that only exercises reads cannot see a system that has stopped
# writing.** Reads are what a monitor naturally does, so the blind spot is the
# default, not an oversight — which is why it needs to be named in the file.
# Same curl, same response, no extra cost: /health now carries the block.
H=$(curl -sm 15 "$BASE/health" 2>/dev/null)
HS=$(printf '%s' "$H" | python3 -c 'import sys,json
d=json.load(sys.stdin)
w=d.get("writes") or {}
# "absent" is a THIRD state, not a pass: an older deployment predating S-168 has
# no writes block, and reporting that as enabled would rebuild the exact silence
# this check exists to break.
print(d.get("status","?"),
      d.get("data_layer",{}).get("supabase","?"),
      ("yes" if w.get("enabled") is True else
       "absent" if not w else "NO"),
      (w.get("role") or "?"))' 2>/dev/null || echo "? ? ? ?")
read -r STATUS SBSTATE WRITES WROLE <<<"$HS"
[ "$STATUS" = "healthy" ] || FAILS+=("health=$STATUS")
[ "$SBSTATE" = "ok" ]     || FAILS+=("supabase=$SBSTATE")
# A read-only production is not "degraded", it is a silent data-loss outage: the
# API looks perfect while nothing is being persisted. Loud on purpose.
[ "$WRITES" = "yes" ]     || FAILS+=("WRITES=$WRITES(role=$WROLE)")

# ── 2. the endpoint that died (THE check) ────────────────────────────────────
# Retry once before failing: a probe that cries wolf gets muted, and a muted
# probe is worse than none — it manufactures assurance. Both failure modes are
# real; neither is traded away for the other.
probe_universe() {
  curl -sm 20 -o /tmp/_probe_u.json -w '%{http_code} %{time_total}' \
    "$BASE/api/v1/cis/universe?limit=2" 2>/dev/null
}
read -r UCODE UTIME <<<"$(probe_universe)"
UMS=$(python3 -c "print(int(float('${UTIME:-99}')*1000))" 2>/dev/null || echo 99999)
# Retry ONLY on hard failure (non-200 / timeout). Do NOT retry on "slow but
# succeeded": a second slow sample costs another 13 s and tells us nothing the
# first did not — the latency IS the observation. Retrying latency was making
# this probe take 33 s, i.e. the tripwire became one of the slow things.
if [ "${UCODE:-000}" != "200" ]; then
  sleep 3; read -r UCODE UTIME <<<"$(probe_universe)"
  UMS=$(python3 -c "print(int(float('${UTIME:-99}')*1000))" 2>/dev/null || echo 99999)
fi
UN=$(python3 -c 'import json;print(len(json.load(open("/tmp/_probe_u.json")).get("universe",[])))' 2>/dev/null || echo 0)
[ "${UCODE:-000}" = "200" ] || FAILS+=("universe=http:${UCODE:-timeout}")
[ "$UMS" -lt 8000 ]         || FAILS+=("universe=${UMS}ms")
[ "$UN" -gt 0 ]             || FAILS+=("universe=empty")

# ── 3. data freshness — a silently dead pipeline killed us twice before ──────
PUSH=$(curl -sm 15 "$BASE/internal/health-summary" 2>/dev/null \
  | python3 -c 'import sys,json,re
try:
    d=json.load(sys.stdin)
    for c in d.get("checks",[]):
        if c.get("name")=="mac_mini_push":
            m=re.search(r"(\d+)s",c.get("detail","")); print(int(m.group(1))//60 if m else -1); break
    else: print(-1)
except Exception: print(-1)' 2>/dev/null || echo -1)
[ "${PUSH:--1}" -ge 0 ] && [ "${PUSH}" -le 180 ] || FAILS+=("macpush=${PUSH}min")

# ── 3b. price-feed freshness — the hole this probe originally had ────────────
# Added 2026-07-31 after the in-process loop watchdog (once bounded, and once
# somebody actually read its output) reported ohlcv_daily stalled at 4 days.
# The probe checked the Mac push and called the data layer healthy, because
# "the pipeline I remembered to check is alive" is not "the data is fresh".
# Silent data-pipeline death is the failure class that already cost us twice;
# a tripwire blind to it is a tripwire with a hole shaped like the last incident.
# Source: /internal/data-freshness — one cheap cached query, built for exactly
# this. A first attempt read ohlcv_daily with the anon key (blocked by the RLS we
# ourselves added, correctly) and then fell back to /internal/loop-health, which
# coupled this fast tripwire to an 8–25 s sweep and made the probe time out. A
# tripwire that depends on a slow watchdog is not a tripwire.
OHLCV_D=$(curl -sm 15 "$BASE/internal/data-freshness" 2>/dev/null \
  | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin).get("ohlcv_daily",{})
    a=d.get("age_days"); print(int(a) if a is not None else -1)
except Exception: print(-1)' 2>/dev/null || echo -1)
[ "${OHLCV_D:--1}" -ge 0 ] && [ "${OHLCV_D}" -le 3 ] || FAILS+=("ohlcv=${OHLCV_D}d")

# ── 4+5. security regression — revoked 2026-07-30 (S-94), must STAY revoked ──
RPC=$(curl -sm 15 -o /dev/null -w '%{http_code}' -X POST -H "apikey: $ANON" \
  -H 'Content-Type: application/json' \
  -d '{"p_symbol":"__probe__","p_asset_class":"crypto","p_start_ms":1}' \
  "$SB/rest/v1/rpc/backfill_binance_ohlcv" 2>/dev/null)
case "$RPC" in 401|403) ;; *) FAILS+=("CRITICAL:anon-rpc=http:$RPC"); CRIT=1;; esac

ROWS=$(curl -sm 15 -H "apikey: $ANON" "$SB/rest/v1/cis_scores?select=id&limit=1" 2>/dev/null)
[ "$ROWS" = "[]" ] || { FAILS+=("CRITICAL:anon-read-cis_scores"); CRIT=1; }

# ── 6. the ① book's clock (2026-08-08) ───────────────────────────────────────
# The beta-core book's only product is elapsed calendar time toward the 60-day
# gate, so its failure mode is NOT WRITING — a daily loop that catches its own
# exception and sleeps 24h fails exactly that way, with a green process. Nothing
# inside the process can report on a process that stopped, or survive the deploy
# that broke it; that is what an EXTERNAL probe is for. A stall here costs
# calendar, and calendar is the one input that cannot be bought back.
CLK=$(curl -sm 15 "$BASE/internal/beta-core-clock" 2>/dev/null)
CLKINFO=$(printf '%s' "$CLK" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("marks",0), d.get("days_since_mark",-1), d.get("gate_days_remaining","?"),
          "stalled" if d.get("stalled") or d.get("started") is False else "ok")
except Exception: print(-1,-1,"?","unreadable")' 2>/dev/null || echo "-1 -1 ? unreadable")
read -r BCMARKS BCSINCE BCGATE BCSTATE <<<"$CLKINFO"
[ "$BCSTATE" = "ok" ] || FAILS+=("beta-core-clock=$BCSTATE(${BCSINCE}d since mark)")

# ── verdict ──────────────────────────────────────────────────────────────────
if [ ${#FAILS[@]} -eq 0 ]; then
  echo "✅ probe OK — universe ${UMS}ms/${UN} assets · mac push ${PUSH}min · security intact · ①book ${BCMARKS}d marked, ${BCGATE}d to gate"
  exit 0
fi
printf '%s probe FAIL — %s\n' "$([ $CRIT -eq 1 ] && echo '🔴 CRITICAL' || echo '⚠️')" "$(IFS=' · '; echo "${FAILS[*]}")"
echo "   context: universe=http:${UCODE:-?}/${UMS}ms/${UN} · health=$STATUS/$SBSTATE · macpush=${PUSH}min · anon-rpc=$RPC"
exit $([ $CRIT -eq 1 ] && echo 2 || echo 1)
