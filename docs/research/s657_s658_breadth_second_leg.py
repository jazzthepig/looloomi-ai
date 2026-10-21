"""S-657(宽度:R-v2 原样用到 HL 独有的币上)与 S-658(第二段介入)—— 预注册见台账,2026-10-21 13:23 UTC。

R-v2 的信号与管理一律复用 `docs/research/t159_bear_short.py`(`run_long` = r_v2_tickets.sql 的逐字转写,T-159 已与
770 张票逐张对过);本文件先复现那 770 张,对不上就停。第二段臂只换进场,管理照抄 `run_long` 的那几行。
HL 日线由 `docs/research/s657_hl_fetch.py` 抓到 `<root>/research/s657/_hl_daily.jsonl`(含已下架的永续)。
仍持有的票按最后一根收盘盯市(与 S-654 同口径),并报个数。
用法:python3 docs/research/s657_s658_breadth_second_leg.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
os.environ.setdefault("T159_DATA", os.path.join(ROOT, "research", "t159") + "/")
os.environ.setdefault("T156_DATA", os.path.join(ROOT, "research", "t156") + "/")
sys.path.insert(0, os.path.join(HERE, "..", ".."))
_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

SINCE, UNTIL = "2019-01-01", "2026-08-31"
COST = 0.004
SEED = 658


# ── 数据 ─────────────────────────────────────────────────────────────────────────────────────────────────
def norm(name: str) -> set[str]:
    """HL 名 → 可能的面板名(kPEPE ↔ PEPE / 1000PEPE)。"""
    out = {name}
    if name.startswith("k") and name[1:2].isupper():
        out |= {name[1:], "1000" + name[1:]}
    return out


def load_hl(panel: set[str]):
    rows = [json.loads(line) for line in open(os.path.join(ROOT, "research", "s657", "_hl_daily.jsonl"))]
    native, overlap = {}, []
    for r in rows:
        if norm(r["coin"]) & panel:
            overlap.append(r["coin"])
            continue
        bars = sorted({(b["d"], b["o"], b["h"], b["l"], b["c"], b["c"] * b["v"]) for b in r["bars"] if b["c"] > 0})
        if bars:
            native["HL:" + r["coin"]] = bars
    return native, overlap, rows


# ── 共用的管理(run_long 的出场几行,原样)────────────────────────────────────────────────────────────────
def manage(a, i, sym, n):
    ei = i + 1
    if ei >= n:
        return None
    entry, stop = a["o"][ei], a["o"][ei] - 2.5 * a["atr14"][i]
    if not (entry > stop):
        return None
    k = None
    for j in range(ei, min(i + 120, n - 1) + 1):
        if a["l"][j] <= stop or a["c"][j] < a["sma20"][j]:
            k = j
            break
    if k is None:
        xi, xp, still = min(i + 120, n - 1), a["c"][min(i + 120, n - 1)], (i + 120 > n - 1)
    elif a["l"][k] <= stop:
        xi, xp, still = k, (a["o"][k] if (k > ei and a["o"][k] <= stop) else stop), False
    elif k + 1 <= n - 1:
        xi, xp, still = k + 1, a["o"][k + 1], False
    else:
        xi, xp, still = k, a["c"][k], True
    r = (xp - entry) / (entry - stop) - COST * entry / (entry - stop)
    return dict(symbol=sym, signal_d=a["d"][i], entry_d=a["d"][ei], exit_d=None if still else a["d"][xi],
                entry_px=entry, stop_px=stop, exit_px=xp, ei=ei, xi=xi, still=still, r=r)


def mtm(tickets, bars):
    """run_long 的仍持有票 r = None ⇒ 按最后收盘盯市。"""
    for t in tickets:
        if t.get("r") is None:
            last_c = bars[t["symbol"]][-1][4]
            t["r"] = (last_c - t["entry_px"]) / (t["entry_px"] - t["stop_px"]) - COST * t["entry_px"] / (
                t["entry_px"] - t["stop_px"])
            t["still"] = True
    return tickets


# ── 第二段臂 ──────────────────────────────────────────────────────────────────────────────────────────────
def second_leg(bars, gate):
    out = []
    for sym, rows in bars.items():
        a = t159.indicators(rows)
        n = len(rows)
        c, h, dv = a["c"], a["h"], a["dv"]
        sma50 = [t159.win(c, i, 0, 49) for i in range(n)]
        busy_until, used_peaks = -1, set()
        for i in range(150, n):
            d = a["d"][i]
            if not (SINCE <= d <= UNTIL) or i <= busy_until:
                continue
            if a["atr14"][i] is None or a["atr14"][i] <= 0 or a["adv30"][i] is None or a["adv30"][i] < 5e6:
                continue
            lo_i, hi_i = i - 120, i - 15
            seg = c[lo_i:hi_i + 1]
            P = max(seg)
            tp = lo_i + max(k for k, v in enumerate(seg) if v == P)          # 并列取最近的那个峰
            L = min(c[max(0, tp - 120):tp + 1])
            if L <= 0 or P / L < 2.0:
                continue
            m = min(c[tp + 1:i])
            if not (0.5 * P <= m <= 0.8 * P):
                continue
            if not (c[i] > max(h[i - 20:i]) and sma50[i] is not None and c[i] > sma50[i]
                    and dv[i] >= 1.5 * (sum(dv[i - 20:i]) / 20.0)):
                continue
            if not gate.get(d, {}).get("gate_open", True):
                continue
            if (sym, tp) in used_peaks:
                continue
            t = manage(a, i, sym, n)
            if t is None:
                continue
            t["peak_d"], t["leg_x"], t["pullback"] = a["d"][tp], P / L, m / P - 1.0
            out.append(t)
            used_peaks.add((sym, tp))
            busy_until = t["xi"]
    out.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return out


def random_null(tickets, bars, draws=1000):
    """④:每张票换成同币、同日历月里随机一天(adv30 ≥ 500 万)次日开盘进,同样管理。"""
    cache = {}
    pools = {}
    for t in tickets:
        s, ym = t["symbol"], t["signal_d"][:7]
        if s not in cache:
            cache[s] = t159.indicators(bars[s])
        a = cache[s]
        key = (s, ym)
        if key not in pools:
            pools[key] = [i for i in range(150, len(a["d"]) - 1) if a["d"][i][:7] == ym and a["adv30"][i]
                          and a["adv30"][i] >= 5e6 and a["atr14"][i] and a["atr14"][i] > 0]
    rng = random.Random(SEED)
    rcache: dict = {}
    means = []
    for _ in range(draws):
        rs = []
        for t in tickets:
            s, ym = t["symbol"], t["signal_d"][:7]
            pool = pools[(s, ym)]
            if not pool:
                continue
            i = rng.choice(pool)
            if (s, i) not in rcache:
                x = manage(cache[s], i, s, len(cache[s]["d"]))
                rcache[(s, i)] = x["r"] if x else None
            if rcache[(s, i)] is not None:
                rs.append(rcache[(s, i)])
        means.append(sum(rs) / len(rs))
    return means


# ── 统计 ──────────────────────────────────────────────────────────────────────────────────────────────────
def mean(xs):
    return sum(xs) / len(xs) if xs else None


def boot_months(tickets, draws=2000, seed=SEED):
    by = defaultdict(list)
    for t in tickets:
        by[t["signal_d"][:7]].append(t["r"])
    months = list(by)
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        rs = [r for _m in (rng.choice(months) for _ in months) for r in by[_m]]
        out.append(sum(rs) / len(rs))
    return out


def summary(tickets):
    rs = sorted(t["r"] for t in tickets)
    by_y = defaultdict(lambda: [0, 0.0])
    for t in tickets:
        by_y[t["signal_d"][:4]][0] += 1
        by_y[t["signal_d"][:4]][1] += t["r"]
    return {"n": len(rs), "mean": mean(rs), "total": sum(rs), "win": sum(r > 0 for r in rs) / len(rs) if rs else None,
            "median": rs[len(rs) // 2] if rs else None, "ex_top5_mean": mean(rs[:-5]) if len(rs) > 5 else None,
            "still_open": sum(1 for t in tickets if t.get("still")),
            "by_year": {y: (v[0], round(v[1], 2)) for y, v in sorted(by_y.items())},
            "top10": [(t["symbol"], t["signal_d"], round(t["r"], 2)) for t in sorted(tickets, key=lambda t: -t["r"])[:10]]}


def main():
    panel = t159.load_bars()
    gate = t159.load_gate()
    # 0. 复现 R-v2 的 770 张
    ref = json.load(open(os.path.join(os.environ["T159_DATA"], "_tickets_2020-03-01_2026-06-20.json")))["long"]
    mine = t159.run_long(panel, gate, "2020-03-01", "2026-10-19")
    key = lambda t: (t["symbol"], t["signal_d"])                              # noqa: E731
    same = {key(t) for t in mine} == {key(t) for t in ref}
    print(json.dumps({"replica": {"n": len(mine), "ref_n": len(ref), "same_set": same,
                                  "ref_total_r": round(sum(t["r"] or 0 for t in ref), 3),
                                  "mine_total_r": round(sum(t["r"] or 0 for t in mine), 3)}}))
    if not same:
        sys.exit("R-v2 复现对不上 770 张 —— 停")
    hl, overlap, raw = load_hl(set(panel))
    res: dict = {"hl": {"universe": len(raw), "in_panel": len(overlap), "native": len(hl),
                        "native_ge220_bars": sum(1 for v in hl.values() if len(v) >= 221)}}
    # 1. S-657:HL 独有币上的 R-v2
    s657 = mtm(t159.run_long(hl, gate, SINCE, UNTIL), hl)
    res["s657"] = summary(s657)
    if s657:
        bm = boot_months(s657)
        res["s657"]["p_mean_le_0"] = sum(m <= 0 for m in bm) / len(bm)
        d0 = min(t["signal_d"] for t in s657)
        pan = mtm([t for t in t159.run_long(panel, gate, d0, UNTIL)], panel)
        bp = boot_months(pan, seed=SEED + 1)
        diffs = sorted(x - y for x, y in zip(bm, bp))
        res["s657"]["panel_same_window"] = {"from": d0, "n": len(pan), "mean": mean([t["r"] for t in pan])}
        res["s657"]["diff_ci95"] = (diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs))])
        n = len(s657)
        res["s657"]["verdict"] = ("样本不足(n < 30),只报" if n < 30 else
                                  "过" if (res["s657"]["p_mean_le_0"] < 0.10 and res["s657"]["diff_ci95"][0] > -0.5)
                                  else "不过")
    # 2. S-658:第二段(面板 ∪ HL 独有)
    allb = {**panel, **hl}
    s658 = mtm(second_leg(allb, gate), allb)
    res["s658"] = summary(s658)
    rs = [t["r"] for t in s658]
    if s658:
        bm = boot_months(s658)
        p1 = sum(m <= 0 for m in bm) / len(bm)
        halves = {h: mean([t["r"] for t in s658 if (t["signal_d"] < "2023-01-01") == (h == "lt2023")])
                  for h in ("lt2023", "ge2023")}
        null = sorted(random_null(s658, allb))
        q95 = null[int(0.95 * len(null))]
        judged = {"1_mean_gt0_p": p1, "2_ex_top5_mean": res["s658"]["ex_top5_mean"], "3_halves": halves,
                  "4_null_q95": q95, "4_null_median": null[len(null) // 2], "4_pct": sum(x < mean(rs) for x in null) / len(null)}
        ok = (p1 < 0.05 and (res["s658"]["ex_top5_mean"] or -1) > 0 and all(v is not None and v > 0 for v in halves.values())
              and mean(rs) > q95)
        res["s658"]["judged"], res["s658"]["verdict"] = judged, ("过" if ok else "不过")
        # 只报
        rv2 = mtm(t159.run_long(allb, gate, SINCE, UNTIL), allb)
        def near(t):
            return any(u["symbol"] == t["symbol"] and abs((dt.date.fromisoformat(u["signal_d"]) -
                                                           dt.date.fromisoformat(t["signal_d"])).days) <= 30 for u in rv2)
        res["s658"]["overlap_rv2_30d"] = sum(near(t) for t in s658)
        mo = lambda ts: {m: sum(t["r"] for t in ts if t["signal_d"][:7] == m) for m in {t["signal_d"][:7] for t in ts}}  # noqa: E731
        a_, b_ = mo(s658), mo(rv2)
        ms = sorted(set(a_) | set(b_))
        xa, xb = [a_.get(m, 0.0) for m in ms], [b_.get(m, 0.0) for m in ms]
        ma, mb = mean(xa), mean(xb)
        cov = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
        va, vb = sum((x - ma) ** 2 for x in xa) ** .5, sum((y - mb) ** 2 for y in xb) ** .5
        res["s658"]["monthly_corr_rv2"] = cov / (va * vb) if va and vb else None
        res["s658"]["panel_vs_hl"] = {g: summary([t for t in s658 if t["symbol"].startswith("HL:") == (g == "hl")])
                                      for g in ("panel", "hl")}
        res["s658"]["hype_uni"] = [(t["symbol"], t["signal_d"], t["peak_d"], round(t["leg_x"], 2), round(t["pullback"], 3),
                                    round(t["r"], 2), t["exit_d"]) for t in s658
                                   if t["symbol"] in ("HL:HYPE", "UNI", "HL:UNI")]
        res["rv2_all_universe"] = summary(rv2)
    out = os.path.join(HERE, "s657_s658_results.json")
    json.dump(res, open(out, "w"), indent=1, default=str, ensure_ascii=False)
    print(json.dumps(res, indent=1, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
