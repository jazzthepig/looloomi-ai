"""T-089 v3.1 — 整只基金的按时点模拟。

**本轮(T-089-v3.1+,2026-10-14,补 v3.1 第二段):** 把两维度首版扩成完整五臂 + 配置层
按时点合成一条基金 NAV。

**输入**: 由 `t089_panel_loader.panel_from_public` 拉取的 5 臂宽表 panel
(columns = d / core_u / multiplier / portfolio_layer / cis_tilt / btc)。

**合成规则**(按时点):
  - **每周末(= panel[d] 周一)做一次 rebalance**:对该天 daily weights 给前面整条回放
    决定权重。权重保持到下个周末。
  - **配权规则**(简化版 L3,适配 panel-only 的纯函数模拟,不读 Supabase):
      ① core_u:默认 = 1 - Σ(其它权重);非 ① 的权重总和按比例压到 ≤ 100%。
      ② multiplier / ③ portfolio_layer:相对 ① 的超额 ⇒ mu_post / σ² × KELLY,
        单本上限 40%(S-485 v0.2 §3.5 「可能全仓一个币」)。
      ④ cis_tilt:同上 + 上限 10%(S-485 「④ 合计 ≤ 10%」)。
      证据门:MIN_DAYS=20 天;任意时刻下界 mu_lo_cs > 0;μ_post 与 σ 都存在;
        否则权重 = 0。
  - **现金 = 1 - Σ(所有臂权重)**,零收益,不留敞口(模拟期纯做基金 NAV,不调总敞口)。

**NAV 合成**:
    r_arm(t) = arm_nav(t)/arm_nav(t-1) - 1
    r_fund(t) = Σ_i w_i(t-1) · r_arm_i(t)
    fund_nav(t) = Π (1 + r_fund)   ← 起点 1.0

**对照**:
    - **BTC**:整段 btc_arm NAV。
    - **① 本身**:core_u NAV。
    - **随机 500**:同臂集 + 同窗口,每个臂的权重抽自 Dirichlet(1,...,1)/N,
      每周重抽一次;不算配置层,不算证据门。报 p50 / p95 总收益、相对 ① 的超额分位、
      maxDD 中位。随机对照可作为「纯随机权重会不会比 ① 好」的标尺。

**窗口**:
    W1 = 2023-01-02 → 2024-12-31(2023-2024)
    W2 = 2025-01-01 → 2026-10-11(2025 → 10-12 起点前一天)
    W3 = 2026-10-12 → 末日(10-12 起前向)

**指标**(满 ANNUALISE_DAYS 才年化,否则只给 total / maxDD):
    total_return, max_dd, ann_return, ann_std, sharpe,
    excess_vs_core_u(= 基金相对 core_u NAV 的累计超额与其分位)

**产物落 Mac 数据根**:
    `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t089_v3.1_full_*.{json,md,csv}`
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ANNUALISE_DAYS = 365
INCEPTION = "2023-01-02"          # 起点 — 取 panel 起点与 INCEPTION 的较大者
REBALANCE_WEEKDAY = 0             # Monday = 0 (isodow)
KELLY = 0.25
SINGLE_BOOK_CAP_NON_TILT = 0.40   # 单本上限(②③ + 未来非 ④)
TILT_CAP = 0.10                   # ④ 合计上限
MIN_DAYS = 20                     # 证据窗口下限
CS_ALPHA = 0.10
CS_RHO_DAYS = 60
PRIOR_EXCESS_SD_ANN = 0.10
RANDOM_TRIALS = 500
RANDOM_SEED = 20261014            # 复现性
WINDOWS = (
    ("W1", "2023-01-02", "2024-12-31"),
    ("W2", "2025-01-01", "2026-10-11"),
    ("W3", "2026-10-12", None),   # 终点 = panel 末日
)
ARMS_NON_CORE = ("multiplier", "portfolio_layer", "cis_tilt")
ARM_OF_CIS_TILT = "cis_tilt"


# ── 证据(L3 纯函数版,无 I/O)─────────────────────────────────────────────
def cs_halfwidth(n: int, s: float, alpha: float = CS_ALPHA, rho_days: float = CS_RHO_DAYS) -> float:
    """任意时刻有效半宽(正态混合边界);与 src/data/allocation/allocator.py 同型。"""
    if n < 1 or not s > 0:
        return float("inf")
    v, rho = n * s * s, rho_days * s * s
    return math.sqrt((v + rho) * math.log((v + rho) / (rho * alpha * alpha))) / n


def shrink(m: float, s: float, n: int, prior_sd_ann: float = PRIOR_EXCESS_SD_ANN) -> float:
    """日均值向 0 收缩;与 allocator.shrink 同型。"""
    tau = prior_sd_ann / 365.0
    return m * (n * tau * tau) / (n * tau * tau + s * s) if s > 0 else 0.0


def _evidence_window(arm: pd.Series, bench: pd.Series, end: pd.Timestamp) -> pd.Series:
    """[INCEPTION - 1d, end] 的窗口,两端闭合;空舍地 ⇒ 返回空。"""
    a = pd.Timestamp(INCEPTION) - pd.Timedelta(days=1)
    common = (arm.index >= a) & (arm.index <= end)
    return arm[common].dropna().sort_index()


def evidence(arm: pd.Series, bench: pd.Series, end: pd.Timestamp) -> dict[str, Any]:
    """相对 ① 的日超额证据;与 allocator.evidence 同口径(但以 end 为窗口右端)。"""
    aw = _evidence_window(arm, bench, end)
    bw = _evidence_window(bench, bench, end)
    if bw.empty:
        return {"n_days": 0}
    a, b = aw.pct_change(), bw.reindex(aw.index).pct_change()
    ex = (a - b).dropna()
    n = len(ex)
    if n < 2:
        return {"n_days": n}
    m, s = float(ex.mean()), float(ex.std())
    raw = {
        "n_days":    n,
        "mu":        m * 365,
        "sigma":     s * math.sqrt(365),
        "mu_lo95":   (m - 2 * s / math.sqrt(n)) * 365,
        "mu_lo_cs":  (m - cs_halfwidth(n, s)) * 365,
        "mu_hi_cs":  (m + cs_halfwidth(n, s)) * 365,
        "mu_post":   shrink(m, s, n) * 365,
    }
    return {k: (v if (not isinstance(v, float) or math.isfinite(v)) else None) for k, v in raw.items()}


# ── 配置层:每天一行权重(给定 rebalance 节奏)─────────────────────────────
@dataclass(frozen=True)
class Cap:
    single_non_tilt: float = SINGLE_BOOK_CAP_NON_TILT
    tilt: float = TILT_CAP


def decide(d: pd.Timestamp, arms: dict[str, pd.Series], core_arm: pd.Series,
           cap: Cap = Cap()) -> dict[str, Any]:
    """一天的配置。返回 {weights, why};weights = {core_u, multiplier, portfolio_layer, cis_tilt}。"""
    why: list[str] = []
    raw_w: dict[str, float] = {}
    bench_w = _evidence_window(core_arm, core_arm, d)
    if bench_w.empty:
        return {"weights": {"core_u": 1.0}, "why": ["①: 1.00 —— ① 尚未无数据,bet 全部"]}
    for bid in ARMS_NON_CORE:
        ser = arms.get(bid)
        if ser is None:
            why.append(f"{bid}: 0 —— 缺臂")
            continue
        ev = evidence(ser, core_arm, d)
        n = ev.get("n_days", 0)
        if n < MIN_DAYS:
            why.append(f"{bid}: 0 —— 前向 {n} 天,小于 MIN_DAYS={MIN_DAYS}")
            continue
        if ev.get("mu_lo_cs") is None or ev.get("mu_post") is None or not ev.get("sigma"):
            why.append(f"{bid}: 0 —— 证据缺项(任意时刻下界 / 收缩均值 / 超额波动)")
            continue
        if not ev["mu_lo_cs"] > 0:
            why.append(f"{bid}: 0 —— 超额 {ev['mu']:+.1%}/年,任意时刻下界 {ev['mu_lo_cs']:+.1%} ≤ 0({n} 天)")
            continue
        book_cap = cap.tilt if bid == ARM_OF_CIS_TILT else cap.single_non_tilt
        w = min(book_cap, max(0.0, KELLY * ev["mu_post"] / max(ev["sigma"] ** 2, 1e-9)))
        raw_w[bid] = w
        why.append(f"{bid}: {w:.1%} —— 超额 {ev['mu']:+.1%}/年(收缩 {ev['mu_post']:+.1%}),σ {ev['sigma']:.1%},"
                   f"任意时刻下界 {ev['mu_lo_cs']:+.1%},{n} 天"
                   + (f";触上限 {book_cap:.0%}" if w >= book_cap else ""))
    tot = sum(raw_w.values())
    if tot > 1.0:
        scale = 1.0 / tot
        raw_w = {k: v * scale for k, v in raw_w.items()}
        why.append(f"非 ① 合计 {tot:.1%} > 100%,按比例压到 {scale:.2f}×")
    weights = {"core_u": max(0.0, 1.0 - sum(raw_w.values())), **raw_w}
    why.insert(0, f"① core_u: {weights['core_u']:.1%} —— 默认持有,非 ① 权重从这里拨出")
    return {"weights": weights, "why": why}


# ── NAV 合成 ──────────────────────────────────────────────────────────────
def _arm_returns(nav: pd.Series) -> pd.Series:
    return nav.pct_change().dropna()


def compose_nav(panel: pd.DataFrame, rebalance_dates: list[pd.Timestamp]) -> tuple[pd.Series, list[dict]]:
    """按时点权重合成一条 NAV;返回 (n, decisions)。"""
    arms = {c: panel[c].dropna() for c in ("multiplier", "portfolio_layer", "cis_tilt") if c in panel}
    core = panel["core_u"].dropna()
    decisions: list[dict] = []
    rebal_set = set(pd.Timestamp(d).normalize() for d in rebalance_dates)
    cur_weights = {"core_u": 1.0}
    nav, t, rows = 1.0, None, []
    rows.append({"d": panel["d"].iloc[0], "nav": 1.0, "ret": 0.0,
                 "weights": dict(cur_weights), "rebal": False})
    for i in range(1, len(panel)):
        prev, today = panel["d"].iloc[i - 1], panel["d"].iloc[i]
        if pd.Timestamp(today).normalize() in rebal_set and pd.Timestamp(today) >= INCEPTION:
            dec = decide(pd.Timestamp(today), arms, core)
            cur_weights = dec["weights"]
            decisions.append({"d": pd.Timestamp(today).date().isoformat(), "weights": cur_weights, "why": dec["why"]})
            is_rebal = True
        else:
            is_rebal = False
        r = 0.0
        for bid, w in cur_weights.items():
            col = bid if bid != "core_u" else "core_u"
            v_prev = panel[panel["d"] == prev][col].iloc[0] if (panel["d"] == prev).any() else None
            v_today = panel[panel["d"] == today][col].iloc[0] if (panel["d"] == today).any() else None
            if v_prev is None or v_today is None or pd.isna(v_prev) or pd.isna(v_today) or v_prev == 0:
                continue
            r += w * (float(v_today) / float(v_prev) - 1.0)
        nav *= 1.0 + r
        rows.append({"d": today, "nav": nav, "ret": r, "weights": dict(cur_weights), "rebal": is_rebal})
    nav_ser = pd.Series([r["nav"] for r in rows], index=pd.to_datetime([r["d"] for r in rows]))
    return nav_ser, decisions


def random_compose_nav(panel: pd.DataFrame, rebalance_dates: list[pd.Timestamp],
                       rng: np.random.Generator) -> pd.Series:
    """同形状的随机对照:每个 rebalance 日期抽一组权重(臂集 = 5 臂,含 btc 与 core_u),下周按这组权重合成。"""
    arm_cols = ["core_u", "multiplier", "portfolio_layer", "cis_tilt", "btc"]
    nav, prev_w = 1.0, None
    rows = [(panel["d"].iloc[0], 1.0)]
    rebal_set = set(pd.Timestamp(d).normalize() for d in rebalance_dates)
    for i in range(1, len(panel)):
        prev, today = panel["d"].iloc[i - 1], panel["d"].iloc[i]
        if pd.Timestamp(today).normalize() in rebal_set and pd.Timestamp(today) >= INCEPTION:
            w = rng.dirichlet(np.ones(len(arm_cols)))
            prev_w = dict(zip(arm_cols, w))
        if prev_w is None:
            prev_w = dict.fromkeys(arm_cols, 0.0)
            prev_w["core_u"] = 1.0
        r = 0.0
        for bid, wi in prev_w.items():
            v_prev = panel[panel["d"] == prev][bid].iloc[0] if (panel["d"] == prev).any() else None
            v_today = panel[panel["d"] == today][bid].iloc[0] if (panel["d"] == today).any() else None
            if v_prev is None or v_today is None or pd.isna(v_prev) or pd.isna(v_today) or v_prev == 0:
                continue
            r += wi * (float(v_today) / float(v_prev) - 1.0)
        nav *= 1.0 + r
        rows.append((today, nav))
    return pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows]))


# ── 指标 ──────────────────────────────────────────────────────────────────
def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    return float((nav / nav.cummax() - 1.0).min())


def metrics(nav: pd.Series) -> dict[str, Any]:
    r = nav.pct_change().dropna()
    out = {
        "n_days":       len(r),
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1.0),
        "max_dd":       _max_dd(nav),
    }
    if len(r) >= ANNUALISE_DAYS and r.std() > 0:
        ann_ret = float(r.mean()) * 365
        ann_std = float(r.std()) * math.sqrt(365)
        out.update({"ann_return": ann_ret, "ann_std": ann_std, "sharpe": ann_ret / ann_std})
    return out


# ── 周一索引 ──────────────────────────────────────────────────────────────
def rebalance_dates(panel: pd.DataFrame) -> list[pd.Timestamp]:
    d = pd.to_datetime(panel["d"])
    wk = d[d.dt.isocalendar().day == 1] if hasattr(d.dt, "isocalendar") else d[d.dt.weekday == REBALANCE_WEEKDAY]
    return [pd.Timestamp(x).normalize() for x in wk]


# ── 报告 ──────────────────────────────────────────────────────────────────
def _fmt_pct(x):
    return "—" if x is None else f"{x:+.2%}"


def _fmt_sharpe(d):
    s = d.get("sharpe")
    return "—" if s is None else f"{s:+.2f}"


def render_window(win_label: str, sub: pd.DataFrame, fund: pd.Series, btc: pd.Series,
                  core: pd.Series, rand_metrics: list[dict]) -> str:
    lines = [f"## {win_label}  (n = {len(sub)})", ""]
    lines.append("| 臂 | total_return | max_dd | ann_return | sharpe |")
    lines.append("| --- | --- | --- | --- | --- |")
    for label, nav in (("fund", fund), ("① core_u", core), ("btc", btc)):
        m = metrics(nav)
        lines.append(f"| {label} | {_fmt_pct(m.get('total_return'))} | {_fmt_pct(m.get('max_dd'))} | "
                     f"{_fmt_pct(m.get('ann_return'))} | {_fmt_sharpe(m)} |")
    lines.append("")
    lines.append("### 随机 500 对照(同臂集,同窗口,Dirichlet(1..1) 每周末重抽)")
    lines.append("")
    lines.append("| 指标 | fund 实测 | 随机 p50 | 随机 p95 | fund 相对随机的分位 |")
    lines.append("| --- | --- | --- | --- | --- |")
    f_m = metrics(fund)
    if rand_metrics:
        keys = ("total_return", "max_dd")
        rand_total = np.array([m["total_return"] for m in rand_metrics])
        rand_maxdd = np.array([m["max_dd"] for m in rand_metrics])
        for label, fv, rv in (
            ("total_return", f_m.get("total_return"), rand_total),
            ("max_dd",      f_m.get("max_dd"),      rand_maxdd),
        ):
            if fv is None or len(rv) == 0:
                lines.append(f"| {label} | {_fmt_pct(fv)} | — | — | — |")
                continue
            pct = float((rv <= fv).mean()) if label == "total_return" else float((rv >= fv).mean())
            lines.append(
                f"| {label} | {_fmt_pct(fv)} | {_fmt_pct(np.percentile(rv, 50))} | "
                f"{_fmt_pct(np.percentile(rv, 95))} | {pct:.2f} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-csv",
                    default="/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t089_series_2026-10-14.csv")
    ap.add_argument("--absorb-dir",
                    default="/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input")
    ap.add_argument("--tag", default="t089_v3.1_full")
    ap.add_argument("--random-trials", type=int, default=RANDOM_TRIALS)
    args = ap.parse_args()

    panel = pd.read_csv(args.panel_csv)
    panel["d"] = pd.to_datetime(panel["d"])
    panel = panel.sort_values("d").reset_index(drop=True)

    # 起点:panel 首日与 INCEPTION 取较大
    panel_start = panel["d"].iloc[0]
    inc_ts = pd.Timestamp(INCEPTION)
    if panel_start < inc_ts:
        panel = panel[panel["d"] >= inc_ts].reset_index(drop=True)

    panel_meta = {
        "rows":        len(panel),
        "first":       panel["d"].iloc[0].date().isoformat(),
        "last":        panel["d"].iloc[-1].date().isoformat(),
        "any_na":      bool(panel.isna().any().any()),
        "arms":        ["core_u", "multiplier", "portfolio_layer", "cis_tilt", "btc"],
        "inception":   INCEPTION,
        "rebalance":   "weekly (isodow=1)",
        "windows":     [{"label": l, "start": s, "end": e} for l, s, e in WINDOWS],
        "random_trials": args.random_trials,
        "source":      args.panel_csv,
        "caps":        {"single_non_tilt": SINGLE_BOOK_CAP_NON_TILT, "tilt": TILT_CAP},
        "l3_params":   {"KELLY": KELLY, "MIN_DAYS": MIN_DAYS, "CS_ALPHA": CS_ALPHA,
                        "CS_RHO_DAYS": CS_RHO_DAYS, "PRIOR_EXCESS_SD_ANN": PRIOR_EXCESS_SD_ANN},
    }

    rds = rebalance_dates(panel)
    fund_nav, decisions = compose_nav(panel, rds)

    rng = np.random.default_rng(RANDOM_SEED)
    random_navs: list[pd.Series] = []
    for _ in range(args.random_trials):
        random_navs.append(random_compose_nav(panel, rds, rng))

    reports = []
    for label, start, end in WINDOWS:
        s = pd.Timestamp(start)
        e = pd.Timestamp(end) if end else panel["d"].max()
        sub_panel = panel[(panel["d"] >= s) & (panel["d"] <= e)].copy()
        sub_fund = fund_nav[(fund_nav.index >= s) & (fund_nav.index <= e)]
        sub_core = pd.Series(sub_panel["core_u"].values, index=pd.to_datetime(sub_panel["d"]))
        sub_btc = pd.Series(sub_panel["btc"].values, index=pd.to_datetime(sub_panel["d"]))
        sub_rand = []
        for rn in random_navs:
            sub = rn[(rn.index >= s) & (rn.index <= e)]
            if len(sub) >= 2:
                sub_rand.append(metrics(sub))
        win_label = f"{label} ({start} → {end or panel_meta['last']})"
        reports.append({
            "label": win_label,
            "n_days": len(sub_panel),
            "markdown": render_window(win_label, sub_panel, sub_fund, sub_btc, sub_core, sub_rand),
            "fund_metrics": metrics(sub_fund),
            "core_metrics": metrics(sub_core),
            "btc_metrics": metrics(sub_btc),
            "random_metrics": sub_rand,
        })

    out = Path(args.absorb_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{args.tag}_results.json"
    md_path = out / f"{args.tag}_report.md"
    csv_path = out / f"{args.tag}_fund_nav.csv"

    json_payload = {
        "panel_meta": panel_meta,
        "windows":    reports,
        "n_rebalances": len(rds),
        "n_decisions":  len(decisions),
        "ts":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "argv":        sys.argv[1:],
    }
    json_path.write_text(json.dumps(json_payload, indent=2, default=str))

    md_lines = [
        "# T-089 v3.1 — 整只基金按时点模拟(完整版)\n",
        f"_{json_payload['ts']}_\n",
        "## 命令行\n", "```\n", " ".join(sys.argv), "\n```\n",
        "## 数据与口径\n",
        "- 来源:`t089_panel_loader.panel_from_public`(后端 P,公开只读端点,沙箱无外网时读 `--panel-csv`)\n",
        "- 5 臂:`core_u / multiplier / portfolio_layer / cis_tilt / btc`(列对齐 BTC 索引,freq='D',无 ffill/bfill/fillna)\n",
        "- INCEPTION = 2023-01-02;rebalance = 每周一(panel index weekday=0)\n",
        "- 配权:L3 `SRC_DATA_ALLOCATION_ALLOCATOR.py` v0.2 的 KELLY + 收缩 + 任意时刻下界 + 单本/④ 上限\n",
        "- 随机 500 = 同臂集、同窗口、Dirichlet(1..1) 每周末重抽(只 5 臂合计 ≤ 1.0,不调 ① 默认)\n",
        "- cash = 1 - Σw_i(零收益;模拟期纯基金 NAV,不调总敞口)\n",
        "## Panel 元\n", "```json", json.dumps(panel_meta, indent=2, default=str), "```\n",
    ]
    for r in reports:
        md_lines.append(r["markdown"])
    md_lines.append("\n## 产物路径\n")
    md_lines.append(f"- json: `{json_path}`\n")
    md_lines.append(f"- md:   `{md_path}`\n")
    md_lines.append(f"- csv:  `{csv_path}` (fund NAV)\n")
    md_path.write_text("\n".join(md_lines) + "\n")

    fund_nav.to_frame("fund_nav").rename_axis("d").reset_index().to_csv(csv_path, index=False)

    print(f"[ok] panel {panel_meta['first']} → {panel_meta['last']} ({panel_meta['rows']} 天)")
    print(f"[ok] rebalances={len(rds)}, decisions={len(decisions)}, random_trials={args.random_trials}")
    for r in reports:
        m = r["fund_metrics"]
        sh = f"{m['sharpe']:+.2f}" if "sharpe" in m else "—"
        an = f"{m['ann_return']:+.2%}" if "ann_return" in m else "—"
        print(f"  {r['label']:60s} fund total={m['total_return']:+.2%}  maxDD={m['max_dd']:+.2%}  ann={an}  sharpe={sh}")
    print(f"\n[ok] 产物落 {out}/ 前缀={args.tag}_*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())