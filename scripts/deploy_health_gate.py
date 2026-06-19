#!/usr/bin/env python3
"""
deploy_health_gate.py — one command to answer "is prod healthy, and is my local
HEAD ahead of what's deployed?"

Probes the live CometCloud API, runs contract-integrity checks (so the bugs we
just fixed can't silently regress), and diffs the live git sha against local
HEAD to count undeployed commits.

Usage:
    python3 scripts/deploy_health_gate.py                 # check prod
    python3 scripts/deploy_health_gate.py --url https://web-production-0cdf76.up.railway.app
    python3 scripts/deploy_health_gate.py --wait 180      # wait for deploy first

Exit code 0 = all critical checks pass, 1 = at least one critical failure.
Deploy-lag (local ahead of live) is reported as a WARNING, not a failure.
Stdlib only — no dependencies — so Jazz can run it anywhere, and CI can too.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

DEFAULT_URL = "https://looloomi.ai"
EXPECTED_SCHEMA_VERSION = "1.0"
BANNED_SIGNALS = {"BUY", "SELL", "HOLD", "AVOID", "ACCUMULATE", "REDUCE", "STRONG BUY"}

G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[94m", "\033[0m"


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "deploy-health-gate"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


class Report:
    def __init__(self):
        self.rows = []
        self.critical_failed = 0
        self.warnings = 0

    def add(self, name, ok, detail="", critical=True, warn=False):
        self.rows.append((name, ok, detail, critical, warn))
        if warn:
            self.warnings += 1
        elif not ok and critical:
            self.critical_failed += 1

    def render(self):
        print(f"\n{B}── CometCloud deploy health gate ─────────────────────────{X}")
        for name, ok, detail, critical, warn in self.rows:
            if warn:
                tag = f"{Y}WARN{X}"
            elif ok:
                tag = f"{G}PASS{X}"
            else:
                tag = f"{R}FAIL{X}" if critical else f"{Y}SKIP{X}"
            print(f"  [{tag}] {name}" + (f"  — {detail}" if detail else ""))
        print(f"{B}──────────────────────────────────────────────────────────{X}")
        if self.critical_failed == 0:
            print(f"{G}RESULT: PASS{X} — {len(self.rows)} checks, {self.warnings} warning(s)\n")
        else:
            print(f"{R}RESULT: FAIL{X} — {self.critical_failed} critical failure(s), "
                  f"{self.warnings} warning(s)\n")


def check(rep, name, url, validate, critical=True, timeout=20):
    try:
        status, body = _get(url, timeout=timeout)
        if status != 200:
            rep.add(name, False, f"HTTP {status}", critical)
            return None
        ok, detail = validate(body)
        rep.add(name, ok, detail, critical)
        return body
    except urllib.error.HTTPError as e:
        rep.add(name, False, f"HTTP {e.code}", critical)
    except Exception as e:
        rep.add(name, False, f"{type(e).__name__}: {e}", critical)
    return None


def _local_head():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return None


def _commits_ahead(live_sha):
    try:
        n = subprocess.check_output(
            ["git", "rev-list", f"{live_sha}..HEAD", "--count"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return int(n)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--wait", type=int, default=0, help="seconds to wait before probing (deploy settle)")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    if args.wait:
        print(f"Waiting {args.wait}s for Railway deploy to settle...")
        time.sleep(args.wait)

    rep = Report()

    # 1. App up — use /api/v1/health (bypasses Cloudflare SPA cache; /health
    #    behind Cloudflare can return the SPA HTML instead of JSON)
    check(rep, "app health", f"{base}/api/v1/health",
          lambda b: (b.get("status") == "healthy", f"v{b.get('version')} {b.get('environment')}"))

    # 2. Contract echo alive + version matches
    check(rep, "contract schema echo", f"{base}/internal/cis-scores/schema",
          lambda b: (b.get("schema_version") == EXPECTED_SCHEMA_VERSION,
                     f"schema_version={b.get('schema_version')}"))

    # 3. CIS universe — data flowing + contract integrity (regression guards)
    def _validate_universe(b):
        uni = b.get("universe") or b.get("assets") or []
        if len(uni) < 10:
            return False, f"only {len(uni)} assets"
        if not any(a.get("cis_score") is not None for a in uni):
            return False, "no cis_score on any asset"
        # compliance: no banned buy/sell language
        bad = [a.get("symbol") for a in uni
               if str(a.get("signal", "")).upper() in BANNED_SIGNALS]
        if bad:
            return False, f"banned signal on {bad[:5]}"
        # contract regression guard: T1 assets must have O pillar populated
        t1 = [a for a in uni if str(a.get("data_tier")).upper() in ("T1", "1")]
        if t1:
            o_ok = sum(1 for a in t1
                       if (a.get("pillars") or {}).get("O") is not None or a.get("pillar_o") is not None)
            if o_ok == 0:
                return False, f"O pillar None on all {len(t1)} T1 assets (contract drift!)"
            return True, f"{len(uni)} assets, T1={len(t1)} O-pillar ok={o_ok}"
        return True, f"{len(uni)} assets (no T1 present)"
    check(rep, "cis/universe + integrity", f"{base}/api/v1/cis/universe", _validate_universe, timeout=45)

    # 4. Signal performance system alive
    check(rep, "signals/performance", f"{base}/api/v1/signals/performance",
          lambda b: (b.get("status") in ("building", "live"),
                     f"status={b.get('status')} closed={b.get('closed_signals')}"),
          critical=False)

    # 5. Build-state + last push freshness + deploy lag
    bs = check(rep, "build-state", f"{base}/internal/build-state",
               lambda b: (True, f"v{b.get('version')} sha={b.get('git_sha_short')} "
                                f"routes={b.get('route_count')}"))
    if bs:
        lp = bs.get("last_cis_push") or {}
        if lp.get("present"):
            stale = lp.get("stale")
            rep.add("last Mac Mini push fresh", not stale,
                    f"age={lp.get('age_seconds')}s assets={lp.get('asset_count')} "
                    f"drift_warns={lp.get('drift_warnings')} engine_sha={lp.get('engine_git_sha')}",
                    critical=False, warn=bool(stale))
        else:
            rep.add("last Mac Mini push fresh", False, "no push in cache", critical=False, warn=True)

        # deploy lag: local HEAD vs live sha
        live = bs.get("git_sha")
        head = _local_head()
        if live and head:
            if live == head:
                rep.add("deploy in sync", True, f"live == HEAD ({head[:8]})", critical=False)
            else:
                ahead = _commits_ahead(live)
                msg = (f"{ahead} commit(s) pending deploy (live={live[:8]} HEAD={head[:8]})"
                       if ahead is not None else
                       f"live={live[:8]} != HEAD={head[:8]}")
                rep.add("deploy in sync", False, msg, critical=False, warn=True)
        elif not live:
            rep.add("deploy in sync", False, "live git_sha unavailable (RAILWAY_GIT_COMMIT_SHA unset)",
                    critical=False, warn=True)

    rep.render()
    return 1 if rep.critical_failed else 0


if __name__ == "__main__":
    sys.exit(main())
