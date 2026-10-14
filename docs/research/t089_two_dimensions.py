"""T-089 v3.1 — 两维度首版真数字(§Seth-1014d)。

维度 1:候选 = `core_u` (cap_uncapped) 与 `btc`
维度 2:恒定仓位档 ∈ {0.5, 0.75, 1.0},其余现金 4%/年(常数,不是择时)

组合 NAV(起点 1.0):
    r_arm(t)   = arm_nav(t) / arm_nav(t-1) - 1
    r_cash     = 0.04 / 365
    r_port(t)  = w · r_arm(t) + (1 - w) · r_cash
    port_nav(t)= Π_{i=1..t} (1 + r_port(i))

窗口:
    W1 = 2023-01-02 → 2024-12-31(2023-2024)
    W2 = 2025-01-01 → 最新(2025-01 → latest)

指标(满 ANNUALISE_DAYS=365 才年化,否则只给总收益与 maxDD):
    total_return, max_dd, ann_return, ann_std, sharpe

数据源:
    上一轮 v3 loader (d15bae7) 落地的 `t089_series_2026-10-14.csv` —
    端点 raw 拉的 5 个 arm,1380 行,无 ffill/bfill/fillna(1.0) 污染。
    沙箱无外网,本轮不重拉;新 v3.1 loader 已上线,未来重拉会按严格口径补
    provenance(各臂 first/last/n/最大缺口/首行 NAV=1 断言)。

产物:
    `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t089_v3.1_*.{json,md,csv}`
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

CASH_ANNUAL = 0.04
ANNUALISE_DAYS = 365
W1 = ("W1", "2023-01-02", "2024-12-31")
W2 = ("W2", "2025-01-01", None)        # 终点 = 末日(从 panel 拿)
CANDIDATES = ("core_u", "btc")
EXPOSURES = (0.5, 0.75, 1.0)


def _arm_returns(nav: pd.Series) -> pd.Series:
    """arm 日收益 = nav(t)/nav(t-1) - 1;起点首行 drop。"""
    return nav.pct_change().dropna()


def _port_returns(arm_ret: pd.Series, w: float, cash_annual: float = CASH_ANNUAL) -> pd.Series:
    """组合日收益 = w * arm_ret + (1 - w) * cash_annual/365"""
    cash_daily = cash_annual / 365.0
    return w * arm_ret + (1.0 - w) * cash_daily


def _port_nav(arm_ret: pd.Series, w: float) -> pd.Series:
    """组合 NAV,起点 1.0,长度 = len(arm_ret)。"""
    r = _port_returns(arm_ret, w)
    return (1.0 + r).cumprod()


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float((nav / peak - 1.0).min())


def _metrics(nav: pd.Series) -> dict:
    """满 ANNUALISE_DAYS 天才年化(否则只给 total/maxDD)。"""
    r = nav.pct_change().dropna()
    out = {
        "n_days":    len(r),
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1.0),
        "max_dd":    _max_dd(nav),
    }
    if len(r) >= ANNUALISE_DAYS and r.std() > 0:
        ann_ret = float(r.mean()) * 365
        ann_std = float(r.std()) * math.sqrt(365)
        out["ann_return"] = ann_ret
        out["ann_std"]    = ann_std
        out["sharpe"]     = ann_ret / ann_std
    return out


def _slice(panel: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    s = pd.Timestamp(start)
    e = pd.Timestamp(end) if end else panel["d"].max()
    sub = panel[(panel["d"] >= s) & (panel["d"] <= e)].copy()
    return sub


def _window_report(panel_w: pd.DataFrame, win_label: str) -> dict:
    rows = []
    for cand in CANDIDATES:
        arm = panel_w[cand]
        arm_ret = _arm_returns(arm)
        for w in EXPOSURES:
            nav = _port_nav(arm_ret, w)
            m = _metrics(nav)
            # 纯 arm 与 纯 cash 对照
            m_arm_only = _metrics(arm)
            cash_nav = (1.0 + CASH_ANNUAL / 365.0) ** np.arange(len(arm_ret) + 1)[1:]
            m_cash = _metrics(pd.Series(cash_nav, index=arm_ret.index))
            rows.append({
                "candidate": cand,
                "exposure":  w,
                "fund":      m,
                "arm_only":  m_arm_only,
                "cash_only": m_cash,
            })
    return {"label": win_label, "n_days": len(panel_w), "rows": rows}


def _fmt_pct(x):
    return "—" if x is None else f"{x:+.2%}"


def _fmt_sharpe(d):
    s = d.get("sharpe")
    return "—" if s is None else f"{s:+.2f}"


def _fmt_total(d):
    return _fmt_pct(d.get("total_return"))


def _fmt_maxdd(d):
    return _fmt_pct(d.get("max_dd"))


def _render_table(report: dict) -> str:
    """W1 / W2 各一张表 — 行 = (candidate, exposure), 列 = total / maxDD / sharpe。"""
    out = [f"## {report['label']}  (n_days = {report['n_days']})", ""]
    out.append("| candidate | exposure | total_return | max_dd | ann_return | sharpe | arm_only_total | cash_only_total |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in report["rows"]:
        f = r["fund"]
        out.append(
            f"| {r['candidate']} | {r['exposure']:.2f} | "
            f"{_fmt_total(f)} | {_fmt_maxdd(f)} | "
            f"{_fmt_pct(f.get('ann_return'))} | {_fmt_sharpe(f)} | "
            f"{_fmt_total(r['arm_only'])} | {_fmt_total(r['cash_only'])} |"
        )
    out.append("")
    return "\n".join(out)


def _render_markdown(reports: list[dict], panel_meta: dict, argv: list[str],
                     out_paths: dict[str, str]) -> str:
    lines = [
        "# T-089 v3.1 — 两维度首版真数字(§Seth-1014d)\n",
        f"_{datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n",
        "## 命令行\n", "```\n", " ".join(argv), "\n```\n",
        "## 数据源\n",
        "- panel 来自上一轮 v3 loader (d15bae7) 落地的 `t089_series_2026-10-14.csv`\n",
        "- 端点 raw,无 ffill/bfill/fillna(1.0) 污染(sandbox 无外网,本轮不重拉)\n",
        "- v3.1 loader (本轮新提交) 已上线:删 ffill/bfill/fillna(1.0)、删 synthetic/csv 后端、"
        "校验改逐列 + 断言首行 NAV=1;未来重拉会按 §Seth-1014a 三处修订补 provenance\n",
        "## 维度\n",
        "- 候选 = `core_u` (cap_uncapped) / `btc`\n",
        "- 恒定仓位档 ∈ {0.5, 0.75, 1.0},其余现金 4%/年(常数,不是择时)\n",
        "## Panel 元\n", "```json", json.dumps(panel_meta, indent=2, default=str), "```\n",
    ]
    for r in reports:
        lines.append(_render_table(r))
    lines.append("## 产物路径\n")
    for k, v in out_paths.items():
        lines.append(f"- **{k}**: `{v}`\n")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-csv",
                    default="/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t089_series_2026-10-14.csv",
                    help="panel CSV 路径(默认 = 上一轮 v3 落地的真数据)")
    ap.add_argument("--absorb-dir",
                    default="/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input",
                    help="产物落点(Mac 数据根)")
    ap.add_argument("--tag", default="t089_v3.1_two_dim")
    args = ap.parse_args()
    argv = sys.argv[1:]

    panel = pd.read_csv(args.panel_csv)
    panel["d"] = pd.to_datetime(panel["d"])
    panel = panel.sort_values("d").reset_index(drop=True)

    panel_meta = {
        "rows":        len(panel),
        "first":       panel["d"].iloc[0].date().isoformat(),
        "last":        panel["d"].iloc[-1].date().isoformat(),
        "any_na":      bool(panel.isna().any().any()),
        "candidates":  list(CANDIDATES),
        "exposures":   list(EXPOSURES),
        "cash_annual": CASH_ANNUAL,
        "annualise_threshold_days": ANNUALISE_DAYS,
        "source":      args.panel_csv,
    }

    reports = []
    for label, start, end in (W1, W2):
        sub = _slice(panel, start, end)
        win_label = f"{label} ({start} → {end or panel_meta['last']})"
        reports.append(_window_report(sub, win_label))

    # 落 Mac 数据根
    out = Path(args.absorb_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{args.tag}_results.json"
    md_path   = out / f"{args.tag}_report.md"

    json_payload = {
        "panel_meta": panel_meta,
        "windows":    reports,
        "ts":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    json_path.write_text(json.dumps(json_payload, indent=2, default=str))

    out_paths = {"json": str(json_path), "md": str(md_path), "panel_csv": args.panel_csv}
    md = _render_markdown(reports, panel_meta, argv, out_paths)
    md_path.write_text(md)

    # 控制台一段直给
    print(f"[ok] panel {panel_meta['first']} → {panel_meta['last']} ({panel_meta['rows']} 天)")
    for r in reports:
        print(f"\n{r['label']}  (n={r['n_days']})")
        for row in r["rows"]:
            f = row["fund"]
            sh = f"{f['sharpe']:+.2f}" if "sharpe" in f else "—"
            an = f"{f['ann_return']:+.2%}" if "ann_return" in f else "—"
            print(f"  {row['candidate']:12s} w={row['exposure']:.2f}  total={f['total_return']:+.2%}  "
                  f"maxDD={f['max_dd']:+.2%}  ann={an}  sharpe={sh}")
    print(f"\n[ok] 产物落 {out}/ 前缀={args.tag}_*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
