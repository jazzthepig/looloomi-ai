#!/usr/bin/env python3
"""Jazz ⓪ 开关 —— 在 Mac 上提交 / 查看「何时在场、在哪」的判断(src/data/execution/regime_call.py)。

    python3 scripts/regime_call.py on   --conviction 2 --battlefield HYPE,UNI --note "第二段" [--days 14]
    python3 scripts/regime_call.py off  --note "流动性在转向"
    python3 scripts/regime_call.py flat --note "全平"
    python3 scripts/regime_call.py on   --close HYPE --note "HYPE 先走"
    python3 scripts/regime_call.py status

每次提交都是一条**完整**的判断(不是增量),最新一条生效;默认 14 天到期,到期回到系统默认(on、1 档、无战场)。
提交当天的判断管第二天 00:45 UTC 那一轮。要立刻停,用一键停(POST /internal/executor/halt)。
INTERNAL_TOKEN 先读环境变量,没有再读仓库根目录 .env 里那一行;不打印。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://web-production-0cdf76.up.railway.app"


def _token() -> str:
    t = os.environ.get("INTERNAL_TOKEN", "").strip()
    if t:
        return t
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("INTERNAL_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("没有 INTERNAL_TOKEN(环境变量或仓库 .env)")


def _call(method: str, path: str, api: str, body: dict | None = None):
    req = urllib.request.Request(api.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Internal-Token": _token(), "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:600]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Jazz ⓪ 开关")
    ap.add_argument("state", choices=["on", "off", "flat", "status"])
    ap.add_argument("--conviction", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--battlefield", default="", help="逗号分隔的 HL 永续币名,如 HYPE,UNI")
    ap.add_argument("--close", default="", help="这些币的 J 票下一轮出场")
    ap.add_argument("--note", default="", help="为什么(会进记分卡)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--api", default=os.environ.get("COMETCLOUD_API", API))
    a = ap.parse_args()
    if a.state == "status":
        r = _call("GET", "/internal/regime-call", a.api)
        nxt, last = r["next_cycle"], r["last_cycle"]
        print(f"下一轮(asof {nxt['asof']}):{json.dumps(nxt['call'], ensure_ascii=False)}")
        print(f"上一轮(asof {last['asof']}):{json.dumps(last['call'], ensure_ascii=False)}")
        print(f"在持 J 票:{[(j['ticket_id'], j['status']) for j in r['j_live']]}")
        print(f"记分:{json.dumps(r['scorecard']['totals'], ensure_ascii=False)}")
        return
    body = {"state": a.state, "conviction": a.conviction, "note": a.note, "days": a.days,
            "battlefield": [c.strip() for c in a.battlefield.split(",") if c.strip()],
            "close": [c.strip() for c in a.close.split(",") if c.strip()]}
    print(json.dumps(_call("POST", "/internal/regime-call", a.api, body), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
