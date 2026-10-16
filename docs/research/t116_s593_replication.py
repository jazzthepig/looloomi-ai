"""T-116 S-593 independent replication. Stats via apparatus, prose-only."""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test, percentile_of  # noqa: E402

PANEL = Path("/Volumes/CometCloudAI/cometcloud-local/research/crypto_daily/panel.json")
GRID_FIRST = "2019-06-07"
GRID_LAST = "2026-09-25"
EVERY_N_WEEKS = 4
N_TOP_A = 15
N_TOP_C = 24
UNIVERSE_TOP = 50
VOL26_MIN = 0.15
VOL13_MULT = 1.5
SUPPLY13_MAX = 0.10
FALLBACK_MIN_UNIVERSE = 10

WRAPPED_STR = (
    "WBTC WETH STETH WSTETH CBBTC RETH WEETH EETH TBTC BTCB CBETH METH EZETH "
    "RSETH LBTC SOLVBTC CLBTC BUIDL USDT USDC DAI USDE SUSDE FDUSD PYUSD USDS "
    "USD1 TUSD USDD FRAX RLUSD USDTB USDF USDG BFUSD XAUT PAXG JITOSOL MSOL "
    "BNSOL JUPSOL OUSG USYC BENJI WBETH SAVAX OSETH SFRXETH FIGR_HELOC"
)
WRAPPED = set(WRAPPED_STR.split())

SEG_CUTS = ["2019-06-07", "2020-01-01", "2021-01-01", "2022-01-01",
            "2023-01-01", "2024-01-01", "2025-01-01", "2026-09-26"]


def fridays(first: str, last: str) -> list[str]:
    d = date.fromisoformat(first)
    d += timedelta(days=(4 - d.weekday()) % 7)
    out: list[str] = []
    while d.isoformat() <= last:
        out.append(d.isoformat())
        d += timedelta(days=7)
    return out


def weekly_closes(dates, closes, grid, max_gap=6):
    pts = [(dt, c) for dt, c in zip(dates, closes) if c is not None and c > 0]
    ds = [dt for dt, _ in pts]
    out = []
    for g in grid:
        i = int(np.searchsorted(ds, g, side="right")) - 1
        if i >= 0 and (date.fromisoformat(g) - date.fromisoformat(ds[i])).days <= max_gap:
            out.append(pts[i][1])
        else:
            out.append(None)
    return out


def weekly_returns_fn(wc):
    out = [None]
    for a, b in zip(wc, wc[1:]):
        if a and b and a > 0:
            out.append(b / a - 1)
        else:
            out.append(None)
    return out


def rebalance_dates(grid, first):
    i0 = grid.index(next(g for g in grid if g >= first))
    return grid[i0::4]


def stats(rets):
    r = np.asarray(rets, dtype=float)
    r = r[np.isfinite(r) & (r > -1)]
    if r.size == 0:
        return {"cum_x": float("nan"), "ann_pct": float("nan"), "max_dd_pct": float("nan")}
    nav = np.cumprod(1 + r)
    years = r.size / 13.0
    if years <= 0 or nav[-1] <= 0:
        ann = float("nan")
    else:
        ann = nav[-1] ** (1 / years) - 1
    dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"cum_x": float(nav[-1]), "ann_pct": ann * 100, "max_dd_pct": dd * 100}


def build_arms(j, grid, wc, wmc, wr, units, rng, e_drop_count):
    snap = {s: (wmc[s][j] if wmc[s][j] is not None and wmc[s][j] > 0 else 0.0)
            for s in wmc if wmc[s][j] is not None and wmc[s][j] > 0}
    syms_nonbtc = [s for s in snap if s.upper() not in WRAPPED and s != "BTC"]
    ranked = sorted(syms_nonbtc, key=lambda s: -snap[s])
    a_top15 = ranked[:N_TOP_A]
    arm_A = {s: 1.0 / N_TOP_A for s in a_top15}

    cand = ranked[:UNIVERSE_TOP]
    ok = []
    for s in cand:
        rs = [x for x in wr[s][max(0, j - 25): j + 1] if x is not None and x > -1]
        if len(rs) < 13:
            continue
        v = float(np.std(np.log1p(rs), ddof=1) * math.sqrt(52))
        if v >= VOL26_MIN:
            ok.append(s)
    universe_for_B = ok if len(ok) >= FALLBACK_MIN_UNIVERSE else []

    v13, s13 = {}, {}
    for s in universe_for_B:
        rs = [x for x in wr[s][max(0, j - 12): j + 1] if x is not None and x > -1]
        if len(rs) >= 13:
            v13[s] = float(np.std(np.log1p(rs), ddof=1) * math.sqrt(52))
        u_now = units[s][j] if units[s][j] is not None and units[s][j] > 0 else None
        u_prev = units[s][j - 13] if j >= 13 and units[s][j - 13] is not None and units[s][j - 13] > 0 else None
        if u_now is not None and u_prev is not None:
            s13[s] = u_now / u_prev - 1
    thr = float(np.median(list(v13.values()))) * VOL13_MULT if v13 else float("nan")

    keep = [s for s in a_top15 if v13.get(s) is not None and v13[s] <= thr
            and s13.get(s) is not None and s13[s] <= SUPPLY13_MAX]
    if not keep:
        arm_B = dict(arm_A)
        n_b = len(a_top15)
    else:
        arm_B = {s: 1.0 / len(keep) for s in keep}
        n_b = len(keep)

    all_syms = [s for s in snap if s.upper() not in WRAPPED]
    all_ranked = sorted(all_syms, key=lambda s: -snap[s])
    c_top = all_ranked[:N_TOP_C]
    cw = {s: snap[s] for s in c_top}
    sw = sum(cw.values())
    arm_C = {s: cw[s] / sw for s in c_top} if sw > 0 else {s: 1.0 / len(c_top) for s in c_top}
    arm_D = {"BTC": 1.0}

    arms = {"A": arm_A, "B": arm_B, "C": arm_C, "D": arm_D}

    if e_drop_count is not None and 0 < e_drop_count < len(a_top15):
        drop = list(rng.choice(a_top15, size=e_drop_count, replace=False))
        keep2 = [s for s in a_top15 if s not in drop]
        arms["E"] = {s: 1.0 / len(keep2) for s in keep2} if keep2 else dict(arm_A)
    else:
        arms["E"] = dict(arm_A)
    return arms, n_b


def period_return(arm, j, wc, j_next):
    r_total = 0.0
    w_total = 0.0
    for k in arm:
        p0 = wc[k][j] if wc[k][j] is not None and wc[k][j] > 0 else None
        p1 = wc[k][j_next] if wc[k][j_next] is not None and wc[k][j_next] > 0 else None
        if p0 is None or p1 is None:
            continue
        r = p1 / p0 - 1
        r_total += arm[k] * r
        w_total += arm[k]
    return (float(r_total / w_total) if w_total > 0 else 0.0), 0.0


def main():
    p = json.loads(PANEL.read_text())
    grid = fridays(GRID_FIRST, GRID_LAST)
    print(f"grid={len(grid)} {grid[0]}..{grid[-1]}")

    keep = [s for s in p["price"] if s.upper() not in WRAPPED]
    print(f"syms={len(keep)} (incl BTC)")

    wc, wmc, wr, units = {}, {}, {}, {}
    for s in keep:
        wc[s] = weekly_closes(p["dates"], p["price"][s], grid)
        wmc[s] = weekly_closes(p["dates"], p["mcap"][s], grid)
        wr[s] = weekly_returns_fn(wc[s])
        u = []
        for pp, mm in zip(wc[s], wmc[s]):
            u.append(mm / pp if pp and mm and pp > 0 else None)
        units[s] = u

    reb = rebalance_dates(grid, GRID_FIRST)
    print(f"rebal_dates={len(reb)} {reb[0]}..{reb[-1]}")

    reb_idx = []
    for r0 in reb:
        j0 = grid.index(r0)
        j1 = j0 + 4
        if j1 >= len(grid):
            break
        reb_idx.append((j0, j1, r0))
    print(f"completed_periods={len(reb_idx)}")

    rng = np.random.default_rng(20261016)
    rets = {"A": [], "B": [], "C": [], "D": []}
    weeks, b_n = [], []
    for j0, j1, d0 in reb_idx:
        arms, n_b = build_arms(j0, grid, wc, wmc, wr, units, rng, None)
        b_n.append(n_b)
        weeks.append(d0)
        for a in rets:
            r, _ = period_return(arms[a], j0, wc, j1)
            rets[a].append(r)

    summary = {a: stats(rets[a]) for a in rets}
    summary["b_avg_n"] = float(np.mean(b_n))
    summary["n_periods"] = len(reb_idx)

    seg_pairs = [(SEG_CUTS[i], SEG_CUTS[i + 1]) for i in range(len(SEG_CUTS) - 1)]
    seg = {a: {} for a in rets}
    for a in rets:
        for lo, hi in seg_pairs:
            mask = [lo <= w < hi for w in weeks]
            sub = [rv for rv, m in zip(rets[a], mask) if m]
            seg[a][f"{lo[:4]}->{hi[:4]}"] = stats(sub)

    ab_b_a = ab_test(rets["A"], rets["B"], mean_block=3, days_per_year=13)
    ab_b_c = ab_test(rets["C"], rets["B"], mean_block=3, days_per_year=13)
    ab_b_d = ab_test(rets["D"], rets["B"], mean_block=3, days_per_year=13)

    rng_e = np.random.default_rng(42)
    e_log = []
    for _ in range(1000):
        rs = []
        for j0, j1, d0 in reb_idx:
            arms_b, n_b = build_arms(j0, grid, wc, wmc, wr, units, rng_e, n_b)
            r, _ = period_return(arms_b["E"], j0, wc, j1)
            rs.append(r)
        e_log.append(float(np.log1p(np.array(rs)).sum()))

    b_log = float(np.log1p(np.array(rets["B"])).sum())
    b_pct = percentile_of(b_log, e_log)

    out = {
        "summary": summary,
        "ab_B_vs_A": ab_b_a,
        "ab_B_vs_C": ab_b_c,
        "ab_B_vs_D": ab_b_d,
        "E": {
            "b_pct_in_e": b_pct,
            "b_log_actual": b_log,
            "e_log_mean": float(np.mean(e_log)),
            "e_log_p50": float(np.median(e_log)),
            "e_log_p95": float(np.quantile(e_log, 0.95)),
            "e_log_min": float(np.min(e_log)),
            "e_log_max": float(np.max(e_log)),
        },
        "segment": seg,
    }
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False, default=float))