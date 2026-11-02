"""T-219 step 6: M-585 EXPLORATORY run on the PUBLIC-source panel.

The pre-registered test (M-585) needs the 10 rail tickers in OUR ohlcv_daily (EODHD) —
still 0 rows as of 2026-11-02 09:2x UTC, so the pre-registered verdict stays BLANK.
This script runs the SAME mechanical pipeline on the public (Nasdaq) panel so the
machinery is exercised and a directional read exists, labelled EXPLORATORY and
UNDERPOWERED (11 months => 10 monthly observations, discovery 6 / holdout 4).

Zero distributions, block bootstrap and percentiles: src/data/evaluation/apparatus.py only.
Read-only. Writes docs/research/t219_m585_explore.json.
"""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from src.data.evaluation.apparatus import (block_permute, shuffle_within, null_distribution,
                                           percentile_of, stationary_bootstrap_index)
from t219_db import DB

RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
SEED = 20261102
N_BOOT = 2000


def spearman(x, y):
    n = len(x)
    if n < 3:
        return None, None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(list(x)), rank(list(y))
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(sum((v - mx) ** 2 for v in rx) * sum((v - my) ** 2 for v in ry))
    if den == 0:
        return None, None
    rho = num / den
    t = None
    if abs(rho) < 1:
        t = rho * math.sqrt(n - 2) / math.sqrt(1 - rho * rho)
    return rho, t


def main():
    raw = json.load(open(os.path.join(HERE, "t219_nasdaq_raw.json")))["series"]

    # --- panel inclusion rule: a name joins the window only with >=60 trading days of history ---
    all_days = sorted({d for s in RAIL for d in raw[s]})
    panel_start = None
    for d in all_days:
        if all(sum(1 for x in raw[s] if x <= d) >= 60 for s in RAIL):
            panel_start = d
            break
    days = [d for d in all_days if d >= panel_start]
    print("panel start:", panel_start, "trading days:", len(days), days[0], "->", days[-1])

    # --- equal-weight daily-rebalanced panel index (base 100) ---
    idx, prev_px = 100.0, None
    panel, qqq = {}, {}
    for d in days:
        px = {s: raw[s][d] for s in RAIL if d in raw[s]}
        if len(px) < len(RAIL):
            continue
        if prev_px is not None:
            rs = [px[s] / prev_px[s] - 1.0 for s in RAIL]
            idx *= (1.0 + sum(rs) / len(rs))
        panel[d] = idx
        if d in raw["QQQ"]:
            qqq[d] = raw["QQQ"][d]
        prev_px = px
    qqq_dates = sorted(qqq)
    qqq_idx, qqq_prev = 100.0, None
    qseries = {}
    for d in qqq_dates:
        if qqq_prev is not None:
            qqq_idx *= qqq[d] / qqq_prev
        qseries[d] = qqq_idx
        qqq_prev = qqq[d]

    # --- month ends (last trading day of each month, from panel_start) ---
    def month_ends(series_dates):
        bym = {}
        for d in series_dates:
            bym[d[:7]] = d
        return [bym[k] for k in sorted(bym)]

    pm = month_ends(sorted(panel))
    qm = set(month_ends(qqq_dates))
    months = [d for d in pm if d in qm]
    print("month ends:", len(months), months[0], "->", months[-1])

    # --- signal: state_daily stable_supply_30d at month end ---
    db = DB()
    rows = db.all("state_daily", select="d,feature,value,entity",
                  order="d.asc", filters={"feature": "eq.stable_supply_30d"},
                  limit=1000, max_rows=100000)
    sig = {}
    for r in rows:
        if r.get("value") is None:
            continue
        sig[r["d"]] = float(r["value"])
    print("stable_supply_30d rows:", len(sig))

    # --- monthly excess E(m) = ln(panel m->m+1) - ln(QQQ m->m+1) ---
    obs = []
    for i in range(len(months) - 1):
        m0, m1 = months[i], months[i + 1]
        e = math.log(panel[m1] / panel[m0]) - math.log(qseries[m1] / qseries[m0])
        s = sig.get(m0)
        obs.append({"m0": m0, "m1": m1, "E": e, "S": s})
    obs = [o for o in obs if o["S"] is not None]
    print("monthly observations:", len(obs))

    n_disc = int(math.floor(0.6 * len(obs)))
    disc, hold = obs[:n_disc], obs[n_disc:]
    print("discovery n=%d (%s..%s)  holdout n=%d (%s..%s)" % (
        len(disc), disc[0]["m0"], disc[-1]["m1"], len(hold), hold[0]["m0"], hold[-1]["m1"]))

    def variant_stats(rows, lead):
        """lead=0 -> rho(S(m), E(m)); lead=1 -> rho(S(m), E(m+1))"""
        s = [r["S"] for r in rows]
        e = [r["E"] for r in rows[lead:]] if lead else [r["E"] for r in rows]
        s = s[:len(e)]
        rho, t = spearman(s, e)
        med = sorted(s)[len(s) // 2] if s else None
        hi = [r["E"] for r, sv in zip(rows[lead:], s) if sv >= med] if lead else \
             [r["E"] for r, sv in zip(rows, s) if sv >= med]
        lo = [r["E"] for r, sv in zip(rows[lead:], s) if sv <= med] if lead else \
             [r["E"] for r, sv in zip(rows, s) if sv <= med]
        diff = (sum(hi) / len(hi) - sum(lo) / len(lo)) if hi and lo else None
        return {"rho": rho, "t": t, "n": len(e), "hi_mean_E": (sum(hi) / len(hi)) if hi else None,
                "lo_mean_E": (sum(lo) / len(lo)) if lo else None, "median_split_diff": diff,
                "n_hi": len(hi), "n_lo": len(lo)}

    results = {"panel_start": panel_start, "panel_trading_days": len(days),
               "months": [months[0], months[-1]], "n_obs": len(obs),
               "discovery": {"n": len(disc), "from": disc[0]["m0"], "to": disc[-1]["m1"]},
               "holdout": {"n": len(hold), "from": hold[0]["m0"], "to": hold[-1]["m1"]},
               "variants": {}, "obs": obs}

    for lead, vname in [(0, "contemporaneous"), (1, "lead_1m")]:
        dstat = variant_stats(disc, lead)
        passed = (dstat["rho"] is not None and dstat["rho"] > 0 and dstat["t"] is not None
                  and dstat["t"] >= 2.0)
        v = {"discovery": dstat, "passed_discovery": passed}

        # zero-signal control on the DISCOVERY segment: block-permute S (3-month blocks)
        def make_fn(rows, lead):
            def fn(rng):
                s = [r["S"] for r in rows]
                e = [r["E"] for r in rows[lead:]] if lead else [r["E"] for r in rows]
                s = list(block_permute(s, 3, rng))[:len(e)]
                rho, _ = spearman(s, e)
                return float("nan") if rho is None else float(rho)
            return fn
        try:
            null = null_distribution(make_fn(disc, lead), N_BOOT, SEED,
                                     actual=dstat["rho"] if dstat["rho"] is not None else None)
            v["null_block_permute"] = {"n": len(null), "pct": percentile_of(dstat["rho"], null),
                                       "mean": float(np.mean(null)), "sd": float(np.std(null))}
        except Exception as ex:
            v["null_block_permute"] = {"error": str(ex)}
        # second control: shuffle_within (values shuffled within year)
        try:
            def make_fn2(rows, lead):
                def fn(rng):
                    s = [r["S"] for r in rows]
                    e = [r["E"] for r in rows[lead:]] if lead else [r["E"] for r in rows]
                    groups = [r["m0"][:4] for r in rows]
                    s = list(shuffle_within(s, groups, rng))[:len(e)]
                    rho, _ = spearman(s, e)
                    return float("nan") if rho is None else float(rho)
                return fn
            null2 = null_distribution(make_fn2(disc, lead), N_BOOT, SEED + 1,
                                      actual=dstat["rho"] if dstat["rho"] is not None else None)
            v["null_shuffle_within"] = {"n": len(null2), "pct": percentile_of(dstat["rho"], null2)}
        except Exception as ex:
            v["null_shuffle_within"] = {"error": str(ex)}

        # holdout (only for variants that passed discovery)
        if passed:
            hs = variant_stats(hold, lead)
            v["holdout"] = hs
            # one-sided block bootstrap (3-month blocks) of the median-split difference
            e = np.array([r["E"] for r in hold])
            s = np.array([r["S"] for r in hold])
            med = np.median(s)
            d = np.where(s >= med, 1.0, -1.0) * e
            rng = np.random.default_rng(SEED + 2)
            idx = stationary_bootstrap_index(len(d), 3.0, N_BOOT, rng)
            boot = d[idx].mean(axis=1)
            v["holdout"]["boot_mean_diff"] = float(np.mean(d))
            v["holdout"]["boot_p_one_sided"] = float((boot >= 0).mean())
            v["holdout"]["boot_ci95"] = [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]
            v["holdout"]["underpowered"] = True
        else:
            v["holdout"] = None
        results["variants"][vname] = v

    with open(os.path.join(HERE, "t219_m585_explore.json"), "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n=== M-585 exploratory (public panel, UNDERPOWERED) ===")
    for name, v in results["variants"].items():
        d = v["discovery"]
        print("%-16s disc n=%d rho=%s t=%s split_diff=%s | null pct(block_permute)=%s pct(shuffle)=%s | pass=%s"
              % (name, d["n"],
                 "%.3f" % d["rho"] if d["rho"] is not None else "-",
                 "%.2f" % d["t"] if d["t"] is not None else "-",
                 "%.4f" % d["median_split_diff"] if d["median_split_diff"] is not None else "-",
                 v["null_block_permute"].get("pct"), v["null_shuffle_within"].get("pct"),
                 v["passed_discovery"]))
        if v.get("holdout"):
            h = v["holdout"]
            print("      holdout n=%d rho=%s t=%s split_diff=%s boot_p=%s" % (
                h["n"], "%.3f" % h["rho"] if h["rho"] is not None else "-",
                "%.2f" % h["t"] if h["t"] is not None else "-",
                "%.4f" % h["median_split_diff"] if h["median_split_diff"] is not None else "-",
                h.get("boot_p_one_sided")))
    print("\nmonthly obs:")
    for o in obs:
        print("   %s -> %s  S=%.4f  E=%+.4f" % (o["m0"], o["m1"], o["S"], o["E"]))


main()
