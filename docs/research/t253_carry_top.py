#!/usr/bin/env python3
"""T-253 / S-735 — ④ 套息的截面选择:只做过去 30 天费率最高的一半名字,对照 S-733 规则 B(全部 22 名)。

口径照 REFUTATION_LEDGER §S-735 写死,一项不改:

  数据    Mac 数据根 _data/hyperliquid_funding/*_funding_1h.csv(HL 已实现小时费率)
  面板    ① 24 名里有小时档的 22 名(缺 ADA、LTC)
  窗口    2023-06-08 → 2026-07-20(2023-06-01~06-07 当日 < 20 小时档,按 S-733 丢弃)
  每日    已实现 funding = 当日小时费率之和;当日 ≥ 20 个小时档才算「有数」
  控制臂  S-733 规则 B:每周一看过去 7 天日费率均值 > 0 且至少 5 天有数则开、否则空仓,按周换仓;
          等权 = 当日有费率的 22 名等权(不动 S-733)
  处理臂  carry_b_top:每周一按**过去 30 天(不含当天)**日费率均值排名,只在前一半(11 名,并列按代码字母)
          上执行规则 B;其余空仓;11 名等权(每个槽位 = 1/11 本钱)
  净      毛 − 7.5bp × 切换次数(现货 taker 4bp + 永续 taker 3.5bp);切换 = 该名「在选中名单且开仓」
          状态相对上周发生变化(开仓、关仓、被名单踢出都算一次)

控制臂的取数 / 门控 / 费用口径直接 import `t250_carry.py`(S-733 盲复算,与 Seth 的实现逐项吻合),
不重写一遍。只算、不改代码、不入库。

【槽位分母的口径歧义 —— 主口径 + 三个敏感性都算】
台账 §S-735 写「只在前一半(11 名)上执行规则 B,等权;其余空仓」,但没写清「等权」的分母是
  (i)  选中且当日有费率的 11 名(本脚本主口径,照 S-733「当日有费率的名字等权」套到选中名单上)
  (ii) 固定 11(名单里有名字当日没数据 ⇒ 那个槽位空转)
  (iii) 当日有费率的全部 22 名(= 只在 11 个槽位上交易,另外 11 个槽位的钱闲置)
  (iv) 当日选中且开仓的名数(钱在开仓的名之间重新分配)
(i) 与 (ii) 几乎相同;(iii) 是另一种读法(处理臂只有一半本钱在场上),(iv) 是更激进的一种。
(iii) 下 (a) 的「净差 ≥ +2pp」几乎不可能达成 —— 处理臂结构性地只有控制臂一半的槽位在收租,
     任何截面挑选都改不了这一点 ⇒ 那样的判据等于没设。故以 (i) 为主口径,(iii) 明确标为敏感性。
"""
from __future__ import annotations

import ast
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from src.data.evaluation.apparatus import ab_test  # noqa: E402
import t250_carry as T  # noqa: E402  — S-733 口径(不重写)

DATA_ROOT = T.DATA_ROOT
FEE = T.FEE
MIN_BARS_PER_DAY = T.MIN_BARS_PER_DAY
PERIODS = T.PERIODS

WIN_START = date(2023, 6, 8)      # 卡片/S-735 的样本起点(首个 ≥20 小时档的日子)
WIN_END = date(2026, 7, 20)
TOP_N = 11                        # 前一半(22 名的一半)
LOOKBACK_DAYS = 30                # 排名只用信号日之前 30 天
AB_SEED = 735


# ───────────────────────────── 取数(照 t250,不动) ─────────────────────────────
def load_panel() -> list[str]:
    tree = ast.parse(open(T.PANEL_SRC, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "DEFAULT_UNIVERSE" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise RuntimeError("DEFAULT_UNIVERSE not found")


def load_funding(sym: str) -> dict[date, tuple[float, int]]:
    path = os.path.join(DATA_ROOT, f"{sym.lower()}_funding_1h.csv")
    agg: dict[date, list[float]] = defaultdict(lambda: [0.0, 0])
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0] == "fundingTime":
                continue
            day = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).date()
            cell = agg[day]
            cell[0] += float(row[1])
            cell[1] += 1
    return {d: (v[0], v[1]) for d, v in agg.items()}


def build_matrices(panel: list[str]):
    """与 t250.build_matrices 同口径(窗口从 2023-06-01 起,便于回看与门控周一完全一致)。"""
    days = list(T.daterange(T.WIN_START, T.WIN_END))
    idx = {d: i for i, d in enumerate(days)}
    n_t, n_n = len(days), len(panel)
    R = np.zeros((n_t, n_n))
    PRESENT = np.zeros((n_t, n_n), dtype=bool)
    aggs = []
    for j, sym in enumerate(panel):
        agg = load_funding(sym)
        aggs.append(agg)
        if not agg:
            continue
        for d, (s, c) in agg.items():
            if d in idx and c >= MIN_BARS_PER_DAY:
                R[idx[d], j] = s
                PRESENT[idx[d], j] = True
    return days, idx, R, PRESENT, aggs


# ───────────────────────── 截面选择:过去 30 天前一半 ─────────────────────────
def select_at(m, aggs_view, panel, top_n=TOP_N):
    """周一 m 的选择:过去 30 天(不含 m)日费率均值降序,取前 top_n;并列按代码字母。

    只用 d < m 的日子 —— 断言写在这里。
    """
    rows = []
    for j, sym in enumerate(panel):
        vals = []
        for k in range(1, LOOKBACK_DAYS + 1):
            d = m - timedelta(days=k)
            cell = aggs_view[j].get(d)
            if cell and cell[1] >= MIN_BARS_PER_DAY:
                vals.append((d, cell[0]))
        if not vals:
            continue
        # —— 防未来函数:用的日子必须全部落在 [m-30, m) ——
        assert all(d < m for d, _ in vals), f"泄漏:用了 {m} 当天或之后的费率"
        assert all(d >= m - timedelta(days=LOOKBACK_DAYS) for d, _ in vals)
        rows.append({"sym": sym, "j": j, "mean": sum(v for _, v in vals) / len(vals),
                     "n_days": len(vals)})
    rows.sort(key=lambda r: (-r["mean"], r["sym"]))
    return rows[:top_n], rows


def build_selection(panel, aggs, mons, top_n=TOP_N):
    sel = np.zeros((len(mons), len(panel)), dtype=bool)
    info = []
    for wi, m in enumerate(mons):
        top, rows = select_at(m, aggs, panel, top_n)
        for r in top:
            sel[wi, r["j"]] = True
        info.append({
            "monday": str(m),
            "pool_size": len(rows),
            "selected": [r["sym"] for r in top],
            "cut_mean": top[-1]["mean"] if top else None,
            "first_mean": top[0]["mean"] if top else None,
            "min_valid_days": min((r["n_days"] for r in top), default=None),
        })
    return sel, info


class _Poisoned:
    """把 cutoff(含)之后的所有日子换成随机费率 —— 用来证伪「未来函数」。"""

    def __init__(self, agg, cutoff, rng):
        self.agg = agg
        self.cutoff = cutoff
        self.rng = rng

    def get(self, d):
        if d >= self.cutoff:
            return (self.rng.uniform(-3e-4, 3e-4), 24)
        return self.agg.get(d)


def assert_no_future_leakage(panel, aggs, mons, sel):
    """把信号日之后的费率全部打乱,重算选择 —— 结果必须一字不差。"""
    rng = np.random.default_rng(AB_SEED)
    for wi, m in enumerate(mons):
        view = [_Poisoned(aggs[j], m, rng) for j in range(len(panel))]
        top, _ = select_at(m, view, panel)
        got = {r["sym"] for r in top}
        want = {panel[j] for j in np.flatnonzero(sel[wi])}
        assert got == want, f"未来函数:选择受 {m} 之后的数据影响"
    return {"mondays_checked": len(mons),
            "method": "poison every rate on/after the signal day → selection must be unchanged"}


# ───────────────────────── 处理臂:选中 ∩ 规则 B,逐周状态 = 切换 ─────────────────────────
def build_treatment(days, idx, R, PRESENT, gate, sel, mons):
    n_t, n_n = R.shape
    active = np.zeros((n_t, n_n), dtype=bool)
    selected = np.zeros((n_t, n_n), dtype=bool)
    switch_day = np.zeros((n_t, n_n), dtype=bool)
    switch_count = np.zeros(n_n, dtype=int)
    prev = np.zeros(n_n, dtype=bool)
    for wi, m in enumerate(mons):
        for j in range(n_n):
            st = bool(sel[wi, j] and gate[idx[m], j])
            if st != prev[j]:
                switch_day[idx[m], j] = True
                switch_count[j] += 1
            prev[j] = st
            for k in range(0, 7):
                d = m + timedelta(days=k)
                if d in idx:
                    active[idx[d], j] = st
                    selected[idx[d], j] = bool(sel[wi, j])
    return active, selected, switch_day, switch_count


def arm_from(active, R, switch_day, denom):
    """按给定槽位分母算一条臂:毛 = Σ(持仓中的费率) / 分母;费 = 7.5bp × 当日切换数 / 分母。"""
    d = np.maximum(denom, 1)
    gross = (active * R).sum(axis=1) / d
    fee = FEE * switch_day.sum(axis=1) / d
    return gross, fee, gross - fee


def stats(net, gross, fee_daily, mask, switches):
    n = int(mask.sum())
    years = n / 365.0
    nav = float(np.prod(1.0 + net[mask]))
    navs = np.cumprod(1.0 + net[mask])
    return {
        "days": n,
        "years": round(years, 4),
        "total_pct": float(np.expm1(np.log1p(net[mask]).sum())) * 100,
        "arith_ann_pct": float(net[mask].mean()) * 365 * 100,
        "compound_ann_pct": (nav ** (365.0 / n) - 1.0) * 100 if nav > 0 else None,
        "gross_ann_pct": float(gross[mask].mean()) * 365 * 100,
        "fee_ann_pct": float(fee_daily[mask].mean()) * 365 * 100,
        "fee_total_pct": float(fee_daily[mask].sum()) * 100,
        "max_dd_pct": float((navs / np.maximum.accumulate(navs) - 1.0).min()) * 100,
        "switches": int(switches),
        "switches_per_year": switches / years if years > 0 else None,
    }


def per_period(net, days, mask_base):
    out = {}
    for label, a, b in PERIODS:
        m = mask_base & np.array([(d >= a) and (d <= b) for d in days])
        if m.sum() == 0:
            continue
        seg = net[m]
        n = int(m.sum())
        nav = float(np.prod(1.0 + seg))
        navs = np.cumprod(1.0 + seg)
        out[label] = {
            "days": n,
            "total_pct": float(np.expm1(np.log1p(seg).sum())) * 100,
            "arith_ann_pct": float(seg.mean()) * 365 * 100,
            "compound_ann_pct": (nav ** (365.0 / n) - 1.0) * 100 if nav > 0 else None,
            "max_dd_pct": float((navs / np.maximum.accumulate(navs) - 1.0).min()) * 100,
        }
    return out


def neg_segments(panel, days, R, active, fee_name):
    """逐名:在「持仓日」序列上找连续负费率段(缺口/未持仓断段),累计 = Σ费率 + Σ费用。"""
    longest = worst = None
    segs = []
    for j, sym in enumerate(panel):
        act = list(np.flatnonzero(active[:, j]))
        run: list[int] = []
        for i in act + [None]:
            if i is not None and R[i, j] < 0:
                run.append(i)
                continue
            if run:
                cum = float(sum(R[i, j] for i in run)) + float(sum(fee_name[i, j] for i in run))
                seg = {"symbol": sym, "days": len(run), "cum_pct": cum * 100,
                       "start": str(days[run[0]]), "end": str(days[run[-1]])}
                segs.append(seg)
                if longest is None or seg["days"] > longest["days"]:
                    longest = seg
                if worst is None or seg["cum_pct"] < worst["cum_pct"]:
                    worst = seg
                run = []
    return longest, worst, segs


def mechanism_check(panel, aggs, mons, R, idx, days):
    """机制检查:信号(过去 30 天日费率均值)对**下一周**实际收的费率有没有预测力。

    每周一:对池子里每个名字算 signal = 过去 30 天日费率均值、outcome = 当周 [m, m+6] 的日费率均值,
    算截面 Spearman;再看 11 名里每名的 signal 是否与 outcome 同号。
    """
    rhos, hit, n_pair = [], [], []
    for m in mons:
        rows = []
        for j, sym in enumerate(panel):
            agg = aggs[j]
            sig, sig_days = [], []
            for k in range(1, LOOKBACK_DAYS + 1):
                d = m - timedelta(days=k)
                cell = agg.get(d)
                if cell and cell[1] >= MIN_BARS_PER_DAY:
                    sig.append(cell[0])
                    sig_days.append(d)
            out = []
            for k in range(0, 7):
                d = m + timedelta(days=k)
                cell = agg.get(d)
                if cell and cell[1] >= MIN_BARS_PER_DAY:
                    out.append(cell[0])
            if len(sig) < 5 or len(out) < 5:
                continue
            rows.append({"sym": sym, "sig": sum(sig) / len(sig), "out": sum(out) / len(out)})
        if len(rows) < 8:
            continue
        x = [r["sig"] for r in rows]
        y = [r["out"] for r in rows]
        rho = T.spearman(x, y)
        if rho is not None:
            rhos.append(rho)
        rows.sort(key=lambda r: (-r["sig"], r["sym"]))
        top11 = rows[:TOP_N]
        hit.append(sum(1 for r in top11 if r["out"] > 0) / len(top11))
        n_pair.append(len(rows))
    rhos_arr = np.array(rhos)
    hit_arr = np.array(hit)
    return {
        "weeks_measured": len(rhos),
        "mean_spearman_sig_vs_next_week": float(rhos_arr.mean()),
        "median_spearman": float(np.median(rhos_arr)),
        "frac_weeks_rho_positive": float((rhos_arr > 0).mean()),
        "frac_top11_with_positive_next_week_funding": float(hit_arr.mean()),
        "note": "signal = 过去 30 天日费率均值(周一决策);outcome = 该周 [m, m+6] 实际日费率均值",
    }


def main() -> None:
    out = {"task": "T-253", "ledger": "S-735",
           "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    panel = load_panel()
    days, idx, R, PRESENT, aggs = build_matrices(panel)
    n_t, n_n = R.shape
    mons = T.mondays(T.WIN_START, T.WIN_END)
    mask = np.array([(d >= WIN_START) and (d <= WIN_END) for d in days])
    mask_full = np.ones(n_t, dtype=bool)

    out["window"] = {"start": str(WIN_START), "end": str(WIN_END), "days": int(mask.sum()),
                     "note": "2023-06-01~06-07 当日 <20 小时档,按 S-733 丢弃;门控周一与 S-733 同(从 06-05 起)"}
    out["panel"] = panel
    out["panel_with_funding"] = [p for j, p in enumerate(panel) if len(aggs[j]) > 0]
    out["caliber"] = {
        "min_bars_per_day": MIN_BARS_PER_DAY, "fee_bps_per_switch": T.FEE_BPS,
        "top_n": TOP_N, "lookback_days": LOOKBACK_DAYS,
        "switch_definition": "该名「在选中名单且开仓」状态相对上周变化(开/关/被踢出名单各记 1 次)",
        "primary_slot_base": "selected_present —— 选中且当日有费率的 11 个槽位等权(S-733「当日有费率的名字等权」套到选中名单)",
        "sensitivity_slot_bases": ["fixed_11", "panel_22", "open_selected"],
    }

    # ── 控制臂:S-733 规则 B(全部 22 名,不动) ──
    gate, switch_day, switch_count = T.weekly_gate(R, PRESENT, days, idx, aggs)
    ctrl_net, ctrl_gross, ctrl_fee_daily, ctrl_fee_name = T.rule_b(R, PRESENT, gate, switch_day)
    ctrl_net_a, ctrl_gross_a, ctrl_fee_a, ctrl_fee_name_a, _entry = T.rule_a(R, PRESENT)
    ctrl_switches = int(switch_count.sum())
    count = PRESENT.sum(axis=1)

    # ── 处理臂:前一半 ──
    sel, sel_info = build_selection(panel, aggs, mons)
    out["leakage_assertion"] = assert_no_future_leakage(panel, aggs, mons, sel)
    act_mask, selected_mask, top_switch_day, top_switch_count = build_treatment(
        days, idx, R, PRESENT, gate, sel, mons)
    active = PRESENT & act_mask
    top_switches = int(top_switch_count.sum())

    denom_sel_present = (selected_mask & PRESENT).sum(axis=1).astype(float)
    denom_sel_fixed = selected_mask.sum(axis=1).astype(float)
    denom_panel = count.astype(float)
    denom_open_sel = active.sum(axis=1).astype(float)

    variants = {}
    for name, den in (("selected_present", denom_sel_present),
                      ("fixed_11", denom_sel_fixed),
                      ("panel_22", denom_panel),
                      ("open_selected", denom_open_sel)):
        g, f, n_ = arm_from(active, R, top_switch_day, den)
        variants[name] = {"gross": g, "fee": f, "net": n_}

    out["control_rule_b"] = stats(ctrl_net, ctrl_gross, ctrl_fee_daily, mask, ctrl_switches)
    out["control_rule_b_full_window"] = stats(ctrl_net, ctrl_gross, ctrl_fee_daily, mask_full, ctrl_switches)
    out["control_rule_a_full_window"] = stats(ctrl_net_a, ctrl_gross_a, ctrl_fee_a, mask_full,
                                               int((ctrl_fee_name_a != 0).sum()))

    arm = {k: stats(v["net"], v["gross"], v["fee"], mask, top_switches) for k, v in variants.items()}
    out["arm_top_half"] = arm["selected_present"]
    out["arm_top_half_variants"] = {
        k: {**arm[k],
            "ann_diff_vs_control_pp": arm[k]["arith_ann_pct"] - out["control_rule_b"]["arith_ann_pct"],
            "note": {"selected_present": "主口径",
                     "fixed_11": "固定 11 槽位(名单里有名字当日没数据则空转)",
                     "panel_22": "另一种读法:22 个槽位,只在 11 个上交易,另外 11 个的钱闲置",
                     "open_selected": "钱在当日选中且开仓的名之间重新分配"}[k]}
        for k in arm
    }

    # ── 逐期(主口径) ──
    pp_ctrl = per_period(ctrl_net, days, mask)
    pp_top = per_period(variants["selected_present"]["net"], days, mask)
    for label in pp_ctrl:
        pp_ctrl[label]["diff_total_pp"] = pp_top[label]["total_pct"] - pp_ctrl[label]["total_pct"]
        pp_ctrl[label]["diff_arith_ann_pp"] = pp_top[label]["arith_ann_pct"] - pp_ctrl[label]["arith_ann_pct"]
    out["per_period"] = {"control_rule_b": pp_ctrl, "arm_top_half": pp_top}

    # ── (a) 年化净差 + ab_test(主口径;敏感性口径只报差与 p) ──
    ab = ab_test(ctrl_net[mask].tolist(), variants["selected_present"]["net"][mask].tolist(),
                 mean_block=20.0, n_boot=2000, seed=AB_SEED)
    out["ab_test"] = {"ret_a": "control_rule_b", "ret_b": "arm_top_half(selected_present)",
                      "mean_block": 20, "n_boot": 2000, "seed": AB_SEED, **ab}
    ab_by_variant = {}
    for k, v in variants.items():
        r = ab_test(ctrl_net[mask].tolist(), v["net"][mask].tolist(),
                    mean_block=20.0, n_boot=2000, seed=AB_SEED)
        ab_by_variant[k] = {"p_one_sided_B_gt_A": r["p_b_le_a"], "p_one_sided_B_lt_A": r["p_b_ge_a"],
                            "ci95_log_diff": r["ci95_log_diff"], "verdict": r["verdict"]}
    out["ab_test_by_slot_base"] = ab_by_variant

    ann_diff = out["arm_top_half"]["arith_ann_pct"] - out["control_rule_b"]["arith_ann_pct"]
    ann_diff_comp = (out["arm_top_half"]["compound_ann_pct"] -
                      out["control_rule_b"]["compound_ann_pct"])

    # ── (b) 2025-01 → 2026-07 这段单独看 ──
    m_b = mask & np.array([(d >= date(2025, 1, 1)) and (d <= WIN_END) for d in days])
    b_ctrl = float(np.expm1(np.log1p(ctrl_net[m_b]).sum())) * 100
    b_top = float(np.expm1(np.log1p(variants["selected_present"]["net"][m_b]).sum())) * 100
    b_diff_sum = float((variants["selected_present"]["net"][m_b] - ctrl_net[m_b]).sum()) * 100

    # ── (c) 最长负段(逐名口径) ──
    top_fee_name = np.zeros_like(R)
    for j in range(n_n):
        top_fee_name[top_switch_day[:, j], j] = FEE
    c_long, c_worst, c_segs = neg_segments(panel, days, R, active, top_fee_name)
    ctl_long, ctl_worst, _ = neg_segments(panel, days, R, PRESENT & gate, ctrl_fee_name)

    # ── (d) 换手 ──
    years = out["control_rule_b"]["years"]
    ctrl_spy = ctrl_switches / years
    top_spy = top_switches / years

    out["criteria"] = {
        "a": {"ann_diff_pp_arith": ann_diff, "ann_diff_pp_compound": ann_diff_comp,
              "threshold_pp": 2.0, "p_one_sided_B_gt_A": ab["p_b_le_a"],
              "p_one_sided_B_lt_A": ab["p_b_ge_a"], "ab_verdict": ab["verdict"],
              "ci95_log_diff": ab["ci95_log_diff"], "verdict": None},
        "b": {"window": "2025-01-01 → 2026-07-20", "days": int(m_b.sum()),
              "control_total_pct": b_ctrl, "top_total_pct": b_top,
              "diff_total_pp": b_top - b_ctrl, "diff_daily_sum_pp": b_diff_sum, "verdict": None},
        "c": {"longest_neg_segment": c_long, "worst_neg_segment": c_worst,
              "control_longest": ctl_long, "control_worst": ctl_worst, "verdict": None},
        "d": {"control_switches": ctrl_switches, "top_switches": top_switches,
              "control_per_year": ctrl_spy, "top_per_year": top_spy,
              "ratio": top_spy / ctrl_spy if ctrl_spy else None,
              "control_switches_per_slot_per_year": ctrl_spy / 22.0,
              "top_switches_per_slot_per_year": top_spy / TOP_N,
              "note_per_slot": "判据按台账写死的「年化切换次数」判(总数);每槽位的换手另列",
              "verdict": None},
    }
    c = out["criteria"]
    c["a"]["verdict"] = bool(ann_diff >= 2.0 and ab["p_b_le_a"] < 0.05)
    c["b"]["verdict"] = bool((b_top - b_ctrl) >= 0)
    c["c"]["verdict"] = bool(c_long is not None and abs(c_long["cum_pct"]) <= 5.0)
    c["d"]["verdict"] = bool(top_spy <= 2 * ctrl_spy)
    c["all_pass"] = all(c[k]["verdict"] for k in ("a", "b", "c", "d"))
    c["note_slot_base"] = ("判据按主口径 selected_present 判;台账没写死「等权」的分母,"
                           "panel_22 读法下 (a) 结构上不可能达成(见脚本头注)")

    # ── 选择机制:名单换手 ──
    churn = [len(set(sel_info[wi - 1]["selected"]) - set(sel_info[wi]["selected"]))
             for wi in range(1, len(sel_info))]
    out["selection"] = {
        "weeks": len(sel_info),
        "avg_names_swapped_per_week": float(np.mean(churn)) if churn else None,
        "max_names_swapped_in_a_week": int(np.max(churn)) if churn else None,
        "weeks_with_change": int(sum(1 for c_ in churn if c_ > 0)),
        "pool_size_min": int(min(i["pool_size"] for i in sel_info)),
        "avg_cut_mean": float(np.mean([i["cut_mean"] for i in sel_info
                                       if i["cut_mean"] is not None])) if sel_info else None,
        "detail": sel_info,
    }

    # 逐名
    per_name = []
    for j, sym in enumerate(panel):
        per_name.append({
            "symbol": sym,
            "ctrl_gross_pct": float(ctrl_gross[mask].sum() * 100),
            "top_gross_pct": float((active * R)[mask].sum() * 100),
            "ctrl_switches": int(switch_count[j]),
            "top_switches": int(top_switch_count[j]),
            "ctrl_days_held": int((PRESENT[:, j] & gate[:, j]).sum()),
            "top_days_held": int(active[:, j].sum()),
            "weeks_selected": int(sel[:, j].sum()),
        })
    out["per_name"] = sorted(per_name, key=lambda r: -r["top_gross_pct"])

    # ── 探索性:控制臂开着但名单没选中的名-日,贡献了多少毛 ──
    dropped = PRESENT & gate & ~act_mask
    n_days_win = int(mask.sum())
    dropped_ann_pp = float((dropped * R).sum()) / n_days_win / 22.0 * 365 * 100
    ctrl_gross_ann_pp = float(ctrl_gross[mask].mean()) * 365 * 100
    out["exploratory_dropped_by_selection"] = {
        "name_days": int(dropped.sum()),
        "dropped_gross_ann_pp": dropped_ann_pp,
        "control_gross_ann_pp": ctrl_gross_ann_pp,
        "share_of_control_gross": dropped_ann_pp / ctrl_gross_ann_pp if ctrl_gross_ann_pp else None,
        "note": "控制臂开着、处理臂名单没选中的名-日,占控制臂毛收益的比例",
    }
    # 每槽位平均费率:选中名单 vs 全体(截面挑选的直接读数)
    out["exploratory_per_slot_funding"] = {
        "control_pct_per_slot_ann": ctrl_gross_ann_pp,
        "top_pct_per_slot_ann": float(variants["selected_present"]["gross"][mask].mean()) * 365 * 100,
        "note": "每槽位年化毛费率:控制臂 = 22 槽位等权;处理臂 = 11 个选中槽位等权",
    }
    # 直接读数:持仓名-日上的平均费率,选中 vs 全体(不含任何分母效应)
    sel_open = active
    all_open = PRESENT & gate
    out["mechanism_check"] = mechanism_check(panel, aggs, mons, R, idx, days)
    out["mechanism_check"]["mean_funding_per_nameday_selected_open"] = float(
        (sel_open * R).sum() / max(int(sel_open.sum()), 1))
    out["mechanism_check"]["mean_funding_per_nameday_all_open"] = float(
        (all_open * R).sum() / max(int(all_open.sum()), 1))
    out["mechanism_check"]["mean_funding_per_nameday_all_present"] = float(
        (PRESENT * R).sum() / max(int(PRESENT.sum()), 1))
    # 费用敏感性:把 7.5bp/次放大到多少倍,两臂的净差归零
    gross_gap = (float(variants["selected_present"]["gross"][mask].mean()) -
                 float(ctrl_gross[mask].mean())) * 365 * 100
    fee_gap = (float(variants["selected_present"]["fee"][mask].mean()) -
               float(ctrl_fee_daily[mask].mean())) * 365 * 100
    out["fee_sensitivity"] = {
        "gross_gap_pp_per_yr": gross_gap,
        "fee_gap_pp_per_yr_at_7_5bp": fee_gap,
        "breakeven_fee_multiple": (gross_gap / fee_gap) if fee_gap else None,
        "note": "费用放大到几倍时两臂净差归零(= 毛差 / 费差)",
    }
    # 边的来源:逐名贡献(处理臂毛 − 控制臂毛,按槽位口径折算)
    edge_rows = []
    for j, sym in enumerate(panel):
        ctrl_per_slot = float(ctrl_gross[mask].sum()) / 22.0
        top_per_slot = float((active * R)[mask].sum()) / 11.0
        edge_rows.append({"symbol": sym, "weeks_selected": int(sel[:, j].sum()),
                          "days_held": int(active[:, j].sum())})
    out["edge_attribution"] = {
        "per_name": edge_rows,
        "top5_by_days_held": [r["symbol"] for r in sorted(edge_rows, key=lambda r: -r["days_held"])[:5]],
        "note": "每名在名单里的周数 / 实际持仓日",
    }

    with open(os.path.join(HERE, "t253_results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)

    # ── 控制台摘要 ──
    print("== 控制臂 S-733 规则 B(22 槽位)==")
    for k in ("arith_ann_pct", "compound_ann_pct", "total_pct", "max_dd_pct", "gross_ann_pct",
              "fee_ann_pct", "fee_total_pct", "switches", "switches_per_year"):
        print(f"  {k}: {out['control_rule_b'][k]}")
    print(f"  (全窗口对照 T-250: arith {out['control_rule_b_full_window']['arith_ann_pct']:.4f}%, "
          f"switch {out['control_rule_b_full_window']['switches']})")
    print("== 处理臂 carry_b_top(各槽位分母口径)==")
    for k, v in out["arm_top_half_variants"].items():
        print(f"  [{k}] arith {v['arith_ann_pct']:.3f}% / comp {v['compound_ann_pct']:.3f}% / "
              f"gross {v['gross_ann_pct']:.3f}% / fee {v['fee_ann_pct']:.3f}% / "
              f"Δ {v['ann_diff_vs_control_pp']:+.3f}pp / p(B>A)={ab_by_variant[k]['p_one_sided_B_gt_A']}")
    print("== 判据(主口径 selected_present)==")
    print(json.dumps(out["criteria"], ensure_ascii=False, indent=1, default=float))
    print("== 逐期 ==")
    for label in pp_ctrl:
        c_ = pp_ctrl[label]
        t_ = pp_top[label]
        print(f"  {label}: ctrl arith {c_['arith_ann_pct']:.2f}% / total {c_['total_pct']:.2f}% "
              f"|| top arith {t_['arith_ann_pct']:.2f}% / total {t_['total_pct']:.2f}% "
              f"|| Δtotal {c_['diff_total_pp']:+.2f}pp")


if __name__ == "__main__":
    main()
