#!/usr/bin/env python3
"""T-239 补充件 · ⓪ 相位机制的分解(只报不判)—— shift 到底在量什么。

为什么有这一件:T-239(S-720)v2 回放 ❌,notes 里的机制读数是两句未经量化的断言 ——
  ①「真崩塌里恶化分是到了的(v2 在 2021-11→2022-06 那 283 天有 91 天 ≤ −0.5),卡住相位的是 shift_pct
     (那 283 天最高只 0.73;涨势中段 0.996)」;
  ②「shift 量的是单分量离群,不是状态迁移」。
下一版规则若要改 shift 的定义,得先知道这两句话在数上成不成立。本件把它们量化。

**本件不做的事**(与 T-239 的纪律一致):
  · 不测任何新规则、不做新预注册、不改卡、不改代码、不做 DDL、不入库;
  · 不报告任何规则变体的收益 / 回撤 / 分位(那属于下一张卡,且必须有新数据段);
  · 只做「已有 v1 序列的机制读数」:shift 的构成、shift_pct 的分位来源、搬家是单分量还是多分量。
只读:全程 SELECT。
"""
from __future__ import annotations

import importlib.util
import json
import math
import statistics
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t234 = _load(HERE / "t234_cycle.py", "t234_cycle")   # 取数 / 事件段 / 表口径,同一份函数
cv = t234.cv                                        # src/data/state/cycle_vector.py(真源)

WIN0, WIN1 = "2021-02-01", "2026-10-31"
CENTROID_FROM, CENTROID_TO = 90, 30                # 真源常数(索引行数,不是日历天)
MIN_COMPONENTS = cv.MIN_COMPONENTS                 # 6
SIGN = cv.SIGN
LEVEL = ("fed_liq_60d", "stable_supply_30d", "breadth", "taker_buy", "mom_60")
LEV = ("funding", "oi_chg", "lend_apy", "vratio")
TURN_SEGS = [("2023-06-17", "2023-10-21"), ("2025-01-15", "2025-04-19")]
CRASH = ("2021-11-08", "2022-06-18")               # T-239 ② 的第一段最大回撤
CRASH2 = ("2025-10-06", "2026-02-05")


# ── 取数:表里 v1.1 的逐日 z / shift / shift_pct / phase ──────────────────────
def load_rows() -> tuple[list[dict], dict]:
    rows = t234.fetch(
        "cycle_vector_daily",
        {"select": "d,z,shift,shift_pct,deterioration,phase,n_components,code_ref",
         "order": "d.asc,code_ref.asc"},
    )
    by_ref: dict[str, list[dict]] = {}
    for r in rows:
        by_ref.setdefault(r.get("code_ref") or "(null)", []).append(r)
    v11 = sorted(k for k in by_ref if k.startswith("cycle_vector v1.1"))
    code_ref = v11[0] if v11 else (sorted(by_ref)[-1] if by_ref else None)
    sel = sorted(by_ref.get(code_ref, []), key=lambda r: str(r["d"])[:10])
    info = {
        "table_rows": len(rows),
        "code_refs": {k: len(v) for k, v in by_ref.items()},
        "code_ref_used": code_ref,
        "n_rows_used": len(sel),
        "min_d": str(sel[0]["d"])[:10] if sel else None,
        "max_d": str(sel[-1]["d"])[:10] if sel else None,
    }
    return sel, info


# ── 复刻真源:搬家距离 shift = RMS(z − cen),cen = z 在 [i−90, i−30] 的均值 ────
def decompose(rows: list[dict]) -> tuple[list[dict], dict]:
    z_hist = [(r.get("z") or {}) for r in rows]
    shift_hist: list[float] = []
    out: list[dict] = []
    checks = {"shift_diff_max": 0.0, "pct_diff_max": 0.0, "shift_mismatch": 0,
              "pct_mismatch": 0, "n_comp_distinct": {}}
    for i, r in enumerate(rows):
        d = str(r["d"])[:10]
        z = z_hist[i]
        past = [h for h in z_hist[max(0, i - CENTROID_FROM):max(0, i - CENTROID_TO)]
                if len(h) >= MIN_COMPONENTS]
        shift = pct = None
        dev: dict[str, float] = {}
        cen: dict[str, float] = {}
        if past:
            keys = [k for k in z if all(k in h for h in past)]
            if len(keys) >= MIN_COMPONENTS:
                cen = {k: sum(h[k] for h in past) / len(past) for k in keys}
                dev = {k: z[k] - cen[k] for k in keys}
                shift = math.sqrt(sum(v * v for v in dev.values()) / len(keys))
                pct = sum(1 for s in shift_hist if s <= shift) / len(shift_hist) if shift_hist else None
                shift_hist.append(shift)
        sq = {k: v * v for k, v in dev.items()}
        tot = sum(sq.values())
        share = {k: (sq[k] / tot if tot > 0 else 0.0) for k in sq}
        argmax = max(share, key=lambda k: share[k]) if share else None
        absdev = sum(abs(v) for v in dev.values())
        bad = [k for k in dev if SIGN.get(k, 1) * dev[k] > 0]
        bad_w = (sum(abs(dev[k]) for k in bad) / absdev) if absdev > 0 else None
        det_chg = (sum(SIGN.get(k, 1) * dev[k] for k in dev) / len(dev)) if dev else None
        # 与表里现成的 shift / shift_pct 对账(源里 round 到 4/3 位)
        ts, tp = r.get("shift"), r.get("shift_pct")
        if shift is not None and ts is not None:
            dd = abs(shift - float(ts))
            checks["shift_diff_max"] = max(checks["shift_diff_max"], dd)
            if dd > 2e-3:
                checks["shift_mismatch"] += 1
        if pct is not None and tp is not None:
            dd = abs(pct - float(tp))
            checks["pct_diff_max"] = max(checks["pct_diff_max"], dd)
            if dd > 2e-3:
                checks["pct_mismatch"] += 1
        nc = r.get("n_components")
        checks["n_comp_distinct"][str(nc)] = checks["n_comp_distinct"].get(str(nc), 0) + 1
        # 水平口径的同时性(与上面的「相对质心」口径是**两件事**):
        #   n_neg  = 今天有几个分量的 z 落在自己历史的下侧(SIGN*z < 0)
        #   n_le1  = 今天有几个分量的 z 低于自己历史 1 个标准差(SIGN*z ≤ −1)
        # 崩塌是「水平上多分量齐塌」,turning 是「单分量尖峰」—— 这两个口径能量出这件事。
        sgn_z = {k: SIGN.get(k, 1) * v for k, v in z.items()}
        n_neg = sum(1 for v in sgn_z.values() if v < 0)
        n_le1 = sum(1 for v in sgn_z.values() if v <= -1.0)
        out.append({
            "d": d, "phase": r.get("phase"),
            "deterioration": r.get("deterioration"),
            "shift": shift, "shift_pct": pct,
            "argmax": argmax,
            "argmax_share": share.get(argmax) if argmax else None,
            "n_bad": len(bad), "bad_weight": bad_w,
            "det_change": det_chg,
            "n_neg": n_neg, "n_le1": n_le1,
            "n_components": nc,
            "z": z,
            "clip": {k: v for k, v in z.items() if abs(v) >= 4.0},
        })
    return out, checks


# ── v2 口径的恶化分(照 T-239:五个取水平 z,四个取 −(z 的 30 日变化)) ──────────
def v2_det(days: list[dict], idx30: dict[str, str | None], d: str) -> float | None:
    z = days[d]["z"]
    vals: dict[str, float] = {}
    for k in LEVEL:
        if k in z:
            vals[k] = SIGN[k] * z[k]
    for k in LEV:
        z1, z0 = z, (days.get(idx30.get(d) or "") or {}).get("z") or {}
        if k in z1 and k in z0:
            vals[k] = SIGN[k] * (z1[k] - z0[k])
    if len(vals) < MIN_COMPONENTS:
        return None
    return sum(vals.values()) / len(vals)


def build_idx30(days: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for d in days:
        back = (date.fromisoformat(d) - timedelta(days=30)).isoformat()
        j = bisect_right(days, back) - 1
        out[d] = days[j] if j >= 0 else None
    return out


# ── 分组统计 ────────────────────────────────────────────────────────────────
def q(xs, p):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    s = sorted(xs)
    k = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[k]


def summarise(name: str, sub: list[dict]) -> dict:
    def col(key):
        return [x[key] for x in sub]
    res = {"regime": name, "n_days": len(sub),
           "n_components": sorted({x["n_components"] for x in sub if x["n_components"] is not None})}
    for key in ("deterioration", "shift", "shift_pct", "argmax_share", "n_bad", "bad_weight",
                "det_change", "n_neg", "n_le1"):
        c = col(key)
        res[key] = {"median": q(c, 0.5), "q10": q(c, 0.1), "q90": q(c, 0.9),
                    "mean": (sum(c) / len(c)) if c and all(v is not None for v in c) else None}
    # 相位门槛的两半各自成立的天数(门槛:det ≤ −0.5 且 shift_pct ≥ 0.75)
    res["n_days_det_le_-0.5"] = sum(1 for x in sub if x["deterioration"] is not None and x["deterioration"] <= -0.5)
    res["n_days_pct_ge_0.75"] = sum(1 for x in sub if x["shift_pct"] is not None and x["shift_pct"] >= 0.75)
    res["n_days_both"] = sum(1 for x in sub if x["deterioration"] is not None and x["deterioration"] <= -0.5
                              and x["shift_pct"] is not None and x["shift_pct"] >= 0.75)
    res["n_components_hist"] = {str(n): sum(1 for x in sub if x["n_components"] == n)
                                for n in sorted({x["n_components"] for x in sub if x["n_components"] is not None})}
    # 谁是搬家距离的最大贡献者
    cnt: dict[str, int] = {}
    for x in sub:
        if x["argmax"]:
            cnt[x["argmax"]] = cnt.get(x["argmax"], 0) + 1
    res["argmax_counts"] = dict(sorted(cnt.items(), key=lambda kv: -kv[1]))
    # 同时性:坏方向分量数的分布(状态迁移的粗代理)
    res["n_bad_hist"] = {str(n): sum(1 for x in sub if x["n_bad"] == n)
                         for n in sorted({x["n_bad"] for x in sub})}
    # 截顶(±4)的天数:源里 z 被 clip 过
    clip: dict[str, int] = {}
    for x in sub:
        for k in (x["clip"] or {}):
            clip[k] = clip.get(k, 0) + 1
    res["clipped_days"] = dict(sorted(clip.items()))
    return res


def main() -> None:
    rows, info = load_rows()
    dec, checks = decompose(rows)
    by_day = {x["d"]: x for x in dec}
    days = sorted(by_day)
    idx30 = build_idx30(days)
    win = [x for x in dec if WIN0 <= x["d"] <= WIN1]

    # v2 恶化分(逐日)
    for x in dec:
        x["deterioration_v2"] = v2_det(by_day, idx30, x["d"])

    regimes = {
        "turning_v1(phase=turning)": [x for x in win if x["phase"] == "turning"],
        "crash1_2021-11→2022-06(det_v1≤−0.5)": [x for x in win if CRASH[0] <= x["d"] <= CRASH[1]
                                                   and x["deterioration"] is not None and x["deterioration"] <= -0.5],
        "crash1_all_days": [x for x in win if CRASH[0] <= x["d"] <= CRASH[1]],
        "crash2_2025-10→2026-02(det_v1≤−0.5)": [x for x in win if CRASH2[0] <= x["d"] <= CRASH2[1]
                                                   and x["deterioration"] is not None and x["deterioration"] <= -0.5],
        "seg1_2023-06→10": [x for x in win if TURN_SEGS[0][0] <= x["d"] <= TURN_SEGS[0][1]],
        "seg2_2025-01→04": [x for x in win if TURN_SEGS[1][0] <= x["d"] <= TURN_SEGS[1][1]],
        "background": [x for x in win if x["phase"] != "turning"],
    }
    # v2 恶化分的对应口径(照 T-239 notes 的读法)
    regimes["crash1_2021-11→2022-06(det_v2≤−0.5)"] = [
        x for x in win if CRASH[0] <= x["d"] <= CRASH[1]
        and x["deterioration_v2"] is not None and x["deterioration_v2"] <= -0.5]
    regimes["crash1_v1_vs_v2_det_le_-0.5"] = [
        x for x in win if CRASH[0] <= x["d"] <= CRASH[1]
        and (x["deterioration"] or 0) <= -0.5 and (x["deterioration_v2"] or 0) <= -0.5]

    summary = {k: summarise(k, v) for k, v in regimes.items() if v}

    # 崩溃窗口里 shift_pct 的天花板 / 恶化分的天花板
    crash_all = regimes["crash1_all_days"]
    detail = {
        "crash1_shift_pct_max": max((x["shift_pct"] for x in crash_all if x["shift_pct"] is not None), default=None),
        "crash1_shift_median": q([x["shift"] for x in crash_all], 0.5),
        "crash1_shift_q90": q([x["shift"] for x in crash_all], 0.9),
        "win_shift_median": q([x["shift"] for x in win], 0.5),
        "win_shift_q90": q([x["shift"] for x in win], 0.9),
        "win_shift_pct_median": q([x["shift_pct"] for x in win], 0.5),
        "turning_shift_pct_max": max((x["shift_pct"] for x in regimes["turning_v1(phase=turning)"]
                                       if x["shift_pct"] is not None), default=None),
        "seg1_shift_pct_max": max((x["shift_pct"] for x in regimes["seg1_2023-06→10"]
                                   if x["shift_pct"] is not None), default=None),
        "seg1_det_min": min((x["deterioration"] for x in regimes["seg1_2023-06→10"]
                              if x["deterioration"] is not None), default=None),
        "crash1_det_min": min((x["deterioration"] for x in crash_all
                               if x["deterioration"] is not None), default=None),
        "crash1_det_v2_min": min((x["deterioration_v2"] for x in crash_all
                                  if x["deterioration_v2"] is not None), default=None),
        "n_days_det_le_-0.5_crash1_v1": len(regimes["crash1_2021-11→2022-06(det_v1≤−0.5)"]),
        "n_days_det_le_-0.5_crash1_v2": len(regimes["crash1_2021-11→2022-06(det_v2≤−0.5)"]),
    }

    # 四个窗口的门槛天花板:崩塌窗口 vs 假 turning 段
    win_defs = {
        "crash1_2021-11-08→2022-06-18": (CRASH[0], CRASH[1]),
        "crash2_2025-10-06→2026-02-05": (CRASH2[0], CRASH2[1]),
        "seg1_2023-06-17→2023-10-21": TURN_SEGS[0],
        "seg2_2025-01-15→2025-04-19": TURN_SEGS[1],
    }
    windows = {}
    for nm, (a, b) in win_defs.items():
        sub = [x for x in win if a <= x["d"] <= b]
        sp = [x["shift_pct"] for x in sub if x["shift_pct"] is not None]
        windows[nm] = {
            "n_days": len(sub),
            "shift_pct_max": max(sp) if sp else None,
            "shift_pct_q99": q(sp, 0.99),
            "n_days_pct_ge_0.75": sum(1 for v in sp if v >= 0.75),
            "n_days_pct_ge_0.70": sum(1 for v in sp if v >= 0.70),
            "det_min": min((x["deterioration"] for x in sub if x["deterioration"] is not None), default=None),
            "n_neg_median": q([x["n_neg"] for x in sub], 0.5),
            "n_le1_median": q([x["n_le1"] for x in sub], 0.5),
            "n_le1_max": max((x["n_le1"] for x in sub), default=None),
            "n_components": sorted({x["n_components"] for x in sub if x["n_components"] is not None}),
        }

    # 分母漂移:恶化分 = Σ SIGN·z / n,而 n(=有分的分量数)逐日不同(6/7/8)。
    # 同一个绝对阈值 −0.5 在不同 n 的年代量纲不同:换成「平均每个分量的 σ 单位」= det·√n,
    # 门槛 −0.5 相当于 −0.5·√n 个 σ(n=6:1.22σ / 7:1.32σ / 8:1.41σ)⇒ 年代之间不可直接比。
    era: dict[str, dict] = {}
    for x in dec:
        y = x["d"][:4]
        e = era.setdefault(y, {"days": 0, "n_hist": {}, "det_sigma": []})
        e["days"] += 1
        nc = str(x["n_components"])
        e["n_hist"][nc] = e["n_hist"].get(nc, 0) + 1
        if x["deterioration"] is not None and x["n_components"]:
            e["det_sigma"].append(x["deterioration"] * math.sqrt(x["n_components"]))
    for y, e in era.items():
        e["det_sigma_median"] = q(e["det_sigma"], 0.5)
        e["det_sigma_q10"] = q(e["det_sigma"], 0.1)
        e.pop("det_sigma")
    for nm, sub in regimes.items():
        sig = [x["deterioration"] * math.sqrt(x["n_components"]) for x in sub
               if x["deterioration"] is not None and x["n_components"]]
        sub_stats = summary.get(nm, {})
        if sub_stats:
            sub_stats["det_sigma_median"] = q(sig, 0.5)
            sub_stats["det_sigma_q10"] = q(sig, 0.1)
            sub_stats["det_sigma_q90"] = q(sig, 0.9)
            ns = sorted({x["n_components"] for x in sub if x["n_components"]})
            sub_stats["threshold_sigma_units"] = {str(n): round(-0.5 * math.sqrt(n), 4) for n in ns}

    res = {
        "card": "T-239(supplement)", "prereg": "S-720(T-239);本件无新预注册,只做机制读数",
        "window": [WIN0, WIN1], "read_only": True,
        "table": info, "selfcheck": checks,
        "detail": detail, "regimes": summary, "windows": windows, "era_n_components": era,
        "candidates_untested": [
            "带方向的搬家:Σ SIGN_k(z_k − cen_k)/n 的自身分位(搬家有方向,不只是距离)",
            "同时性:坏方向分量数 ≥ 5 的天数占比(状态迁移 vs 单分量离群)",
            "恶化分的自身分位:用 deterioration 在自己历史里的分位替代绝对 −0.5",
        ],
        "per_day": [{k: x[k] for k in ("d", "phase", "deterioration", "deterioration_v2", "shift",
                                       "shift_pct", "argmax", "argmax_share", "n_bad", "bad_weight",
                                       "det_change", "n_neg", "n_le1", "n_components")} for x in dec],
    }
    out = HERE / "t239b_shift_results.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({"selfcheck": checks, "detail": detail}, ensure_ascii=False, indent=1))
    for k, v in summary.items():
        print(k, "| n=", v["n_days"],
              "| shift_pct med/max=", v["shift_pct"]["median"], "/", q([x["shift_pct"] for x in regimes[k]], 1.0),
              "| argmax_share med=", v["argmax_share"]["median"],
              "| n_bad med=", v["n_bad"]["median"],
              "| bad_weight med=", v["bad_weight"]["median"],
              "| argmax=", list(v["argmax_counts"].items())[:4])


if __name__ == "__main__":
    main()
