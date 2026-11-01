#!/usr/bin/env python3
"""T-217 ②: the per-loop liveness rows for the six loops the card names.

/internal/data-freshness exposes liveness.per_loop (beat state: last_ok_at,
last_run_at, n_consecutive_failures/refusals, reason) — the CURRENT state per
loop. loop_attempt's 7-day error rows are RLS-blocked for the publishable key,
so this is what the card's §② can be answered with directly; the rest is
mechanism read from source.
"""
from __future__ import annotations

import json
from pathlib import Path
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
LOOPS = ["_forward_record_loop", "_forward_return_backfill_loop", "_feature_arms_loop",
         "_core_variants_loop", "_public_cache_warm_loop", "_tokenization_tilt_loop",
         "executor_host", "_live_account_loop", "_allocation_loop", "_core_pit_loop"]


def main() -> None:
    d = json.loads(urllib.request.urlopen(f"{BASE}/internal/data-freshness", timeout=90).read().decode())
    liv = d.get("liveness") or {}
    per = liv.get("per_loop") or {}
    rows = {r.get("loop"): r for r in ((d.get("loops") or {}).get("rows") or [])}
    print("liveness overall:", {k: v for k, v in liv.items() if k not in ("per_loop",)})
    print()
    for lp in LOOPS:
        a = per.get(lp)
        b = rows.get(lp)
        print(f"--- {lp}")
        print("    per_loop:", json.dumps(a, ensure_ascii=False)[:400] if a else "ABSENT")
        print("    rows    :", json.dumps(b, ensure_ascii=False)[:400] if b else "ABSENT")
    with open(str(Path(__file__).resolve().parent / "t217_loop_liveness.json"), "w") as f:
        json.dump({"liveness": liv, "rows": rows}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
