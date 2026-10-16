"""S-584 —— World50 的动量标准:周度 / 双周调仓、更短的回看(预注册见 REFUTATION_LEDGER §S-584)。

用法:python3 docs/research/s584_world50_weekly_mom.py <w50_daily 目录> [输出 json]
  输入 = docs/research/w50_export_daily.py 的 close.json / mcap.json。
成分规则与 S-581 相同(world50.select_members,每年 12 月重选);只变权重(world50.momentum_scores / tilt_weights 的打分变换)
与调仓频率。主判据只有一条:双周「快合成」(4 周 + 13 周)对双周等权,apparatus.ab_test(周收益,mean_block 4,days_per_year 52)。
"""
from __future__ import annotations

import bisect
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test  # noqa: E402
from src.data.universe.world50 import momentum_scores, select_members, tilt_weights  # noqa: E402

FIRST_SELECTION = "2015-12-31"
LAST_WEEK = "2026-09-25"
N_MEMBERS = 50
COST_BP = {"equity": 10, "metal": 10, "crypto": 20}
VOL_WEEKS, MIN_VOL_WEEKS = 52, 13


# ── 网格与对齐(纯函数) ───────────────────────────────────────────────────────

def fridays(first: str, last: str) -> list[str]:
    d = date.fromisoformat(first)
    d += timedelta(days=(4 - d.weekday()) % 7)
    out = []
    while d.isoformat() <= last:
        out.append(d.isoformat())
        d += timedelta(days=7)
    return out


def weekly_closes(dates: list[str], closes: list[Optional[float]], grid: list[str], max_gap: int = 6) -> list[Optional[float]]:
    """每个周五取当天或之前 max_gap 天内最后一个收盘。"""
    pts = [(d, c) for d, c in zip(dates, closes) if c is not None and c > 0]
    ds = [d for d, _ in pts]
    out: list[Optional[float]] = []
    for g in grid:
        i = bisect.bisect_right(ds, g) - 1
        if i >= 0 and (date.fromisoformat(g) - date.fromisoformat(ds[i])).days <= max_gap:
            out.append(pts[i][1])
        else:
            out.append(None)
    return out


def last_value(points: list[list], d: str, within_days: int) -> Optional[float]:
    ds = [p[0] for p in points]
    i = bisect.bisect_right(ds, d) - 1
    if i < 0 or (date.fromisoformat(d) - date.fromisoformat(ds[i])).days > within_days:
        return None
    return float(points[i][1])


def weekly_returns(wc: list[Optional[float]]) -> list[Optional[float]]:
    return [None] + [(b / a - 1) if a and b else None for a, b in zip(wc, wc[1:])]


def mom_value(wc: list[Optional[float]], wr: list[Optional[float]], i: int, look: int) -> Optional[float]:
    """第 i 周收盘时的风险调整动量:P(i) / P(i − look) − 1,除以过去 52 周周收益(至少 13 个)的年化波动。不跳过最近一段。"""
    if i - look < 0 or not wc[i] or not wc[i - look]:
        return None
    r = [x for x in wr[max(1, i - VOL_WEEKS + 1): i + 1] if x is not None and x > -1]
    if len(r) < MIN_VOL_WEEKS:
        return None
    vol = float(np.std(np.log1p(r), ddof=1) * math.sqrt(52))
    if not vol > 0:
        return None
    return (wc[i] / wc[i - look] - 1) / vol


def arm_weights(arm: str, members: list[str], wc: dict, wr: dict, i: int) -> tuple[dict[str, float], int]:
    if arm == "EW":
        return {k: 1.0 / len(members) for k in members}, 0
    looks = {"M4": (4, None), "M13": (13, None), "M26": (26, None), "FAST": (4, 13), "Q": (26, 52)}[arm]
    vals = {}
    for k in members:
        a = mom_value(wc[k], wr[k], i, looks[0])
        b = mom_value(wc[k], wr[k], i, looks[1]) if looks[1] else None
        vals[k] = (a, b)
    scores = momentum_scores(vals)
    neutral = [k for k in members if k not in scores]
    for k in neutral:
        scores[k] = 1.0
    return tilt_weights(members, scores), len(neutral)


# ── 一条臂 ─────────────────────────────────────────────────────────────────

def run_arm(arm: str, every: int, grid: list[str], wc: dict, wr: dict, snaps: dict[str, dict[str, float]],
            cls: dict[str, str], cost_bp_scale: float = 1.0, quarterly: bool = False) -> dict[str, Any]:
    i0 = grid.index(next(g for g in grid if g >= FIRST_SELECTION)) - 1   # 2015-12-31 前最后一个周五
    members: list[str] = []
    w: dict[str, float] = {}
    rets, weeks = [], []
    turnover, neutral_n, max_w, eff_n, n_reb = 0.0, 0, [], [], 0
    last_reconst_year = None
    since = 0
    for i in range(i0, len(grid)):
        g = grid[i]
        if g > LAST_WEEK:
            break
        if i > i0:
            avail = {k: wr[k][i] for k in w if wr[k][i] is not None and math.isfinite(wr[k][i])}
            tot = sum(w[k] for k in avail)
            r = sum(w[k] * avail[k] for k in avail) / tot if tot > 0 else 0.0
            rets.append(r)
            weeks.append(g)
            grown = {k: w[k] * (1 + avail.get(k, 0.0)) for k in w}
            s = sum(grown.values())
            w = {k: v / s for k, v in grown.items()} if s > 0 else w
            since += 1
        nxt = grid[i + 1] if i + 1 < len(grid) else "9999-12-31"
        year_end = g[5:7] == "12" and nxt[:4] != g[:4]               # 12 月最后一个周五
        q_end = nxt[5:7] != g[5:7] and g[5:7] in ("03", "06", "09", "12")
        due = (q_end if quarterly else since >= every) or not members or year_end
        if not due:
            continue
        snap = snaps.get(g, {})
        if (year_end and last_reconst_year != g[:4]) or not members:
            ranked = [k for k, v in sorted(snap.items(), key=lambda kv: -kv[1]) if v and v > 0]
            members = select_members(ranked, previous=members, n=N_MEMBERS)
            last_reconst_year = g[:4]
        members = [k for k in members if k in snap]
        if not members:
            continue
        new, nn = arm_weights(arm, members, wc, wr, i)
        keys = set(new) | set(w)
        tv = sum(abs(new.get(k, 0.0) - w.get(k, 0.0)) for k in keys)
        cost = cost_bp_scale * sum(abs(new.get(k, 0.0) - w.get(k, 0.0)) * COST_BP.get(cls.get(k, "equity"), 10) / 1e4
                                   for k in keys)
        if rets:
            rets[-1] = (1 + rets[-1]) * (1 - cost) - 1
        turnover += tv / 2
        neutral_n += nn
        n_reb += 1
        w = new
        since = 0
        max_w.append(max(w.values()))
        eff_n.append(1.0 / sum(v * v for v in w.values()))
    years = len(rets) / 52
    return {"weeks": weeks, "ret": rets, "annual_turnover": turnover / years if years else None,
            "max_weight": max(max_w) if max_w else None, "avg_eff_n": float(np.mean(eff_n)) if eff_n else None,
            "neutral_scores": neutral_n, "rebalances": n_reb}


def stats(rets: list[float]) -> dict[str, Any]:
    r = np.asarray(rets, dtype=float)
    nav = np.cumprod(1 + r)
    years = len(r) / 52
    cagr = float(nav[-1] ** (1 / years) - 1)
    vol = float(r.std(ddof=1) * math.sqrt(52))
    dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"cagr": cagr, "vol": vol, "sharpe0": cagr / vol if vol > 0 else None, "max_dd": dd,
            "calmar": cagr / abs(dd) if dd < 0 else None, "total_x": float(nav[-1])}


def per_year(weeks: list[str], rets: list[float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for g, r in zip(weeks, rets):
        out[g[:4]] = out.get(g[:4], 1.0) * (1 + r)
    return {y: v - 1 for y, v in out.items()}


# ── 主程序 ─────────────────────────────────────────────────────────────────

def load(dir_: str) -> tuple[list[str], dict, dict, dict, dict]:
    d = Path(dir_)
    cj = json.loads((d / "close.json").read_text())
    mj = json.loads((d / "mcap.json").read_text())
    grid = fridays("2014-06-06", LAST_WEEK)
    from src.data.universe.world50 import CANDIDATES
    pool = {c.key for c in CANDIDATES}          # 10-16:共用面板被扩成 380 个加密(含稳定币)—— 只取 World50 候选池 + 对照组
    keys = [k for k, c in cj["cls"].items() if c != "benchmark" and k in pool] + [k for k, c in cj["cls"].items() if c == "benchmark"]
    wc = {k: weekly_closes(cj["dates"], cj["close"][k], grid) for k in keys}
    wr = {k: weekly_returns(wc[k]) for k in keys}
    snaps: dict[str, dict[str, float]] = {}
    for g in grid:
        if g < "2015-12-01":
            continue
        snap = {}
        for k, pts in mj.items():
            if cj["cls"].get(k) == "benchmark" or k not in wc:
                continue
            v = last_value(pts, g, 14)
            if v:
                snap[k] = v
        snaps[g] = snap
    return grid, wc, wr, snaps, cj["cls"]


def main(dir_: str, out_path: Optional[str] = None) -> dict[str, Any]:
    grid, wc, wr, snaps, cls = load(dir_)
    arms: dict[str, dict] = {}
    for every, tag in ((1, "W"), (2, "B")):
        for arm in ("EW", "M4", "M13", "M26", "FAST"):
            arms[f"{arm}_{tag}"] = run_arm(arm, every, grid, wc, wr, snaps, cls)
    arms["EW_Q"] = run_arm("EW", 13, grid, wc, wr, snaps, cls, quarterly=True)
    arms["Q_Q"] = run_arm("Q", 13, grid, wc, wr, snaps, cls, quarterly=True)
    weeks = arms["EW_B"]["weeks"]
    assert all(a["weeks"] == weeks for a in arms.values()), "各臂的周不一致"
    res: dict[str, Any] = {"weeks": [weeks[0], weeks[-1], len(weeks)], "arms": {}}
    for name, a in arms.items():
        res["arms"][name] = {**stats(a["ret"]), **{k: a[k] for k in ("annual_turnover", "max_weight", "avg_eff_n",
                                                                     "neutral_scores", "rebalances")},
                             "per_year": per_year(a["weeks"], a["ret"])}
    res["primary"] = ab_test(arms["EW_B"]["ret"], arms["FAST_B"]["ret"], mean_block=4, days_per_year=52)
    res["explore_ab"] = {f"{n} vs {base}": ab_test(arms[base]["ret"], arms[n]["ret"], mean_block=4, days_per_year=52)
                         for n, base in (("M4_W", "EW_W"), ("M13_W", "EW_W"), ("M26_W", "EW_W"), ("FAST_W", "EW_W"),
                                         ("M4_B", "EW_B"), ("M13_B", "EW_B"), ("M26_B", "EW_B"), ("Q_Q", "EW_Q"),
                                         ("FAST_B", "Q_Q"))}
    # 成本敏感:主判据两臂在 0 与 25 bp
    for scale, tag in ((0.0, "0bp"), (2.5, "25bp")):
        a = run_arm("EW", 2, grid, wc, wr, snaps, cls, cost_bp_scale=scale)
        b = run_arm("FAST", 2, grid, wc, wr, snaps, cls, cost_bp_scale=scale)
        res[f"primary_{tag}"] = ab_test(a["ret"], b["ret"], mean_block=4, days_per_year=52)
    # 分状态:ACWI 过去 26 周收益 > 0 / ≤ 0(期初已知)
    if "ACWI" in wc:
        acwi = wc["ACWI"]
        idx = {g: i for i, g in enumerate(grid)}
        state = []
        for g in weeks:
            i = idx[g] - 1
            state.append("up" if acwi[i] and i - 26 >= 0 and acwi[i - 26] and acwi[i] / acwi[i - 26] > 1 else "down")
        res["by_state"] = {}
        for s in ("up", "down"):
            sel = [j for j, x in enumerate(state) if x == s]
            res["by_state"][s] = {"weeks": len(sel), **{n: float(np.mean([arms[n]["ret"][j] for j in sel]) * 52)
                                                        for n in ("EW_B", "FAST_B", "EW_W", "FAST_W", "Q_Q")}}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    p = r["primary"]
    print("weeks", r["weeks"])
    for n, a in r["arms"].items():
        print(f"{n:8s} CAGR {a['cagr']*100:6.2f}%  vol {a['vol']*100:5.1f}%  MDD {a['max_dd']*100:6.1f}%  "
              f"turnover/yr {a['annual_turnover']:.2f}  maxw {a['max_weight']:.3f}")
    print("PRIMARY FAST_B vs EW_B:", p["verdict"], "ratio", round(p["ratio_b_over_a"], 3),
          "MDE/yr", round(p["mde_log_diff_per_year"], 4), "p", round(p["p_b_le_a"], 3))
