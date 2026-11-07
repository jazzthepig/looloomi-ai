#!/usr/bin/env python3
"""T-283 摘要打印:新旧出场逐票对照 + 出场方式分组的盈亏 + 尾部分析。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
R = json.loads((OUT / "t283_results.json").read_text())
rows = R["ticket_compare"]
old = R["old_S761_recomputed"]
new = R["new_S762_gross"]


def grp(ts):
    a = np.asarray(ts, dtype=float)
    return (f"n={a.size:3d} mean={a.mean()*100:8.2f}% med={np.median(a)*100:8.2f}% "
            f"min={a.min()*100:8.2f}% max={a.max()*100:7.2f}%")


print("=== 复算校验(旧规则 = S-761)===")
print(" matches_ref:", old["matches_ref"], old["ref_S761"])
print(" old main:", json.dumps({k: round(v, 4) if isinstance(v, float) else v
                               for k, v in old["main"].items()
                               if k in ("n", "mean_pct", "median_pct", "worst5_mean_pct",
                                        "win_rate_pct", "std_pct")}, ensure_ascii=False))
print(" old exits:", old["exit_kinds"], " new exits:", new["exit_kinds"])

print("\n=== 主口径(gross)判据 ===")
for k, v in new["criteria"].items():
    print(f"  {k}: {v}")
print("  verdict:", new["verdict"], " control:", json.dumps(new["null_control"], ensure_ascii=False))

print("\n=== 逐票对照(净盈亏 %)=old → new ===")
hdr = f"{'sym':>8} {'d':>10} {'old_kind':>13} {'old_date':>10} {'old_net':>9} | {'new_kind':>13} {'new_date':>10} {'new_net':>9} {'delta':>8} {'maxh%':>8}"
print(hdr)
for r in sorted(rows, key=lambda x: x["new_net_pct"]):
    print(f"{r['sym']:>8} {r['d']:>10} {str(r['old_exit_kind']):>13} {str(r['old_exit_date']):>10} "
          f"{r['old_net_pct']:9.2f} | {str(r['new_exit_kind']):>13} {str(r['new_exit_date']):>10} "
          f"{r['new_net_pct']:9.2f} {r['delta_net_pp']:8.2f} "
          f"{(r['max_high_pct'] if r['max_high_pct'] is not None else float('nan')):8.1f}")

print("\n=== 出场方式分组(净盈亏)===")
pairs = defaultdict(list)
for r in rows:
    if r["old_exit_kind"]:
        pairs["old_" + str(r["old_exit_kind"])].append(r["old_net_pct"] / 100)
    if r["new_exit_kind"]:
        pairs["new_" + str(r["new_exit_kind"])].append(r["new_net_pct"] / 100)
for k in sorted(pairs):
    print(f"  {k:>16}: {grp(pairs[k])}")

print("\n=== 尾部:最差 10 张票(新规则)===")
for r in sorted(rows, key=lambda x: x["new_net_pct"])[:10]:
    atr = None
    print(f"  {r['sym']:>8} d={r['d']} new {r['new_exit_kind']}@{r['new_exit_date']} "
          f"net={r['new_net_pct']:8.2f}% (old {r['old_exit_kind']}@{r['old_exit_date']} "
          f"{r['old_net_pct']:8.2f}%) tok={r['new_tok_ret_pct']:8.2f}% btc={r['new_btc_ret_pct']:7.2f}% "
          f"fund={r['new_funding_tok_pct']:7.2f}% maxh={r['max_high_pct']:7.1f}%")

print("\n=== 跳空 vs 触及(止损出场单)=new ===")
gap = touch = 0
for r in rows:
    if r["new_exit_kind"] != "stop_intraday":
        continue
    stop_px = r["entry_px"] + 2.5 * (r.get("atr_at_exit_new") or 0)
    if r["new_exit_px"] > stop_px * 1.0001:
        gap += 1
    else:
        touch += 1
print(f"  止损出场里:跳空高于止损价成交 {gap} 张 / 触及止损价成交 {touch} 张")

print("\n=== 资金费保护触发的票 ===")
for r in rows:
    if r["new_exit_kind"] in ("fund", "fund_no_next"):
        print(f"  {r['sym']} d={r['d']} new {r['new_exit_kind']}@{r['new_exit_date']} "
              f"net={r['new_net_pct']:.2f}% old {r['old_exit_kind']}@{r['old_exit_date']} "
              f"net={r['old_net_pct']:.2f}% 累计付出(gross)={r['new_fund_paid_gross_pct']:.2f}% "
              f"触发时累计={r['new_cum_paid_at_trigger_pct']:.2f}%")

print("\n=== 副项 ===")
for k, v in R["sub"].items():
    if isinstance(v, dict) and "mean_pct" in v:
        print(f"  {k:>20}: mean={v['mean_pct']:8.2f}% med={v['median_pct']:8.2f}% "
              f"worst5={v['worst5_mean_pct']:8.2f}% n={v['n_tickets']} exits={v.get('exit_kinds')}")

print("\n=== 止损距离(2.5×ATR 相对进场价)===")
dists = []
for r in rows:
    atr = r.get("atr_at_exit_new")
    if atr and r["entry_px"]:
        dists.append((r["sym"], r["d"], (2.5 * atr) / r["entry_px"] * 100, r["new_exit_kind"]))
arr = np.asarray([x[2] for x in dists])
print(f"  n={arr.size} 中位={np.median(arr):.1f}% 均值={arr.mean():.1f}% "
      f"p90={np.quantile(arr,0.9):.1f}% 最大={arr.max():.1f}%")
for thr in (30, 50, 100):
    print(f"  止损距离 > {thr}% 的票: {int((arr > thr).sum())}")
print("  最远的 8 张:", ", ".join(f"{s}({d}) {v:.0f}%" for s, d, v, k in
                                  sorted(dists, key=lambda x: -x[2])[:8]))

print("\n=== 案例:止损单的逐根路径(进场 → 出场)===")
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t282_cache")


def load_bars(sym: str, d: str) -> list[dict]:
    d0 = date.fromisoformat(d)
    lo = (d0 - timedelta(days=15)).isoformat()
    hi = (d0 + timedelta(days=400)).isoformat()
    p = CACHE / f"perp_bv_daily_{sym}_{lo}_{hi}.json"
    rows_ = json.loads(p.read_text())
    rows_.sort(key=lambda r: r["d"])
    return rows_


for sym, d in (("ONE", "2021-03-17"), ("BNX", "2022-03-31"), ("OGN", "2021-04-01")):
    bars = load_bars(sym, d)
    entry = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    idx = next((i for i, b in enumerate(bars) if b["d"] == entry), None)
    print(f" -- {sym} 事件日 {d} 进场 {entry}")
    if idx is None:
        print("    找不到进场 bar")
        continue
    trs: list[float] = []
    for j in range(max(0, idx - 1), min(len(bars), idx + 12)):
        b = bars[j]
        o, h, l, c = b.get("o"), b.get("h"), b.get("l"), b.get("c")
        pc = bars[j - 1]["c"] if j > 0 else None
        tr = max(h - l, abs(h - pc), abs(l - pc)) if pc is not None else (h - l)
        pcs = "None" if pc is None else f"{pc:.6g}"
        if j >= idx:
            trs.append(tr)
            atr = sum(trs[-min(len(trs), 14):]) / min(len(trs), 14)
            stop_px = o + 2.5 * atr
            print(f"    {b['d']} o={o:<10.6g} h={h:<10.6g} l={l:<10.6g} c={c:<10.6g} "
                  f"pc={pcs:<10} TR={tr:<10.6g} "
                  f"ATR_k={atr:<10.6g} stop=+{2.5*atr/o*100:6.1f}% of entry")
        else:
            print(f"    {b['d']} o={o:<10.6g} h={h:<10.6g} l={l:<10.6g} c={c:<10.6g} (进场前)")

