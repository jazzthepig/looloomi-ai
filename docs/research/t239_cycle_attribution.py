#!/usr/bin/env python3
"""T-239 · S-720 —— ⓪ 周期向量 v1.1:两段 turning 的归因 + 三段最大回撤的分量走势
+ v2 规则(杠杆类分量取 z 的 30 日变化并取负号)重打相位。

预注册(S-720 原文)逐字写在 docs/research/T-239_cycle_attribution.md 开头,先写后算,只算一次。

只读:全程 SELECT,不写库、不做 DDL、不改代码。
事件段切法 / 窗口 / 回放 / 随机对照机械照 T-234 的脚本(docs/research/t234_cycle.py —— 直接 import 同一份函数);
零分布与分位只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t234 = _load(HERE / "t234_cycle.py", "t234_cycle")
apparatus = t234.apparatus
cv = t234.cv

WIN0, WIN1 = "2021-02-01", "2026-10-31"
SEED = 720          # S-720:随机对照种子 720(S-713 用的是 713)
N_NULL = 1000
TURN_SEGS = [("2023-06-17", "2023-10-21"), ("2025-01-15", "2025-04-19")]
DD_SEGS = [("2021-11-08", "2022-06-18"), ("2021-04-13", "2021-07-20"), ("2025-10-06", "2026-02-05")]
LEVEL = ("fed_liq_60d", "stable_supply_30d", "breadth", "taker_buy", "mom_60")
LEV = ("funding", "oi_chg", "lend_apy", "vratio")
ALL_COMP = LEVEL + LEV
COMPS = ("stable_supply_30d", "fed_liq_60d", "breadth", "taker_buy", "mom_60",
         "funding", "oi_chg", "lend_apy", "vratio")


# ── 30 日变化的时点对齐:dz30(t) = z(t) − z(t'),t' = ≤ (t − 30 日历天) 的最近一行 ──
def build_idx30(by_day: dict[str, dict]) -> dict[str, str | None]:
    days = sorted(by_day)
    out: dict[str, str | None] = {}
    for d in days:
        back = (date.fromisoformat(d) - timedelta(days=30)).isoformat()
        j = bisect_right(days, back) - 1
        out[d] = days[j] if j >= 0 else None
    return out


IDX30: dict[str, str | None] = {}


def z_of(by_day: dict[str, dict], d: str | None) -> dict:
    if not d:
        return {}
    return (by_day.get(d) or {}).get("z") or {}


def dz30(by_day: dict[str, dict], d: str, k: str) -> float | None:
    """z 的 30 日变化。"""
    z1, z0 = z_of(by_day, d), z_of(by_day, IDX30.get(d))
    if k in z1 and k in z0:
        return z1[k] - z0[k]
    return None


# ── ① 归因:逐日把 deterioration 拆成 SIGN × z / n ──────────────────────────
def day_contribs(by_day: dict[str, dict], d: str) -> tuple[dict[str, float], int]:
    z = z_of(by_day, d)
    n = len(z)
    if n == 0:
        return {}, 0
    return {k: cv.SIGN[k] * v / n for k, v in z.items()}, n


def seg_attribution(by_day: dict[str, dict], d0: str, d1: str, label: str) -> dict:
    days = [d for d in sorted(by_day) if d0 <= d <= d1]
    acc: dict[str, list[float]] = {k: [] for k in ALL_COMP}
    zs: dict[str, list[float]] = {k: [] for k in ALL_COMP}
    dz: dict[str, list[float]] = {k: [] for k in ALL_COMP}
    dets = []
    for d in days:
        c, n = day_contribs(by_day, d)
        dets.append(sum(c.values()) if c else None)
        for k in ALL_COMP:
            if k in c:
                acc[k].append(c[k])
            zz = z_of(by_day, d).get(k)
            if zz is not None:
                zs[k].append(zz)
            d30 = dz30(by_day, d, k)
            if d30 is not None:
                dz[k].append(d30)
    rows = []
    for k in ALL_COMP:
        mc = float(np.mean(acc[k])) if acc[k] else None
        rows.append({
            "component": k, "sign_v1": cv.SIGN[k],
            "mean_contrib": mc,
            "contrib_sign": (None if mc is None else ("neg" if mc < 0 else "pos")),
            "mean_z": float(np.mean(zs[k])) if zs[k] else None,
            "mean_dz30": float(np.mean(dz[k])) if dz[k] else None,
            "n_days_present": len(acc[k]), "n_days": len(days),
        })
    ranked = sorted([r for r in rows if r["mean_contrib"] is not None], key=lambda r: r["mean_contrib"])
    return {
        "label": label, "seg": [d0, d1], "n_days": len(days),
        "deterioration_mean": float(np.mean([x for x in dets if x is not None])) if dets else None,
        "deterioration_min": float(np.min([x for x in dets if x is not None])) if dets else None,
        "deterioration_max": float(np.max([x for x in dets if x is not None])) if dets else None,
        "components": rows,
        "top3_most_negative": [r["component"] for r in ranked[:3]],
        "top3_detail": ranked[:3],
    }


# ── ② 回撤段:峰前 60 天 → 谷,逐分量的 z 起点 / 峰 / 谷 + 30 日变化 ────────────
def dd_attribution(by_day: dict[str, dict], peak: str, trough: str) -> dict:
    start = (date.fromisoformat(peak) - timedelta(days=60)).isoformat()
    days = [d for d in sorted(by_day) if start <= d <= trough]
    acc: dict[str, list[float]] = {k: [] for k in ALL_COMP}
    for d in days:
        c, _ = day_contribs(by_day, d)
        for k in ALL_COMP:
            if k in c:
                acc[k].append(c[k])
    rows = []
    for k in ALL_COMP:
        rows.append({
            "component": k, "sign_v1": cv.SIGN[k],
            "z_start": z_of(by_day, start).get(k),
            "z_peak": z_of(by_day, peak).get(k),
            "z_trough": z_of(by_day, trough).get(k),
            "dz30_start": dz30(by_day, start, k),
            "dz30_peak": dz30(by_day, peak, k),
            "dz30_trough": dz30(by_day, trough, k),
            "mean_contrib": float(np.mean(acc[k])) if acc[k] else None,
        })
    ranked = sorted([r for r in rows if r["mean_contrib"] is not None], key=lambda r: r["mean_contrib"])
    return {
        "peak_d": peak, "trough_d": trough, "window_start": start, "n_days": len(days),
        "components": rows,
        "top3_most_negative": [r["component"] for r in ranked[:3]],
    }


# ── ③ 九分量 × {turning 段 / 回撤段 / 其余}:z 均值与 30 日变化均值 ─────────────
def group_table(by_day: dict[str, dict], win_days: list[str], turn_days_set: set[str],
                dd_days_set: set[str], ev_days_set: set[str]) -> list[dict]:
    groups = {
        "turning": [d for d in win_days if d in turn_days_set],
        "dd_big3": [d for d in win_days if d in dd_days_set],
        "rest": [d for d in win_days if d not in turn_days_set and d not in dd_days_set],
    }
    groups["events_all"] = [d for d in win_days if d in ev_days_set]
    rows = []
    for k in ALL_COMP:
        row = {"component": k, "sign_v1": cv.SIGN[k]}
        for gname, ds in groups.items():
            zz = [z_of(by_day, d).get(k) for d in ds]
            zz = [x for x in zz if x is not None]
            dd = [dz30(by_day, d, k) for d in ds]
            dd = [x for x in dd if x is not None]
            row[f"{gname}_n"] = len(ds)
            row[f"{gname}_mean_z"] = float(np.mean(zz)) if zz else None
            row[f"{gname}_mean_dz30"] = float(np.mean(dd)) if dd else None
        allz = [z_of(by_day, d).get(k) for d in win_days]
        allz = [x for x in allz if x is not None]
        alld = [dz30(by_day, d, k) for d in win_days]
        alld = [x for x in alld if x is not None]
        row["all_mean_z"] = float(np.mean(allz)) if allz else None
        row["all_mean_dz30"] = float(np.mean(alld)) if alld else None
        rows.append(row)
    return rows


# ── ④ v2 规则:deterioration_v2(杠杆类分量取 z 的 30 日变化并取负号) ────────────
def v2_values(by_day: dict[str, dict], d: str) -> dict[str, float]:
    """v2 的逐分量贡献:五个流动性/广度/动量分量照旧取水平 z;四个杠杆类分量取 −(z 的 30 日变化)。"""
    z1 = z_of(by_day, d)
    z0 = z_of(by_day, IDX30.get(d))
    vals: dict[str, float] = {}
    for k in LEVEL:
        if k in z1:
            vals[k] = cv.SIGN[k] * z1[k]
    for k in LEV:
        if k in z1 and k in z0:
            vals[k] = cv.SIGN[k] * (z1[k] - z0[k])   # SIGN = −1 ⇒ 升(z 变高)= 负贡献 = 坏
    return vals


def rephase_v2(by_day: dict[str, dict], turn_days: int = 3, drop: tuple[str, ...] = ()) -> tuple[dict[str, str], dict[str, float | None]]:
    """相位规则逐字照 S-713:恶化 ≤ −0.5 且 shift_pct ≥ 0.75 连续 N 天进;恶化 > 0 出(滞回)。
    shift / shift_pct 不变(照表里的水平 z 版本)。返回 (phase_by_day, det_v2_by_day)。"""
    phase, streak = "normal", 0
    out: dict[str, str] = {}
    dets: dict[str, float | None] = {}
    for d in sorted(by_day):
        rec = by_day[d]
        vals = {k: v for k, v in v2_values(by_day, d).items() if k not in drop}
        det = pct = None
        if len(vals) >= cv.MIN_COMPONENTS:
            det = sum(vals.values()) / len(vals)
            pct = rec.get("shift_pct")
        dets[d] = det
        if det is not None:
            hit = pct is not None and det <= cv.TURN_DET and pct >= cv.TURN_SHIFT_PCT
            streak = streak + 1 if hit else 0
            if phase == "normal" and streak >= turn_days:
                phase = "turning"
            elif phase == "turning" and det > cv.EXIT_DET:
                phase, streak = "normal", 0
        out[d] = phase if det is not None else None
    return out, dets


# ── ⑤ (a)–(d) 判据(逐字照 S-713) ──────────────────────────────────────────
def judge(phase: dict[str, str], dates: list[str], closes: list[float], segs: list[dict],
          widx: dict[str, int], seed: int = SEED, n_null: int = N_NULL) -> dict:
    rep = t234.replay(dates, closes, phase)
    st = t234.stats(rep)
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
        a_rows.append({**s, "seg_days": n, "turning_days": t,
                       "turning_share": (t / n) if n else None,
                       "p2t_days": n2, "p2t_turning_days": t2,
                       "p2t_turning_share": (t2 / n2) if n2 else None})
    sh = [r["turning_share"] for r in a_rows if r["turning_share"] is not None]
    sh2 = [r["p2t_turning_share"] for r in a_rows if r["p2t_turning_share"] is not None]
    big = sorted(segs, key=lambda s: s["depth_p2t"])[:3]
    b_rows = [{**s, **t234.segment_paths(rep, s)} for s in big]
    b_pass = sum(1 for b in b_rows if b.get("shallower_rel") is not None and b["shallower_rel"] >= 0.15)
    c_share = non_turn / max(1, len(rep) - len(ev_days))
    lens = t234.turning_segments(phase, dates)
    n = len(rep)

    def null_fn(rng: np.random.Generator) -> float:
        ts = t234.sample_turn_days(rng, n, lens, turn_days)
        s2 = t234.stats(t234.replay_with_set(rep, ts))
        return s2["calmar_R"] if s2["calmar_R"] is not None else 0.0

    null_note = None
    try:
        null = apparatus.null_distribution(null_fn, n_null, seed, actual=st["calmar_R"])
        p_cal = apparatus.percentile_of(st["calmar_R"], null)
    except apparatus.NoOpNull as e:
        null = np.array([])
        p_cal = None
        null_note = f"NoOpNull: {e}"
    a_pass = (float(np.median(sh2)) if sh2 else None)
    return {
        "turning_days": turn_days,
        "a_median_cluster_share": float(np.median(sh)) if sh else None,
        "a_median_p2t_share": a_pass,
        "a_segs_ge_30pct": sum(1 for r in a_rows if r["turning_share"] and r["turning_share"] >= 0.30),
        "a_rows": a_rows,
        "b_big3": [{k: b.get(k) for k in ("peak_d", "trough_d", "depth_p2t", "depth_hold", "depth_R",
                                         "shallower_abs", "shallower_rel", "peak_in_window", "n_days")}
                   for b in b_rows],
        "b_pass_ge_15pct": b_pass,
        "c_non_event_turning_share": c_share,
        "d_stats": st,
        "d_calmar_pct": p_cal,
        "d_null_median": float(np.median(null)) if len(null) else None,
        "d_null_q95": float(np.quantile(null, 0.95)) if len(null) else None,
        "d_null_note": null_note,
        "n_null": n_null, "seed": seed,
    }


def verdict(j: dict) -> dict:
    """(a) 只报不单判;其余三条按 S-713 原文判。"""
    a_share = j["a_median_p2t_share"]
    b_ok = j["b_pass_ge_15pct"] >= 2
    c_ok = j["c_non_event_turning_share"] <= 0.15
    d_ok = (j["d_calmar_pct"] is not None) and (j["d_calmar_pct"] >= 0.95)
    return {
        "a_reported": a_share, "a_note": "报,不单判",
        "b_pass_ge_15pct": j["b_pass_ge_15pct"], "b_ok": b_ok,
        "c_non_event_share": j["c_non_event_turning_share"], "c_ok": c_ok,
        "d_calmar_pct": j["d_calmar_pct"], "d_ok": d_ok,
        "all_pass": bool(b_ok and c_ok and d_ok),
    }


def phase_runs(phase: dict[str, str], dates: list[str]) -> list[dict]:
    runs, cur = [], None
    for d in dates:
        if phase.get(d) == "turning":
            if cur is None:
                cur = {"start_d": d, "end_d": d, "days": 0}
            cur["days"] += 1
            cur["end_d"] = d
        else:
            if cur:
                runs.append(cur)
                cur = None
    if cur:
        runs.append(cur)
    return runs


def main() -> None:
    global IDX30
    # ---- ① 相位(表 = 预注册口径;gate 口径照 T-234) ----
    table, n_table, tinfo = t234.phase_from_table()
    by_day = table
    source = f"cycle_vector_daily(table, code_ref={tinfo['code_ref_used']})"
    if n_table < t234.GATE_ROWS:
        by_day, n_local, cover, _fb = t234.phase_local_recompute()
        source = f"local_recompute(origin/main cycle_vector.py) | table_rows={n_table}"
        print(f"[gate] 表只有 {n_table} 行 → 本地重算 {n_local} 行")
    else:
        print(f"[gate] 表 {n_table} 行 ≥ {t234.GATE_ROWS} → 直接读表 (code_ref={tinfo['code_ref_used']})")
    IDX30 = build_idx30(by_day)
    phase_v1 = {d: rec["phase"] for d, rec in by_day.items()}

    # ---- 原始分量(不是 z):查「推手」是真的还是采集口径的台阶 ----
    raw_rows = t234.fetch("cycle_vector_daily",
                           {"select": "d,components,code_ref", "code_ref": f"like.{tinfo.get('code_ref_used')}*",
                            "order": "d.asc"})
    raw_by_day = {str(r.get("d"))[:10]: (r.get("components") or {}) for r in raw_rows}
    # 大跳变(相对前一日 ±25% 以上的相对跳)—— 采集口径换手会在这里露出来
    jumps: dict[str, list] = {k: [] for k in ALL_COMP}
    rdays = sorted(raw_by_day)
    for i, d in enumerate(rdays):
        if i == 0:
            continue
        p = raw_by_day[rdays[i - 1]]
        for k in ALL_COMP:
            a, b = p.get(k), raw_by_day[d].get(k)
            if a is None or b is None or a == 0:
                continue
            if abs(b - a) / abs(a) >= 0.25:
                jumps[k].append({"d": d, "from": a, "to": b, "rel": (b - a) / abs(a)})
    raw_diag = {
        "key_dates": {},
        "jump_counts": {k: len(v) for k, v in jumps.items()},
        "largest_jumps": {k: sorted(v, key=lambda x: -abs(x["rel"]))[:3] for k, v in jumps.items() if v},
        "segments": [],
    }
    for d0, d1 in TURN_SEGS:
        seg = [d for d in rdays if d0 <= d <= d1]
        pre = [d for d in rdays if (date.fromisoformat(d0) - timedelta(days=180)).isoformat() <= d < d0]
        row = {"seg": [d0, d1], "raw": {}}
        for k in ALL_COMP:
            sv = [raw_by_day[d].get(k) for d in seg]
            sv = [x for x in sv if x is not None]
            pv = [raw_by_day[d].get(k) for d in pre]
            pv = [x for x in pv if x is not None]
            row["raw"][k] = {
                "seg_first": raw_by_day.get(d0, {}).get(k), "seg_last": raw_by_day.get(d1, {}).get(k),
                "seg_min": min(sv) if sv else None, "seg_max": max(sv) if sv else None,
                "pre180_median": float(np.median(pv)) if pv else None,
                "pre180_min": min(pv) if pv else None, "pre180_max": max(pv) if pv else None,
                "n": len(sv),
            }
        raw_diag["segments"].append(row)
    for d in ("2021-09-09", "2021-11-08", "2022-06-18", "2023-06-16", "2023-10-20",
              "2025-01-14", "2025-04-18", "2025-10-06", "2026-02-05"):
        raw_diag["key_dates"][d] = raw_by_day.get(d)
    # 扩张窗口的均值 / 标准差 / 样本数(照 cycle_vector.zscores 的算法,只用 ≤ d 的历史)
    KEYD = ("2023-06-16", "2025-01-14", "2021-11-08", "2025-10-06")
    sums: dict[str, float] = {}
    sq: dict[str, float] = {}
    cnt: dict[str, int] = {}
    exp_at: dict[str, dict] = {}
    for d in rdays:
        row = raw_by_day[d]
        for k in ALL_COMP:
            v = row.get(k)
            if v is None:
                continue
            sums[k] = sums.get(k, 0.0) + v
            sq[k] = sq.get(k, 0.0) + v * v
            cnt[k] = cnt.get(k, 0) + 1
        if d in KEYD:
            exp_at[d] = {}
            for k in ALL_COMP:
                n = cnt.get(k, 0)
                if n < 2:
                    continue
                m = sums[k] / n
                var = sq[k] / n - m * m
                sd = float(np.sqrt(var)) if var > 1e-18 else 0.0
                exp_at[d][k] = {"mean": m, "sd": sd, "n": n,
                                "raw": row.get(k),
                                "gap_sd": ((row.get(k) - m) / sd) if sd > 0 and row.get(k) is not None else None}
    raw_diag["expanding_stats"] = exp_at
    # 分量原始值的年度分布(看有没有口径台阶)
    per_year_raw: dict[str, dict] = {}
    for d in rdays:
        y = d[:4]
        for k in ALL_COMP:
            v = raw_by_day[d].get(k)
            if v is None:
                continue
            per_year_raw.setdefault(k, {}).setdefault(y, []).append(v)
    raw_diag["per_year_raw"] = {
        k: {y: {"n": len(v), "min": float(np.min(v)), "max": float(np.max(v)), "median": float(np.median(v))}
            for y, v in sorted(ys.items())} for k, ys in per_year_raw.items()}

    # ---- 前向预期的经验基准(给 scenarios/lane-c-T-239.json 校概率用) ----
    calib: dict = {}
    tb = [(d, raw_by_day[d]["taker_buy"]) for d in rdays if raw_by_day[d].get("taker_buy") is not None]
    tb = [(d, v) for d, v in tb if d >= "2022-01-25"]
    calib["taker_buy"] = {
        "n": len(tb), "first": tb[0][0], "last": tb[-1][0],
        "last_value": tb[-1][1],
        "frac_gt_0_49": sum(1 for _, v in tb if v > 0.49) / len(tb),
        "frac_le_0_485": sum(1 for _, v in tb if v <= 0.485) / len(tb),
        "frac_le_0_484": sum(1 for _, v in tb if v <= 0.484) / len(tb),
        "min": min(v for _, v in tb), "max": max(v for _, v in tb),
    }
    br = [(d, raw_by_day[d]["breadth"]) for d in rdays if raw_by_day[d].get("breadth") is not None]
    br = [(d, v) for d, v in br if d >= WIN0]
    calib["breadth"] = {
        "n": len(br), "first": br[0][0], "last": br[-1][0], "last_value": br[-1][1],
        "frac_gt_0_20": sum(1 for _, v in br if v > 0.20) / len(br),
        "frac_le_0_0417": sum(1 for _, v in br if v <= 0.0417) / len(br),
        "min": min(v for _, v in br), "max": max(v for _, v in br),
    }
    # BTC:41 个日历天之后的收益分布(用历史上可得的起点;BTC 序列在下面才取)
    raw_diag["forward_calibration"] = calib

    # ---- 归因的分族小计:流动性/广度/动量族 vs 杠杆族 ----
    def fam_split(d0: str, d1: str) -> dict:
        fl, lv, n_tot = [], [], []
        for d in sorted(by_day):
            if not (d0 <= d <= d1):
                continue
            c, n = day_contribs(by_day, d)
            if not c:
                continue
            fl.append(sum(v for k, v in c.items() if k in LEVEL))
            lv.append(sum(v for k, v in c.items() if k in LEV))
            n_tot.append(sum(c.values()))
        if not n_tot:
            return {}
        net = float(np.mean(n_tot))
        f, l = float(np.mean(fl)), float(np.mean(lv))
        return {"n_days": len(n_tot), "net_mean": net, "flow_family_mean": f, "lev_family_mean": l,
                "flow_share_of_net": (f / net) if net else None,
                "lev_offset_pct_of_flow": (-l / abs(f)) if f else None}
    raw_diag["family_split"] = {
        **{f"turning{i+1}_{d0}": fam_split(d0, d1) for i, (d0, d1) in enumerate(TURN_SEGS)},
        **{f"dd_{p}_{t}": fam_split((date.fromisoformat(p) - timedelta(days=60)).isoformat(), t) for p, t in DD_SEGS},
        "window_all": fam_split(WIN0, WIN1),
    }
    # ---- v2 的恶化分在关键日上的取值与分量构成(需要 phase_v2,放到后面填) ----

    # ---- ② BTC + 事件段(照 T-234) ----
    dates, closes, src = t234.btc_closes()
    # BTC 前瞻 41 日的收益分布(给 scenarios 的价格带概率校准)
    fwd = []
    for i, d in enumerate(dates):
        if not (WIN0 <= d <= "2026-09-20"):
            continue
        j = bisect_right(dates, (date.fromisoformat(d) + timedelta(days=41)).isoformat()) - 1
        if j > i:
            fwd.append(closes[j] / closes[i] - 1.0)
    cur_px = closes[-1]
    lo_b, hi_b = 70000 / cur_px - 1.0, 95000 / cur_px - 1.0
    raw_diag["forward_calibration"]["btc_fwd41"] = {
        "n": len(fwd), "last_px": cur_px, "band_lo_ret": lo_b, "band_hi_ret": hi_b,
        "frac_in_band": sum(1 for x in fwd if lo_b <= x <= hi_b) / len(fwd),
        "q10": float(np.quantile(fwd, 0.10)), "median": float(np.median(fwd)), "q90": float(np.quantile(fwd, 0.90)),
    }
    segs_all = t234.events(dates, closes)
    segs = [s for s in segs_all if WIN0 <= s["start_d"] <= WIN1]
    win_idx = [i for i, d in enumerate(dates) if WIN0 <= d <= WIN1]
    w_dates = [dates[i] for i in win_idx]
    w_closes = [closes[i] for i in win_idx]
    widx = {d: i for i, d in enumerate(w_dates)}
    print(f"[btc] {src} · 段 {len(segs_all)}(窗口内 {len(segs)}) · 窗口 {len(w_dates)} 天")

    # ---- 自检:我的 judge() 在 v1 相位上须与 T-234 的 side_eval 一致 ----
    selfcheck = {}
    j_v1 = judge(phase_v1, w_dates, w_closes, segs, widx, seed=SEED)
    se_v1 = t234.side_eval(w_dates, w_closes, phase_v1, segs, widx, seed=SEED)
    selfcheck["c_share_match"] = abs((j_v1["c_non_event_turning_share"] or 0) - (se_v1["c_non_event_turning_share"] or 0)) < 1e-12
    selfcheck["b_pass_match"] = j_v1["b_pass_ge_15pct"] == se_v1["b_pass_ge_15pct"]
    selfcheck["calmar_pct_match"] = ((j_v1["d_calmar_pct"] is None and se_v1["d_calmar_pct"] is None) or
                                     abs((j_v1["d_calmar_pct"] or 0) - (se_v1["d_calmar_pct"] or 0)) < 1e-12)
    selfcheck["turn_days_match"] = j_v1["turning_days"] == se_v1["turning_days"]
    selfcheck["v1_judge"] = {k: j_v1[k] for k in ("turning_days", "a_median_p2t_share", "b_pass_ge_15pct",
                                                 "c_non_event_turning_share", "d_calmar_pct")}
    # 另:T-234 的 rephase(照抄 zscores 规则)须与表里的 phase 逐日一致
    ph_self = t234.rephase(by_day)
    selfcheck["rephase_mismatch_days"] = sum(1 for d in w_dates if ph_self.get(d) != phase_v1.get(d))

    # ---- ③ 归因 ①:两段 turning ----
    turn_attr = [seg_attribution(by_day, d0, d1, f"turning{i+1}") for i, (d0, d1) in enumerate(TURN_SEGS)]
    runs_v1 = phase_runs(phase_v1, w_dates)
    turn_attr_meta = {
        "v1_turning_runs": runs_v1,
        "card_segments_match_v1_runs": sorted([r["start_d"] for r in runs_v1]) == sorted([s[0] for s in TURN_SEGS]),
    }
    # ---- ④ 归因 ②:三段最大回撤 ----
    dd_attr = [dd_attribution(by_day, p, t) for p, t in DD_SEGS]
    seg_by_pair = {(s["peak_d"], s["trough_d"]): s for s in segs_all}
    dd_attr_meta = [{"pair": [p, t], "in_t234_segments": (p, t) in seg_by_pair,
                     "depth_p2t": seg_by_pair[(p, t)]["depth_p2t"] if (p, t) in seg_by_pair else None}
                    for p, t in DD_SEGS]
    # ---- ⑤ 归因 ③:九分量 × 三组 ----
    turn_set = set()
    for d0, d1 in TURN_SEGS:
        turn_set.update(d for d in sorted(by_day) if d0 <= d <= d1)
    dd_set = set()
    for p, t in DD_SEGS:
        start = (date.fromisoformat(p) - timedelta(days=60)).isoformat()
        dd_set.update(d for d in sorted(by_day) if start <= d <= t)
    ev_set = set()
    for s in segs:
        i0, i1 = widx.get(s["start_d"]), widx.get(s["end_d"])
        if i0 is not None and i1 is not None:
            ev_set.update(w_dates[i0:i1 + 1])
    comp_table = group_table(by_day, w_dates, turn_set, dd_set, ev_set)

    # ---- ⑥ v2 规则 ----
    phase_v2, det_v2 = rephase_v2(by_day, 3)
    # v2 的恶化分在关键日上的取值与分量构成
    KEYD2 = ("2021-11-08", "2022-06-18", "2021-04-13", "2021-07-20",
             "2025-10-06", "2026-02-05", "2023-06-16", "2023-10-20", "2025-01-14", "2025-04-18")
    raw_diag["v2_key_dates"] = {
        d: {"det_v1_table": (by_day.get(d) or {}).get("deterioration"),
            "det_v2": det_v2.get(d),
            "shift_pct": (by_day.get(d) or {}).get("shift_pct"),
            "phase_v1": (by_day.get(d) or {}).get("phase"),
            "phase_v2": phase_v2.get(d),
            "v2_contribs": v2_values(by_day, d)}
        for d in KEYD2}
    # v2 恶化分在三段回撤窗口内 vs 窗口其余
    dd_win = set()
    for p, t in DD_SEGS:
        st_ = (date.fromisoformat(p) - timedelta(days=60)).isoformat()
        dd_win.update(d for d in sorted(by_day) if st_ <= d <= t)
    dvv = [(d, det_v2.get(d)) for d in w_dates if det_v2.get(d) is not None]
    in_dd = [v for d, v in dvv if d in dd_win]
    out_dd = [v for d, v in dvv if d not in dd_win]
    raw_diag["det_v2_by_group"] = {
        "dd_big3_mean": float(np.mean(in_dd)) if in_dd else None,
        "dd_big3_min": float(np.min(in_dd)) if in_dd else None,
        "dd_big3_n": len(in_dd),
        "rest_mean": float(np.mean(out_dd)) if out_dd else None,
        "rest_min": float(np.min(out_dd)) if out_dd else None,
        "rest_n": len(out_dd),
    }
    # 哪个条件在卡:恶化 ≤ −0.5 与搬家分位 ≥ 0.75,在各段里分别有多少天成立
    def cond_split(d0: str, d1: str) -> dict:
        ds = [d for d in w_dates if d0 <= d <= d1]
        d1s = [(by_day.get(d) or {}).get("deterioration") for d in ds]
        d1s = [x for x in d1s if x is not None]
        sp = [(by_day.get(d) or {}).get("shift_pct") for d in ds]
        sp = [x for x in sp if x is not None]
        d2s = [det_v2.get(d) for d in ds]
        d2s = [x for x in d2s if x is not None]
        both1 = sum(1 for d in ds
                    if (by_day.get(d) or {}).get("deterioration") is not None
                    and (by_day.get(d) or {}).get("deterioration") <= cv.TURN_DET
                    and (by_day.get(d) or {}).get("shift_pct") is not None
                    and (by_day.get(d) or {}).get("shift_pct") >= cv.TURN_SHIFT_PCT)
        both2 = sum(1 for d in ds
                    if det_v2.get(d) is not None and det_v2[d] <= cv.TURN_DET
                    and (by_day.get(d) or {}).get("shift_pct") is not None
                    and (by_day.get(d) or {}).get("shift_pct") >= cv.TURN_SHIFT_PCT)
        return {"n_days": len(ds),
                "v1_det_le_-0.5_days": sum(1 for x in d1s if x <= cv.TURN_DET),
                "v1_det_min": float(np.min(d1s)) if d1s else None,
                "v1_shiftpct_ge_0.75_days": sum(1 for x in sp if x >= cv.TURN_SHIFT_PCT),
                "v1_shiftpct_max": float(np.max(sp)) if sp else None,
                "v1_both_days": both1,
                "v2_det_le_-0.5_days": sum(1 for x in d2s if x <= cv.TURN_DET),
                "v2_det_min": float(np.min(d2s)) if d2s else None,
                "v2_both_days": both2}
    raw_diag["condition_split"] = {
        **{f"turning{i+1}": cond_split(d0, d1) for i, (d0, d1) in enumerate(TURN_SEGS)},
        **{f"dd_{p}_{t}": cond_split((date.fromisoformat(p) - timedelta(days=60)).isoformat(), t)
           for p, t in DD_SEGS},
        "window_all": cond_split(WIN0, WIN1),
    }
    j_v2 = judge(phase_v2, w_dates, w_closes, segs, widx, seed=SEED)
    v_v2 = verdict(j_v2)
    variants = {}
    for nm, td in (("turn_days_1", 1), ("turn_days_5", 5)):
        ph, _ = rephase_v2(by_day, td)
        jv = judge(ph, w_dates, w_closes, segs, widx, seed=SEED)
        variants[nm] = {**{k: jv[k] for k in ("turning_days", "a_median_p2t_share", "b_pass_ge_15pct",
                                              "c_non_event_turning_share", "d_calmar_pct",
                                              "d_null_median", "d_null_q95")},
                        "verdict": verdict(jv)}
    # v2 相位的落点诊断
    runs_v2 = phase_runs(phase_v2, w_dates)
    per_year_v2: dict[str, dict] = {}
    for d in w_dates:
        y = d[:4]
        per_year_v2.setdefault(y, {"days": 0, "turning": 0})
        per_year_v2[y]["days"] += 1
        if phase_v2.get(d) == "turning":
            per_year_v2[y]["turning"] += 1
    # v2 的 det 分位数 + 命中率诊断
    det_vals = [v for v in det_v2.values() if v is not None]
    hit_days = [d for d in w_dates if det_v2.get(d) is not None and
                det_v2[d] <= cv.TURN_DET and (by_day[d].get("shift_pct") or 0) >= cv.TURN_SHIFT_PCT]
    scored_days = [d for d in w_dates if det_v2.get(d) is not None]
    v2_meta = {
        "first_scored_day": scored_days[0] if scored_days else None,
        "n_scored_days": len(scored_days),
        "det_v2_min": float(np.min(det_vals)) if det_vals else None,
        "det_v2_mean": float(np.mean(det_vals)) if det_vals else None,
        "hit_days": len(hit_days),
        "turning_runs": runs_v2,
        "turning_days_per_year": per_year_v2,
        "n_components_hist": {},
        "exact_t_minus_30_ratio": (sum(1 for d in w_dates if IDX30.get(d) == (date.fromisoformat(d) - timedelta(days=30)).isoformat())
                                   / max(1, len(w_dates))),
    }
    nc: dict[str, int] = {}
    for d in w_dates:
        vals = v2_values(by_day, d)
        k = str(len(vals))
        nc[k] = nc.get(k, 0) + 1
    v2_meta["n_components_hist"] = nc
    # 分量可用性:每个分量在窗口内有多少天有 z / 有 dz30(z 的 30 日变化)
    avail = []
    for k in ALL_COMP:
        zd = [d for d in sorted(by_day) if k in z_of(by_day, d)]
        inwin = [d for d in w_dates if k in z_of(by_day, d)]
        dz = [d for d in w_dates if dz30(by_day, d, k) is not None]
        avail.append({"component": k, "z_days_all": len(zd),
                      "z_first": zd[0] if zd else None, "z_last": zd[-1] if zd else None,
                      "z_days_window": len(inwin), "dz30_days_window": len(dz)})
    v2_meta["component_availability"] = avail
    # v2 与 v1 相位逐日对照
    v2_meta["same_phase_days"] = sum(1 for d in w_dates if phase_v2.get(d) == phase_v1.get(d))
    v2_meta["turning_both"] = sum(1 for d in w_dates if phase_v2.get(d) == "turning" and phase_v1.get(d) == "turning")

    out = {
        "card": "T-239", "prereg": "S-720",
        "generated_at": "2026-11-05 (lane-c)",
        "phase_source": source, "phase_rows_table": n_table, "phase_rows_used": len(by_day),
        "code_ref_used": tinfo.get("code_ref_used"),
        "window": [WIN0, WIN1], "n_trading_days": len(w_dates),
        "btc_source": src, "cost_bp": t234.COST * 10000, "turn_exposure": t234.TURN_EXPOSURE,
        "segments_all": len(segs_all), "segments_in_window": len(segs),
        "segments": [{k: s.get(k) for k in ("start_d", "end_d", "days", "peak_d", "trough_d",
                                            "depth", "depth_p2t", "peak_to_trough_days")} for s in segs],
        "selfcheck": selfcheck,
        "attribution": {
            "turning_segments": turn_attr,
            "turning_meta": turn_attr_meta,
            "drawdown_segments": dd_attr,
            "drawdown_meta": dd_attr_meta,
            "component_table": comp_table,
            "raw_diagnostics": raw_diag,
            "group_defs": {
                "turning": "卡上两段 v1.1 turning(2023-06-17→10-21、2025-01-15→04-19)",
                "dd_big3": "三段最大回撤各自的峰前 60 日 → 谷(与 ② 同口径)",
                "rest": "窗口内其余交易日",
                "events_all": "窗口内全部 24 段事件段(峰→谷之外按段起止)",
            },
        },
        "v1_reference": {"judge": {k: j_v1[k] for k in ("turning_days", "a_median_p2t_share", "b_pass_ge_15pct",
                                                       "c_non_event_turning_share", "d_calmar_pct",
                                                       "d_null_median", "d_null_q95")},
                         "verdict": verdict(j_v1),
                         "note": "v1 = 表里的现成相位(S-713 的口径);随机对照种子改成 720 以便与 v2 同口径对照"},
        "v2": {"rule": {
            "level_components": list(LEVEL), "leverage_components": list(LEV),
            "leverage_value": "SIGN × (z(t) − z(t−30 日历天))(SIGN = −1 ⇒ z 上升 = 负贡献 = 坏)",
            "shift": "不变(照表的水平 z 版本 shift_pct)",
            "phase_rule": f"deterioration_v2 ≤ {cv.TURN_DET} 且 shift_pct ≥ {cv.TURN_SHIFT_PCT} 连续 3 天进;"
                          f"deterioration_v2 > {cv.EXIT_DET} 出",
            "min_components": cv.MIN_COMPONENTS,
        },
            "meta": v2_meta, "judge": j_v2, "verdict": v_v2, "variants": variants},
    }
    (HERE / "t239_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"selfcheck": selfcheck,
                      "attrib_top3": [{k: s["top3_most_negative"]} for s in turn_attr],
                      "v2_verdict": v_v2,
                      "v2_meta": {k: v2_meta[k] for k in ("first_scored_day", "n_scored_days", "hit_days",
                                                           "det_v2_min", "turning_days_per_year",
                                                           "n_components_hist", "same_phase_days")},
                      "v1_verdict": verdict(j_v1)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
