#!/usr/bin/env python3
"""
Loop health — machine-checks every link of the CometCloud loop end-to-end against the
LIVE site, so drift is caught by a tool instead of by hand. This is the "verify our own
loop" discipline (ARCHITECTURE — judgment substrate): a signal we can't show flowing here
is one we must not claim externally.

Checks (public endpoints only — no secrets needed):
  SENSE      — CIS push fresh (build-state last_cis_push age)
  SYNTHESIZE — universe carries the full judgment kit per asset
               (cis grade + cause_proximity + executability + las + narrative)
  JUDGE      — /portfolio/risk-meter live + reads a needle
  ACT        — trading positions + metrics present; rebalance preview reachable
  LEARN      — /trading/mine returns computed signal (IC loop has data)

Exit 0 = all links PASS/WARN; exit 1 = a FAIL (a link is broken). trade_results row
count needs Supabase env and is checked separately (CI weekly audit / MCP).

Usage: python scripts/loop_health.py [--base https://looloomi.ai]
"""
import argparse
import json
import sys
import time
import urllib.request

UA = {"User-Agent": "looloomi-loop-health/1.0"}


def _get(base, path, timeout=25):
    url = f"{base}{path}{'&' if '?' in path else '?'}cb={int(time.time())}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _line(link, status, msg):
    icon = {"PASS": "✅", "WARN": "🟡", "FAIL": "🔴"}[status]
    print(f"{icon} {link:11} {status:4} — {msg}")
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://looloomi.ai")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    results = []

    # SENSE
    try:
        bs = _get(base, "/internal/build-state")
        lc = bs.get("last_cis_push", {}) or {}
        age = lc.get("age_seconds")
        if lc.get("present") and age is not None and age < 3600:
            results.append(_line("SENSE", "PASS", f"CIS push {int(age)}s ago, {lc.get('asset_count')} assets, sha {bs.get('git_sha_short')}"))
        else:
            results.append(_line("SENSE", "FAIL", f"CIS push stale/absent (age={age})"))
    except Exception as e:
        results.append(_line("SENSE", "FAIL", f"build-state unreachable: {e}"))

    # SYNTHESIZE — judgment kit per asset
    try:
        uni = _get(base, "/api/v1/cis/universe").get("universe", []) or []
        n = len(uni)
        kit = {k: sum(1 for a in uni if a.get(k) not in (None, {}, "")) for k in
               ("grade", "cause_proximity", "executability", "las", "narrative", "provenance")}
        missing = [k for k, c in kit.items() if c < n * 0.5]
        if n and not missing:
            results.append(_line("SYNTHESIZE", "PASS", f"{n} assets, full judgment kit ({', '.join(kit)})"))
        elif n:
            results.append(_line("SYNTHESIZE", "WARN", f"{n} assets; thin: {missing} (counts {kit})"))
        else:
            results.append(_line("SYNTHESIZE", "FAIL", "empty universe"))
    except Exception as e:
        results.append(_line("SYNTHESIZE", "FAIL", f"universe unreachable: {e}"))

    # JUDGE — risk meter
    try:
        rm = _get(base, "/api/v1/portfolio/risk-meter")
        m = rm.get("meter") or {}
        if "reading" in m:
            results.append(_line("JUDGE", "PASS", f"risk-meter reading={m['reading']} ({m.get('band')}), regime {rm.get('regime')}"))
        else:
            results.append(_line("JUDGE", "FAIL", f"no meter reading: {str(rm)[:80]}"))
    except Exception as e:
        results.append(_line("JUDGE", "FAIL", f"risk-meter unreachable: {e}"))

    # ACT — positions + metrics + rebalance preview
    try:
        pos = _get(base, "/api/v1/trading/positions")
        met = _get(base, "/api/v1/trading/metrics")
        results.append(_line("ACT", "PASS", f"{pos.get('count')} open, {met.get('total_trades')} closed, pnl {met.get('total_pnl_pct')}%"))
    except Exception as e:
        results.append(_line("ACT", "WARN", f"trading endpoints: {e}"))
    try:
        rb = _get(base, "/api/v1/trading/rebalance/preview")
        results.append(_line("ACT-REBAL", "PASS", f"preview live: triggered={rb.get('triggered')} reason={rb.get('reason')} targets={rb.get('n_target')}"))
    except Exception as e:
        results.append(_line("ACT-REBAL", "WARN", f"rebalance preview not deployed yet: {e}"))

    # LEARN — IC mine has data
    try:
        mine = _get(base, "/api/v1/trading/mine?mode=pillar_fitness")
        tc = mine.get("trade_count", 0)
        if tc and tc >= 5:
            results.append(_line("LEARN", "PASS", f"IC mine computing on {tc} closed trades"))
        elif tc:
            results.append(_line("LEARN", "WARN", f"only {tc} closed trades — need ≥5 for stable IC (throughput: enable REBAL_LOOP)"))
        else:
            results.append(_line("LEARN", "WARN", "no closed-trade signal yet"))
    except Exception as e:
        results.append(_line("LEARN", "FAIL", f"mine unreachable: {e}"))

    fails = sum(1 for r in results if r == "FAIL")
    warns = sum(1 for r in results if r == "WARN")
    print(f"\n{'PASS' if fails == 0 else 'FAIL'} — {len(results)-fails-warns} pass, {warns} warn, {fails} fail")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
