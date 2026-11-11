"""T-345 探针:把 t345_results.json 压成可核的表(不改任何数)。

用法:python3 docs/research/_t345_probe.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = json.load(open(HERE / "t345_results.json"))
C = R["cells"]

print("=== 验证 ===")
for k, v in R["validation"].items():
    if k != "exit_reason_mismatch_sample":
        print(f"  {k}: {v}")
print("  exit_mismatch_sample:", R["validation"]["exit_reason_mismatch_sample"])

print("\n=== 叠加层(t251 simulate) ===")
print("cell            n  bl_gross bl_cap bl_min bl_coin  gross_max  days>cap   ov_total   ov_cagr   ov_mdd")
for k, c in C.items():
    o = c["overlay"]
    print(f"{k:16s}{c['n_tickets_taken']:3d} {o['blocked_gross']:8d} {o['blocked_cap']:6d} "
          f"{o['blocked_min']:6d} {o['blocked_coin']:8d} {o['gross_ratio_max']:9.4f} "
          f"{o['days_above_cap']:9d} {o['total_return']:9.4%} {o['cagr']:8.4%} {o['max_dd']:8.4%}")

print("\n=== 账户层(L3 装配) ===")
print("cell            total     cagr      mdd    uw_days  uw_peak    uw_recov   uw_depth%  worst_m")
for k, c in C.items():
    a = c["account"]
    u = a["underwater"]
    print(f"{k:16s}{a['total_return']:8.4%} {a['cagr']:8.4%} {a['max_drawdown']:8.4%} "
          f"{u['days']:7d}  {str(u['peak_date']):10s} {str(u['recovered_date']):10s} "
          f"{str(u['depth_pct']):9s}  {a['worst_month_key']} {a['worst_month']:+.2%}")

print("\n=== 去掉实现 R 最大的一张(S-796) ===")
print("cell            dropped_ticket             r      n_after  total     cagr      mdd     uw_days")
for k, c in C.items():
    d = c["drop_max_r"]
    if not d:
        print(f"{k:16s} <无>")
        continue
    print(f"{k:16s} {d['symbol']:>6s} {d['signal_d']} {d['r']:+.4f} {d['n_taken_after']:5d} "
          f"{d['total_return']:8.4%} {d['cagr']:8.4%} {d['max_drawdown']:8.4%} {d['underwater']['days']:7d}")

print("\n=== 判据 ===")
print("cell             i(ii值)   ii(值/限)  iii(值/限)      iv(值/限)      pass")
for k, c in C.items():
    j = c["judgement"]
    print(f"{k:16s} {str(j['i']['ok']):5s}{j['i']['value']:5d}  {str(j['ii']['ok']):5s}"
          f"{j['ii']['value']:.4f}/{j['ii']['limit']:.4f}  {str(j['iii']['ok']):5s}"
          f"{(j['iii']['value'] if j['iii']['value'] is not None else float('nan')):.4f}/{j['iii']['limit']:.4f}"
          f"  {str(j['iv']['ok']):5s}{j['iv']['value']:.4f}/{j['iv']['limit']:.4f}  {j['pass_all']}")

print("\n=== 逐年(账户总收益) ===")
years = sorted({y for c in C.values() for y in c["yearly"]})
print("cell           " + " ".join(f"{y:>9s}" for y in years))
for k, c in C.items():
    row = " ".join(f"{(c['yearly'].get(y) if c['yearly'].get(y) is not None else float('nan')):9.2%}" for y in years)
    print(f"{k:16s}" + row)

print("\n=== f★ ===")
print(json.dumps(R["f_star"], ensure_ascii=False))
