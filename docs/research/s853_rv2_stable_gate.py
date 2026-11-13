"""S-853(11-13,Seth):R-v2 的票在「稳定币在流出」的日子里是不是更差;闸门加这一条(G1:流出时不开新票)值不值。

登记见 REFUTATION_LEDGER `## S-853`(先登记后算)。只读。用法(仓库根目录):
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/s853_rv2_stable_gate.py <cometcloud-local/research/> main
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/s853_rv2_stable_gate.py <cometcloud-local/research/> null <起> <止>   # 对照分批跑(每次 simulate 一两秒)
  python3 docs/research/s853_rv2_stable_gate.py - judge
状态序列在 docs/research/s853_stable_runs.json(库里按连续段压缩取出)。
"""
import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

sys.path.insert(0, "docs/research"); sys.path.insert(0, ".")
OUT, NULL = "docs/research/s853_results.json", "/tmp/s853_null.jsonl"
SEED, N_NULL = 20261113, 200
HALVES = (("2020-08-16", "2023-09-30"), ("2023-10-01", "2026-09-30"))


def neg_days() -> dict:
    runs = json.load(open("docs/research/s853_stable_runs.json"))["runs"]
    out = {}
    for a, b, s in runs:
        d = dt.date.fromisoformat(a)
        while d <= dt.date.fromisoformat(b):
            out[d] = (s == "N")
            d += dt.timedelta(days=1)
    return out


def setup(R):
    import t310_slots as T310
    T310.UM = R + "s681/_um_daily.jsonl"; T310.STYLE = R + "t156/_style.json"
    sp = importlib.util.spec_from_file_location("t352_engine", "docs/research/t352_engine.py"); E1 = importlib.util.module_from_spec(sp); sp.loader.exec_module(E1)
    raw, _ = T310.load_tickets(); bars = T310.load_bars({t["symbol"] for t in raw}); exits, _ = T310.classify_exits(raw, bars)
    TK = T310.to_engine_tickets(raw, exits); gate_d, _, _ = T310.load_gate()
    return E1, raw, TK, bars, gate_d


def curve(E1, TK, bars, gate_d):
    res = E1.simulate(TK, bars, gate_d, 0.80, equity0=630.0, risk_frac=0.0075, cap_n=10, fix=True)
    return [(dt.date.fromisoformat(str(r[0])[:10]), float(r[1])) for r in res["curve"]]


def metrics(cv):
    d0, d1 = cv[0][0], cv[-1][0]
    eq = np.array([e for _, e in cv])
    cagr = float((eq[-1] / eq[0]) ** (365.25 / (d1 - d0).days) - 1)
    peak, start, longest, span = eq[0], cv[0][0], 0, None
    for d, e in cv:
        if e >= peak:
            peak, start = e, d
        elif (d - start).days > longest:
            longest, span = (d - start).days, (str(start), str(d))
    w20 = float(min(eq[i] / eq[i - 20] - 1 for i in range(20, len(eq))))
    halves = []
    for a, b in HALVES:
        seg = [(d, e) for d, e in cv if dt.date.fromisoformat(a) <= d <= dt.date.fromisoformat(b)]
        halves.append(float((seg[-1][1] / seg[0][1]) ** (365.25 / (seg[-1][0] - seg[0][0]).days) - 1) if len(seg) > 30 else None)
    return {"cagr_pct": round(cagr * 100, 2), "longest_uw_days": longest, "longest_uw_span": span, "worst20_pct": round(w20 * 100, 2),
            "halves_cagr_pct": [None if h is None else round(h * 100, 2) for h in halves], "end_equity": round(float(eq[-1]), 2)}


def blocked(t, neg) -> bool:
    """信号日前一天在流出 ⇒ 不开这张票。读不到状态 ⇒ 不挡(照旧开)。"""
    return bool(neg.get(dt.date.fromisoformat(str(t["signal_d"])[:10]) - dt.timedelta(days=1), False))


def shifted(neg: dict, k: int) -> dict:
    ds = sorted(neg)
    v = [neg[d] for d in ds]
    return {d: v[(i - k) % len(v)] for i, d in enumerate(ds)}


if __name__ == "__main__":
    mode = sys.argv[2] if len(sys.argv) > 2 else "main"
    neg = neg_days()
    if mode == "judge":
        res = json.load(open(OUT))
        nd = [json.loads(x) for x in open(NULL)]
        g0, g1 = res["G0"], res["G1"]
        nc, nu, nw = [x["cagr_pct"] for x in nd], [x["longest_uw_days"] for x in nd], [x["worst20_pct"] for x in nd]
        uw_gain, w20_gain = g0["longest_uw_days"] - g1["longest_uw_days"], g1["worst20_pct"] - g0["worst20_pct"]
        pct = {"cagr": round(float(np.mean(np.array(nc) < g1["cagr_pct"])), 3), "uw_shorter": round(float(np.mean(np.array(nu) > g1["longest_uw_days"])), 3),
               "worst20_better": round(float(np.mean(np.array(nw) < g1["worst20_pct"])), 3)}
        a = uw_gain >= 60 or w20_gain >= 2.0
        b = g1["cagr_pct"] >= g0["cagr_pct"] - 2.0
        c = g1["cagr_pct"] > float(np.median(nc)) and ((uw_gain >= 60 and pct["uw_shorter"] >= 0.8) or (w20_gain >= 2.0 and pct["worst20_better"] >= 0.8))
        d_ = all(h1 is not None and h0 is not None and h1 >= h0 - 2.0 for h0, h1 in zip(g0["halves_cagr_pct"], g1["halves_cagr_pct"]))
        e = res["tickets"]["blocked_ex_2023_sum_r"] <= 0
        res["null"] = {"n": len(nd), "cagr_median": round(float(np.median(nc)), 2), "uw_median": float(np.median(nu)), "worst20_median": round(float(np.median(nw)), 2), "real_pctile": pct}
        res["verdict"] = {"a_recovery_or_worst20": bool(a), "b_cagr_within_2pp": bool(b), "c_beats_shift_null": bool(c), "d_both_halves": bool(d_), "e_not_only_2023": bool(e),
                          "pass": bool(a and b and c and d_ and e), "uw_gain_days": uw_gain, "worst20_gain_pp": round(w20_gain, 2)}
        json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("NULL", json.dumps(res["null"])); print("VERDICT", json.dumps(res["verdict"]))
        sys.exit(0)
    E1, raw, TK, bars, gate_d = setup(sys.argv[1])
    key = "signal_d" if "signal_d" in TK[0] else None
    assert key, f"引擎票里没有 signal_d:{sorted(TK[0])}"
    if mode == "null":
        lo, hi = int(sys.argv[3]), int(sys.argv[4])
        rng = np.random.default_rng(SEED)
        ks = [int(rng.integers(30, len(neg) - 30)) for _ in range(N_NULL)]
        with open(NULL, "a") as f:
            for k in ks[lo:hi]:
                n2 = shifted(neg, k)
                f.write(json.dumps({"k": k, **metrics(curve(E1, [t for t in TK if not blocked(t, n2)], bars, gate_d))}) + "\n")
        print("null done", lo, hi)
        sys.exit(0)
    done = [t for t in raw if t.get("r") is not None]                                   # 票级只统计已了结的(还在场的没有 R)
    grp = {"draining": [t for t in done if blocked(t, neg)], "adding": [t for t in done if not blocked(t, neg)]}
    tick = {k: {"n": len(v), "mean_r": round(float(np.mean([t["r"] for t in v])), 3), "sum_r": round(float(np.sum([t["r"] for t in v])), 1),
                "win_rate": round(float(np.mean([t["r"] > 0 for t in v])), 3)} for k, v in grp.items()}
    by_year = {}
    for t in done:
        y = str(t["signal_d"])[:4]; s = "draining" if blocked(t, neg) else "adding"
        by_year.setdefault(y, {"draining": [0, 0.0], "adding": [0, 0.0]})
        by_year[y][s][0] += 1; by_year[y][s][1] = round(by_year[y][s][1] + float(t["r"]), 1)
    tick["by_year_n_sumr"] = by_year
    tick["blocked_ex_2023_sum_r"] = round(float(sum(t["r"] for t in grp["draining"] if str(t["signal_d"])[:4] != "2023")), 1)
    g0 = metrics(curve(E1, TK, bars, gate_d))
    g1 = metrics(curve(E1, [t for t in TK if not blocked(t, neg)], bars, gate_d))
    assert metrics(curve(E1, [t for t in TK if not blocked(t, {})], bars, gate_d)) == g0, "自检:状态全空时必须与 G0 逐项相同"
    res = {"tickets": tick, "G0": g0, "G1": g1, "state_days": {"draining": sum(neg.values()), "all": len(neg)}}
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("TICKETS", json.dumps({k: v for k, v in tick.items() if k != "by_year_n_sumr"})); print("BY_YEAR", json.dumps(by_year))
    print("G0", json.dumps(g0)); print("G1", json.dumps(g1))
