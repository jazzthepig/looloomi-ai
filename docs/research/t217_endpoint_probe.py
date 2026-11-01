#!/usr/bin/env python3
"""T-217 只读:批量探测公开端点,找能读受限前向表/活账户/心跳的路径。"""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
SCRATCH = str(Path(__file__).resolve().parent)

EPS = [
    "/internal/executor/book-of-truth?mode=live",
    "/internal/executor/book-of-truth?mode=live&detail=true",
    "/internal/allocation/latest",
    "/internal/research/book-navs",
    "/internal/books/scorecard",
    "/api/v1/proof/books",
    "/api/v1/proof/anchors",
    "/api/v1/signals/nav-monitor",
    "/api/v1/admin/data-landing",
    "/internal/risk-meter-history",
    "/internal/build-state",
    "/api/v1/trading/portfolio",
    "/api/v1/portfolio/books",
]


def http(url, timeout=45):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "t217"}), timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def main():
    for ep in EPS:
        st, body = http(BASE + ep)
        fn = SCRATCH + "/ep2_" + ep.replace("/", "_").replace("?", "_").replace("&", "_") + ".json"
        with open(fn, "w") as f:
            f.write(body)
        print("=" * 4, ep, st, len(body))
        print(body[:700].replace("\n", " ")[:700])


if __name__ == "__main__":
    main()
