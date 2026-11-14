"""S-865:周期仓位通道(T-370)的管票形态 —— 止损线放哪、要不要止盈减仓、到期多久,各自的代价是多少。

为什么:通道上线前要 Jazz 定三样默认值(止损线 / 止盈减仓形态 / 档位名义)。前两样可以先量:同一批进场日上,
3 种止损 × 3 种出场 × 2 个到期 = 18 种管法各自的结果分布。**这里量的是「管法」,不是「信号」** —— 进场日不是任何人的判断。

只描述。预期与读法写在台账 S-865(先登记,后计算)。不进生产;通道真建的时候,生产内核要能复现这里的数。

进场日(两组,BTC / ETH 各自算;D 日收盘判、D + 1 开盘进):
  cell  「该资产周线结构坏 且 收盘在自己 200 日线下」每一段的第一天(空);镜像条件(周线没坏且线上)每一段的第一天(多)
  all   每隔 5 天一个进场日(不看任何条件)—— 对照:管法本身在随便哪天是什么结果
「被止损」只数亏着出去的(跟踪止损带利润出场、减半后保本出场不算)。
止损(初始):K1 上一个自然周的最高价(空)/ 最低价(多)外 0.1%;K2 进场价 ± 2.5 × ATR14;K3 进场价 ± 8%
出场:X0 拿到到期;X1 到 2R 减半、其余止损移到进场价;X2 不设目标、止损跟着最好的收盘走(保持 1R 距离)
到期:14 / 28 天。同一天既碰止损又碰目标 ⇒ 按先碰止损算。跳空越过止损 ⇒ 按开盘价出。资金费不计(写在局限里)。

用法(仓库根目录;取数与 s851 同一个 get()):
    python3 docs/research/s865_ticket_forms.py --selftest
    python3 docs/research/s865_ticket_forms.py            # 写 docs/research/s865_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

_sp = importlib.util.spec_from_file_location("s851", os.path.join(os.path.dirname(os.path.abspath(__file__)), "s851_watch_base_rate.py"))
S = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(S)

OUT = "docs/research/s865_results.json"
ASSETS = ("BTC", "ETH")
STOPS, EXITS, HORIZONS = ("K1", "K2", "K3"), ("X0", "X1", "X2"), (14, 28)
ATR_N, ATR_MULT, FIXED_PCT, WEEK_BUFFER = 14, 2.5, 0.08, 0.001
TP_R = 2.0
GAP_MERGE_D, EVERY_N = 5, 5
START = dt.date(2019, 6, 1)


def atr14(days, o, h, l, c) -> dict:
    tr = {}
    for i, d in enumerate(days):
        pc = c[days[i - 1]] if i else c[d]
        tr[d] = max(h[d] - l[d], abs(h[d] - pc), abs(l[d] - pc))
    return {d: float(np.mean([tr[x] for x in days[i - ATR_N + 1:i + 1]])) for i, d in enumerate(days) if i >= ATR_N - 1}


def prev_week_extreme(days, h, l, d) -> tuple:
    """d 所在周的**上一个**自然周(周一到周日)的最高 / 最低;只用 d 之前的数据。"""
    mon = d - dt.timedelta(days=d.weekday())
    wk = [x for x in days if mon - dt.timedelta(days=7) <= x < mon]
    return (max(h[x] for x in wk), min(l[x] for x in wk)) if wk else (None, None)


def entry_days(days, c, side: int, kind: str) -> list:
    """进场信号日 D(收盘后判)。cell:条件成立的每一段的第一天;all:每隔 EVERY_N 天。"""
    usable = [d for d in days if d >= START]
    if kind == "all":
        return usable[::EVERY_N]
    wdown = S.weekly_down_days(days, c)
    idx = {d: i for i, d in enumerate(days)}
    ok = []
    for d in usable:
        i = idx[d]
        if i < 200 or wdown.get(d) is None:
            continue
        below = c[d] < float(np.mean([c[x] for x in days[i - 199:i + 1]]))
        if (side < 0 and wdown[d] and below) or (side > 0 and not wdown[d] and not below):
            ok.append(d)
    firsts, last = [], None
    for d in ok:
        if last is None or (d - last).days > GAP_MERGE_D:
            firsts.append(d)
        last = d
    return firsts


def run_ticket(days, o, h, l, c, atr, D, side: int, K: str, X: str, H: int):
    """一张票。返回 None = 开不了(止损线在进场价错的一侧,或数据不够)。pnl = 占名义的比例(已含减半)。"""
    i = days.index(D) + 1
    if i + H >= len(days) or D not in atr:
        return None
    e = o[days[i]]
    if K == "K1":
        hi, lo = prev_week_extreme(days, h, l, D)
        if hi is None:
            return None
        stop = hi * (1 + WEEK_BUFFER) if side < 0 else lo * (1 - WEEK_BUFFER)
    elif K == "K2":
        stop = e + ATR_MULT * atr[D] * (1 if side < 0 else -1)
    else:
        stop = e * (1 + FIXED_PCT * (1 if side < 0 else -1))
    R = (stop - e) * (1 if side < 0 else -1)
    if R <= 0:
        return None
    size, pnl, best, half_done = 1.0, 0.0, e, False
    for j in range(i, i + H + 1):
        d = days[j]
        op, hi_, lo_, cl = o[d], h[d], l[d], c[d]
        hit_stop = (hi_ >= stop) if side < 0 else (lo_ <= stop)
        if hit_stop:
            px = max(op, stop) if side < 0 else min(op, stop)        # 跳空越过止损 ⇒ 按开盘价
            pnl += size * (e - px) / e * (1 if side < 0 else -1)
            # stopped = 「被止损打出去而且这张票是亏的」;跟踪止损带着利润出场、减半后保本出场都不算
            return {"pnl": pnl, "r": pnl * e / R, "days": j - i + 1, "stopped": pnl < 0, "half": half_done}
        if X == "X1" and not half_done:
            tgt = e - TP_R * R if side < 0 else e + TP_R * R
            if (lo_ <= tgt) if side < 0 else (hi_ >= tgt):
                pnl += 0.5 * (e - tgt) / e * (1 if side < 0 else -1)
                size, half_done, stop = 0.5, True, e
        if X == "X2":
            best = min(best, cl) if side < 0 else max(best, cl)
            trail = best + R if side < 0 else best - R
            stop = min(stop, trail) if side < 0 else max(stop, trail)
    cl = c[days[i + H]]
    pnl += size * (e - cl) / e * (1 if side < 0 else -1)
    return {"pnl": pnl, "r": pnl * e / R, "days": H + 1, "stopped": False, "half": half_done}


def summarise(ts: list, n_signals: int) -> dict:
    if not ts:
        return {"n": 0, "not_opened": n_signals}
    p, r = np.array([t["pnl"] for t in ts]), np.array([t["r"] for t in ts])
    return {"n": len(ts), "not_opened": n_signals - len(ts), "mean_pct": round(float(p.mean()) * 100, 2), "median_pct": round(float(np.median(p)) * 100, 2),
            "win": round(float((p > 0).mean()), 3), "worst_pct": round(float(p.min()) * 100, 2), "best_pct": round(float(p.max()) * 100, 2),
            "mean_r": round(float(r.mean()), 3), "stopped_at_a_loss": round(float(np.mean([t["stopped"] for t in ts])), 3),
            "took_half": round(float(np.mean([t["half"] for t in ts])), 3), "mean_days": round(float(np.mean([t["days"] for t in ts])), 1)}


def run(data: dict) -> dict:
    out = {"table": {}, "n_signals": {}, "dominated": {}}
    for a in ASSETS:
        days, o, h, l, c = data[a]
        atr = atr14(days, o, h, l, c)
        for side, sname in ((-1, "short"), (1, "long")):
            for kind in ("cell", "all"):
                sig = entry_days(days, c, side, kind)
                out["n_signals"][f"{a}|{sname}|{kind}"] = len(sig)
                for H in HORIZONS:
                    key = f"{a}|{sname}|{kind}|H{H}"
                    forms = {}
                    for K in STOPS:
                        for X in EXITS:
                            ts = [t for t in (run_ticket(days, o, h, l, c, atr, D, side, K, X, H) for D in sig) if t]
                            forms[f"{K}+{X}"] = summarise(ts, len(sig))
                    out["table"][key] = forms
                    live = {k: v for k, v in forms.items() if v.get("n", 0) >= 5}
                    out["dominated"][key] = sorted(b for b in live if any(
                        live[x]["mean_pct"] > live[b]["mean_pct"] and live[x]["worst_pct"] >= live[b]["worst_pct"] and live[x]["stopped_at_a_loss"] < live[b]["stopped_at_a_loss"]
                        for x in live if x != b))
    slices = [k for k in out["table"] if "|short|" in k]
    out["non_dominated_count_short"] = {f: sum(1 for k in slices if f in out["table"][k] and f not in out["dominated"][k]) for f in (f"{K}+{X}" for K in STOPS for X in EXITS)}
    out["n_short_slices"] = len(slices)
    # 自检:截断到 T 的数据,到期日 ≤ T 的票必须一模一样(没有偷看未来)
    a = ASSETS[0]
    days, o, h, l, c = data[a]
    cut = days[len(days) * 2 // 3]
    dz = [d for d in days if d <= cut]
    full = [(D, run_ticket(days, o, h, l, c, atr14(days, o, h, l, c), D, -1, "K1", "X1", 14)) for D in entry_days(days, c, -1, "cell") if D + dt.timedelta(days=30) <= cut]
    part = [(D, run_ticket(dz, o, h, l, c, atr14(dz, o, h, l, c), D, -1, "K1", "X1", 14)) for D in entry_days(dz, c, -1, "cell") if D + dt.timedelta(days=30) <= cut]
    out["self_checks"] = {"tickets_before_cut_ignore_the_future": full == part and len(full) > 0, "n_checked": len(full)}
    return out


def load_live() -> dict:
    data = {}
    for a in ASSETS:
        rows = S.get("ohlcv_daily", {"select": "trade_date,open,high,low,close", "symbol": f"eq.{a}", "source": "eq.binance_hist",
                                    "trade_date": "gte.2018-06-01", "order": "trade_date.asc"})
        rows = [r for r in rows if all(r.get(k) is not None for k in ("open", "high", "low", "close"))]
        days = [S.D(r["trade_date"]) for r in rows]
        data[a] = (days, *({d: float(r[k]) for d, r in zip(days, rows)} for k in ("open", "high", "low", "close")))
        print("loaded", a, len(days), flush=True)
    return data


def synthetic() -> dict:
    data = {}
    for n, a in enumerate(ASSETS):
        rng = np.random.default_rng(865 + n)
        days = [dt.date(2018, 6, 1) + dt.timedelta(days=i) for i in range(2900)]
        cl = 100 * np.exp(np.cumsum(0.0004 + 0.04 * np.sin(np.arange(2900) / 110.0) / 40 + rng.normal(0, 0.03, 2900)))
        op = np.concatenate([[100.0], cl[:-1]]) * np.exp(rng.normal(0, 0.004, 2900))
        hi = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, 0.012, 2900)))
        lo = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, 0.012, 2900)))
        data[a] = (days, *(dict(zip(days, map(float, x))) for x in (op, hi, lo, cl)))
    return data


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    out = run(synthetic() if selftest else load_live())
    print("N_SIGNALS", json.dumps(out["n_signals"], ensure_ascii=False), flush=True)
    for key, forms in out["table"].items():
        print("SLICE", key, "| dominated:", ",".join(out["dominated"][key]) or "-", flush=True)
        for f, v in forms.items():
            print("  ", f, json.dumps(v, ensure_ascii=False), flush=True)
    print("NON_DOMINATED_SHORT", json.dumps(out["non_dominated_count_short"]), "of", out["n_short_slices"], flush=True)
    print("SELF_CHECKS", json.dumps(out["self_checks"]), flush=True)
    if selftest:
        assert out["self_checks"]["tickets_before_cut_ignore_the_future"], out["self_checks"]
        assert all(v.get("n", 0) + v.get("not_opened", 0) == out["n_signals"]["|".join(k.split("|")[:3])] for k, forms in out["table"].items() for v in forms.values())
        t = out["table"]["BTC|short|all|H14"]
        assert t["K3+X0"]["worst_pct"] >= -8.0 - 6.0, "固定 8% 止损的最差结果应在 −8% 附近(跳空除外)"
        assert t["K2+X1"]["took_half"] > 0 and t["K2+X0"]["took_half"] == 0
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
