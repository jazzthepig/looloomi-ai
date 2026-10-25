"""做空研究共用模拟器(台账 S-681)—— H1–H4 四道都 import 这一份,不各写一版。

口径(S-681 写死):信号日 t 收盘定、t+1 开盘进空;硬止损 = 进场 × (1 + s),日内最高触及 ⇒ 按止损价出,
跳空开在止损上方 ⇒ 按开盘出;另有可选「次日开盘出」的规则(H4:收盘 > 20 日线);到期 = 第 t+1+N 天开盘出;
单边成本 0.10%;资金费按真实结算记入(空头收正费率、付负费率;缺数据记 0,另报覆盖率);R = 收益 ÷ s。
同币持仓期间不叠票(按进场先后贪心)。资金曲线用 t159.nav(支持空单:止损在进场上方)。
数据:数据根 research/s681/_um_daily.jsonl 与 _um_funding.jsonl(s681_um_fetch.py 抓的 Binance Vision 永续月档)。
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import random
from typing import Any, Callable, Iterable, Optional

import numpy as np

DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
S681 = os.path.join(DATA_ROOT, "research", "s681")
COST_SIDE = 0.001
SEED = 681
DISCOVERY = ("2020-01-01", "2023-12-31")
HOLDOUT_FROM = "2024-01-01"


# ── 数据 ─────────────────────────────────────────────────────────────────────────────────────────
def load_um(root: str = S681) -> dict[str, dict[str, np.ndarray | list]]:
    """symbol → {d: [日期], o, h, l, c, qv: ndarray}。按日期排序、去重、去掉收盘 ≤ 0。"""
    out = {}
    for line in open(os.path.join(root, "_um_daily.jsonl")):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if b[4] > 0})
        if not rows:
            continue
        a = np.array([r[1:] for r in rows], float)
        out[x["symbol"]] = {"d": [r[0] for r in rows], "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3],
                            "qv": a[:, 4]}
    return out


def load_funding(root: str = S681) -> dict[str, tuple[list[str], np.ndarray]]:
    """symbol → (按时间排序的 ISO 时间戳, 费率)。"""
    out = {}
    path = os.path.join(root, "_um_funding.jsonl")
    if not os.path.exists(path):
        return out
    for line in open(path):
        x = json.loads(line)
        rs = sorted(x["rates"])
        out[x["symbol"]] = ([r[0] for r in rs], np.array([r[1] for r in rs], float))
    return out


def daily_funding(f: dict[str, tuple[list[str], np.ndarray]]) -> dict[str, dict[str, float]]:
    """symbol → {UTC 日期: 当天所有结算费率之和}。"""
    out = {}
    for s, (ts, rs) in f.items():
        dd: dict[str, float] = {}
        for t, r in zip(ts, rs):
            dd[t[:10]] = dd.get(t[:10], 0.0) + float(r)
        out[s] = dd
    return out


# ── 指标(全部只用当天及以前)──────────────────────────────────────────────────────────────────
def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.r_[0.0, x])
    for i in range(n - 1, len(x)):
        out[i] = (cs[i + 1] - cs[i + 1 - n]) / n
    return out


def adv30(a: dict) -> np.ndarray:
    return rolling_mean(a["qv"], 30)


# ── 单张空单 ─────────────────────────────────────────────────────────────────────────────────────
def short_ticket(a: dict, i: int, s: float, n_hold: int, fund: Optional[dict[str, float]] = None,
                 exit_rule: Optional[Callable[[dict, int], bool]] = None, stop_px: Optional[float] = None,
                 symbol: str = "") -> Optional[dict[str, Any]]:
    """信号日下标 i(收盘定),t+1 开盘进空。stop_px 给了就用它(H4 的反弹高点),否则 = 进场 × (1 + s)。
    exit_rule(a, j) 为真 ⇒ 第 j+1 天开盘出。返回票(含 r_mult、资金费、是否跳空穿止损、是否仍持有)。"""
    n = len(a["d"])
    ei = i + 1
    if ei >= n:
        return None
    entry = float(a["o"][ei])
    stop = float(stop_px) if stop_px is not None else entry * (1 + s)
    if not (stop > entry > 0):
        return None
    risk = stop / entry - 1
    last = min(ei + n_hold, n - 1)
    xi, xp, why, gap = None, None, None, False
    for j in range(ei, last + 1):
        if j > ei and a["o"][j] >= stop:                       # 跳空开在止损上方
            xi, xp, why, gap = j, float(a["o"][j]), "stop_gap", True
            break
        if a["h"][j] >= stop:
            xi, xp, why = j, stop, "stop"
            break
        if j == ei + n_hold:
            xi, xp, why = j, float(a["o"][j]), "time"
            break
        if exit_rule is not None and exit_rule(a, j) and j + 1 <= n - 1:
            xi, xp, why = j + 1, float(a["o"][j + 1]), "rule"
            break
    still = xi is None
    if still:
        xi, xp, why = n - 1, float(a["c"][n - 1]), "open"
    gross = (entry - xp) / entry                                    # 空单收益(相对进场名义)
    cost = 2 * COST_SIDE
    fsum, covered = 0.0, 0
    if fund is not None:
        for j in range(ei, xi):
            v = fund.get(a["d"][j])
            if v is not None:
                fsum += v
                covered += 1
    ret = gross - cost + fsum                                        # 空头收正费率
    return {"symbol": symbol, "signal_d": a["d"][i], "entry_d": a["d"][ei], "exit_d": a["d"][xi], "ei": ei, "xi": xi,
            "entry_px": entry, "stop_px": stop, "exit_px": xp, "risk": risk, "ret": ret, "r": ret / risk,
            "funding": fsum, "funding_days": covered, "hold_days": xi - ei, "why": why, "gap": gap, "still": still}


def chain(tickets: Iterable[dict]) -> list[dict]:
    """同币持仓期间不叠票:按进场先后贪心。"""
    by: dict[str, list[dict]] = {}
    for t in tickets:
        by.setdefault(t["symbol"], []).append(t)
    out = []
    for s, ts in by.items():
        ts.sort(key=lambda t: t["ei"])
        last_x = -1
        for t in ts:
            if t["ei"] > last_x:
                out.append(t)
                last_x = t["xi"]
    out.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return out


# ── 统计 ─────────────────────────────────────────────────────────────────────────────────────────
def in_window(tickets: list[dict], lo: str, hi: str) -> list[dict]:
    return [t for t in tickets if lo <= t["signal_d"] <= hi]


def summary(tickets: list[dict]) -> dict[str, Any]:
    if not tickets:
        return {"n": 0}
    r = np.array([t["r"] for t in tickets])
    by_y: dict[str, list[float]] = {}
    for t in tickets:
        by_y.setdefault(t["signal_d"][:4], []).append(t["r"])
    return {"n": len(r), "mean_r": float(r.mean()), "median_r": float(np.median(r)), "win": float((r > 0).mean()),
            "total_r": float(r.sum()), "worst_r": float(r.min()), "p01_r": float(np.quantile(r, 0.01)),
            "best_r": float(r.max()), "gaps": int(sum(t["gap"] for t in tickets)),
            "mean_ret": float(np.mean([t["ret"] for t in tickets])),
            "funding_mean": float(np.mean([t["funding"] for t in tickets])),
            "funding_coverage": float(np.mean([t["funding_days"] / max(1, t["hold_days"]) for t in tickets])),
            "by_year": {y: (len(v), round(float(np.mean(v)), 3)) for y, v in sorted(by_y.items())}}


def boot_months(tickets: list[dict], draws: int = 2000, seed: int = SEED) -> float:
    """月块自助:p(均值 ≤ 0)。"""
    by: dict[str, list[float]] = {}
    for t in tickets:
        by.setdefault(t["signal_d"][:7], []).append(t["r"])
    months = list(by)
    if not months:
        return float("nan")
    rng = random.Random(seed)
    le0 = 0
    for _ in range(draws):
        rs = [r for m in (rng.choice(months) for _ in months) for r in by[m]]
        le0 += (sum(rs) / len(rs)) <= 0
    return le0 / draws


def null_same_day(tickets: list[dict], pools: dict[str, list[tuple[str, int]]], make: Callable[[str, int], Optional[dict]],
                  draws: int = 1000, seed: int = SEED) -> np.ndarray:
    """对照:每张票换成同一信号日、从 pools[信号日] 里随机抽的(币, 下标),用 make 按同样规则开票。返回每次抽样的平均 R。"""
    rng = random.Random(seed)
    cache: dict[tuple[str, int], Optional[float]] = {}
    out = []
    for _ in range(draws):
        rs = []
        for t in tickets:
            pool = pools.get(t["signal_d"])
            if not pool:
                continue
            k = rng.choice(pool)
            if k not in cache:
                x = make(*k)
                cache[k] = x["r"] if x else None
            if cache[k] is not None:
                rs.append(cache[k])
        if rs:
            out.append(float(np.mean(rs)))
    return np.array(out)


def judge(tickets: list[dict], null: np.ndarray, holdout: list[dict]) -> dict[str, Any]:
    """S-681 四条:① 发现段均值 > 0 且月块 p < 0.05;② ≥ 对照 95 分位;③ 留出段均值 > 0;④ 发现段 ≥ 50 张。"""
    m = float(np.mean([t["r"] for t in tickets])) if tickets else float("nan")
    p = boot_months(tickets) if tickets else float("nan")
    q95 = float(np.quantile(null, 0.95)) if len(null) else float("nan")
    hm = float(np.mean([t["r"] for t in holdout])) if holdout else float("nan")
    j = {"1_mean_r": m, "1_p_le0": p, "1_ok": bool(m > 0 and p < 0.05),
         "2_null_median": float(np.median(null)) if len(null) else None, "2_null_q95": q95,
         "2_pct": float((null < m).mean()) if len(null) else None, "2_ok": bool(m >= q95),
         "3_holdout_n": len(holdout), "3_holdout_mean_r": hm, "3_ok": bool(hm > 0),
         "4_n": len(tickets), "4_ok": len(tickets) >= 50}
    j["verdict"] = "过" if all(j[k] for k in ("1_ok", "2_ok", "3_ok", "4_ok")) else "不过"
    return j


def money(tickets: list[dict], bars_for_nav: dict[str, list], d_to: str, f: float = 0.005, cap: int = 10) -> Optional[dict]:
    """资金曲线(t159.nav,每票风险 f、最多同时 cap 张)。bars_for_nav = symbol → [(d, o, h, l, c, …)]。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if "t159" not in sys.modules:
        spec = importlib.util.spec_from_file_location("t159", os.path.join(here, "t159_bear_short.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["t159"] = mod
        spec.loader.exec_module(mod)
    t159 = sys.modules["t159"]
    tk = [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
           "exit_d": None if t["still"] else t["exit_d"], "entry_px": t["entry_px"], "stop_px": t["stop_px"],
           "exit_px": None if t["still"] else t["exit_px"]} for t in tickets]
    curve = list(t159.nav(tk, bars_for_nav, f, cap=cap, d_to=d_to))
    return t159.stats(curve) if curve else None


def nav_bars(um: dict) -> dict[str, list]:
    return {s: [(d, a["o"][i], a["h"][i], a["l"][i], a["c"][i]) for i, d in enumerate(a["d"])] for s, a in um.items()}


def plus_days(d: str, k: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat()
