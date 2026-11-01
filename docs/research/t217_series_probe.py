#!/usr/bin/env python3
"""T-217 只读:探测 /api/v1/portfolio/series 能读到哪些表 + 每表字段。只读。"""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
SCRATCH = str(Path(__file__).resolve().parent)

TABLES = [
    "core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
    "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
    "depth_divergence_log", "rr_matrix_daily", "core_variants_daily", "multiplier_daily",
    "portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily",
    "r_money_daily", "short_paper_money", "execution_intents", "decisions",
]


def http(url, timeout=45):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "t217"}), timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:150]


def main():
    out = {}
    for t in TABLES:
        st, body = http(BASE + "/api/v1/portfolio/series?table=" + t)
        try:
            j = json.loads(body)
        except Exception:
            j = body
        arms = j.get("arms") if isinstance(j, dict) else None
        n_arms = len(arms) if isinstance(arms, list) else -1
        first = ""
        if isinstance(arms, list) and arms:
            a0 = arms[0]
            first = "arm0=" + json.dumps(a0, ensure_ascii=False)[:180]
        out[t] = {"status": st, "keys": list(j) if isinstance(j, dict) else None,
                  "n_arms": n_arms, "sample": first}
        print(t, st, "arms=", n_arms, first[:200])
        with open(SCRATCH + "/series_probe_" + t + ".json", "w") as f:
            f.write(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))
    with open(SCRATCH + "/series_probe_index.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
