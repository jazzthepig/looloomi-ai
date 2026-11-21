#!/usr/bin/env python3
"""T-422 独立复核(lane-a 交叉复核提出的那三个基准的分解)。

只读:/Volumes/CometCloudAI/cometcloud-local/research/t422/ab_rows.json(lane-b 的 A/B 产物)
不自跑 A/B(不重跑实验),只把**已经落盘的那一份**按三个基准拆开重算:

    A − B  = 兜底效应(同一环境下开/关兜底)   ← 卡上问的是这个
    pub − A = 环境效应(重跑本身 vs 已发布档)
    pub − B = 净值(lane-b 报告的头条)

用法:python3 docs/research/t422_seth_verify.py [path/to/ab_rows.json]
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

DEFAULT = Path("/Volumes/CometCloudAI/cometcloud-local/research/t422/ab_rows.json")
CRYPTO_CLASSES = {"L1", "L2", "DeFi", "Memecoin", "Gaming", "AI", "RWA", "Infrastructure"}


def _band(row: dict, tag: str) -> str:
    """档位(分位带):优先用产物里的 pctband_*,否则用分位数分箱(0.2 一档)。"""
    v = row.get(f"pctband_{tag}")
    if v is not None:
        return str(v)
    p = row.get(f"{tag}_pct")
    if p is None:
        return ""
    return str(min(4, int(float(p) * 5)))


def _grade(row: dict, tag: str) -> str:
    return str(row.get(f"{tag}_grade") or "")


def _score(row: dict, tag: str) -> float:
    for key in (f"{tag}_score", f"{tag}_raw"):
        v = row.get(key)
        if v is not None:
            return float(v)
    return float("nan")


def _summarize(rows: list[dict], lo: str, hi: str) -> dict:
    ds = [_score(r, lo) - _score(r, hi) for r in rows]
    ds = [d for d in ds if d == d]  # 去掉 NaN
    grade_ch = sum(1 for r in rows if _grade(r, lo) != _grade(r, hi))
    band_ch = sum(1 for r in rows if _band(r, lo) != _band(r, hi))
    return {
        "n": len(rows),
        "d_mean": round(statistics.fmean(ds), 4) if ds else None,
        "d_median": round(statistics.median(ds), 4) if ds else None,
        "d_min": round(min(ds), 4) if ds else None,
        "d_max": round(max(ds), 4) if ds else None,
        "grade_changed": grade_ch,
        "band_changed": band_ch,
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    rows = json.loads(path.read_text())
    crypto = [r for r in rows if r.get("asset_class") in CRYPTO_CLASSES]
    tradfi = [r for r in rows if r.get("asset_class") not in CRYPTO_CLASSES]
    print(f"source: {path}  total={len(rows)}  crypto={len(crypto)}  tradfi={len(tradfi)}")
    print()
    for name, group in (("CRYPTO", crypto), ("TRADFI", tradfi)):
        print(f"── {name} (n={len(group)}) ──")
        for lo, hi, label in (("A", "B", "A−B  兜底效应(同环境)"),
                              ("pub", "A", "pub−A 环境效应(重跑本身)"),
                              ("pub", "B", "pub−B 净值(报告头条)")):
            s = _summarize(group, lo, hi)
            print(f"  {label:28s} Δscore mean={s['d_mean']} median={s['d_median']} "
                  f"[{s['d_min']}, {s['d_max']}]  等级变={s['grade_changed']}/{s['n']}  "
                  f"档位变={s['band_changed']}/{s['n']}")
        print()
    # 噪声底:TradFi 上兜底 provably 不碰 ⇒ pub−A 的变化纯环境
    tradfi_env = _summarize(tradfi, "pub", "A")
    crypto_fb = _summarize(crypto, "A", "B")
    print("── 判读用的两个数 ──")
    print(f"  档位噪声底(TradFi pub−A)      = {tradfi_env['band_changed']}/{tradfi_env['n']} "
          f"(兜底不碰 TradFi ⇒ 这全是环境噪声)")
    print(f"  档位效应(加密 A−B)            = {crypto_fb['band_changed']}/{crypto_fb['n']}")
    print(f"  ⇒ 档位效应 {'低于' if crypto_fb['band_changed'] < tradfi_env['band_changed'] else '不低于'}"
          f"噪声底 ⇒ 档位这把尺子{'不可用' if crypto_fb['band_changed'] < tradfi_env['band_changed'] else '勉强可用'}")

    # 五支柱逐条差(A−B,加密)—— 差到底出在哪一维
    pillars = ["f", "m", "o", "s", "a"]
    print()
    print("── 五支柱差(加密 A−B,B 值 − A 值 = 兜底相对 CG 的变化)──")
    for p in pillars:
        ds = []
        for r in crypto:
            pa, pb = r.get("A_pillars") or {}, r.get("B_pillars") or {}
            if p in pa and p in pb:
                ds.append(float(pb[p]) - float(pa[p]))
        if ds:
            print(f"  pillar {p.upper()}: Δmean={statistics.fmean(ds):+8.4f}  "
                  f"median={statistics.median(ds):+8.4f}  min={min(ds):+8.4f}  max={max(ds):+8.4f}")
    # 成交额比(A 路径的 volume ÷ B 路径的 volume)—— 口径差有多大
    ratios = []
    for r in crypto:
        va, vb = r.get("A_volume"), r.get("B_volume")
        if va and vb and float(vb) != 0:
            ratios.append((float(va) / float(vb), r.get("symbol")))
    if ratios:
        ratios.sort()
        vals = [x[0] for x in ratios]
        print()
        print("── 成交额比(A_volume ÷ B_volume,同一天同一口径的对照)──")
        print(f"  n={len(vals)} min={min(vals):.2f}× median={statistics.median(vals):.2f}× max={max(vals):.2f}×")
        print("  最低三个: " + ", ".join(f"{s} {v:.2f}×" for v, s in ratios[:3]))
        print("  最高三个: " + ", ".join(f"{s} {v:.2f}×" for v, s in ratios[-3:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
