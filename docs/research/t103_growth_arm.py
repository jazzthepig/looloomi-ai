"""T-103 —— World50 EW×(Mom+Growth) 臂(S-581 预注册里留的那条)。

预注册见 REFUTATION_LEDGER.md 的 M-583。本脚本只在 `world50_revenue` 至少有一行才进 §3 计算,
否则按 T-103 acceptance 停在此处并报「数据未到,等下一轮循环」。

用法(Mac 上,环境里有 SUPABASE_URL / SUPABASE_KEY;key 不打印、不写文件):
    python3 docs/research/t103_growth_arm.py \
        /Volumes/CometCloudAI/cometcloud-local/research/t103/panel.json \
        /Volumes/CometCloudAI/cometcloud-local/research/t103/growth_scores.json \
        /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-103_growth_arm.md
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test  # noqa: E402
from src.data.universe.world50 import (  # noqa: E402
    BENCHMARKS, CANDIDATES, momentum_scores, momentum_values, select_members, tilt_weights,
)

PAGE = 1000
FIRST_SELECTION = "2015-12"
LAST_MONTH = "2026-09"
COST_BP = {"equity": 10, "metal": 10, "crypto": 20}
VOL_TARGET = 0.10


# ── §0 数据 probe ─────────────────────────────────────────────────────────────

def probe_revenue() -> tuple[int, int]:
    base, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    with httpx.Client(base_url=base, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30) as c:
        r = c.get("/rest/v1/world50_revenue?select=key&limit=1", headers={"Prefer": "count=exact"})
        cr = r.headers.get("content-range", "0-0/0")
        total = int(cr.split("/")[-1])
    return total, 0


def fetch_all_revenue() -> list[dict]:
    base, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    out: list[dict] = []
    with httpx.Client(base_url=base, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=120) as c:
        while True:
            r = c.get(f"/rest/v1/world50_revenue?select=key,tag,unit,period_start,period_end,filed,revenue"
                      f"&limit={PAGE}&offset={len(out)}&order=key,filed")
            if r.status_code != 200:
                raise RuntimeError(f"world50_revenue HTTP {r.status_code}: {r.text[:160]}")
            rows = r.json()
            out += rows
            if len(rows) < PAGE:
                return out
    return out


# ── §1 增长分定义 ─────────────────────────────────────────────────────────────

def period_days(ps: str, pe: str) -> int:
    return (date.fromisoformat(pe) - date.fromisoformat(ps)).days


def is_quarter(ps: str, pe: str) -> bool:
    return 80 <= period_days(ps, pe) <= 100


def is_year(ps: str, pe: str) -> bool:
    return 350 <= period_days(ps, pe) <= 380


def quarter_end_quarters(reference_months: list[str]) -> list[str]:
    return [m for m in reference_months if m[5:] in ("03", "06", "09", "12")]


def build_growth_scores(rev_rows: list[dict], q_ends: list[str]) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """对每季末 t,对每家公司只用 filed ≤ t 的行;选报得最新 tag;TTM = 最近 4 个连续季度或最近 1 年。
    增长 = TTM(t) / TTM(t − 4 季) − 1。算不出记 1(中性)。
    返回: ({quarter_end: {key: growth_raw}}, {key: neutral_count})
    """
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rev_rows:
        k = r.get("key")
        if k and r.get("filed") and r.get("period_start") and r.get("period_end") and r.get("revenue") is not None:
            try:
                rev = float(r["revenue"])
                if rev > 0:
                    by_key[k].append({
                        "filed": r["filed"], "ps": r["period_start"], "pe": r["period_end"],
                        "tag": r.get("tag", ""), "unit": r.get("unit", ""), "rev": rev,
                    })
            except (TypeError, ValueError):
                continue
    for k in by_key:
        by_key[k].sort(key=lambda x: (x["filed"], x["ps"], x["pe"]))

    # 选"报得最新"的 tag,对每家公司只用 filed ≤ t 的行 + 该公司最新 tag 一致
    # 取 t 时点的"最新 tag":本季末前所有行中报得最晚的 tag
    qe_dates = {m: quarter_end_date(m) for m in q_ends}
    growth_raw: dict[str, dict[str, float]] = {m: {} for m in q_ends}
    neutral_count: dict[str, int] = defaultdict(int)
    all_keys = sorted(by_key.keys())
    for k in all_keys:
        rows = by_key[k]
        for i, q in enumerate(q_ends):
            t = qe_dates[q]
            avail = [r for r in rows if r["filed"] <= t]
            if not avail:
                neutral_count[k] += 1
                growth_raw[q][k] = 1.0
                continue
            # 最新 tag = 所有行里 filed 最晚的那个 tag
            latest_tag = max(avail, key=lambda x: x["filed"])["tag"]
            tagged = [r for r in avail if r["tag"] == latest_tag]
            if not tagged:
                neutral_count[k] += 1
                growth_raw[q][k] = 1.0
                continue
            # 拆出季度行(period ≤ 100 天) + 年度行
            quarters = sorted([r for r in tagged if is_quarter(r["ps"], r["pe"])], key=lambda r: (r["pe"], r["ps"]))
            years = sorted([r for r in tagged if is_year(r["ps"], r["pe"])], key=lambda r: r["pe"])
            ttm_now = None
            ttm_yoy = None
            if len(quarters) >= 4:
                # 最近 4 个连续季度(用 pe 升序取末 4 个,且不重叠:pe_i ≥ pe_{i-1} 的后 90 天以内)
                last4 = quarters[-4:]
                # 检查这 4 个季度是否相邻(pe 单调 + 间距 ~ 90 天)
                last_dates = [date.fromisoformat(r["pe"]) for r in last4]
                gaps_ok = all((last_dates[i + 1] - last_dates[i]).days in range(80, 100) for i in range(3))
                if gaps_ok:
                    ttm_now = sum(r["rev"] for r in last4)
                    # TTM(t − 4 季) = 这 4 个季度之前的 4 个连续季度
                    if len(quarters) >= 8:
                        prev4 = quarters[-8:-4]
                        prev_dates = [date.fromisoformat(r["pe"]) for r in prev4]
                        prev_gaps = all((prev_dates[i + 1] - prev_dates[i]).days in range(80, 100) for i in range(3))
                        if prev_gaps:
                            ttm_yoy = sum(r["rev"] for r in prev4)
            if ttm_now is None and years:
                # 年度行:TTM = 该年行(period ~ 1 年),不算 rolling
                # 同理用最早的年报算 YoY
                year_now = years[-1]
                ttm_now = year_now["rev"]
                if len(years) >= 2:
                    # 取两年里"filed 早于 t"的最近一对
                    year_prev = years[-2]
                    ttm_yoy = year_prev["rev"]
            if ttm_now is None or ttm_yoy is None or ttm_yoy <= 0:
                neutral_count[k] += 1
                growth_raw[q][k] = 1.0
                continue
            growth_raw[q][k] = ttm_now / ttm_yoy - 1.0
    return growth_raw, neutral_count


def quarter_end_date(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:])
    nxt = date(y + (mm == 12), mm % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1).isoformat()


def growth_to_score(growth_raw: dict[str, dict[str, float]], q_ends: list[str], cand_keys: list[str]) -> dict[str, dict[str, float]]:
    """§1 增长分 = 横截面 z → 截 ±3 → 1 + z 或 1 / (1 − z)。每季对候选做一次(中性 1 不进 z)。"""
    score: dict[str, dict[str, float]] = {m: {} for m in q_ends}
    for q in q_ends:
        vals = []
        keys_for_z = []
        for k in cand_keys:
            v = growth_raw.get(q, {}).get(k, 1.0)
            if v == 1.0 and k not in growth_raw.get(q, {}):
                continue  # 中性不参 z
            vals.append(v)
            keys_for_z.append(k)
        if not vals:
            continue
        arr = np.asarray(vals, dtype=float)
        sd = float(arr.std(ddof=1))
        if sd == 0:
            for k in keys_for_z:
                score[q][k] = 1.0
            continue
        mu = float(arr.mean())
        for k, v in zip(keys_for_z, vals):
            z = (v - mu) / sd
            z = max(-3.0, min(3.0, z))
            if z >= 0:
                s = 1.0 + z
            else:
                s = 1.0 / (1.0 - z)  # 1 / (1 − z) for z<0  → 0.something at z=−1,0.5 at z=−0.5;与 S-578 / S-581 一致
            score[q][k] = s
        # 没进 z 的(中性 1)记 1
        for k in cand_keys:
            if k not in score[q]:
                score[q][k] = 1.0
    return score


def combined_score(mom_z: dict[str, float], grw_z: dict[str, float]) -> dict[str, float]:
    """合成分 = (增长 z + 动量 z) / 2,再标准化。"""


# ── §2 回放 ───────────────────────────────────────────────────────────────────

def closes_from_returns(rets: list[Optional[float]]) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    level: Optional[float] = None
    for r in rets:
        if r is None or not math.isfinite(r) or r <= -1:
            level = None
            out.append(None)
            continue
        level = (level if level is not None else 1.0) * (1 + r)
        out.append(level)
    return out


def rank_at(mcap: dict[str, float]) -> list[str]:
    return [k for k, v in sorted(mcap.items(), key=lambda kv: -kv[1]) if v and v > 0]


def inv_vol_weights(members: list[str], rets: dict[str, list[Optional[float]]], i: int) -> dict[str, float]:
    sig = {}
    for k in members:
        window = [r for r in rets.get(k, [])[max(0, i - 11): i + 1] if r is not None and math.isfinite(r)]
        sig[k] = float(np.std(window, ddof=1)) if len(window) >= 6 else None
    known = [s for s in sig.values() if s and s > 0]
    med = float(np.median(known)) if known else 1.0
    inv = {k: 1.0 / (s if s and s > 0 else med) for k, s in sig.items()}
    tot = sum(inv.values())
    return {k: v / tot for k, v in inv.items()}


def _tilt(members: list[str], scores_map: dict[str, float]) -> dict[str, float]:
    s = {k: scores_map.get(k, 1.0) for k in members}
    return tilt_weights(members, s)


def mom_at(i: int, members: list[str], closes: dict[str, list[Optional[float]]]) -> tuple[dict[str, float], int]:
    vals = {}
    for k in members:
        series = [c for c in closes.get(k, [])[: i + 1]]
        tail: list[float] = []
        for c in reversed(series):
            if c is None:
                break
            tail.append(c)
        vals[k] = momentum_values(list(reversed(tail))) if len(tail) >= 7 else (None, None)
    return momentum_scores(vals), vals


def cap_weights(members: list[str], mcap: dict[str, float]) -> dict[str, float]:
    tot = sum(mcap[k] for k in members)
    return {k: mcap[k] / tot for k in members}


def standardize_scores(scores_by_q: dict[str, dict[str, float]], q_ends: list[str],
                       candles_per_q: dict[str, list[str]]) -> dict[str, dict[str, float]]:
    """合成分 = (mom_raw + growth_raw) / 2,再每季横截面 z → 截 ±3 → 1 ± z 或 1/(1−z)。
    使用 growth_to_score 同套,只是输入是 (mom_raw, growth_raw) 的均值。
    """
    out: dict[str, dict[str, float]] = {m: {} for m in q_ends}
    for q in q_ends:
        keys = candles_per_q.get(q, [])
        vals = []
        for k in keys:
            mr = scores_by_q.get("mom", {}).get(q, {}).get(k, 1.0)
            gr = scores_by_q.get("grw", {}).get(q, {}).get(k, 1.0)
            vals.append((mr + gr) / 2.0 if mr > 0 and gr > 0 else 1.0)
        # 把中性 1 (mr==1 且 gr==1) 排除在 z 之外
        keep = [(k, v) for k, v in zip(keys, vals) if v != 1.0]
        if not keep:
            for k in keys:
                out[q][k] = 1.0
            continue
        arr = np.asarray([v for _, v in keep], dtype=float)
        sd = float(arr.std(ddof=1))
        if sd == 0:
            for k, _ in keep:
                out[q][k] = 1.0
        else:
            mu = float(arr.mean())
            for k, v in keep:
                z = (v - mu) / sd
                z = max(-3.0, min(3.0, z))
                out[q][k] = 1.0 + z if z >= 0 else 1.0 / (1.0 - z)
        for k in keys:
            if k not in out[q]:
                out[q][k] = 1.0
    return out


def run_arm_with_arm(arm: str, months: list[str], rets: dict[str, list[Optional[float]]],
                     mcap_q: dict[str, dict[str, float]], cls: dict[str, str],
                     closes: dict[str, list[Optional[float]]],
                     mom_q: dict[str, dict[str, float]],
                     grw_q: dict[str, dict[str, float]],
                     combo_q: dict[str, dict[str, float]]) -> dict:
    """arm ∈ {EW, InvVol, EWxMom, Cap, EWxMomGrowth, EWxGrowth};其余同 S-581。
    EWxGrowth 用 grw_q(不带动量);EWxMomGrowth 用 combo_q;EWxMom 用 mom_q。
    """
    i0 = months.index(FIRST_SELECTION)
    i_end = months.index(LAST_MONTH)
    members: list[str] = []
    w: dict[str, float] = {}
    out_r, out_m = [], []
    max_w, eff_n, turnover, renorm, neutral_n = [], [], 0.0, 0, 0
    for i in range(i0, i_end + 1):
        m = months[i]
        if i > i0:
            avail = {k: rets[k][i] for k in w if rets.get(k) and rets[k][i] is not None and math.isfinite(rets[k][i])}
            if len(avail) < len(w):
                renorm += 1
            tot_w = sum(w[k] for k in avail)
            r = sum(w[k] * avail[k] for k in avail) / tot_w if tot_w > 0 else 0.0
            out_r.append(r)
            out_m.append(m)
            grown = {k: w[k] * (1 + avail.get(k, 0.0)) for k in w}
            g = sum(grown.values())
            w = {k: v / g for k, v in grown.items()}
        if m[5:] in ("03", "06", "09", "12") and i < i_end:
            snap = mcap_q.get(m, {})
            if m[5:] == "12" or not members:
                members = select_members(rank_at(snap), previous=members, n=50)
            members = [k for k in members if k in snap]
            if arm == "EW":
                new = {k: 1.0 / len(members) for k in members}
            elif arm == "InvVol":
                new = inv_vol_weights(members, rets, i)
            elif arm == "EWxMom":
                scores_map = mom_q.get(m, {})
                new = _tilt(members, scores_map)
            elif arm == "Cap":
                new = cap_weights(members, snap)
            elif arm == "EWxMomGrowth":
                scores_map = combo_q.get(m, {})
                new = _tilt(members, scores_map)
            elif arm == "EWxGrowth":
                scores_map = grw_q.get(m, {})
                new = _tilt(members, scores_map)
            else:
                raise ValueError(arm)
            keys = set(new) | set(w)
            tv = sum(abs(new.get(k, 0.0) - w.get(k, 0.0)) for k in keys)
            cost = sum(abs(new.get(k, 0.0) - w.get(k, 0.0)) * COST_BP.get(cls.get(k, "equity"), 10) / 1e4 for k in keys)
            if out_r:
                out_r[-1] = (1 + out_r[-1]) * (1 - cost) - 1
            turnover += tv / 2
            w = new
            max_w.append(max(w.values()))
            eff_n.append(1.0 / sum(v * v for v in w.values()))
    years = len(out_r) / 12
    return {"months": out_m, "ret": out_r, "max_weight": max(max_w), "avg_eff_n": float(np.mean(eff_n)),
            "annual_turnover": turnover / years, "renormalized_months": renorm, "neutral_scores": neutral_n,
            "last_members": members}


def stats(rets: list[float]) -> dict:
    r = np.asarray(rets, dtype=float)
    nav = np.cumprod(1 + r)
    years = len(r) / 12
    cagr = nav[-1] ** (1 / years) - 1
    vol = float(r.std(ddof=1) * math.sqrt(12))
    peak = np.maximum.accumulate(np.concatenate([[1.0], nav]))
    dd = float((np.concatenate([[1.0], nav]) / peak - 1).min())
    return {"cagr": round(float(cagr), 4), "vol": round(vol, 4), "sharpe_rf0": round(float(cagr / vol), 2) if vol else None,
            "max_dd_monthly": round(dd, 4), "calmar": round(float(cagr / -dd), 2) if dd < 0 else None,
            "total": round(float(nav[-1] - 1), 3)}


def per_year(months: list[str], rets: list[float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for m, r in zip(months, rets):
        out[m[:4]] = (1 + out.get(m[:4], 0.0)) * (1 + r) - 1
    return {y: round(v, 4) for y, v in out.items()}


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main(panel_path: str, growth_path: str, report_path: Optional[str] = None) -> None:
    total, _ = probe_revenue()
    print(f"world50_revenue rows: {total}")
    if total == 0:
        Path(growth_path).write_text("# data not ready\n")
        return

    rev = fetch_all_revenue()
    p = json.loads(Path(panel_path).read_text())
    months: list[str] = p["months"]
    rets = {k: [None if v is None else float(v) for v in vs] for k, vs in p["ret"].items()}
    cls = p["cls"]
    mcap_q = {m: {k: float(v) for k, v in snap.items() if v} for m, snap in p["mcap"].items()}
    closes = {k: closes_from_returns(v) for k, v in rets.items()}

    q_ends = [m for m in months if m[5:] in ("03", "06", "09", "12")]
    qe_dates = {m: quarter_end_date(m) for m in q_ends}

    # ── §1 增长分:横截面(候选每季)→ z → 截 ±3 → 1+z / 1/(1−z)
    cand_keys = [c.key for c in CANDIDATES]
    growth_raw, neutral_count = build_growth_scores(rev, q_ends)
    growth_score = growth_to_score(growth_raw, q_ends, cand_keys)

    # ── §2 动量分:沿用 S-581(t099_world50_replay.py 的 mom_weights 但写入每季)
    i0 = months.index(FIRST_SELECTION)
    mom_score: dict[str, dict[str, float]] = {m: {} for m in q_ends}
    growth_neutral_at: dict[str, int] = {}
    rebalance_months = [i for i, m in enumerate(months) if m[5:] in ("03", "06", "09", "12") and i < months.index(LAST_MONTH)]
    for i in rebalance_months:
        m = months[i]
        snap = mcap_q.get(m, {})
        if m[5:] == "12" or True:
            members = select_members(rank_at(snap), previous=[], n=50)
        members = [k for k in members if k in snap]
        vals = {}
        for k in members:
            series = [c for c in closes.get(k, [])[: i + 1]]
            tail: list[float] = []
            for c in reversed(series):
                if c is None:
                    break
                tail.append(c)
            vals[k] = momentum_values(list(reversed(tail))) if len(tail) >= 7 else (None, None)
        scores = momentum_scores(vals)
        for k in members:
            mom_score[m][k] = scores.get(k, 1.0)

    # ── §1 合成分 =(mom_raw + growth_raw) / 2 再标准化。只对有营收的公司算。
    combo_score: dict[str, dict[str, float]] = {m: {} for m in q_ends}
    for q in q_ends:
        keys = list({k for k in growth_raw.get(q, {}).keys()})
        avg_vals = []
        keep = []
        for k in keys:
            mr = mom_score.get(q, {}).get(k, 1.0)
            gr = growth_score.get(q, {}).get(k, 1.0)
            if mr == 1.0 and gr == 1.0:
                combo_score[q][k] = 1.0
                continue
            v = (mr + gr) / 2.0
            avg_vals.append(v)
            keep.append(k)
        if not avg_vals:
            continue
        arr = np.asarray(avg_vals, dtype=float)
        sd = float(arr.std(ddof=1))
        if sd == 0:
            for k in keep:
                combo_score[q][k] = 1.0
        else:
            mu = float(arr.mean())
            for k, v in zip(keep, avg_vals):
                z = (v - mu) / sd
                z = max(-3.0, min(3.0, z))
                combo_score[q][k] = 1.0 + z if z >= 0 else 1.0 / (1.0 - z)
    # 候选但没进 combo(q 与 keys 都不出现)的留默认 1
    for q in q_ends:
        for k in cand_keys:
            combo_score[q].setdefault(k, 1.0)
            mom_score[q].setdefault(k, 1.0)
            growth_score[q].setdefault(k, 1.0)

    # 写出 growth_scores.json
    Path(growth_path).write_text(json.dumps({
        "quarter_ends": q_ends,
        "growth_raw": {m: {k: round(v, 6) for k, v in d.items()} for m, d in growth_raw.items()},
        "growth_score": {m: {k: round(v, 6) for k, v in d.items()} for m, d in growth_score.items()},
        "combo_score": {m: {k: round(v, 6) for k, v in d.items()} for m, d in combo_score.items()},
        "neutral_count_per_key": dict(neutral_count),
        "panel_months": months,
    }, ensure_ascii=False, indent=1))

    # ── §3 回放 6 臂
    arms_res: dict = {}
    for arm in ("EW", "InvVol", "EWxMom", "Cap", "EWxGrowth", "EWxMomGrowth"):
        arms_res[arm] = run_arm_with_arm(arm, months, rets, mcap_q, cls, closes,
                                          mom_q=mom_score, grw_q=growth_score, combo_q=combo_score)

    span = arms_res["EW"]["months"]
    idx = [months.index(m) for m in span]

    def bench(key: str) -> list[float]:
        return [rets[key][i] for i in idx]
    benches = {k: bench(k) for k in ("ACWI", "QQQ", "SPY", "BTC") if k in rets}
    if "ACWI" in rets and "AGG" in rets:
        benches["60/40"] = [0.6 * a + 0.4 * b for a, b in zip(benches["ACWI"], bench("AGG"))]

    # 写报告
    ab_summary = {}
    ab_summary["B_vs_A (EWxMom vs EW)"] = ab_test(arms_res["EW"]["ret"], arms_res["EWxMom"]["ret"],
                                                  mean_block=3, days_per_year=12)
    ab_summary["C_vs_A (EWxMomGrowth vs EW)"] = ab_test(arms_res["EW"]["ret"], arms_res["EWxMomGrowth"]["ret"],
                                                        mean_block=3, days_per_year=12)
    ab_summary["E (EWxGrowth vs EW) — exploratory"] = ab_test(arms_res["EW"]["ret"], arms_res["EWxGrowth"]["ret"],
                                                              mean_block=3, days_per_year=12)
    ab_summary["C_vs_B (EWxMomGrowth vs EWxMom)"] = ab_test(arms_res["EWxMom"]["ret"], arms_res["EWxMomGrowth"]["ret"],
                                                            mean_block=3, days_per_year=12)

    lines: list[str] = []
    lines.append("# T-103 World50 EW×(Mom+Growth) 臂(M-583) — 数据到位,跑完\n")
    lines.append(f"- 预注册:M-583(lane-c,2026-10-15 写于看数之前)")
    lines.append(f"- 数据:`world50_revenue` rows={total}、distinct keys={len(set(r['key'] for r in rev))};M-583 立的 KO / CRWD / NVS / HSBC / TCEHY 共 5 家无营收行(记中性 1)")
    lines.append(f"- 面板:`{panel_path}`(从 Supabase 直接导,供应商数据,不进 git)")
    lines.append(f"- 增长分 json:`{growth_path}`")
    lines.append(f"- 季度窗口:\"{span[0]}\" → \"{span[-1]}\"(共 {len(span)} 个月)\n")

    lines.append("## §1 检验:四臂 + 新臂的年化 / 波动 / 回撤 / 卡玛 / 换手\n")
    lines.append("| 臂 | 年化 | 波动 | Sharpe | 回撤 | 卡玛 | 平均有效 N | 年化换手 | 中性季数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for arm in ("EW", "InvVol", "EWxMom", "Cap", "EWxMomGrowth", "EWxGrowth"):
        r = arms_res[arm]
        s = stats(r["ret"])
        lines.append(f"| {arm} | {s['cagr']*100:.2f}% | {s['vol']*100:.2f}% | {s['sharpe_rf0']} | "
                     f"{s['max_dd_monthly']*100:.2f}% | {s['calmar']} | {r['avg_eff_n']:.1f} | "
                     f"{r['annual_turnover']*100:.2f}% | {r['neutral_scores']} |")
    lines.append("")
    lines.append("## §2 基准(同窗口)")
    lines.append("| 基准 | 年化 | 波动 | 回撤 | 卡玛 |")
    lines.append("|---|---|---|---|---|")
    for name, r in benches.items():
        s = stats(r)
        lines.append(f"| {name} | {s['cagr']*100:.2f}% | {s['vol']*100:.2f}% | {s['max_dd_monthly']*100:.2f}% | {s['calmar']} |")
    lines.append("")
    lines.append("## §3 A/B(主判据,apparatus.ab_test,mean_block=3,days_per_year=12)\n")
    for name, ab in ab_summary.items():
        lines.append(f"### {name}")
        lines.append(f"- n_days={ab['n_days']} years={ab['years']} cumA={ab['cum_a']*100:.2f}% cumB={ab['cum_b']*100:.2f}%")
        lines.append(f"- log_diff_total={ab['log_diff_total']:.4f} ratio_B_over_A={ab['ratio_b_over_a']:.4f}")
        lines.append(f"- ci95_log_diff=({ab['ci95_log_diff'][0]:.4f}, {ab['ci95_log_diff'][1]:.4f})")
        lines.append(f"- p(B≤A)={ab['p_b_le_a']:.4f} p(B≥A)={ab['p_b_ge_a']:.4f}")
        lines.append(f"- MDE_total={ab['mde_log_diff_total']:.4f} MDE/year={ab['mde_log_diff_per_year']:.4f} underpowered={ab['underpowered']}")
        lines.append(f"- **verdict = {ab['verdict']}**")
        lines.append("")
    lines.append("## §4 算不出增长分(neutral_count_per_key)\n")
    total_neutral = sum(neutral_count.values())
    total_quarters = len(q_ends)
    lines.append(f"- 候选池共 {len(cand_keys)} 个 key × {total_quarters} 季末 = {len(cand_keys) * total_quarters} 个 (key, t) 点")
    lines.append(f"- 增长分算不出(中性 1)的总点: {total_neutral}(占 {total_neutral / (len(cand_keys) * total_quarters) * 100:.2f}%)")
    lines.append(f"- 完全无营收标签的 5 家:**{','.join(k for k in cand_keys if neutral_count.get(k, 0) == total_quarters)}**")
    lines.append(f"- 全部季都中性 1 的公司(中性季数 ≥ 总季数的 80%):")
    cutoff = max(int(total_quarters * 0.8), 1)
    n_mostly_neutral = sorted([(k, v) for k, v in neutral_count.items() if v >= cutoff])
    for k, v in n_mostly_neutral[:15]:
        lines.append(f"  - {k}: {v}/{total_quarters}")
    lines.append("")

    lines.append("## §5 探索性发现\n")
    lines.append("- 本节内容均为**探索性**——未经预注册、未经零信号对照,需另立预注册 + 在新数据上验证。")
    cagrs = {a: stats(arms_res[a]["ret"])["cagr"] for a in arms_res}
    lines.append(f"- 6 臂里 CAGR 最高的:{max(cagrs, key=cagrs.get)} {cagrs[max(cagrs, key=cagrs.get)]*100:.2f}%")
    lines.append(f"- 6 臂里 CAGR 最低的:{min(cagrs, key=cagrs.get)} {cagrs[min(cagrs, key=cagrs.get)]*100:.2f}%")
    lines.append("- 详见预注册的 M-583 §3「E 臂不参与判据」——本节只看方向,不据结论。")
    lines.append("")

    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text("\n".join(lines))
        print(f"写好报告 {report_path}")
    print(f"\n主判据:C(A vs A) verdict = {ab_summary['C_vs_A (EWxMomGrowth vs EW)']['verdict']}")
    print(f"主判据:B(A vs A) verdict = {ab_summary['B_vs_A (EWxMom vs EW)']['verdict']}")
    print(f"探索:E(A vs A) verdict = {ab_summary['E (EWxGrowth vs EW) — exploratory']['verdict']}")
    print(f"边际:C - B verdict = {ab_summary['C_vs_B (EWxMomGrowth vs EWxMom)']['verdict']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
