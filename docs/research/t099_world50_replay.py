"""T-099 / S-581 —— World50 按时点回放(指数层 + 风险层分开记账)。预注册见台账 S-581(写于看结果之前)。

用法:python3 docs/research/t099_world50_replay.py <panel.json> [out.json]

panel.json(由 Supabase 导出,放在私有仓库 research_data/,供应商数据不进公开仓库):
  {"months": ["2015-01", ...],                       # 月份,升序
   "ret":    {key: [月收益 或 null, ...]},             # 成分与对照组的月总收益(复权月末收盘之比 − 1)
   "mcap":   {"YYYY-MM": {key: 美元市值, ...}, ...},   # 每个季末当时可知的市值(公司 / 加密 / 黄金可投资存量)
   "cls":    {key: "equity" | "metal" | "crypto"}}

只用 `world50` 的编制函数与 `apparatus` 的统计函数(T-097 起研究卡的规矩)。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test  # noqa: E402
from src.data.universe.world50 import momentum_scores, momentum_values, select_members, tilt_weights  # noqa: E402

N_MEMBERS = 50
COST_BP = {"equity": 10, "metal": 10, "crypto": 20}
FIRST_SELECTION = "2015-12"
LAST_MONTH = "2026-09"
VOL_TARGET = 0.10
DD_WINDOWS = {"2018Q4": ("2018-10", "2018-12"), "2020 疫情": ("2020-02", "2020-03"), "2022 全年": ("2022-01", "2022-12")}


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def closes_from_returns(rets: list[Optional[float]]) -> list[Optional[float]]:
    """月收益 → 以 1 起算的价格指数(缺月之前的价格不可用:缺口之后重新从 1 起算会让动量失真,所以缺口前一律 None)。"""
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


def mom_weights(members: list[str], closes: dict[str, list[Optional[float]]], i: int) -> tuple[dict[str, float], int]:
    vals = {}
    for k in members:
        series = [c for c in closes.get(k, [])[: i + 1]]
        # 只用连续可用的尾段(缺口之前的价格不可比)
        tail: list[float] = []
        for c in reversed(series):
            if c is None:
                break
            tail.append(c)
        vals[k] = momentum_values(list(reversed(tail))) if len(tail) >= 7 else (None, None)
    scores = momentum_scores(vals)
    neutral = [k for k in members if k not in scores]
    for k in neutral:
        scores[k] = 1.0
    return tilt_weights(members, scores), len(neutral)


def cap_weights(members: list[str], mcap: dict[str, float]) -> dict[str, float]:
    tot = sum(mcap[k] for k in members)
    return {k: mcap[k] / tot for k in members}


def run_arm(arm: str, months: list[str], rets: dict[str, list[Optional[float]]], mcap_q: dict[str, dict[str, float]],
            cls: dict[str, str], closes: dict[str, list[Optional[float]]]) -> dict[str, Any]:
    """一条臂:12 月选成分(缓冲区),季末重设权重,季内漂移;返回月收益序列与持仓统计。"""
    i0 = months.index(FIRST_SELECTION)
    i_end = months.index(LAST_MONTH)
    members: list[str] = []
    w: dict[str, float] = {}
    out_r, out_m = [], []
    max_w, eff_n, turnover, renorm, neutral_n = [], [], 0.0, 0, 0
    for i in range(i0, i_end + 1):
        m = months[i]
        if i > i0:
            # 这个月的收益(用上个月末的权重)
            avail = {k: rets[k][i] for k in w if rets.get(k) and rets[k][i] is not None and math.isfinite(rets[k][i])}
            if len(avail) < len(w):
                renorm += 1
            tot_w = sum(w[k] for k in avail)
            r = sum(w[k] * avail[k] for k in avail) / tot_w if tot_w > 0 else 0.0
            out_r.append(r)
            out_m.append(m)
            # 漂移
            grown = {k: w[k] * (1 + avail.get(k, 0.0)) for k in w}
            g = sum(grown.values())
            w = {k: v / g for k, v in grown.items()}
        if m[5:] in ("03", "06", "09", "12") and i < i_end:
            snap = mcap_q.get(m, {})
            if m[5:] == "12" or not members:
                members = select_members(rank_at(snap), previous=members, n=N_MEMBERS)
            members = [k for k in members if k in snap]          # 当季市值不可算 / 退市的不持
            if arm == "EW":
                new = {k: 1.0 / len(members) for k in members}
            elif arm == "InvVol":
                new = inv_vol_weights(members, rets, i)
            elif arm == "EWxMom":
                new, nn = mom_weights(members, closes, i)
                neutral_n += nn
            elif arm == "Cap":
                new = cap_weights(members, snap)
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


def stats(rets: list[float]) -> dict[str, Any]:
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


def window_ret(months: list[str], rets: list[float], a: str, b: str) -> float:
    v = 1.0
    for m, r in zip(months, rets):
        if a <= m <= b:
            v *= 1 + r
    return round(v - 1, 4)


def vol_target(months: list[str], rets: list[float]) -> tuple[list[float], list[float]]:
    """风险层:敞口 = min(1, 10% / 过去 6 个月已实现年化波动)(用到上月为止),其余现金 0。"""
    exp, out = [], []
    for i, r in enumerate(rets):
        hist = rets[max(0, i - 6): i]
        e = 1.0 if len(hist) < 6 else min(1.0, VOL_TARGET / max(1e-9, float(np.std(hist, ddof=1) * math.sqrt(12))))
        exp.append(e)
        out.append(e * r)
    return out, exp


# ── 主程序 ──────────────────────────────────────────────────────────────────

def main(panel_path: str, out_path: Optional[str] = None) -> dict[str, Any]:
    p = json.loads(Path(panel_path).read_text())
    months: list[str] = p["months"]
    rets = {k: [None if v is None else float(v) for v in vs] for k, vs in p["ret"].items()}
    cls = p["cls"]
    mcap_q = {m: {k: float(v) for k, v in snap.items() if v} for m, snap in p["mcap"].items()}
    closes = {k: closes_from_returns(v) for k, v in rets.items()}

    arms = {a: run_arm(a, months, rets, mcap_q, cls, closes) for a in ("EW", "InvVol", "EWxMom", "Cap")}
    span = arms["EW"]["months"]
    idx = [months.index(m) for m in span]

    def bench(key: str) -> list[float]:
        return [rets[key][i] for i in idx]
    benches = {k: bench(k) for k in ("ACWI", "QQQ", "SPY", "BTC") if k in rets}
    if "ACWI" in rets and "AGG" in rets:
        benches["60/40"] = [0.6 * a + 0.4 * b for a, b in zip(bench("ACWI"), bench("AGG"))]

    report: dict[str, Any] = {"window": (span[0], span[-1]), "months": len(span), "arms": {}, "benchmarks": {}}
    for a, res in arms.items():
        report["arms"][a] = {**stats(res["ret"]), "max_weight": round(float(res["max_weight"]), 4),
                             "avg_eff_n": round(res["avg_eff_n"], 1), "annual_turnover": round(float(res["annual_turnover"]), 2),
                             "renormalized_months": res["renormalized_months"], "neutral_scores": res["neutral_scores"],
                             "per_year": per_year(span, res["ret"]),
                             "drawdowns": {n: window_ret(span, res["ret"], *w) for n, w in DD_WINDOWS.items()},
                             "last_members": res["last_members"]}
    for b, r in benches.items():
        if any(x is None for x in r):
            report["benchmarks"][b] = {"why": f"{sum(x is None for x in r)} 个月缺数据"}
            continue
        report["benchmarks"][b] = {**stats(r), "per_year": per_year(span, r),
                                   "drawdowns": {n: window_ret(span, r, *w) for n, w in DD_WINDOWS.items()}}
    # 产品对基准 —— 只用 apparatus
    report["ab_EWxMom_vs_EW"] = ab_test(arms["EW"]["ret"], arms["EWxMom"]["ret"], mean_block=3, days_per_year=12)
    report["ab_InvVol_vs_EW"] = ab_test(arms["EW"]["ret"], arms["InvVol"]["ret"], mean_block=3, days_per_year=12)
    if "ACWI" in benches and None not in benches["ACWI"]:
        report["ab_EW_vs_ACWI"] = ab_test(benches["ACWI"], arms["EW"]["ret"], mean_block=3, days_per_year=12)
    # 风险层(另记):对照同平均敞口恒定持有
    vt, exp = vol_target(span, arms["EWxMom"]["ret"])
    avg_e = float(np.mean(exp))
    const = [avg_e * r for r in arms["EWxMom"]["ret"]]
    report["risk_layer"] = {"vol_target": {**stats(vt), "avg_exposure": round(avg_e, 3)},
                            "constant_same_exposure": stats(const),
                            "ab_voltarget_vs_constant": ab_test(const, vt, mean_block=3, days_per_year=12)}
    if out_path:
        Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return report


if __name__ == "__main__":
    rep = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps({k: v for k, v in rep.items() if k in ("window", "months")}, ensure_ascii=False))
    for a, s in rep["arms"].items():
        print(a, {k: s[k] for k in ("cagr", "vol", "max_dd_monthly", "calmar", "max_weight", "avg_eff_n", "annual_turnover")})
    for b, s in rep["benchmarks"].items():
        print(b, {k: s.get(k) for k in ("cagr", "vol", "max_dd_monthly", "calmar", "why")})
