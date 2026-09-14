"""Online schema-drift check (A-28).

The OFFLINE half (`tests/test_every_written_table_exists.py`) verifies the
manifest matches what the source code does. This ONLINE half verifies the
manifest matches the LIVE database — every table the code writes to really
exists in Postgres. Together they catch the `fusion_paper_state` drift
(manifest says X exists, DB says X doesn't) that the offline test cannot.

Reads only, idempotent. Skipped (exit 0) when credentials are missing,
NOT failed — the offline stage is still authoritative, this is additive.

Auth: `X-Internal-Token` against `INTERNAL_TOKEN` env var. The Railway
deploy already has the right key. Local Mac sources `.env` at the project
root before invoking preflight. CI sets both `INTERNAL_TOKEN` (GitHub
secret) and optionally `SCHEMA_DRIFT_URL`.

Why skipped, not failed, when credentials are absent. S-163 contract says
preflight is offline; this stage is the explicit exception. A developer
without `INTERNAL_TOKEN` still gets the offline test, which is a real
signal — it just doesn't catch the "manifest says X exists, DB says X
doesn't" class. The CI run, which has both vars, catches that class.

Exit codes:
  0 — drift absent (ok=true from endpoint) OR credentials missing (skipped)
  1 — drift present (ok=false from endpoint, with missing/column_drift detail)
  2 — endpoint unreachable (network/auth error). Preflight treats 2 as
      skipped too, but distinguishes from a clean pass via stderr text.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


URL = os.environ.get(
    "SCHEMA_DRIFT_URL",
    "https://web-production-0cdf76.up.railway.app/internal/schema-drift",
)
TOKEN = os.environ.get("INTERNAL_TOKEN", "")
TIMEOUT_S = 30


def _fetch(url: str, token: str) -> dict:
    """GET the schema-drift endpoint. Returns parsed JSON or raises."""
    req = urllib.request.Request(url, headers={"X-Internal-Token": token})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def main() -> int:
    if not TOKEN:
        print("  ⓘ online schema-drift skipped "
              "(INTERNAL_TOKEN not set; offline stage authoritative)")
        return 0

    try:
        d = _fetch(URL, TOKEN)
    except urllib.error.HTTPError as e:
        # 401 / 403 → token wrong but server reachable; treat as RED, not skip
        if e.code in (401, 403):
            print(f"✗ online schema-drift auth failed (HTTP {e.code}): "
                  f"INTERNAL_TOKEN rejected", file=sys.stderr)
            return 1
        print(f"  ⓘ online schema-drift skipped "
              f"(HTTP {e.code}: {type(e).__name__})")
        return 0
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ⓘ online schema-drift skipped "
              f"({type(e).__name__}: {e})")
        return 0
    except json.JSONDecodeError as e:
        print(f"  ⓘ online schema-drift skipped "
              f"(response not JSON: {e})")
        return 0

    if not d.get("ok"):
        checked = d.get("checked", "?")
        present = d.get("present", "?")
        miss = d.get("missing") or []
        rpc_chk = d.get("rpc_checked", "?")
        rpc_pres = d.get("rpc_present", "?")
        rpc_miss = d.get("rpc_missing") or []
        cd = d.get("column_drift") or {}
        cc = d.get("column_check_unavailable") or []
        cons = d.get("consequence") or ""
        print(f"✗ online schema-drift RED — manifest disagrees with live DB:",
              file=sys.stderr)
        print(f"  tables: {present}/{checked} present", file=sys.stderr)
        if miss:
            print(f"  missing ({len(miss)}): {miss}", file=sys.stderr)
        print(f"  rpc_functions: {rpc_pres}/{rpc_chk} present", file=sys.stderr)
        if rpc_miss:
            print(f"  rpc_missing ({len(rpc_miss)}): {rpc_miss}",
                  file=sys.stderr)
        if cd:
            print(f"  column_drift ({len(cd)}): {cd}", file=sys.stderr)
        if cc:
            print(f"  column_check_unavailable: {cc}", file=sys.stderr)
        if cons:
            print(f"  consequence: {cons}", file=sys.stderr)
        return 1

    n_miss = len(d.get("missing") or [])
    n_rpc_miss = len(d.get("rpc_missing") or [])
    n_cd = sum(len(v) for v in (d.get("column_drift") or {}).values())
    print(f"✓ online schema-drift pass "
          f"(tables {d.get('present')}/{d.get('checked')}, "
          f"rpc {d.get('rpc_present')}/{d.get('rpc_checked')}, "
          f"{n_miss} missing, {n_rpc_miss} rpc_missing, "
          f"{n_cd} column_drift)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
