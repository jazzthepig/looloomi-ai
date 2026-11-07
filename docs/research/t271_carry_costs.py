#!/usr/bin/env python3
"""T-271(S-748):④ 套息在真实成本下还剩多少 —— HL 实测手续费 + 进出场基差 + 换仓频率。

口径照 REFUTATION_LEDGER S-748 写死(一字不改):
  * 基准臂 = S-735 的 carry_b_top(每周一按过去 30 天日费率均值取前一半、规则 B 7 日均 > 0 才开、等权)
             与 S-733 规则 B(全部名字)
  * 成本   = 现货 taker 7bp + 永续 taker 4.5bp + 每腿滑点 2bp,每次开 / 关各付一次 ⇒ 15.5bp/次
             (原口径 S-733/S-735 = 7.5bp/次:先复现,再换真实成本)
  * 基差   = 开仓时付 (永续 − 现货)/现货 的当日值、平仓时收回当日值
             (Binance 同名永续 perp_bv_daily 与现货 ohlcv_daily[source=binance_hist] 收盘作代理;
              缺任一 ⇒ 该次基差记 0 并计数)
  * 频率   = 每周(基准)/ 每两周 / 每月(4 周)
  * 判据 (a)–(d) 照台账,不改。

用法: python3 docs/research/t271_carry_costs.py
输出: docs/research/t271_results.json + 控制台摘要
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import t250_carry as T  # noqa: E402 — S-733 口径(不重写)
import t253_carry_top as T253  # noqa: E402 — S-735 口径(不重写)

# ───────────────────────── 成本口径(台账写死) ─────────────────────────
FEE_ORIG_BPS = 7.5            # S-733/S-735 原口径(现货 4 + 永续 3.5)
SPOT_TAKER_BPS = 7.0          # HL 实测现货 taker
PERP_TAKER_BPS = 4.5          # HL 实测永续 taker
SLIPPAGE_BPS_PER_LEG = 2.0    # 每腿滑点
FEE_REAL_BPS = SPOT_TAKER_BPS + PERP_TAKER_BPS + 2 * SLIPPAGE_BPS_PER_LEG   # 15.5
HL_SPOT_NAMES = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK", "TRX", "AAVE")

WIN_START = T253.WIN_START            # 2023-06-08(S-733 口径:首个 ≥20 小时档的日子)
WIN_END = T253.WIN_END                # 2026-07-20
TOP_N = T253.TOP_N                    # 11(22 名的前一半)
LOOKBACK_DAYS = T253.LOOKBACK_DAYS    # 30
MIN_BARS_PER_DAY = T.MIN_BARS_PER_DAY  # 20
PERIODS = T.PERIODS

# 决策日网格:控制臂从 2023-06-05(周一)起、处理臂从 2023-06-12(周一)起 —— 与 S-733/S-735 相同
CTRL_FIRST_MONDAY = date(2023, 6, 5)
TOP_FIRST_MONDAY = date(2023, 6, 12)

PX_START = "2023-05-01"     # 多取一个月:决策日回看 30 天要用到 4 月底
PX_END = "2026-07-20"

# ───────────────────────── Supabase 只读取价 ─────────────────────────
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(只读研究库)")
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}


def _get(table: str, params: dict):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{URL}/rest/v1/{table}?{q}", headers=HDR)
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode()
        rng = r.headers.get("Content-Range", "") or ""
    total = None
    if "/" in rng:
        tail = rng.split("/")[-1].strip()
        if tail.isdigit():
            total = int(tail)
    return (json.loads(body) if body else []), total


def fetch_closes(table: str, date_col: str, close_col: str, symbols: list[str],
                 extra_filter: str = "") -> tuple[dict, dict]:
    """按 symbol 分片、每页 ≤1000 行、order= 按日期升序翻页;返回 (px, 覆盖统计)。"""
    px: dict[str, dict[str, float]] = {}
    cover: dict[str, dict] = {}
    for sym in symbols:
        cond = f"{date_col}.gte.{PX_START},{date_col}.lte.{PX_END}"
        if extra_filter:
            cond += "," + extra_filter
        params = {"select": f"{date_col},{close_col}", "symbol": f"eq.{sym}",
                  "and": f"({cond})", "order": f"{date_col}.asc", "limit": "1000"}
        out: dict[str, float] = {}
        total = None
        pages = 0
        while True:
            rows, tot = _get(table, params)
            if pages == 0:
                total = tot
            pages += 1
            for r in rows:
                v = r.get(close_col)
                if v is not None:
                    out[str(r[date_col])[:10]] = float(v)
            if len(rows) < 1000:
                break
            last = str(rows[-1][date_col])[:10]
            params["and"] = f"({date_col}.gt.{last},{date_col}.lte.{PX_END}"
            if extra_filter:
                params["and"] += "," + extra_filter
            params["and"] += ")"
        px[sym] = out
        cover[sym] = {"rows": len(out), "count_exact": total, "pages": pages,
                      "first": min(out) if out else None, "last": max(out) if out else None}
    return px, cover


# ───────────────────────── 臂构建(把 S-733/S-735 的两段合成一个可参数化的) ─────────────────────────
def select_at_cols(m, aggs, panel, cols, top_n):
    """周一 m 的选择:过去 30 天(不含 m)日费率均值降序,取前 top_n;并列按代码字母。

    与 t253_carry_top.select_at 同口径(该版遍历全体 panel,无费率的自动跳过)。
    """
    rows = []
    for j in cols:
        vals = []
        for k in range(1, LOOKBACK_DAYS + 1):
            d = m - timedelta(days=k)
            cell = aggs[j].get(d)
            if cell and cell[1] >= MIN_BARS_PER_DAY:
                vals.append((d, cell[0]))
        if not vals:
            continue
        assert all(d < m for d, _ in vals), f"泄漏:用了 {m} 当天或之后的费率"
        rows.append({"sym": panel[j], "j": j, "mean": sum(v for _, v in vals) / len(vals),
                     "n_days": len(vals)})
    rows.sort(key=lambda r: (-r["mean"], r["sym"]))
    return rows[:top_n], rows


def decision_grid(start: date, end: date, step_weeks: int) -> list[date]:
    out = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=7 * step_weeks)
    return out


def build_arm(days, idx, R, PRESENT, aggs, panel, cols, dgrid, step_weeks,
              top_n, fee_bps, perp_px, spot_px, basis_mode="ledger", include_basis=True):
    """一条臂:持仓 / 切换 / 毛 / 费 / 基差 / 净。

    top_n=None ⇒ 规则 B(全部名字);否则 carry_b_top(选中 ∩ 规则 B,等权槽位)。
    basis_mode="ledger" ⇒ 开仓付 b、平仓收 b(台账字面);"econ" ⇒ 符号翻转(口径敏感性,只报)。
    """
    n_t, n_n = R.shape
    span = 7 * step_weeks
    sel = np.zeros((len(dgrid), n_n), dtype=bool)
    if top_n:
        for wi, m in enumerate(dgrid):
            top, _ = select_at_cols(m, aggs, panel, cols, top_n)
            for r in top:
                sel[wi, r["j"]] = True
    # 规则 B 的门:决策日看过去 7 天日费率均值 > 0 且 ≥5 天有数;该名的首个有数日之前不开
    gate: dict[tuple, bool] = {}
    for j in cols:
        agg = aggs[j]
        present_days = np.flatnonzero(PRESENT[:, j])
        if present_days.size == 0:
            continue
        first_day = days[present_days[0]]
        for m in dgrid:
            if m < first_day:
                continue
            vals = []
            for k in range(1, 8):
                cell = agg.get(m - timedelta(days=k))
                if cell and cell[1] >= MIN_BARS_PER_DAY:
                    vals.append(cell[0])
            gate[(m, j)] = bool(len(vals) >= 5 and (sum(vals) / len(vals) > 0))
    # 状态 / 切换
    active = np.zeros((n_t, n_n), dtype=bool)
    selected = np.zeros((n_t, n_n), dtype=bool)
    switch_day = np.zeros((n_t, n_n), dtype=bool)
    switch_open = np.zeros((n_t, n_n), dtype=bool)
    switch_close = np.zeros((n_t, n_n), dtype=bool)
    prev = {j: False for j in cols}
    for wi, m in enumerate(dgrid):
        for j in cols:
            g = gate.get((m, j), False)
            st = bool(sel[wi, j] and g) if top_n else bool(g)
            if st != prev[j]:
                switch_day[idx[m], j] = True
                if st:
                    switch_open[idx[m], j] = True
                else:
                    switch_close[idx[m], j] = True
                prev[j] = st
            for k in range(span):
                d = m + timedelta(days=k)
                if d in idx:
                    active[idx[d], j] = st
                    selected[idx[d], j] = bool(sel[wi, j])
    sub_present = PRESENT[:, cols]
    if top_n:
        denom = (selected[:, cols] & sub_present).sum(axis=1).astype(float)
    else:
        denom = sub_present.sum(axis=1).astype(float)
    denom = np.maximum(denom, 1.0)
    gross = (active[:, cols] * R[:, cols]).sum(axis=1) / denom
    fee = (fee_bps / 10_000.0) * switch_day.sum(axis=1) / denom
    # 基差:开仓付 b、平仓收 b(缺任一 ⇒ 记 0 并计数)
    basis_name = np.zeros((n_t, n_n))
    missing = 0
    missing_detail = []
    basis_at_switch = []
    for j in cols:
        sym = panel[j]
        if not include_basis:
            continue
        for i in np.flatnonzero(switch_day[:, j]):
            t = str(days[i])
            p, s = perp_px.get(sym, {}).get(t), spot_px.get(sym, {}).get(t)
            if p is None or s is None or s == 0:
                missing += 1
                if len(missing_detail) < 40:
                    missing_detail.append({"symbol": sym, "date": str(t),
                                           "side": "open" if switch_open[i, j] else "close"})
                b = 0.0
            else:
                b = (p - s) / s
                basis_at_switch.append(b)
            contrib = -b if switch_open[i, j] else b
            if basis_mode == "econ":
                contrib = -contrib
            basis_name[i, j] = contrib
    basis = basis_name.sum(axis=1) / denom
    net = gross - fee + basis
    # 逐名的费+基差序列(给 (c) 逐名负段用)
    cost_name = np.zeros((n_t, n_n))
    for j in cols:
        cost_name[switch_day[:, j], j] = fee_bps / 10_000.0
    cost_name += basis_name
    return {"gross": gross, "fee": fee, "basis": basis, "net": net,
            "active": active, "selected": selected, "switch_day": switch_day,
            "switch_open": switch_open, "switch_close": switch_close,
            "denom": denom, "cost_name": cost_name, "basis_missing": missing,
            "basis_missing_detail": missing_detail, "basis_at_switch": basis_at_switch,
            "switches": int(switch_day.sum())}


def stats(arm, days, mask, label):
    net, gross, fee, basis = arm["net"], arm["gross"], arm["fee"], arm["basis"]
    s = T253.stats(net, gross, fee, mask, arm["switches"])
    seg = net[mask]
    s["basis_ann_pct"] = float(basis[mask].mean()) * 365 * 100
    s["basis_total_pct"] = float(basis[mask].sum()) * 100
    s["net_total_pct"] = s["total_pct"]
    s["label"] = label
    return s


def per_period(arm, days, mask):
    out = {}
    for label, a, b in PERIODS:
        m = mask & np.array([(d >= a) and (d <= b) for d in days])
        if m.sum() == 0:
            continue
        seg = arm["net"][m]
        n = int(m.sum())
        nav = float(np.prod(1.0 + seg))
        navs = np.cumprod(1.0 + seg)
        out[label] = {
            "days": n,
            "total_pct": float(np.expm1(np.log1p(seg).sum())) * 100,
            "arith_ann_pct": float(seg.mean()) * 365 * 100,
            "compound_ann_pct": (nav ** (365.0 / n) - 1.0) * 100 if nav > 0 else None,
            "gross_ann_pct": float(arm["gross"][m].mean()) * 365 * 100,
            "fee_ann_pct": float(arm["fee"][m].mean()) * 365 * 100,
            "basis_ann_pct": float(arm["basis"][m].mean()) * 365 * 100,
            "max_dd_pct": float((navs / np.maximum.accumulate(navs) - 1.0).min()) * 100,
        }
    return out


def neg_segments(panel_sub, days, R_sub, active_sub, cost_name_sub):
    """逐名:在「持仓日」序列上找连续负费率段,累计 = Σ费率 + Σ(费用+基差)。"""
    longest = worst = None
    segs = []
    for j, sym in enumerate(panel_sub):
        act = list(np.flatnonzero(active_sub[:, j]))
        run: list[int] = []
        for i in act + [None]:
            if i is not None and R_sub[i, j] < 0:
                run.append(i)
                continue
            if run:
                cum = float(sum(R_sub[i, j] for i in run)) + float(sum(cost_name_sub[i, j] for i in run))
                seg = {"symbol": sym, "days": len(run), "cum_pct": cum * 100,
                       "start": str(days[run[0]]), "end": str(days[run[-1]])}
                segs.append(seg)
                if longest is None or seg["days"] > longest["days"]:
                    longest = seg
                if worst is None or seg["cum_pct"] < worst["cum_pct"]:
                    worst = seg
                run = []
    return longest, worst, segs


def main() -> None:
    out = {"task": "T-271", "ledger": "S-748",
           "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "cost_model": {"spot_taker_bps": SPOT_TAKER_BPS, "perp_taker_bps": PERP_TAKER_BPS,
                          "slippage_bps_per_leg": SLIPPAGE_BPS_PER_LEG,
                          "real_fee_bps_per_switch": FEE_REAL_BPS,
                          "orig_fee_bps_per_switch": FEE_ORIG_BPS,
                          "basis_rule": "开仓付 (永续−现货)/现货、平仓收当日值;缺任一记 0 并计数"},
           "window": {"start": str(WIN_START), "end": str(WIN_END)}}

    panel = T.load_panel()
    days, idx, R, PRESENT, aggs = T253.build_matrices(panel)
    n_t, n_n = R.shape
    mask = np.array([(d >= WIN_START) and (d <= WIN_END) for d in days])
    mask_b = mask & np.array([(d >= date(2025, 1, 1)) and (d <= WIN_END) for d in days])
    cols_all = [j for j in range(n_n) if len(aggs[j]) > 0]
    out["panel"] = panel
    out["panel_with_funding"] = [panel[j] for j in cols_all]
    out["window_days"] = int(mask.sum())

    # ── 取价(只读) ──
    syms = [panel[j] for j in cols_all]
    perp_px, perp_cover = fetch_closes("perp_bv_daily", "d", "c", syms)
    spot_px, spot_cover = fetch_closes("ohlcv_daily", "trade_date", "close", syms,
                                       extra_filter="source.eq.binance_hist")
    out["price_coverage"] = {"perp_bv_daily": perp_cover, "ohlcv_daily_binance_hist": spot_cover}
    both = sum(1 for s in syms if perp_px.get(s) and spot_px.get(s))
    out["price_coverage"]["symbols_with_both"] = both

    # ── 基差诊断:窗口内逐日基差水平(永续 − 现货)/现货 ──
    diag = {"per_symbol": {}, "overall": {}, "note": "基差 = (Binance 永续收盘 − 现货收盘)/现货收盘"}
    allv = []
    for sym in syms:
        common = sorted(set(perp_px.get(sym, {})) & set(spot_px.get(sym, {})))
        vals = [(perp_px[sym][d] - spot_px[sym][d]) / spot_px[sym][d] for d in common]
        allv += vals
        if vals:
            sv = sorted(vals)
            diag["per_symbol"][sym] = {"n": len(vals), "mean_bp": float(np.mean(vals)) * 1e4,
                                       "p5_bp": float(sv[len(sv) // 20]) * 1e4,
                                       "p95_bp": float(sv[len(sv) * 19 // 20]) * 1e4}
    if allv:
        sv = sorted(allv)
        diag["overall"] = {"n": len(allv), "mean_bp": float(np.mean(allv)) * 1e4,
                           "p5_bp": float(sv[len(sv) // 20]) * 1e4,
                           "p95_bp": float(sv[len(sv) * 19 // 20]) * 1e4,
                           "abs_mean_bp": float(np.mean(np.abs(allv))) * 1e4}
    out["basis_diagnostics"] = diag

    FREQS = {"weekly": 1, "biweekly": 2, "monthly": 4}

    # ── ① 复现 S-735 原口径(7.5bp/次、无基差) ──
    ref = json.load(open(os.path.join(HERE, "t253_results.json"), encoding="utf-8"))
    repro = {}
    arms = {}
    for fname, step in FREQS.items():
        dgrid_ctrl = decision_grid(CTRL_FIRST_MONDAY, WIN_END, step)
        dgrid_top = decision_grid(TOP_FIRST_MONDAY, WIN_END, step)
        a_ctrl = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_ctrl, step,
                           None, FEE_ORIG_BPS, perp_px, spot_px, include_basis=False)
        a_top = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_top, step,
                          TOP_N, FEE_ORIG_BPS, perp_px, spot_px, include_basis=False)
        arms[(fname, "orig", "rule_b_all")] = a_ctrl
        arms[(fname, "orig", "carry_b_top")] = a_top
        repro[fname] = {
            "rule_b_all": stats(a_ctrl, days, mask, f"orig/{fname}/rule_b_all"),
            "carry_b_top": stats(a_top, days, mask, f"orig/{fname}/carry_b_top"),
        }
    out["reproduce_orig_cost"] = repro
    # 与台账/T-253 的数字对账(weekly)
    r_top = repro["weekly"]["carry_b_top"]
    r_ctrl = repro["weekly"]["rule_b_all"]
    ref_top = ref["arm_top_half"]
    ref_ctrl = ref["control_rule_b"]
    out["reproduce_check"] = {
        "note": "S-735/T-253 台账数:处理臂 15.910%/yr、控制臂 12.263%/yr、切换 433 / 532",
        "carry_b_top": {"mine_arith_ann_pct": r_top["arith_ann_pct"],
                        "ledger_arith_ann_pct": ref_top["arith_ann_pct"],
                        "diff_pp": r_top["arith_ann_pct"] - ref_top["arith_ann_pct"],
                        "mine_switches": r_top["switches"], "ledger_switches": ref_top["switches"],
                        "ok_0p1pp": abs(r_top["arith_ann_pct"] - ref_top["arith_ann_pct"]) <= 0.1},
        "rule_b_all": {"mine_arith_ann_pct": r_ctrl["arith_ann_pct"],
                       "ledger_arith_ann_pct": ref_ctrl["arith_ann_pct"],
                       "diff_pp": r_ctrl["arith_ann_pct"] - ref_ctrl["arith_ann_pct"],
                       "mine_switches": r_ctrl["switches"], "ledger_switches": ref_ctrl["switches"],
                       "ok_0p1pp": abs(r_ctrl["arith_ann_pct"] - ref_ctrl["arith_ann_pct"]) <= 0.1},
    }

    # ── ② 真实成本三档频率 ──
    real = {}
    for fname, step in FREQS.items():
        dgrid_ctrl = decision_grid(CTRL_FIRST_MONDAY, WIN_END, step)
        dgrid_top = decision_grid(TOP_FIRST_MONDAY, WIN_END, step)
        a_ctrl = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_ctrl, step,
                           None, FEE_REAL_BPS, perp_px, spot_px)
        a_top = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_top, step,
                          TOP_N, FEE_REAL_BPS, perp_px, spot_px)
        arms[(fname, "real", "rule_b_all")] = a_ctrl
        arms[(fname, "real", "carry_b_top")] = a_top
        real[fname] = {
            "rule_b_all": stats(a_ctrl, days, mask, f"real/{fname}/rule_b_all"),
            "carry_b_top": stats(a_top, days, mask, f"real/{fname}/carry_b_top"),
            "rule_b_all_b_window": stats(a_ctrl, days, mask_b, f"real/{fname}/rule_b_all/b"),
            "carry_b_top_b_window": stats(a_top, days, mask_b, f"real/{fname}/carry_b_top/b"),
            "basis_missing_events": a_top["basis_missing"],
            "basis_missing_events_rule_b": a_ctrl["basis_missing"],
            "basis_missing_detail": a_top["basis_missing_detail"],
            "per_period_carry_b_top": per_period(a_top, days, mask),
            "per_period_rule_b_all": per_period(a_ctrl, days, mask),
        }
    out["real_cost"] = real

    # ── ③ 判据 (a)–(d) ──
    top_w = arms[("weekly", "real", "carry_b_top")]
    s_top_w = real["weekly"]["carry_b_top"]
    s_top_w_b = real["weekly"]["carry_b_top_b_window"]
    # (c) 逐名最长负段(真实成本 + 基差)
    cols_sub = cols_all
    R_sub = R[:, cols_sub]
    active_sub = top_w["active"][:, cols_sub]
    cost_sub = top_w["cost_name"][:, cols_sub]
    panel_sub = [panel[j] for j in cols_sub]
    c_long, c_worst, c_segs = neg_segments(panel_sub, days, R_sub, active_sub, cost_sub)
    ctrl_w = arms[("weekly", "real", "rule_b_all")]
    ctl_long, ctl_worst, _ = neg_segments(panel_sub, days, R_sub,
                                           ctrl_w["active"][:, cols_sub],
                                           ctrl_w["cost_name"][:, cols_sub])
    # (d) 三档频率里最好的那档与每周的差
    ann_by_freq = {f: real[f]["carry_b_top"]["arith_ann_pct"] for f in FREQS}
    best_freq = max(ann_by_freq, key=lambda f: ann_by_freq[f])
    crit = {
        "a": {"arm": "carry_b_top / 真实成本 / 每周换仓", "window": "全样本",
              "net_ann_pct": s_top_w["arith_ann_pct"],
              "net_compound_ann_pct": s_top_w["compound_ann_pct"],
              "gross_ann_pct": s_top_w["gross_ann_pct"],
              "fee_ann_pct": s_top_w["fee_ann_pct"],
              "basis_ann_pct": s_top_w["basis_ann_pct"],
              "threshold_pct": 6.0, "verdict": bool(s_top_w["arith_ann_pct"] >= 6.0)},
        "b": {"arm": "carry_b_top / 真实成本 / 每周换仓", "window": "2025-01-01 → 2026-07-20",
              "net_ann_pct": s_top_w_b["arith_ann_pct"],
              "net_compound_ann_pct": s_top_w_b["compound_ann_pct"],
              "gross_ann_pct": s_top_w_b["gross_ann_pct"],
              "fee_ann_pct": s_top_w_b["fee_ann_pct"],
              "basis_ann_pct": s_top_w_b["basis_ann_pct"],
              "threshold_pct": 3.0, "verdict": bool(s_top_w_b["arith_ann_pct"] >= 3.0)},
        "c": {"arm": "carry_b_top / 真实成本 / 每周换仓", "reading": "逐名口径",
              "longest_neg_segment": c_long, "worst_neg_segment": c_worst,
              "threshold_pct": 5.0,
              "verdict": bool(c_long is not None and abs(c_long["cum_pct"]) <= 5.0)},
        "d": {"arm": "carry_b_top / 真实成本", "ann_by_freq_pp": ann_by_freq,
              "best_freq": best_freq,
              "best_minus_weekly_pp": ann_by_freq[best_freq] - ann_by_freq["weekly"],
              "threshold_pp": 2.0,
              "verdict": bool((ann_by_freq[best_freq] - ann_by_freq["weekly"]) <= 2.0)},
    }
    crit["all_pass"] = all(crit[k]["verdict"] for k in ("a", "b", "c", "d"))
    out["criteria"] = crit

    # ── ④ 副项(只报不判) ──
    sub = {}
    cols_hl = [j for j in cols_all if panel[j] in HL_SPOT_NAMES]
    for fname, step in FREQS.items():
        dgrid_ctrl = decision_grid(CTRL_FIRST_MONDAY, WIN_END, step)
        dgrid_top = decision_grid(TOP_FIRST_MONDAY, WIN_END, step)
        a_ctrl = build_arm(days, idx, R, PRESENT, aggs, panel, cols_hl, dgrid_ctrl, step,
                           None, FEE_REAL_BPS, perp_px, spot_px)
        a_top = build_arm(days, idx, R, PRESENT, aggs, panel, cols_hl, dgrid_top, step,
                          len(cols_hl) // 2, FEE_REAL_BPS, perp_px, spot_px)
        sub[fname] = {
            "rule_b_all_10": stats(a_ctrl, days, mask, f"hl10/{fname}/rule_b_all"),
            "carry_b_top_5of10": stats(a_top, days, mask, f"hl10/{fname}/top5"),
            "rule_b_all_10_b_window": stats(a_ctrl, days, mask_b, f"hl10/{fname}/rule_b_all/b"),
            "carry_b_top_5of10_b_window": stats(a_top, days, mask_b, f"hl10/{fname}/top5/b"),
        }
    out["hl_spot_10_subset"] = {"names": list(HL_SPOT_NAMES), "by_freq": sub}

    # 成本翻倍(31bp/次)+ 基差符号翻转(口径敏感性)—— 只报
    dgrid_top = decision_grid(TOP_FIRST_MONDAY, WIN_END, 1)
    a_x2 = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_top, 1,
                     TOP_N, FEE_REAL_BPS * 2, perp_px, spot_px)
    a_econ = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_top, 1,
                       TOP_N, FEE_REAL_BPS, perp_px, spot_px, basis_mode="econ")
    a_nobasis = build_arm(days, idx, R, PRESENT, aggs, panel, cols_all, dgrid_top, 1,
                          TOP_N, FEE_REAL_BPS, perp_px, spot_px, include_basis=False)
    out["extras"] = {
        "cost_double_31bp": stats(a_x2, days, mask, "real/weekly/top/cost_x2"),
        "basis_sign_flipped": stats(a_econ, days, mask, "real/weekly/top/basis_econ"),
        "basis_only_note": "基差符号翻转 = 台账字面口径的相反读法(开仓收 b、平仓付 b),只报不判",
        "capital_basis_x075": {
            "note": "1/3 保证金 ⇒ 名义回报 × 0.75 才是资本口径(S-733 结果里的读法)",
            "carry_b_top_real_weekly_ann_pct": s_top_w["arith_ann_pct"] * 0.75,
            "carry_b_top_real_weekly_b_window_ann_pct": s_top_w_b["arith_ann_pct"] * 0.75},
    }
    # 基差单独的年化拖累(分项):只把基差拿掉再算一遍
    out["extras"]["basis_component_ann_pp"] = {
        "with_basis_ann_pct": s_top_w["arith_ann_pct"],
        "without_basis_ann_pct": float(a_nobasis["net"][mask].mean()) * 365 * 100,
        "note": "去掉基差后的净(费不变)与含基差之差",
    }
    bsw = top_w["basis_at_switch"]
    if bsw:
        sb = sorted(bsw)
        out["extras"]["basis_at_switch_days"] = {
            "n": len(bsw), "mean_bp": float(np.mean(bsw)) * 1e4,
            "abs_mean_bp": float(np.mean(np.abs(bsw))) * 1e4,
            "p5_bp": float(sb[len(sb) // 20]) * 1e4,
            "p95_bp": float(sb[len(sb) * 19 // 20]) * 1e4,
            "note": "每次切换(开或平)当日的价格基差水平(永续−现货)/现货"}
    # 逐年 / 逐名
    out["per_name_real_weekly_top"] = []
    for j, sym in enumerate(panel_sub):
        out["per_name_real_weekly_top"].append({
            "symbol": sym,
            "gross_pct": float((top_w["active"][:, j] * R[:, j])[mask].sum() * 100),
            "switches": int(top_w["switch_day"][:, j].sum()),
            "basis_pct": float(top_w["cost_name"][:, j][mask].sum() * 100),
            "days_held": int(top_w["active"][:, j][mask].sum()),
        })
    out["per_name_real_weekly_top"] = sorted(out["per_name_real_weekly_top"],
                                             key=lambda r: -r["gross_pct"])

    with open(os.path.join(HERE, "t271_results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)

    # ── 控制台摘要 ──
    print("== ① 复现 S-735 原口径(weekly,7.5bp)==")
    for k in ("carry_b_top", "rule_b_all"):
        s = repro["weekly"][k]
        print(f"  {k}: arith {s['arith_ann_pct']:.4f}% / comp {s['compound_ann_pct']:.4f}% / "
              f"gross {s['gross_ann_pct']:.4f}% / fee {s['fee_ann_pct']:.4f}% / sw {s['switches']}")
    print(f"  对账: {json.dumps(out['reproduce_check'], ensure_ascii=False)}")
    print("== ② 真实成本(15.5bp/次 + 基差)==")
    for f in FREQS:
        for k in ("carry_b_top", "rule_b_all"):
            s = real[f][k]
            sb = real[f][k + "_b_window"]
            print(f"  [{f}] {k}: 全样本 arith {s['arith_ann_pct']:.3f}% (gross {s['gross_ann_pct']:.3f} "
                  f"fee {s['fee_ann_pct']:.3f} basis {s['basis_ann_pct']:.3f}) | "
                  f"2025-01→2026-07 arith {sb['arith_ann_pct']:.3f}% | sw {s['switches']} "
                  f"({s['switches_per_year']:.1f}/yr) | 基差缺 {real[f]['basis_missing_events']}")
    print("== ③ 判据 ==")
    print(json.dumps(crit, ensure_ascii=False, indent=1, default=float))
    print("== ④ 副项 ==")
    for f in FREQS:
        s = sub[f]
        print(f"  [HL10/{f}] rule_b_all 全样本 {s['rule_b_all_10']['arith_ann_pct']:.3f}% / "
              f"2025+ {s['rule_b_all_10_b_window']['arith_ann_pct']:.3f}%; "
              f"top5 全样本 {s['carry_b_top_5of10']['arith_ann_pct']:.3f}% / "
              f"2025+ {s['carry_b_top_5of10_b_window']['arith_ann_pct']:.3f}%")
    print(f"  成本翻倍: {out['extras']['cost_double_31bp']['arith_ann_pct']:.3f}%")
    print(f"  基差符号翻转: {out['extras']['basis_sign_flipped']['arith_ann_pct']:.3f}%")
    print("  逐年 carry_b_top / real / weekly:")
    for label, v in real["weekly"]["per_period_carry_b_top"].items():
        print(f"    {label}: arith {v['arith_ann_pct']:.2f}% (gross {v['gross_ann_pct']:.2f} "
              f"fee {v['fee_ann_pct']:.2f} basis {v['basis_ann_pct']:.2f})")


if __name__ == "__main__":
    main()
