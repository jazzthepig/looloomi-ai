"""一行提交一个探索仓的机会(T-074 / S-522)。在 Mac 上跑,token 从环境变量读,不进命令行历史:

    python3 scripts/submit_idea.py TRUMP "链上早期介入;代币化 / 上所后短周期动量转负即退出并做空;出圈即错" --chain solana --horizon days

需要环境变量 INTERNAL_TOKEN;API 默认 https://web-production-0cdf76.up.railway.app(可用 COMETCLOUD_API 覆盖)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument("thesis")
    ap.add_argument("--chain")
    ap.add_argument("--contract")
    ap.add_argument("--source")
    ap.add_argument("--horizon", default="days", choices=["hours", "days", "weeks", "months"])
    ap.add_argument("--by", default="jazz")
    a = ap.parse_args()
    token = os.environ.get("INTERNAL_TOKEN")
    if not token:
        print("缺 INTERNAL_TOKEN 环境变量", file=sys.stderr)
        return 2
    base = os.environ.get("COMETCLOUD_API", "https://web-production-0cdf76.up.railway.app").rstrip("/")
    body = {"asset": a.asset, "thesis": a.thesis, "chain": a.chain, "contract": a.contract, "source": a.source,
            "horizon": a.horizon, "submitted_by": a.by}
    req = urllib.request.Request(f"{base}/internal/exploration/ideas", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Internal-Token": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(json.dumps(json.loads(r.read()), ensure_ascii=False, indent=2))
            return 0
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
