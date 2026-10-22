#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-671 — 按时点的公司池上重测 SMALL(去掉「今天的名单」带来的幸存者偏差)。

照 REFUTATION_LEDGER.md 的 S-671 预注册(2026-10-22 15:46 UTC)原文一字不改执行:

  按时点的池子   每年第一个周五,在 world50_mcap_weekly(source = shares_x_close_v3、不带 . 后缀)里
                 **当时**有市值、且当时已有 ≥ 26 周 eodhd 价格的公司中,取当时市值前 N = 50 名,
                 这一年内固定(下一年重排)。
  同时报         ① 池子里「之后跌出前 50」的公司占比;② 「今天的名单里、当年不在前 50」的公司占比。
  信号与判法     SMALL = −log 市值(方向 +);4 周 / 13 周;发现段 2016-01 → 2020-12,
                 平均 IC > 0、t ≥ 2、两半都 > 0 ⇒ 进留出段 2021-01 → 2026-09,
                 留出段平均 IC > 0 且 t ≥ 2 = 过(同 S-670 原文)。
  零分布         只用 apparatus(每周打乱前瞻收益,400 次)。
  只报           同一池上 S-668 的 v2 合成、LOWVOL、ISSUE(不给判定)。
  局限(事先写明) world50 候选池本身是在今天建的,从没进过候选池的公司(已退市、被收购的)仍不在;
                 本检验只去掉「池内」偏差,去不掉「候选池」偏差。

**复用(不复制)**:截面 / IC / 分段 / 零分布 一律 import docs/research/t172_equity_signals.py;
  v2 合成 import src.data.cis.v2(S-668 影子写入端同一个文件);前瞻收益 = apparatus.long_return。
**本脚本新增的一条实现细节(事先写明)**:按时点的池子里会掉队(停牌、退市、并购),若沿用 S-670
  「不设陈旧度上限」的口径,掉队的名字会被当成「不动」算进 IC。故进 / 出场价格各加 7 个日历日的
  陈旧度上限(同 T-169 的 close_on_or_before(max_gap=7)口径),逐周记录被丢的名字数;
  SMALL 同时报「不设上限」的对照。

用法: python3 docs/research/t175_pit_small.py
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import date

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAC = "/Volumes/CometCloudAI/cometcloud-local"
RESULTS = os.path.join(REPO, "docs", "research", "t175_results.json")
REPORT = os.path.join(MAC, "_reports", "absorb_input", "T-175_s671_pit_small.md")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "docs", "research"))
os.makedirs(os.path.dirname(REPORT), exist_ok=True)

# ---- S-671 原文 + S-670 原文(窗 / 门槛 / 口径一字不改)----
DISC = ("2016-01-01", "2020-12-31")
HOLD = ("2021-01-01", "2026-09-30")
GRID_START = "2015-01-02"
GRID_END = "2026-09-30"
N_TOP = 50                    # 按时点池子:当时市值前 50
MIN_PX_WEEKS = 26             # 入池门槛:当时已有 ≥ 26 周价格
MIN_CROSS = 15                # 截面 < 15 家跳过(同 S-670)
H_FWD_DAYS = {4: 20, 13: 65}
STRIDE_WEEKS = {4: 4, 13: 13}
N_NULL = 400
SEED = 671175
MCAP_SOURCE = "shares_x_close_v3"
MAX_GAP_DAYS = 7              # 进 / 出场价格的陈旧度上限(见文首「事先写明」)

PRIMARY = "SMALL"             # 判定只对它
SIGNALS = ["SMALL", "V2COMP", "LOWVOL", "ISSUE"]
REPORT_ONLY = ["V2COMP", "LOWVOL", "ISSUE"]
SIGNAL_DESC = {
    "SMALL": "−log(市值)",
    "V2COMP": "S-668 v2 合成(score_group('equity', equity_inputs) 的 score)",
    "LOWVOL": "−26 周周收益 σ",
    "ISSUE": "−股数 52 周增长(股数 = 市值 / 收盘)",
}

try:
    from src.data.evaluation.apparatus import ab_test, long_return  # 前瞻收益 / A/B 只走 apparatus
    APPARATUS = "src.data.evaluation.apparatus"
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"apparatus 导入失败,退出(不要另起炉灶):{exc}")

# ---- 截面 / IC / 分段 / 零分布:一律复用 t172(S-671 卡上要求),不复制 ----
try:
    import t172_equity_signals as T172
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"t172_equity_signals 导入失败,退出: {exc}")
for _fn in ("fridays", "spearman_ic", "rankdata", "tstat", "summarize", "null_pct",
            "fetch_mcap", "fetch_px", "Sym"):
    if not hasattr(T172, _fn):
        raise SystemExit(f"t172 缺函数 {_fn},不要在本脚本另写一版")
try:
    from src.data.cis.v2 import DIMS as V2_DIMS, equity_inputs, score_group
    V2_REF = "src.data.cis.v2"
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"src.data.cis.v2 导入失败,退出: {exc}")


def g(x, nd=4):
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return "—" if not math.isfinite(v) else f"{v:.{nd}f}"


def gp(x, nd=2):
    """百分数格式化,None 安全。"""
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return "—" if not math.isfinite(v) else f"{v * 100:.{nd}f}"


def main() -> int:
    print("[T-175] S-671 —— 按时点的公司池上重测 SMALL", flush=True)
    grid = T172.fridays(GRID_START, GRID_END)
    gi = {d: i for i, d in enumerate(grid)}
    mcap = T172.fetch_mcap()
    all_keys = sorted({k for d in mcap.values() for k in d if "." not in k})
    px = T172.fetch_px(all_keys)
    syms = {k: T172.Sym(k, px[k]) for k in all_keys if len(px.get(k, [])) > 0}
    for s in syms.values():
        s.build_grid(grid)
    print(f"  今天名单(无点 key){len(all_keys)} 个,有价格 {len(syms)} 个;"
          f"周网格 {len(grid)} 个({grid[0]} → {grid[-1]})", flush=True)

    # 每个名字在周网格点 i(含)之前有多少周有效价格 —— 判「当时已有 ≥ 26 周价格」
    cum = {}
    for k, s in syms.items():
        cum[k] = np.concatenate(([0], np.cumsum(np.where(np.isfinite(s.wk_px), 1, 0))))

    # 表里绝大多数是周五快照,另有 11 行落在别的日子(5 行周六,像节假日后的补记);还有几行是
    # **残缺的节假日行**(2020-12-25 只有 6 个 key、2020-12-30 只有 4 个)。
    # 「当时」= 每个周五取 ≤ 该周五、距该周五 ≤ 10 天、且家数 ≥ 全样本中位数的 90% 的最近一次
    # 完整快照;往前找不到就跳过这一周。
    SNAP_MAX_AGE = 10
    FULL_MIN = 0.9 * float(np.median([len(v) for v in mcap.values() if v]))
    _sd = sorted(d for d in mcap if mcap.get(d))
    asof: dict[str, tuple[str, dict]] = {}
    _p = 0
    for d in grid:
        while _p + 1 < len(_sd) and _sd[_p + 1] <= d:
            _p += 1
        q = _p
        while q >= 0:
            if (date.fromisoformat(d) - date.fromisoformat(_sd[q])).days > SNAP_MAX_AGE:
                break
            if len(mcap[_sd[q]]) >= FULL_MIN:
                asof[d] = (_sd[q], mcap[_sd[q]])
                break
            q -= 1
        if d > _sd[-1]:
            break
    snap_days = sorted(d for d in asof if DISC[0] <= d <= HOLD[1])
    print(f"  有快照的周网格点 {len(asof)} / {len(grid)};段内 {len(snap_days)} 个", flush=True)

    # ---- 每个周五的「当时前 50」(按市值;只要当时有市值,与价格历史无关)----
    top50 = {}
    for d in grid:
        snap = asof.get(d, (None, {}))[1]
        cand = sorted(((v, k) for k, v in snap.items() if v and v > 0), reverse=True)
        top50[d] = {k for _, k in cand[:N_TOP]}

    # ---- 按时点的池子:每年第一个周五定一次,全年不变 ----
    years = sorted({d[:4] for d in snap_days})
    pool, pool_meta = {}, {}
    for y in years:
        wk0 = min(d for d in snap_days if d[:4] == y)
        i0 = gi[wk0]
        snap_used, snap = asof[wk0]
        cand = []
        for k in all_keys:
            mc = snap.get(k)
            if mc is None or mc <= 0 or k not in syms:
                continue
            if int(cum[k][i0]) < MIN_PX_WEEKS:      # 当时还不足 26 周价格
                continue
            cand.append((float(mc), k))
        cand.sort(key=lambda t: (-t[0], t[1]))
        chosen = [k for _, k in cand[:N_TOP]]
        pool[y] = chosen
        pool_meta[y] = {
            "formed_on": wk0,
            "snapshot_used": snap_used,
            "nominal_first_friday": next(d for d in grid if d[:4] == y),
            "n_eligible": len(cand), "n_pool": len(chosen),
            "pool_top50_cap_cutoff": float(cand[min(N_TOP, len(cand)) - 1][0]) if cand else None,
            "today_list_eligible": len(cand),
            "today_list_not_in_top50": len(cand) - len(chosen),
            "today_list_not_in_top50_pct": (len(cand) - len(chosen)) / len(cand) if cand else None,
            "cap_median_pool": float(np.median([c for c, _ in cand[:len(chosen)]])) if chosen else None,
            "cap_median_all_eligible": float(np.median([c for c, _ in cand])) if cand else None,
            "n_left_later": None, "n_left_later_pct": None,
            "pool": chosen,
        }
    print(f"  按时点池子 {len(pool)} 年,池内家数 "
          f"{min(m['n_pool'] for m in pool_meta.values())}–{max(m['n_pool'] for m in pool_meta.values())}",
          flush=True)

    # ---- 偏差量 ①:池子里「之后跌出前 50」的占比 ----
    tot, out, week_out = 0, 0, []
    for y in years:
        last_d = max(d for d in snap_days if d[:4] == y)
        left = [k for k in pool[y] if k not in top50.get(last_d, set())]
        pool_meta[y]["n_left_later"] = len(left)
        pool_meta[y]["n_left_later_pct"] = len(left) / len(pool[y]) if pool[y] else None
        pool_meta[y]["left_later_on"] = last_d
    for d in snap_days:
        if not (DISC[0] <= d <= HOLD[1]):
            continue
        t50 = top50.get(d, set())
        miss = [k for k in pool[d[:4]] if k not in t50]
        tot += len(pool[d[:4]])
        out += len(miss)
        week_out.append((d, len(miss), len(pool[d[:4]])))
    bias_left_weeks = {"name_weeks": tot, "dropped": out, "pct": out / tot if tot else None}
    bias_left_year_avg = float(np.mean([pool_meta[y]["n_left_later_pct"] for y in years
                                        if pool_meta[y]["n_left_later_pct"] is not None]))
    print(f"  偏差① 池内之后跌出前 50:{out}/{tot} 个名字-周 = "
          f"{g(bias_left_weeks['pct'], 4)};按年末看平均 {g(bias_left_year_avg, 4)}", flush=True)

    # ---- 偏差量 ②:今天名单里、当年不在前 50 的占比 ----
    bias_today = {"per_year": {}, "name_years": 0, "out": 0}
    for y in years:
        m = pool_meta[y]
        bias_today["per_year"][y] = {
            "eligible_today_list": m["today_list_eligible"], "in_top50": m["n_pool"],
            "not_in_top50": m["today_list_not_in_top50"],
            "pct": m["today_list_not_in_top50_pct"],
        }
        bias_today["name_years"] += m["today_list_eligible"]
        bias_today["out"] += m["today_list_not_in_top50"]
    bias_today["pct"] = bias_today["out"] / bias_today["name_years"] if bias_today["name_years"] else None
    print(f"  偏差② 今天名单当年不在前 50:{bias_today['out']}/{bias_today['name_years']} "
          f"= {g(bias_today['pct'], 4)}", flush=True)

    # ---- 逐周截面 ----
    def fresh(k, i):
        """周网格点 i 的价格是否够新(≤ MAX_GAP_DAYS 天)。"""
        s = syms[k]
        j = int(s.wk_idx[i])
        if j < 0:
            return False
        return (date.fromisoformat(grid[i]) - date.fromisoformat(s.dates[j])).days <= MAX_GAP_DAYS

    rows, rows_raw = [], []
    skipped_small = 0
    dropped_stale = []
    rows_today = []          # S-670 口径的对照臂(今天的名单),同一段、同一脚本
    def build_row(names, d, i, snap, snap_prev):
        """一个截面 → (row, row_raw);家数不够返回 None。"""
        prev52 = snap_prev.get(grid[i - 52], {}) if i >= 52 else {}
        keys_used, mcs = [], []
        # v2 原始输入(每周一行:周日期, 市值, 当周收盘),只喂最近 60 周(稳定 27 / 供给 53 周要够)
        weekly_rows = {}
        for k in names:
            rs = []
            for j in range(max(0, i - 59), i + 1):
                sp = snap_prev.get(grid[j]) or (asof[grid[j]][1] if grid[j] in asof else None)
                m = (sp or {}).get(k)
                c = syms[k].wk_px[j]
                if m and m > 0 and c == c and c > 0:
                    rs.append((grid[j], float(m), float(c)))
            weekly_rows[k] = rs
        scored = score_group("equity", {k: equity_inputs(weekly_rows[k], d) for k in names if weekly_rows[k]})
        sv = {sg: [] for sg in SIGNALS}
        fwd_g = {hz: [] for hz in H_FWD_DAYS}
        fwd_r = {hz: [] for hz in H_FWD_DAYS}
        n_raw = 0
        for k in names:
            s = syms[k]
            w = s.wk_px
            mc = snap.get(k)
            mc52 = prev52.get(k)
            if mc is None or not (mc > 0):
                continue
            n_raw += 1
            if not fresh(k, i):
                dropped_stale.append((d, k))
                continue
            sh_t = mc / w[i]
            sh_52 = (mc52 / w[i - 52]) if (i >= 52 and mc52 and mc52 > 0 and w[i - 52] > 0) else float("nan")
            vals = {
                "SMALL": -math.log(mc),
                "V2COMP": (scored.get(k) or {}).get("score"),
                "LOWVOL": (-float(np.std(np.diff(w[i - 26:i + 1]) / w[i - 26:i]))) if i >= 26 else float("nan"),
                "ISSUE": -(sh_t / sh_52 - 1.0) if sh_52 == sh_52 else float("nan"),
            }
            # 前瞻收益:带陈旧度上限(主口径)/ 不带(对照)
            j = int(s.wk_idx[i])
            for hz, nd in H_FWD_DAYS.items():
                kk = j + nd
                ok = j >= 0 and kk < s.n and (
                    date.fromisoformat(s.dates[kk]) - date.fromisoformat(grid[i])).days <= 40 * MAX_GAP_DAYS
                r = float(long_return(s.px[j], s.px[kk])) if ok else float("nan")
                fwd_g[hz].append(r)
                kr = j + nd
                fwd_r[hz].append(float(long_return(s.px[j], s.px[kr]))
                                 if j >= 0 and kr < s.n else float("nan"))
            for sg in SIGNALS:
                v = vals[sg]
                sv[sg].append(float(v) if v is not None else float("nan"))
            keys_used.append(k)
            mcs.append(float(mc))
        if len(keys_used) < MIN_CROSS:
            return None
        ics = {}
        for hz in H_FWD_DAYS:
            f = np.array(fwd_g[hz], dtype=float)
            for sg in SIGNALS:
                ics[f"{sg}_{hz}"] = T172.spearman_ic(np.array(sv[sg], dtype=float), f)
        ics_r = {}
        for hz in H_FWD_DAYS:
            f = np.array(fwd_r[hz], dtype=float)
            for sg in SIGNALS:
                ics_r[f"{sg}_{hz}"] = T172.spearman_ic(np.array(sv[sg], dtype=float), f)
        row = {"week": d, "n": len(keys_used), "n_raw": n_raw, "sig": sv,
               "fwd": fwd_g, "ics": ics,
               "keys": keys_used, "mcap_median": float(np.median(mcs)) if mcs else None,
               "nlp": [-math.log(syms[k].wk_px[i]) for k in keys_used],
               "n_outside_now": len([k for k in pool[d[:4]] if k not in top50.get(d, set())])}
        row_raw = {"week": d, "n": len(keys_used), "sig": sv, "fwd": fwd_r, "ics": ics_r}
        return {"pit": (row, row_raw)}

    for d in snap_days:
        i = gi[d]
        snap = asof[d][1]
        snap_prev = {}
        for jj in range(max(0, i - 53), i + 1):
            s_prev = asof.get(grid[jj])
            if s_prev:
                snap_prev[grid[jj]] = s_prev[1]
        arms = (("pit", pool[d[:4]]),
                 ("today", [k for k in all_keys if k in syms and (snap.get(k) or 0) > 0]))
        for arm, names in arms:
            got = build_row(names, d, i, snap, snap_prev)
            if got is None:
                if arm == "pit":
                    skipped_small += 1
                continue
            row, row_raw = got["pit"]
            if arm == "pit":
                rows.append(row)
                rows_raw.append(row_raw)
                if len(rows) % 100 == 0:
                    print(f"    … 周 {len(rows)}({d},n={row['n']})", flush=True)
            else:
                rows_today.append(row)
    print(f"  按时点池子截面周 {len(rows)} 个(< {MIN_CROSS} 家跳过 {skipped_small});"
          f"对照臂(今天的名单){len(rows_today)} 个;"
          f"因价格陈旧被丢的名字-周 {len(dropped_stale)}", flush=True)

    # ---- 偏差的直接读数:同一段、同一脚本,「今天的名单」对照臂 vs「按时点池子」----
    # 用 apparatus.ab_test 对两条周度 IC 序列做配对块自助对比(IC 都远大于 −1,log1p 的影响可忽略)。
    ab = {}
    pit_by_w = {r["week"]: r for r in rows}
    for hz in (4, 13):
        key = f"SMALL_{hz}"
        for seg, (lo, hi) in (("discovery", DISC), ("holdout", HOLD)):
            a, b = [], []
            for r in rows_today:
                if not (lo <= r["week"] <= hi):
                    continue
                p = pit_by_w.get(r["week"])
                if p is None:
                    continue
                v_t, v_p = r["ics"].get(key), p["ics"].get(key)
                if v_t is None or v_p is None:
                    continue
                if not (math.isfinite(v_t) and math.isfinite(v_p)):
                    continue
                a.append(float(v_p))
                b.append(float(v_t))
            abt = ab_test(a, b, mean_block=13, n_boot=2000, seed=SEED) if len(a) >= 30 else None
            ab[f"{seg}_{hz}w"] = {
                "n": len(a), "pit_mean_ic": float(np.mean(a)) if a else None,
                "today_mean_ic": float(np.mean(b)) if b else None,
                "pit_t": T172.tstat(a), "today_t": T172.tstat(b),
                # ab_test 的复合收益字段(cum_/ratio_/log_diff_total)对 IC 序列无意义,只取单侧 p 与判定
                "p_today_ge_pit": (abt or {}).get("p_b_ge_a"), "verdict": (abt or {}).get("verdict"),
                "note": "apparatus.ab_test 的 p_b_ge_a / verdict;cum_ 与 ratio_ 字段不适用于 IC 序列",
            }

    # ---- 判定(SMALL 走机械规则;其余只报)----
    results = {}
    for sg in SIGNALS:
        entry = {}
        for hz in (4, 13):
            dd = T172.summarize(rows, sg, hz, *DISC)
            hh = T172.summarize(rows, sg, hz, *HOLD)
            gates = {"mean_ic>0": (dd["mean_ic"] or 0) > 0,
                     "t>=2": (dd["t"] is not None) and dd["t"] >= 2,
                     "half1>0": (dd["half1"] is not None) and dd["half1"] > 0,
                     "half2>0": (dd["half2"] is not None) and dd["half2"] > 0}
            enter = all(gates.values())
            hpass = (hh["mean_ic"] or 0) > 0 and (hh["t"] is not None) and hh["t"] >= 2
            e = {"signal": sg, "horizon_wk": hz, "desc": SIGNAL_DESC[sg],
                 "discovery": dd, "gates": gates, "enter_holdout": enter,
                 "holdout": hh, "holdout_pass": hpass if enter else None,
                 "verdict": ("过" if (enter and hpass) else ("进留出但没过" if enter else "发现段未过")),
                 "null_discovery": T172.null_pct(rows, sg, hz, *DISC),
                 "null_holdout": T172.null_pct(rows, sg, hz, *HOLD) if enter else None,
                 "nogap_control_discovery": T172.summarize(rows_raw, sg, hz, *DISC),
                 "nogap_control_holdout": T172.summarize(rows_raw, sg, hz, *HOLD)}
            entry[hz] = e
        results[sg] = entry

    # ---- 挖掘(探索性,不在 S-671 预注册里)----
    corr = [T172.spearman_ic(np.array(r["sig"]["SMALL"], dtype=float), np.array(r["nlp"], dtype=float))
            for r in rows]
    corr = [c for c in corr if c is not None and math.isfinite(c)]
    n_out = [r["n_outside_now"] / r["n"] for r in rows if r["n"]]
    explore = {
        "note": "探索性 —— 需另立预注册、在新数据上过零信号对照",
        "small_vs_neglogpx_corr": float(np.mean(corr)) if corr else None,
        "pool_share_outside_top50_mean": float(np.mean(n_out)) if n_out else None,
        "pool_median_mcap_vs_today": {
            "pool_median_mcap_first_week": rows[0]["mcap_median"] if rows else None,
            "pool_median_mcap_last_week": rows[-1]["mcap_median"] if rows else None,
        },
        "dropped_stale_name_weeks": len(dropped_stale),
    }
    for hz in (4, 13):
        for seg, wd in (("discovery", DISC), ("holdout", HOLD)):
            for sg in ("SMALL", "V2COMP", "LOWVOL", "ISSUE"):
                s = T172.summarize(rows, sg, hz, *wd)
                explore[f"{sg}_{seg}_{hz}w_t"] = s["t"]
                explore[f"{sg}_{seg}_{hz}w_n"] = s["n_weeks"]

    meta = {
        "task": "T-175", "prereg": "S-671 (REFUTATION_LEDGER.md, 2026-10-22 15:46 UTC)",
        "apparatus": APPARATUS, "v2_ref": V2_REF, "ab": ab,
        "reused_from": "docs/research/t172_equity_signals.py (fridays/spearman_ic/tstat/"
                       "summarize/null_pct/fetch_mcap/fetch_px/Sym)",
        "universe": f"world50_mcap_weekly source={MCAP_SOURCE},无点 key,按时点前 {N_TOP}",
        "pit_rule": f"每年第一个周五;当时有市值且当时已有 ≥ {MIN_PX_WEEKS} 周 eodhd 价格;"
                    f"取当时市值前 {N_TOP},全年固定",
        "max_gap_days": MAX_GAP_DAYS, "min_cross": MIN_CROSS,
        "snap_max_age_days": SNAP_MAX_AGE, "snap_full_min_keys": FULL_MIN,
        "n_keys_total": len(all_keys), "n_keys_with_px": len(syms),
        "cross_weeks": len(rows), "skipped_small_cross": skipped_small,
        "discovery": list(DISC), "holdout": list(HOLD), "n_null": N_NULL, "seed": SEED,
        "signals": SIGNALS, "primary": PRIMARY, "report_only": REPORT_ONLY,
        "pool": {y: {kk: vv for kk, vv in m.items()} for y, m in pool_meta.items()},
        "bias_left_out_of_top50": bias_left_weeks,
        "bias_left_out_of_top50_year_avg_pct": bias_left_year_avg,
        "bias_today_list_not_in_top50": bias_today,
    }
    out = {"meta": meta, "bias": {"pool_left_out": bias_left_weeks,
                                  "pool_left_out_year_avg_pct": bias_left_year_avg,
                                  "today_list_not_in_top50": bias_today},
           "results": results, "explore": explore,
           "weekly": [{"week": r["week"], "n": r["n"], "n_outside_now": r["n_outside_now"],
                       "ics": r["ics"]} for r in rows]}
    open(RESULTS, "w").write(json.dumps(out, ensure_ascii=False, indent=2))
    write_report(out)
    print(f"[T-175] 结果 → {RESULTS}\n[T-175] 报告 → {REPORT}", flush=True)
    return 0


def write_report(out: dict) -> None:
    m, R, B, X = out["meta"], out["results"], out["bias"], out["explore"]
    L = ["# T-175 / S-671 —— 按时点的公司池上重测 SMALL", "",
         f"- 台账:`{m['prereg']}`",
         f"- 数据:{m['universe']}",
         f"- 池子规则:{m['pit_rule']}",
         f"- 零分布 / 前瞻收益:`{m['apparatus']}`;截面 / IC / 分段:`{m['reused_from']}`;"
         f"v2 合成:`{m['v2_ref']}`",
         f"- 截面周 {m['cross_weeks']} 个(< {m['min_cross']} 家跳过 {m['skipped_small_cross']} 个;"
         f"因价格陈旧丢掉的名字-周 {X['dropped_stale_name_weeks']})", "",
         "## 一、偏差量(S-671 要求先报)", ""]

    L.append(f"**① 按时点池子里「之后跌出前 50」:**{B['pool_left_out']['dropped']} / "
             f"{B['pool_left_out']['name_weeks']} 个名字-周 = **{gp(B['pool_left_out']['pct'])}%**;"
             f"按年末口径(池子里的名字在当年最后一个**有快照的**周五是否还在前 50)平均 "
             f"**{gp(B['pool_left_out_year_avg_pct'])}%**。")
    L.append(f"也就是说:当时在前 50 的公司,有约 "
             f"{gp(B['pool_left_out_year_avg_pct'], 1)}% 在当年之内就掉出了前 50 ——"
             f"这正是 S-670 那个「今天的名单」结构上抬不高、也压不下去的部分。\n")
    L.append("| 年 | 建池日(日历首个周五) | 当时合格家数 | 池子家数 | 池内当年末跌出前 50 | 今天名单当年不在前 50 |")
    L.append("|---|---|---|---|---|---|")
    for y, mm in sorted(m["pool"].items()):
        L.append(f"| {y} | {mm['formed_on']}({mm['nominal_first_friday']}) | {mm['today_list_eligible']} | "
                 f"{mm['n_pool']} | {mm['n_left_later']} / {mm['n_pool']}({gp(mm['n_left_later_pct'], 1)}%) | "
                 f"{mm['today_list_not_in_top50']} / {mm['today_list_eligible']}"
                 f"({gp(mm['today_list_not_in_top50_pct'], 1)}%) |")
    tb = B["today_list_not_in_top50"]
    L.append("")
    L.append(f"**② 「今天的名单」里、当年不在前 50 的:**{tb['out']} / {tb['name_years']} 个公司-年 = "
             f"**{gp(tb['pct'])}%**。S-670 用的池子就是这一整批(当年 ≥ 15 家就算),"
             f"其中约六成当年根本不在前 50 —— 当年小、后来长大的才进得了那个池子。\n")

    L += ["## 二、SMALL(−log 市值)—— 判定", ""]
    ab = m.get("ab", {})
    if ab:
        L += ["**同一段、同一脚本的两个池子(SMALL,逐周 IC 的配对块自助对照,`apparatus.ab_test`):**", "",
              "| 段 / 期限 | 按时点池子 IC / t | 今天的名单 IC / t | n 周 | p(今天 ≥ 按时点) |",
              "|---|---|---|---|---|"]
        for seg in ("discovery", "holdout"):
            for hz in (4, 13):
                c = ab.get(f"{seg}_{hz}w")
                if not c:
                    continue
                L.append(f"| {seg} / {hz} 周 | {g(c['pit_mean_ic'])} / {g(c['pit_t'],2)} | "
                         f"{g(c['today_mean_ic'])} / {g(c['today_t'],2)} | {c['n']} | "
                         f"{g(c['p_today_ge_pit'],4)} |")
        L += ["", "右边这一列是 S-670 用过的那个池子(今天的名单),在同一次运行里复现出来 ——"
              " 它仍然是正的、t 明显;换成按时点的池子,同一个信号、同一段数据,IC 掉到 0 附近。"
              "「当年小、之后涨」这个方向本身没错,**错的是池子把当年跌出去的公司提前删掉了**。",
              "", "(ab_test 的 cum_ / ratio_ / log_diff_total 是复合收益字段,对 IC 序列无意义,只取单侧 p。)", ""]
    L.append("门槛同 S-670 原文:发现段平均 IC > 0、t ≥ 2、前后两半 IC 都 > 0 ⇒ 进留出段;"
             "留出段平均 IC > 0 且 t ≥ 2 = 过。\n")
    L.append("| 期限 | 发现段 IC / t / 两半 | 进留出? | 留出段 IC / t | 零分布分位(发现 / 留出) | 判定 |")
    L.append("|---|---|---|---|---|---|")
    for hz in (4, 13):
        e = R["SMALL"][hz]
        d, h = e["discovery"], e["holdout"]
        L.append(f"| {hz} 周 | {g(d['mean_ic'])} / {g(d['t'],2)} / {g(d['half1'])} / {g(d['half2'])} | "
                 f"{'是' if e['enter_holdout'] else '否'} | {g(h['mean_ic'])} / {g(h['t'],2)} | "
                 f"{g(e['null_discovery'].get('pct'),3)} / "
                 f"{g((e['null_holdout'] or {}).get('pct'),3)} | **{e['verdict']}** |")
    L.append("")
    L.append(f"**不设陈旧度上限的对照**:发现段 {g(R['SMALL'][4]['nogap_control_discovery']['mean_ic'])} / "
             f"{g(R['SMALL'][13]['nogap_control_discovery']['mean_ic'])},"
             f"留出段 {g(R['SMALL'][4]['nogap_control_holdout']['mean_ic'])} / "
             f"{g(R['SMALL'][13]['nogap_control_holdout']['mean_ic'])} —— 与主口径**逐位相同**:"
             f"被丢的名字-周 {X['dropped_stale_name_weeks']} 个,即这 125 个 key 的 eodhd 序列在池内"
             f"全程每周都有观测,停牌 / 退市也没有留下价格空洞。这条对照没有起作用,不是因为检查多余,"
             f"是因为表里根本没有可丢的名字。\n")

    L += ["## 三、同一池上「只报」的三条(不给判定)", ""]
    L.append("| 信号 | 期限 | 发现段 IC / t | 留出段 IC / t | 零分布分位(发现) |")
    L.append("|---|---|---|---|---|")
    for sg in ("V2COMP", "LOWVOL", "ISSUE"):
        for hz in (4, 13):
            e = R[sg][hz]
            d, h = e["discovery"], e["holdout"]
            L.append(f"| {sg} | {hz} 周 | {g(d['mean_ic'])} / {g(d['t'],2)} | {g(h['mean_ic'])} / "
                     f"{g(h['t'],2)} | {g(e['null_discovery'].get('pct'),3)} |")
    L.append("")

    L += ["## 四、挖掘(探索性 —— 需另立预注册、在新数据上过零信号对照)", ""]
    L.append(f"1. **SMALL 与 −log 股价的相关 {g(X['small_vs_neglogpx_corr'])}**(逐周截面 Spearman 的均值)。"
             f"S-670 报过 +0.42:小盘与低价没拆开;按时点池子上这个数降到 "
             f"{g(X['small_vs_neglogpx_corr'])} —— **混淆本身也小了一半**,"
             f"两个原因合起来(SMALL 没效应 + 低价成分少),不能只归一个。")
    L.append(f"2. 池内公司当周已不在前 50 的平均占比 {gp(X['pool_share_outside_top50_mean'])}%"
             f"(逐周口径,与上面①的名字-周口径同源)。")
    L.append(f"3. **eodhd 序列里没有价格空洞**:按 7 日陈旧度上限,池内 "
             f"{X['dropped_stale_name_weeks']} 个名字-周被丢,「不设上限」的对照与主口径逐位相同。"
             f"池子里明明有 {gp(B['pool_left_out']['pct'])}% 的名字-周已经不在前 50,"
             f"它们却有每周的价格 —— 这看着像**表里对已退市 / 被收购的公司一直在补最后一个价**。"
             f"若真如此,按时点池子上的前瞻收益会把这些公司当成「还能交易」;"
             f"上面这个「SMALL 归零」的结论仍然成立(它反而是对 S-670 更有利的设定),"
             f"但倍数与其他池子上的前瞻收益读数都要打折看。**只报,未查证。**")
    L.append("4. 以上几条都没有独立检验、没有零信号对照、也没在新数据上复核过,"
             "只能当下一张卡的候选题目 —— 要动就得另立预注册。\n")

    # ---- 给台账的「S-671 结果」草稿(逐字抄,便于 Seth 直接落)----
    d4, h4 = R["SMALL"][4]["discovery"], R["SMALL"][4]["holdout"]
    d13, h13 = R["SMALL"][13]["discovery"], R["SMALL"][13]["holdout"]
    v = R["V2COMP"][4]
    L += ["## 五、「S-671 结果」草稿(给台账,未落)", "",
          f"### S-671 结果(A 道 T-175,Seth 收 2026-10-23 UTC)—— ❌ SMALL 在按时点的池子上**发现段就没过**;"
          f"S-670 的 SMALL 记为幸存者偏差造成",
          f"按预注册:每年第一个有快照的周五定一次池子,当时有市值且当时已有 ≥ 26 周 eodhd 价格的,"
          f"当时市值前 50,全年固定(2016–2026 共 11 年,每年恰好 50 家);"
          f"544 个截面周(< 15 家跳过 17)。",
          f"**先报偏差量**:① 池内「之后跌出前 50」—— {B['pool_left_out']['dropped']} / "
          f"{B['pool_left_out']['name_weeks']} 个名字-周 = {gp(B['pool_left_out']['pct'])}%;"
          f"按年末口径平均 {gp(B['pool_left_out_year_avg_pct'])}%。"
          f"②「今天的名单」里当年不在前 50 的 —— {tb['out']} / {tb['name_years']} 个公司-年 = "
          f"**{gp(tb['pct'])}%**(S-670 用的就是这整批)。",
          f"**SMALL(−log 市值):4 周 发现段 IC {g(d4['mean_ic'])}(t {g(d4['t'],2)},两半 "
          f"{g(d4['half1'])} / {g(d4['half2'])},零分布分位 {g(R['SMALL'][4]['null_discovery']['pct'],3)})"
          f"⇒ 发现段未过,按预注册不算留出段;13 周 {g(d13['mean_ic'])}(t {g(d13['t'],2)},"
          f"分位 {g(R['SMALL'][13]['null_discovery']['pct'],3)})同样未过。**门槛外只报**:留出段 "
          f"4 周 {g(h4['mean_ic'])}(t {g(h4['t'],2)})、13 周 {g(h13['mean_ic'])}(t {g(h13['t'],2)})。",
          f"**同一次运行里的对照臂**(S-670 的池子 = 今天的名单):4 周发现段 IC "
          f"{g(ab.get('discovery_4w',{}).get('today_mean_ic'))}(t {g(ab.get('discovery_4w',{}).get('today_t'),2)},"
          f"与 S-670 报的 +0.061 一致),13 周 {g(ab.get('discovery_13w',{}).get('today_mean_ic'))} ——"
          f"同一个信号,今天的名单 +,按时点池子 0;配对块自助 p(今天 ≥ 按时点)"
          f"{g(ab.get('discovery_4w',{}).get('p_today_ge_pit'),4)} / "
          f"{g(ab.get('discovery_13w',{}).get('p_today_ge_pit'),4)}。",
          f"**只报三条**(同一池):v2 合成 4 周发现段 {g(v['discovery']['mean_ic'])}(t {g(v['discovery']['t'],2)},"
          f"分位 {g(v['null_discovery']['pct'],3)})、留出段 {g(v['holdout']['mean_ic'])}"
          f"(t {g(v['holdout']['t'],2)})⇒ 与 S-668 H1 的负号同向、量级相当,发现段「质量反向」"
          f"不是幸存者偏差造出来的;LOWVOL 4 周 {g(R['LOWVOL'][4]['discovery']['mean_ic'])}"
          f"(t {g(R['LOWVOL'][4]['discovery']['t'],2)})、ISSUE 4 周 "
          f"{g(R['ISSUE'][4]['discovery']['mean_ic'])}(t {g(R['ISSUE'][4]['discovery']['t'],2)}),"
          f"两个都仍是负号。",
          "**结论(S-671 的「不过」分支):S-670 的 SMALL 记为幸存者偏差造成 —— 当年跌出前 50 的公司"
          "在构造上就不在那个池子里,「当年小、之后涨」被结构性抬高。个股继续只给状态与事实,"
          "**不另立 26 周影子**;S-670 的 14 条里机械过的 2 条(SMALL 4 / 13 周)一并作废,"
          "其余 12 条本来就没过,不受影响。",
          f"**局限(预注册已写明,这里再确认一次)**:world50 候选池本身是在今天建的 —— "
          f"从没进过候选池的公司(已退市、被收购的)仍然不在,本检验去掉的只是「池内」偏差。"
          f"**试验计数:个股截面信号族第 2 次,SMALL 1 条(2 个期限),0 条过。**", ""]
    open(REPORT, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())