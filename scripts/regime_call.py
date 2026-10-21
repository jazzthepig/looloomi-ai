#!/usr/bin/env python3
"""Jazz ⓪ 开关 —— 在 Mac 上提交 / 查看「何时在场、在哪」的判断(src/data/execution/regime_call.py)。

    python3 scripts/regime_call.py on   --conviction 2 --battlefield HYPE,UNI --note "第二段" [--days 14]
    python3 scripts/regime_call.py off  --note "流动性在转向"
    python3 scripts/regime_call.py flat --note "全平"
    python3 scripts/regime_call.py on   --close HYPE --note "HYPE 先走"
    python3 scripts/regime_call.py status
    python3 scripts/regime_call.py brief [--top 40]     # 战场简报:HL 前 N 永续的趋势 / 第二段形态 / 资金费(筛子,不是信号)

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
        if e.code in (404, 405):
            # 未知路径会落到前端的 GET 兜底路由上 ⇒ POST 得到 405:说明线上还是没有这个接口的旧版本
            sha = "?"
            try:
                sha = json.loads(urllib.request.urlopen(api.rstrip("/") + "/internal/build-state", timeout=20).read()
                                 ).get("git_sha_short", "?")
            except Exception:                                           # noqa: BLE001
                pass
            sys.exit(f"HTTP {e.code}:线上还没有 {path}(在跑的版本 {sha})—— 等 Railway 部署到含 regime_call 的提交"
                     f"(e30ac900 或更新)再试。判断没有提交,不用重发别的。")
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:600]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Jazz ⓪ 开关")
    ap.add_argument("state", choices=["on", "off", "flat", "status", "brief"])
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--conviction", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--battlefield", default="", help="逗号分隔的 HL 永续币名,如 HYPE,UNI")
    ap.add_argument("--close", default="", help="这些币的 J 票下一轮出场")
    ap.add_argument("--note", default="", help="为什么(会进记分卡)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--api", default=os.environ.get("COMETCLOUD_API", API))
    a = ap.parse_args()
    if a.state == "brief":
        r = _call("GET", f"/internal/regime-call/brief?top={a.top}", a.api)
        b = r["breadth"]
        pct = lambda x: "—" if x is None else f"{x * 100:+.0f}%"            # noqa: E731
        print(f"{r['at'][:16]}Z · 前 {b['n']} · SMA50 之上 {pct(b['above_sma50'])} · SMA200 之上 {pct(b['above_sma200'])}"
              f" · 破 20 日高 {pct(b['breakout_20d'])} · 第二段形态 {b['second_leg_setups']} 个"
              f" · 30 日中位 {pct(b['median_ret_30d'])} · 资金费中位 {pct(b['funding_apr_median'])}/年")
        print(f"{'币':8s} {'位置':8s} {'7日':>6s} {'30日':>6s} {'90日':>6s} {'离120日高':>8s} {'第一段':>6s} {'回撤':>6s}"
              f" {'止损宽':>6s} {'资金费':>6s} {'未平仓':>8s}")
        for x in r["rows"]:
            leg = f"{x['first_leg_x']:.1f}x" if x.get("first_leg_x") else "—"
            sw = x.get("stop_width")
            stop = "—" if sw is None else f"{sw * 100:.0f}%"
            print(f"{x['coin']:8s} {x['tag']:8s} {pct(x.get('ret_7d')):>6s} {pct(x.get('ret_30d')):>6s} "
                  f"{pct(x.get('ret_90d')):>6s} {pct(x.get('dd_from_120d_high')):>8s} {leg:>6s} {pct(x.get('pullback')):>6s} "
                  f"{stop:>6s} {pct(x.get('funding_apr')):>6s} {(x.get('oi_usd') or 0) / 1e6:>7.0f}M")
        print(r.get("note", ""))
        return
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
