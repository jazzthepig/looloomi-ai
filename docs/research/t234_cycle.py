#!/usr/bin/env python3
"""T-234 · S-713 回放:⓪ 周期向量的 turning 相位在 2020 起每段 ≥ 30% BTC 回撤里亮不亮、
把敞口从 1.0 降到 0.5 有没有削掉回撤。

口径(逐字照 S-713 预注册,不改):
- ① 相位来自 `cycle_vector_daily`(表 = 预注册口径)。**表为空时**用 origin/main 上同一份
  `src/data/state/cycle_vector.py` 的 `components_by_day()` / `zscores()` 纯函数在本地重算
  (同样的源表、同样的规则、无随机性),并在结果里写明 `phase_source`;表灌满后 `--verify-table`
  逐行比对,不一致就以表为准。
- ② 事件段:BTC 现货 `ohlcv_daily(source=binance_hist)` 收盘,滚动 200 个交易日最高收盘为基准,
  回撤 `close/rolling_max − 1`;**连续**满足 ≤ −30% 的交易日为一段(不合并、不去重、不人工判断)。
- ③ 规则 R:turning ⇒ 次日敞口 0.5,normal ⇒ 1.0;窗口 2020-01-01 → 2026-10-31;成本 10bp × |Δ敞口|。
- ④ (a) 每段 turning 占比;(b) 最大三段里 R 的段内回撤相对持有浅多少;(c) 非事件段 turning 天数占比;
  (d) 全区间持有 vs R 的总收益 / MDD / Calmar,随机对照 1,000 次(同样 turning 总天数、段长从实际抽、种子 713)
  的 Calmar 分位。零分布 / 分位只用 `src/data/evaluation/apparatus.py`。
- ⑤ 副列(只报不判):去 Fed 分量 / 去资金费分量(用表里 z 自己重组 deterioration,规则不变);TURN_DAYS 1 / 5。

只读:全程 SELECT,不写库、不做 DDL。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WIN0, WIN1 = "2020-01-01", "2026-10-31"
COST = 0.001  # 10bp × |Δ敞口|
TURN_EXPOSURE = 0.5
ROLL = 200
DD_TRIGGER = -0.30
GATE_ROWS = 2000
SEED = 713
N_NULL = 1000
#: 诊断用的关键日期(各段谷 / 已知崩盘点):看 det / shift_pct 为什么没打灯
KEY_DATES = ("2020-03-12", "2020-02-19", "2021-05-19", "2021-11-08", "2022-03-30",
             "2022-06-18", "2022-11-21", "2023-01-10", "2024-08-05", "2025-10-06",
             "2025-04-08", "2026-01-29")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


apparatus = _load(REPO / "src/data/evaluation/apparatus.py", "apparatus")
cv = _load(REPO / "src/data/state/cycle_vector.py", "cycle_vector")

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}


# ── 只读取数(翻页一律带 order=) ────────────────────────────────────────────
def _get(table: str, params: dict, rng: str = "0-999") -> tuple[list[dict], str]:
    url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=dict(HEAD, Range=rng))
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
        return (json.loads(body) if body else []), (r.headers.get("content-range") or "")


def fetch(table: str, params: dict, page: int = 1000) -> list[dict]:
    out, lo = [], 0
    while True:
        chunk, _ = _get(table, params, f"{lo}-{lo + page - 1}")
        out.extend(chunk)
        if len(chunk) < page:
            return out
        lo += page


# ── ① 相位:表优先,空则本地重算(同一份代码) ───────────────────────────────
def phase_from_table() -> tuple[dict[str, dict], int]:
    rows = fetch("cycle_vector_daily",
                 {"select": "d,phase,z,shift_pct,deterioration,n_components",
                  "order": "d.asc"})
    out = {}
    for r in rows:
        z = r.get("z") or {}
        out[str(r.get("d"))[:10]] = {
            "phase": r.get("phase"), "z": z,
            "shift_pct": r.get("shift_pct"), "deterioration": r.get("deterioration"),
            "n_components": r.get("n_components"),
        }
    return out, len(rows)


def phase_local_recompute() -> tuple[dict[str, dict], int]:
    feats = ",".join(cv.STATE_FEATURES.values())
    state = fetch("state_daily", {"select": "d,entity,feature,value", "entity": "eq.panel",
                                 "order": "d.asc,feature.asc"})
    state = [r for r in state if r.get("feature") in set(cv.STATE_FEATURES.values())
             or r.get("feature") == "funding_7d_ann_binance"]
    macro = fetch("macro_daily", {"select": "d,series,value", "series": "eq.fed_net_liquidity",
                                  "order": "d.asc"})
    comps = cv.components_by_day(state, macro)
    rows = cv.zscores(comps)
    out = {}
    for r in rows:
        out[r["d"]] = {"phase": r["phase"], "z": r["z"], "shift_pct": r["shift_pct"],
                       "deterioration": r["deterioration"], "n_components": r["n_components"]}
    # 探索性变体:funding 分量换成 funding_7d_ann_binance(表里有 2020-01-05 起的完整窗口;
    # 管道当前用的 funding_7d_ann 只有 2026-09 之后有值)。同一份 components_by_day / zscores。
    state_fb = [r for r in state if r.get("feature") != "funding_7d_ann"] + \
               [{**r, "feature": "funding_7d_ann"} for r in state if r.get("feature") == "funding_7d_ann_binance"]
    out_fb = {}
    for r in cv.zscores(cv.components_by_day(state_fb, macro)):
        out_fb[r["d"]] = {"phase": r["phase"], "z": r["z"], "shift_pct": r["shift_pct"],
                          "deterioration": r["deterioration"], "n_components": r["n_components"]}
    # 分量覆盖:每个 feature 的非空天数与最早/最晚日期(解释 n_components 为什么上不去)
    cover: dict[str, dict] = {}
    for r in state:
        f = r.get("feature")
        c = cover.setdefault(f, {"n_rows": 0, "n_nonnull": 0, "first_d": None, "last_d": None})
        c["n_rows"] += 1
        d = str(r.get("d"))[:10]
        if d:
            c["first_d"] = c["first_d"] or d
            c["last_d"] = d
        if r.get("value") is not None:
            c["n_nonnull"] += 1
            c["first_nonnull_d"] = min(c.get("first_nonnull_d") or d, d)
    return out, len(rows), cover, out_fb


# ── 副列:用 z 重组 deterioration,相位规则不变(照抄 zscores 的规则) ─────────
def rephase(by_day: dict[str, dict], drop: tuple[str, ...] = (), turn_days: int = 3) -> dict[str, str]:
    days = sorted(by_day)
    phase, streak = "normal", 0
    out = {}
    for d in days:
        rec = by_day[d]
        z = {k: v for k, v in (rec.get("z") or {}).items() if k not in drop}
        det = pct = None
        if len(z) >= cv.MIN_COMPONENTS:
            det = sum(cv.SIGN[k] * v for k, v in z.items()) / len(z)
            pct = rec.get("shift_pct")
        if det is not None:
            hit = pct is not None and det <= cv.TURN_DET and pct >= cv.TURN_SHIFT_PCT
            streak = streak + 1 if hit else 0
            if phase == "normal" and streak >= turn_days:
                phase = "turning"
            elif phase == "turning" and det > cv.EXIT_DET:
                phase, streak = "normal", 0
        out[d] = phase if det is not None else None
    return out


# ── ② BTC 现货与事件段 ─────────────────────────────────────────────────────
def btc_closes() -> tuple[list[str], list[float], str]:
    for sym in ("BTC", "BTCUSDT", "BTC-USD", "BTCUSD"):
        rows = fetch("ohlcv_daily", {"select": "trade_date,symbol,source,close",
                                     "source": "eq.binance_hist", "symbol": f"eq.{sym}",
                                     "order": "trade_date.asc"})
        if rows:
            ds = [str(r.get("trade_date"))[:10] for r in rows]
            cs = [float(r["close"]) for r in rows if r.get("close") is not None]
            if len(cs) == len(ds) and cs:
                return ds, cs, f"binance_hist/{sym}"
    rows = fetch("ohlcv_daily", {"select": "trade_date,symbol,source,close",
                                 "source": "eq.binance_hist", "symbol": "like.*BTC*",
                                 "order": "symbol.asc,trade_date.asc"})
    syms = sorted({r.get("symbol") for r in rows})
    if not syms:
        raise SystemExit("找不到 BTC 现货(binance_hist)")
    sym = syms[0]
    rows = [r for r in rows if r.get("symbol") == sym]
    ds = [str(r.get("trade_date"))[:10] for r in rows]
    cs = [float(r["close"]) for r in rows if r.get("close") is not None]
    return ds, cs, f"binance_hist/{sym}"


def events(dates: list[str], closes: list[float]) -> list[dict]:
    hi, segs = [], []
    for i, c in enumerate(closes):
        w = closes[max(0, i - ROLL + 1): i + 1]
        hi.append(max(w))
    dd = [closes[i] / hi[i] - 1.0 for i in range(len(closes))]
    i = 0
    while i < len(dates):
        if dd[i] <= DD_TRIGGER:
            j = i
            while j + 1 < len(dates) and dd[j + 1] <= DD_TRIGGER:
                j += 1
            k = min(range(i, j + 1), key=lambda t: dd[t])
            p = max(range(max(0, i - ROLL), i + 1), key=lambda t: closes[t])
            segs.append({
                "start_d": dates[i], "end_d": dates[j], "days": j - i + 1,
                "peak_d": dates[p], "peak_px": closes[p],
                "trough_d": dates[k], "trough_px": closes[k],
                "depth": dd[k], "peak_to_trough_days": k - p,
                # 峰→谷跌幅(不依赖滚动窗口):用来排「最大三段」,也与簇内 dd 口径区分开
                "depth_p2t": closes[k] / closes[p] - 1.0,
            })
            i = j + 1
        else:
            i += 1
    return segs


# ── ③ 规则 R 回放 ──────────────────────────────────────────────────────────
def replay(dates: list[str], closes: list[float], phase: dict[str, str],
           turn_exposure: float = TURN_EXPOSURE) -> list[dict]:
    rows = []
    nav_h = nav_r = 1.0
    prev_exp = 1.0
    for i in range(1, len(dates)):
        d = dates[i]
        ph_prev = phase.get(dates[i - 1])
        exp = turn_exposure if ph_prev == "turning" else 1.0
        r = closes[i] / closes[i - 1] - 1.0
        rr = exp * r - COST * abs(exp - prev_exp)
        nav_h *= (1 + r)
        nav_r *= (1 + rr)
        rows.append({"d": d, "close": closes[i], "phase_prev": ph_prev, "exp": exp,
                     "r_hold": r, "r_R": rr, "nav_h": nav_h, "nav_R": nav_r})
        prev_exp = exp
    return rows


def mdd(vals: list[float]) -> float:
    peak, out = -1e18, 0.0
    for v in vals:
        peak = max(peak, v)
        out = max(out, peak - v)
    return out / peak if peak > 0 else 0.0


def mdd_pct(vals: list[float]) -> float:
    """最大回撤(百分比形式,正数)。"""
    peak, out = -1e18, 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0:
            out = max(out, (peak - v) / peak)
    return out


def stats(rows: list[dict]) -> dict:
    nav_h = [r["nav_h"] for r in rows]
    nav_r = [r["nav_R"] for r in rows]
    th = nav_h[-1] - 1.0
    tr = nav_r[-1] - 1.0
    mh, mr = mdd_pct(nav_h), mdd_pct(nav_r)
    years = len(rows) / 365.0
    return {
        "n_days": len(rows),
        "total_hold": th, "total_R": tr,
        "mdd_hold": mh, "mdd_R": mr,
        "calmar_hold": th / mh if mh > 0 else None,
        "calmar_R": tr / mr if mr > 0 else None,
        "calmar_annual_hold": (((1 + th) ** (1 / years) - 1) / mh) if mh > 0 and years > 0 else None,
        "calmar_annual_R": (((1 + tr) ** (1 / years) - 1) / mr) if mr > 0 and years > 0 else None,
    }


# ── (b) 段内:R 的路径 vs 持有 ───────────────────────────────────────────────
def segment_paths(rep: list[dict], seg: dict) -> dict:
    """段内路径:从段峰(窗口外则从窗口首日)到段谷,比 R 的净值路径与持有的净值路径的最大回撤。"""
    idx = {r["d"]: i for i, r in enumerate(rep)}
    p, t = seg["peak_d"], seg["trough_d"]
    if t not in idx:
        return {}
    i1 = idx[t]
    i0 = idx[p] if p in idx else 0
    peak_in_window = p in idx
    if i1 < i0:
        return {}
    base_h = rep[i0 - 1]["nav_h"] if i0 > 0 else 1.0
    base_r = rep[i0 - 1]["nav_R"] if i0 > 0 else 1.0
    nav_h = [1.0] + [r["nav_h"] / base_h for r in rep[i0:i1 + 1]]
    nav_r = [1.0] + [r["nav_R"] / base_r for r in rep[i0:i1 + 1]]
    mh, mr = mdd_pct(nav_h), mdd_pct(nav_r)
    return {
        "peak_d": p, "trough_d": t, "peak_in_window": peak_in_window,
        "path_from": rep[i0]["d"] if i0 < len(rep) else None,
        "depth_hold": mh, "depth_R": mr,
        "shallower_abs": mh - mr, "shallower_rel": (mh - mr) / mh if mh > 0 else None,
        "n_days": i1 - i0 + 1,
    }


# ── (d) 随机对照:同样 turning 总天数、段长从实际抽、种子 713 ───────────────
def turning_segments(phase: dict[str, str], dates: list[str]) -> list[int]:
    lens, cur = [], 0
    for d in dates:
        if phase.get(d) == "turning":
            cur += 1
        elif cur:
            lens.append(cur)
            cur = 0
    if cur:
        lens.append(cur)
    return lens


def sample_turn_days(rng: np.random.Generator, n: int, lens: list[int], total: int) -> set[int]:
    pool, chosen, s = list(lens), [], 0
    while s < total and pool:
        L = pool.pop(int(rng.integers(len(pool))))
        chosen.append(L)
        s += L
    if chosen:
        chosen[-1] = max(1, chosen[-1] - (s - total))
    gap_total = max(0, n - sum(chosen))
    k = len(chosen)
    cuts = np.sort(rng.integers(0, gap_total + 1, size=k)) if gap_total > 0 else np.array([], dtype=int)
    gaps = np.diff(np.concatenate([[0], cuts, [gap_total]])) if k else np.array([gap_total])
    days, pos = set(), int(gaps[0]) if len(gaps) else 0
    for idx, L in enumerate(chosen):
        for t in range(pos, min(n, pos + L)):
            days.add(t)
        pos += L
        pos += int(gaps[idx + 1]) if idx + 1 < len(gaps) else 0
    return days


def side_eval(w_dates, w_closes, phase, segs, widx, seed=SEED, n_null=N_NULL) -> dict:
    """副列用:与主列同一套 (a)(b)(c)(d) 计算,换一套相位就重算一遍。"""
    rep = replay(w_dates, w_closes, phase)
    st = stats(rep)
    turn_days = sum(1 for r in rep if r["phase_prev"] == "turning")
    ev_days = set()
    for s in segs:
        i0, i1 = widx.get(s["start_d"]), widx.get(s["end_d"])
        if i0 is None or i1 is None:
            continue
        ev_days.update(range(i0, i1 + 1))
    non_turn = sum(1 for i, r in enumerate(rep) if i not in ev_days and r["phase_prev"] == "turning")
    a_rows = []
    for s in segs:
        i0, i1 = widx.get(s["start_d"]), widx.get(s["end_d"])
        n = (i1 - i0 + 1) if (i0 is not None and i1 is not None) else 0
        t = sum(1 for i in range(i0, i1 + 1) if rep[i]["phase_prev"] == "turning") if n else 0
        p0 = widx.get(s["peak_d"], 0)
        pn = widx.get(s["trough_d"])
        n2 = (pn - p0 + 1) if (pn is not None and pn >= p0) else 0
        t2 = sum(1 for i in range(p0, pn + 1) if rep[i]["phase_prev"] == "turning") if n2 else 0
        a_rows.append({"turning_share": (t / n) if n else None,
                       "p2t_turning_share": (t2 / n2) if n2 else None})
    sh = [r["turning_share"] for r in a_rows if r["turning_share"] is not None]
    sh2 = [r["p2t_turning_share"] for r in a_rows if r["p2t_turning_share"] is not None]
    big = sorted(segs, key=lambda s: s["depth_p2t"])[:3]
    b_rows = [{**s, **segment_paths(rep, s)} for s in big]
    b_pass = sum(1 for b in b_rows if b.get("shallower_rel") is not None and b["shallower_rel"] >= 0.15)
    c_share = non_turn / max(1, len(rep) - len(ev_days))
    lens = turning_segments(phase, w_dates)
    n = len(rep)

    def null_fn(rng: np.random.Generator) -> float:
        ts = sample_turn_days(rng, n, lens, turn_days)
        s2 = stats(replay_with_set(rep, ts))
        return s2["calmar_R"] if s2["calmar_R"] is not None else 0.0

    try:
        null = apparatus.null_distribution(null_fn, n_null, seed, actual=st["calmar_R"])
        p_cal = apparatus.percentile_of(st["calmar_R"], null)
        null_note = None
    except apparatus.NoOpNull as e:
        p_cal, null_note = None, f"NoOpNull: {e}"
    return {
        "turning_days": turn_days,
        "a_median_cluster_share": float(np.median(sh)) if sh else None,
        "a_median_p2t_share": float(np.median(sh2)) if sh2 else None,
        "a_segs_ge_30pct": sum(1 for r in a_rows if r["turning_share"] and r["turning_share"] >= 0.30),
        "b_big3": [{k: b.get(k) for k in ("peak_d", "trough_d", "depth_p2t", "depth_hold", "depth_R",
                                         "shallower_abs", "shallower_rel", "peak_in_window", "n_days")}
                   for b in b_rows],
        "b_pass_ge_15pct": b_pass,
        "c_non_event_turning_share": c_share,
        "d_total_R": st["total_R"], "d_mdd_R": st["mdd_R"], "d_calmar_R": st["calmar_R"],
        "d_calmar_pct": p_cal, "d_null_note": null_note,
    }


def main() -> None:
    # ---- ① 相位 ----
    table, n_table = phase_from_table()
    source = "cycle_vector_daily(table)"
    by_day = table
    by_day_fb: dict = {}
    cover: dict = {}
    if n_table < GATE_ROWS:
        by_day, n_local, cover, by_day_fb = phase_local_recompute()
        source = f"local_recompute(origin/main src/data/state/cycle_vector.py zscores()) | table_rows={n_table}"
        print(f"[gate] cycle_vector_daily 只有 {n_table} 行(< {GATE_ROWS})→ 用同一份代码本地重算 {n_local} 行")
    else:
        print(f"[gate] cycle_vector_daily {n_table} 行 ≥ {GATE_ROWS} → 直接读表")

    phase_main = {d: rec["phase"] for d, rec in by_day.items()}
    # ---- ② BTC + 事件段 ----
    dates, closes, src = btc_closes()
    segs_all = events(dates, closes)
    segs = [s for s in segs_all if WIN0 <= s["start_d"] <= WIN1]
    print(f"[btc] {src} · {len(dates)} 天 {dates[0]}→{dates[-1]} · 段 {len(segs_all)}(窗口内 {len(segs)})")

    # ---- ③ 回放 ----
    win_idx = [i for i, d in enumerate(dates) if WIN0 <= d <= WIN1]
    w_dates = [dates[i] for i in win_idx]
    w_closes = [closes[i] for i in win_idx]
    rep = replay(w_dates, w_closes, phase_main)
    st = stats(rep)

    turn_days = sum(1 for r in rep if r["phase_prev"] == "turning")
    ev_days = set()
    for s in segs:
        i0 = w_dates.index(s["start_d"]) if s["start_d"] in w_dates else None
        i1 = w_dates.index(s["end_d"]) if s["end_d"] in w_dates else None
        if i0 is not None and i1 is not None:
            ev_days.update(range(i0, i1 + 1))
    non_turn = sum(1 for i, r in enumerate(rep) if i not in ev_days and r["phase_prev"] == "turning")

    # ---- ④ (a) 两种窗口:簇内(段起→段止)、峰→谷 ----
    widx = {d: i for i, d in enumerate(w_dates)}
    a_rows = []
    for s in segs:
        i0 = widx.get(s["start_d"])
        i1 = widx.get(s["end_d"])
        n = (i1 - i0 + 1) if (i0 is not None and i1 is not None) else 0
        t = sum(1 for i in range(i0, i1 + 1) if rep[i]["phase_prev"] == "turning") if n else 0
        p0 = widx.get(s["peak_d"], 0)
        pn = widx.get(s["trough_d"])
        n2 = (pn - p0 + 1) if (pn is not None and pn >= p0) else 0
        t2 = sum(1 for i in range(p0, pn + 1) if rep[i]["phase_prev"] == "turning") if n2 else 0
        a_rows.append({**s, "seg_days": n, "turning_days": t,
                       "turning_share": (t / n) if n else None,
                       "p2t_days": n2, "p2t_turning_days": t2,
                       "p2t_turning_share": (t2 / n2) if n2 else None})
    a_share = [r["turning_share"] for r in a_rows if r["turning_share"] is not None]
    a_share2 = [r["p2t_turning_share"] for r in a_rows if r["p2t_turning_share"] is not None]
    a_median = float(np.median(a_share)) if a_share else None
    a_median2 = float(np.median(a_share2)) if a_share2 else None
    a_hit = sum(1 for r in a_rows if r["turning_share"] and r["turning_share"] >= 0.30)
    a_hit2 = sum(1 for r in a_rows if r["p2t_turning_share"] and r["p2t_turning_share"] >= 0.30)

    # ---- ④ (b) 最大三段(按峰→谷跌幅排) ----
    big = sorted(segs, key=lambda s: s["depth_p2t"])[:3]
    b_rows = [{**s, **segment_paths(rep, s)} for s in big]
    b_pass = sum(1 for b in b_rows if b.get("shallower_rel") is not None and b["shallower_rel"] >= 0.15)

    # ---- ④ (c) ----
    c_share = non_turn / max(1, len(rep) - len(ev_days))

    # ---- ④ (d) 随机对照 ----
    lens = turning_segments(phase_main, w_dates)
    n = len(rep)
    day_index = {r["d"]: i for i, r in enumerate(rep)}

    def calmar_for(turn_set: set[int]) -> float:
        nav = 1.0
        prev_exp = 1.0
        for i, r in enumerate(rep):
            exp = TURN_EXPOSURE if (i - 1) in turn_set else 1.0
            rr = exp * r["r_hold"] - COST * abs(exp - prev_exp)
            nav *= (1 + rr)
            prev_exp = exp
        return nav - 1.0

    actual_calmar = st["calmar_R"]

    def null_fn(rng: np.random.Generator) -> float:
        ts = sample_turn_days(rng, n, lens, turn_days)
        r2 = replay_with_set(rep, ts)
        s2 = stats(r2)
        return s2["calmar_R"] if s2["calmar_R"] is not None else 0.0

    null = apparatus.null_distribution(null_fn, N_NULL, SEED, actual=actual_calmar)
    p_calmar = apparatus.percentile_of(actual_calmar, null)

    # ---- ⑤ 副列(只报不判) ----
    variants = {}
    for name, kwargs in (("drop_fed", {"drop": ("fed_liq_60d",)}),
                         ("drop_funding", {"drop": ("funding",)}),
                         ("turn_days_1", {"turn_days": 1}),
                         ("turn_days_5", {"turn_days": 5})):
        variants[name] = side_eval(w_dates, w_closes, rephase(by_day, **kwargs), segs, widx)
    # 探索性副列(不是预注册的 ⑤,只报):funding 分量换成 funding_7d_ann_binance
    if by_day_fb:
        variants["exploratory_funding_binance"] = side_eval(
            w_dates, w_closes, {d: r["phase"] for d, r in by_day_fb.items()}, segs, widx)
        variants["exploratory_funding_binance"]["n_components_hist"] = {}
        for d in w_dates:
            v = by_day_fb.get(d, {}).get("n_components")
            variants["exploratory_funding_binance"]["n_components_hist"][str(v)] = \
                variants["exploratory_funding_binance"]["n_components_hist"].get(str(v), 0) + 1

    # ---- 诊断:相位落在哪儿(不判,只看) ----
    turn_runs, cur = [], None
    for r in rep:
        if r["phase_prev"] == "turning":
            if cur is None:
                cur = {"start_d": r["d"], "end_d": r["d"], "days": 0}
            cur["days"] += 1
            cur["end_d"] = r["d"]
        else:
            if cur:
                turn_runs.append(cur)
                cur = None
    if cur:
        turn_runs.append(cur)
    per_year: dict[str, dict] = {}
    for r in rep:
        y = r["d"][:4]
        per_year.setdefault(y, {"days": 0, "turning": 0})
        per_year[y]["days"] += 1
        if r["phase_prev"] == "turning":
            per_year[y]["turning"] += 1
    lead = []
    for s in segs:
        i0 = widx.get(s["start_d"])
        if i0 is None:
            continue
        before = sum(1 for i in range(max(0, i0 - 90), i0) if rep[i]["phase_prev"] == "turning")
        inside = sum(1 for i in range(i0, min(len(rep), i0 + 90)) if rep[i]["phase_prev"] == "turning")
        lead.append({"seg_start": s["start_d"], "depth_p2t": s["depth_p2t"],
                     "turning_90d_before": before, "turning_90d_from_start": inside})
    nc: dict[str, int] = {}
    for d in w_dates:
        v = by_day.get(d, {}).get("n_components")
        nc[str(v)] = nc.get(str(v), 0) + 1
    # 自检:副列的重算(无 drop、TURN_DAYS=3)必须与主列 phase 逐日一致
    ph_self = rephase(by_day)
    self_check_mismatch = sum(1 for d in w_dates if ph_self.get(d) != phase_main.get(d))
    diag = {
        "turning_runs": turn_runs,
        "turning_runs_n": len(turn_runs),
        "turning_days_per_year": per_year,
        "n_components_hist": nc,
        "rephase_selfcheck_mismatch_days": self_check_mismatch,
        "turning_vs_segment": lead,
        "feature_coverage": cover,
        "key_dates": {d: by_day.get(d) for d in KEY_DATES},
    }

    # ---- 落盘 ----
    out = {
        "card": "T-234", "prereg": "S-713", "generated_at": "2026-11-04 (lane-c)",
        "phase_source": source, "phase_rows_table": n_table,
        "phase_rows_used": len(by_day),
        "window": [WIN0, WIN1], "n_trading_days": len(rep),
        "btc_source": src, "cost_bp": COST * 10000, "turn_exposure": TURN_EXPOSURE,
        "gate_rows_required": GATE_ROWS,
        "segments_all": len(segs_all), "segments_in_window": len(segs),
        "segments": a_rows,
        "a_median_segment_turning_share": a_median,
        "a_median_p2t_turning_share": a_median2,
        "a_segments_with_share_ge_30pct": a_hit,
        "a_segments_p2t_share_ge_30pct": a_hit2,
        "b_big3": b_rows,
        "b_segments_rel_shallower_ge_15pct": b_pass,
        "diagnostics": diag,
        "c_non_event_turning_share": c_share,
        "d_hold_vs_R": st,
        "d_null": {"n": N_NULL, "seed": SEED, "calmar_pct": p_calmar,
                   "null_median": float(np.median(null)),
                   "null_q95": float(np.quantile(null, 0.95)),
                   "actual_calmar": actual_calmar},
        "turning_days_total": turn_days,
        "variants": variants,
    }
    (HERE / "t234_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: out[k] for k in ("phase_source", "segments_in_window", "a_median_segment_turning_share",
                                          "c_non_event_turning_share", "d_hold_vs_R", "d_null")},
                     ensure_ascii=False, indent=2))


def replay_with_set(rep: list[dict], turn_set: set[int]) -> list[dict]:
    out = []
    nav = 1.0
    prev_exp = 1.0
    for i, r in enumerate(rep):
        exp = TURN_EXPOSURE if (i - 1) in turn_set else 1.0
        rr = exp * r["r_hold"] - COST * abs(exp - prev_exp)
        nav *= (1 + rr)
        out.append({**r, "r_R": rr, "nav_R": nav})
        prev_exp = exp
    return out


if __name__ == "__main__":
    main()
