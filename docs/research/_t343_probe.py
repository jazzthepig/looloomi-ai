#!/usr/bin/env python3
"""T-343 探针 #5:我的装配 vs 内核 `flex_alloc.dynamic_mix_nav` 在 **L0** 上的逐日差。

三份序列,同一批腿、同一窗口、同一常数权重(30/30/20):
  A = 生产核 `src/data/universe/flex_alloc.dynamic_mix_nav`(11-11 起带 cash_ret / overlay_ret)
  B = 我自己 11-10 之前写的核副本 `docs/research/t320_flex_alloc_core.py`
      (与 A 只差两处:BOUNDS、cash_ret/overlay_ret 两个新参数)
  C = 已交付 `t343_results.json → arms.L0` 的数(重跑对照,不是抄)

判:A 与 B 逐日差应 ≈ 0(差在 BOUNDS 与两个新参数,而 L0 既不触发 clip 也不给 cash/overlay);
   A 的重跑应逐位复现 C 的 total_return / cagr / max_drawdown。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import t343_blind as T343                     # noqa: E402  我的装配(腿 / 窗口 / 权重)
import t320_flex_alloc_core as T320           # noqa: E402  我的核副本(独立于 11-11 的改动)
from src.data.universe import flex_alloc as FA  # noqa: E402  生产核

OUT = HERE / "t343_kernel_diff.json"

print("[load] 腿(与 t343_blind 同一套)…", flush=True)
data = T343.load_legs()
cnav = data["core_nav"]
cnav = cnav[cnav.index >= pd.Timestamp(T343.LEG_FROM)]
cleg_x1v, _ = T343.crypto_leg(cnav, data["funding"])
end = pd.Timestamp(T343.WINDOW_END)
legs = {"crypto": cleg_x1v, "equity": data["equity"], "gold": data["gold"]}
legs = {k: v[v.index <= end] for k, v in legs.items()}
df = pd.concat(legs, axis=1).dropna().sort_index()
common = df.index
nav_start = common[T343.WARM]
print(f"[window] 共同日 {len(common)}  记账起点 {nav_start.date()}", flush=True)


def fn_t25(hist, d):
    """L0:常数 T25(30/30/20)—— 与 t343_blind.main() 的 fn_t25 一字相同。"""
    return dict(FA.BASE_T25)


nav_a, log_a = FA.dynamic_mix_nav(legs, fn_t25, reb=T343.REB, cost=T343.COST, start=nav_start)
nav_b, log_b = T320.dynamic_mix_nav(legs, fn_t25, reb=T343.REB, cost=T343.COST, start=nav_start)

assert list(nav_a.index) == list(nav_b.index), "两条 NAV 的日期轴不同"
d = (nav_a - nav_b)
absd = d.abs()
rel = (absd / nav_a).abs()

ma = T343.metrics(nav_a)
mb = T343.metrics(nav_b)
delivered = json.load(open(HERE / "t343_results.json"))["arms"]["L0"]["metrics"]

# BOUNDS 不可能碰到 L0:常数 30/30/20 落在三段区间内
clipped = FA.clip_to_budget(dict(FA.BASE_T25))

worst = absd.idxmax() if len(absd) else None
out = {
    "card": "T-343",
    "purpose": "装配(A=生产核) vs 我的核副本(B) 在 L0 上的逐日差;以及 A 重跑是否复现已交付 C",
    "window": [nav_start.date().isoformat(), end.date().isoformat()],
    "n_common_days": int(len(common)),
    "n_nav_days": int(len(nav_a)),
    "A_prod_vs_B_copy": {
        "max_abs_diff_nav": float(absd.max()),
        "max_rel_diff": float(rel.max()),
        "n_days_nonzero": int((absd > 0).sum()),
        "worst_day": worst.date().isoformat() if worst is not None else None,
        "identical": bool((absd == 0).all()),
    },
    "A_total_return": ma["total_return"], "B_total_return": mb["total_return"],
    "A_cagr": ma["cagr"], "B_cagr": mb["cagr"],
    "A_max_drawdown": ma["max_drawdown"], "B_max_drawdown": mb["max_drawdown"],
    "n_rebalances": [len(log_a), len(log_b)],
    "rebalance_log_equal": bool(log_a == log_b),
    "C_delivered_L0": {k: delivered[k] for k in ("total_return", "cagr", "max_drawdown", "n_days")},
    "A_reproduces_C": {
        "total_return_diff": round(float(ma["total_return"] - delivered["total_return"]), 12),
        "cagr_diff": round(float(ma["cagr"] - delivered["cagr"]), 12),
        "max_drawdown_diff": round(float(ma["max_drawdown"] - delivered["max_drawdown"]), 12),
        "n_days_match": bool(ma["n_days"] == delivered["n_days"]),
    },
    "bounds_cannot_touch_L0": {
        "BASE_T25": FA.BASE_T25,
        "BOUNDS": {k: list(v) for k, v in FA.BOUNDS.items()},
        "clip_to_budget(BASE_T25)": clipped,
        "unchanged": bool(clipped == {k: float(v) for k, v in FA.BASE_T25.items()}),
    },
}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
print(f"[ok] 写出 {OUT}")
