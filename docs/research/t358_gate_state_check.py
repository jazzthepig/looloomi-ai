#!/usr/bin/env python3
"""T-358 补 ③/情景命题的自检:闸门线(SMA200)与面板状态(state_daily)。

只读、不入库。查:
 1) ohlcv_daily(BTC, binance_hist) 的日收盘 → 自算 SMA200 → 核 2026-11-10 的闸门线
    与当日收盘;并数近 30 个日历日闸门开的天数;
 2) state_daily(entity=panel)的 mom_200 / breadth_above_ma50 / regime 的最近值。

用法: python3 docs/research/t358_gate_state_check.py
产物: docs/research/t358_gate_state_check.json
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t358_gate_state_check.json")


def get(table: str, params: dict) -> list[dict]:
    q = urllib.parse.urlencode(params, safe=".,()")
    req = urllib.request.Request(f"{URL}/rest/v1/{table}?{q}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def main() -> int:
    out: dict = {}

    # ── 1) BTC 日线 → SMA200 ─────────────────────────────────────────────
    start = (date(2026, 11, 12) - timedelta(days=320)).isoformat()
    rows = get("ohlcv_daily", {
        "select": "trade_date,close,source", "symbol": "eq.BTC", "source": "eq.binance_hist",
        "trade_date": f"gte.{start}", "order": "trade_date.asc", "limit": "1000",
    })
    closes = [(str(r["trade_date"])[:10], float(r["close"])) for r in rows if r.get("close") is not None]
    closes.sort()
    out["btc_rows"] = len(closes)
    out["btc_first"] = closes[0][0] if closes else None
    out["btc_last"] = closes[-1] if closes else None

    def sma200_on(d: str) -> float | None:
        w = [c for dd, c in closes if dd <= d]
        if len(w) < 200:
            return None
        return round(sum(w[-200:]) / 200.0, 3)

    smas = {d: sma200_on(d) for d, _ in closes}
    out["sma200_last"] = smas.get(closes[-1][0]) if closes else None
    out["close_last"] = closes[-1][1] if closes else None
    out["sma200_2026_11_10"] = smas.get("2026-11-10")
    out["close_2026_11_10"] = next((c for d, c in closes if d == "2026-11-10"), None)
    out["close_2026_11_11"] = next((c for d, c in closes if d == "2026-11-11"), None)
    out["close_2026_11_12"] = next((c for d, c in closes if d == "2026-11-12"), None)

    # 闸门 = close > 自身 SMA200;数近 30 个日历日开的天数
    gate_tail = []
    for d, c in closes[-30:]:
        s = smas.get(d)
        gate_tail.append({"d": d, "close": c, "sma200": s, "gate_open": bool(s and c > s)})
    out["gate_last30"] = gate_tail
    out["gate_open_days_in_last30"] = sum(1 for g in gate_tail if g["gate_open"])
    out["gate_window"] = [gate_tail[0]["d"], gate_tail[-1]["d"]] if gate_tail else None
    out["gate_tail_last6"] = gate_tail[-6:]
    out["gate_closed_days_in_last30"] = [g["d"] for g in gate_tail if not g["gate_open"]]

    # ── 2) state_daily(entity=panel) ─────────────────────────────────────
    srows = get("state_daily", {
        "select": "d,feature,value", "entity": "eq.panel",
        "feature": "in.(mom_200,breadth_above_ma50,regime)",
        "d": f"gte.2026-10-20", "order": "d.asc,feature.asc", "limit": "1000",
    })
    by_d: dict[str, dict] = {}
    for r in srows:
        by_d.setdefault(str(r["d"])[:10], {})[str(r["feature"])] = r.get("value")
    out["state_days"] = len(by_d)
    out["state_tail"] = [{"d": d, **v} for d, v in sorted(by_d.items())[-6:]]

    # 面板上到底有哪些 feature(找 regime 的真名)
    frows = get("state_daily", {
        "select": "d,feature,value", "entity": "eq.panel",
        "d": f"gte.2026-11-05", "order": "d.asc,feature.asc", "limit": "1000",
    })
    feats: dict[str, dict] = {}
    for r in frows:
        feats.setdefault(str(r["feature"]), {})[str(r["d"])[:10]] = r.get("value")
    out["panel_features"] = sorted(feats.keys())
    reg_like = {k: v for k, v in feats.items() if "regime" in k.lower() or "state" in k.lower()}
    out["panel_regime_like"] = {k: dict(sorted(v.items())[-3:]) for k, v in reg_like.items()}

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "gate_last30"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
