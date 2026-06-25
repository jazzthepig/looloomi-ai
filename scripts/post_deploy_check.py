#!/usr/bin/env python3
"""
External deploy/uptime watchdog — runs OUTSIDE the app (GitHub Actions), so it can
catch what the in-app heartbeat cannot: an app that is down or crash-looping (the
2026-06-14 incident, dark for 5 days, where the in-app heartbeat was also dead).

Checks the public /internal/build-state:
  1. reachable + HTTP 200
  2. (optional) deployed git_sha == expected sha  → catches a deploy that failed and
     silently rolled back to the old build (origin moved, prod didn't)
  3. last CIS push not stale  → catches the Mac→Railway pipeline going dark

Stdlib only (no pip). Exits non-zero on failure → GitHub notifies; optional Telegram.

Usage:
  python scripts/post_deploy_check.py [--expect-sha <sha>] [--max-push-age 7200] [--retries 10]
"""
import argparse, json, sys, time, urllib.request

URL = "https://looloomi.ai/internal/build-state"


def fetch():
    # cache-bust so we don't read a stale CDN copy
    # A real UA avoids WAF/Cloudflare 403s on non-browser clients.
    req = urllib.request.Request(
        f"{URL}?cb={int(time.time())}",
        headers={"Cache-Control": "no-cache",
                 "User-Agent": "looloomi-watchdog/1.0 (+github-actions)",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-sha", default="")
    ap.add_argument("--max-push-age", type=int, default=7200)   # 2h
    ap.add_argument("--retries", type=int, default=10)
    ap.add_argument("--sleep", type=int, default=30)
    a = ap.parse_args()

    last_err = None
    for attempt in range(1, a.retries + 1):
        try:
            status, bs = fetch()
            if status != 200:
                last_err = f"HTTP {status}"
            else:
                sha = (bs.get("git_sha") or "")[:7]
                exp = a.expect_sha[:7]
                push = bs.get("last_cis_push") or {}
                age = push.get("age_seconds")
                problems = []
                if exp and sha and sha != exp:
                    problems.append(f"deployed sha {sha} != expected {exp} (deploy not live / rolled back)")
                if age is not None and age > a.max_push_age:
                    problems.append(f"last CIS push stale: {int(age)}s > {a.max_push_age}s")
                if not problems:
                    print(f"OK · sha={sha} uptime={bs.get('uptime_seconds')}s "
                          f"push_age={age}s routes={bs.get('route_count')}")
                    return 0
                # sha mismatch right after deploy may just be mid-rollout → retry
                if exp and sha != exp and attempt < a.retries:
                    last_err = "; ".join(problems)
                    print(f"  attempt {attempt}: {last_err} — waiting for rollout…")
                    time.sleep(a.sleep); continue
                print("WATCHDOG FAILED: " + "; ".join(problems))
                return 1
        except Exception as e:
            last_err = str(e)
        print(f"  attempt {attempt}: unreachable ({last_err}) — retrying…")
        time.sleep(a.sleep)

    print(f"WATCHDOG FAILED: build-state unreachable after {a.retries} tries · {last_err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
