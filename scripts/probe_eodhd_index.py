#!/usr/bin/env python3
"""EODHD 指数/现货/收益率后缀的可用性探针 (S-275) —— **Mac 侧跑**。

沙箱里没有 `MAC_ENV`,所以 key 读不到,这个探针只能在 Mac 上跑。

## 它回答什么

我们现有代码**每一处都硬编码 `.US`**(ETF/美股交易所),从没用过
`.INDX` / `.FOREX` / `.GBOND` / `.COMM`。所以 S-275 的 `CANONICAL` 表
目前是**一份意图,不是一份已验证的清单**。

在把任何东西落库之前,先确认:我们的档位下这些后缀到底返不返数据、
返多深、字段叫什么。

## 它不做什么

**不写库、不改任何东西。** 只打印形状。
`--json` 可把结果存成文件,供后续落库任务读。

用法:
    python3 scripts/probe_eodhd_index.py
    python3 scripts/probe_eodhd_index.py --json /tmp/eodhd_index_probe.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FROM, TO = "2015-01-01", "2026-09-02"

#: 与 `src/data/market/asset_index.py:CANONICAL` 对齐。
#: 每行是 (symbol, 大类, 为什么要它)。
TARGETS = [
    ("XAUUSD.FOREX", "gold", "伦敦金现货 —— 替掉 GLD(费率泄漏 40bp/年)"),
    ("XAGUSD.FOREX", "silver", "替掉 SLV"),
    ("USDJPY.FOREX", "usdjpy",
     "**S-273 的结论指向这里** —— 套息那一层在 FX,不在 FXY"),
    ("US10Y.GBOND", "ust_10y", "收益率,不是 TLT 价格"),
    ("US30Y.GBOND", "ust_30y", ""),
    ("US2Y.GBOND", "ust_2y", "2s10s 曲线需要它"),
    ("JP10Y.GBOND", "jgb_10y", "**套息的另一条腿** —— S-273 采购单第二项"),
    ("GSPC.INDX", "us_equity", "S&P 价格指数 —— 替掉 SPY"),
    ("SP500TR.INDX", "us_equity_tr", "总回报版 —— 长窗口唯一正确的口径"),
    ("DJI.INDX", "us_equity_dj", ""),
    ("VIX.INDX", "vix", ""),
    ("BRENT.COMM", "brent", "替掉 USO(展期泄漏 3000bp/年,16 天就废)"),
    ("CL.COMM", "wti", ""),
    # 备选后缀 —— 上面那些若不可用,试这些
    ("XAUUSD.CC", "gold", "备选后缀"),
    ("GOLD.COMM", "gold", "备选后缀"),
    ("USDJPY.CC", "usdjpy", "备选后缀"),
]


def _key() -> str:
    from dotenv import dotenv_values
    from src.research.paths import MAC_ENV
    return (dotenv_values(MAC_ENV) if MAC_ENV.exists() else {}).get(
        "EODHD_API_KEY", "")


def probe_one(sym: str, key: str) -> dict:
    url = (f"https://eodhd.com/api/eod/{sym}?from={FROM}&to={TO}"
           f"&period=d&api_token={key}&fmt=json")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"symbol": sym, "ok": False, "verdict": f"http_{e.code}",
                "detail": str(e)[:80]}
    except Exception as e:                                     # noqa: BLE001
        return {"symbol": sym, "ok": False, "verdict": type(e).__name__,
                "detail": str(e)[:80]}
    if not isinstance(body, list) or not body:
        return {"symbol": sym, "ok": False, "verdict": "empty",
                "detail": "返回空 —— 后缀可能不在我们的档位内"}
    first, last = body[0], body[-1]
    return {
        "symbol": sym, "ok": True, "verdict": "ok",
        "n": len(body), "first": first.get("date"), "last": last.get("date"),
        "last_close": last.get("adjusted_close", last.get("close")),
        # **字段名要记下来** —— .GBOND 的 close 是收益率(%),不是价格,
        # 而这件事只有看了实际返回才知道。
        "fields": sorted(last.keys()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="out", default=None)
    args = ap.parse_args()

    key = _key()
    print(f"EODHD key: {'present' if key else 'ABSENT'}")
    if not key:
        print("  ✗ 这个探针必须在 Mac 侧跑(沙箱没有 MAC_ENV)")
        return 1

    rows = []
    for sym, asset, why in TARGETS:
        r = probe_one(sym, key)
        r["asset"], r["why"] = asset, why
        rows.append(r)
        if r["ok"]:
            print(f"  ✓ {sym:16s} {r['n']:5d} 根 · {r['first']} → {r['last']}"
                  f" · 末值 {r['last_close']}")
            print(f"      字段 {r['fields']}")
        else:
            print(f"  ✗ {sym:16s} {r['verdict']} — {r.get('detail', '')}")
        if why:
            print(f"      ↳ {why}")

    ok = [r for r in rows if r["ok"]]
    print(f"\n{len(ok)}/{len(rows)} 个后缀可用")
    print("⚠️ **可用 ≠ 可落库** —— 下一步要确认 .GBOND 的 close 是收益率(%)"
          "还是价格,因为 asset_index 把它标成 unit=rate_pct(不可做比价),"
          "而这个断言现在是推断,不是观测。")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        print(f"已写入 {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
