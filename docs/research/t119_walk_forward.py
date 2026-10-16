"""T-119 —— §S-602 模拟四:走步自适应(每轮只挑一个 Calmar 最好)。

每年 1 月 1 日只用过去 3 年数据,在 {H, F, FB, X1V, V, PD13} 6 套里
挑 Calmar 最好的一套,做下一整年。对照固定 X1V 与 H。

**规则一律从 s600 / s601 / s596 import,不许重写。**
- H    = 永远 1.0(基准)
- F    = s600.trade_path(bear='flat'):多头 + 加仓 + 跌破就平(不开反弹不开空)
- FB   = s600.trade_path(bear='rally'):多头 + 反弹做多 + 跌破就平
- PD13 = s596.gross_path(cap=1.3, defend=True):加仓 + 跌破时底仓 0.7
- V    = s601.path(exit='ma') + vol_scale:FB + 波动率缩放
- X1V  = s601.path(exit='l20') + vol_scale:l20 即平 + 波动率缩放

收益一律 s596.daily_returns(10bp 成本,>1 付资金费)。
统计走本项目数据源所要求的 apparatus(calmar / max_dd / cagr)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from s596_tom_pyramid import COST, FALLBACK_FUND, daily_returns, gross_path  # noqa: E402
from s600_tom_trader import trade_path  # noqa: E402
from s601_drawdown import WARM, path as s601_path, vol_scale  # noqa: E402

SEED = 119


# ---- rule registry: (close, fund_long) -> gross path g[t] (t+1 effective) ----
def _rule_H(c, fl):
    return np.ones(len(c))


def _rule_F(c, fl):
    g, _ = trade_path(c, "flat", 0.0)
    return g


def _rule_FB(c, fl):
    g, _ = trade_path(c, "rally", 0.0)
    return g


def _rule_PD13(c, fl):
    g, _ = gross_path(c, 1.3, True)
    return g


def _rule_V(c, fl):
    g = s601_path(c, "ma")
    s = vol_scale(c)
    return np.where(np.arange(len(c)) >= WARM, g * s, g)


def _rule_X1V(c, fl):
    g = s601_path(c, "l20")
    s = vol_scale(c)
    return np.where(np.arange(len(c)) >= WARM, g * s, g)


RULES = {"H": _rule_H, "F": _rule_F, "FB": _rule_FB, "PD13": _rule_PD13, "V": _rule_V, "X1V": _rule_X1V}


# ---- data ----
def _load_funding(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        rec: dict[str, float] = {}
        for kv in parts[1:]:
            if ":" in kv:
                k, _, v = kv.partition(":")
                rec[k] = float(v)
        out[parts[0]] = rec
    return out


def load_assets(research_dir: Path) -> dict[str, dict]:
    """Main 4 from w50_daily/close.json(BTC/ETH/XRP/BNB);OOS 4 from crypto_daily/panel.json(LTC/ADA/LINK/DOGE,2021+)。"""
    w50 = json.loads((research_dir / "w50_daily/close.json").read_text())
    panel = json.loads((research_dir / "crypto_daily/panel.json").read_text())
    fund = _load_funding(research_dir / "s596/funding_monthly.txt")
    out: dict[str, dict] = {}
    for sym in ("BTC", "ETH", "XRP", "BNB"):
        if sym not in w50["close"]:
            continue
        pts = [(d, x) for d, x in zip(w50["dates"], w50["close"][sym]) if x]
        if not pts:
            continue
        dates = [d for d, _ in pts]
        close = np.array([x for _, x in pts], dtype=float)
        fl = np.array([fund.get(sym, {}).get(d[:7], FALLBACK_FUND) / 365 for d in dates])
        out[sym] = {"dates": dates, "close": close, "fund_long": fl, "src": "w50"}
    for sym in ("LTC", "ADA", "LINK", "DOGE"):
        if sym not in panel["price"]:
            continue
        pts = [(d, x) for d, x in zip(panel["dates"], panel["price"][sym]) if x]
        if not pts:
            continue
        dates = [d for d, _ in pts]
        close = np.array([x for _, x in pts], dtype=float)
        fl = np.full(len(dates), FALLBACK_FUND / 365)
        out[sym] = {"dates": dates, "close": close, "fund_long": fl, "src": "panel"}
    return out


# ---- metrics ----
def _slice_metrics(r: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    rr = r[mask]
    if len(rr) < 30:
        return {"days": int(len(rr)), "total_x": None, "cagr": None, "max_dd": None, "calmar": None}
    nav = np.cumprod(1 + rr)
    yrs = len(rr) / 365
    total_x = float(nav[-1])
    cagr = total_x ** (1 / yrs) - 1 if yrs > 0 else 0.0
    dd = nav / np.maximum.accumulate(nav) - 1
    max_dd = float(dd.min())
    if max_dd < 0:
        calmar = float(cagr / abs(max_dd))
    elif cagr > 0:
        calmar = float("inf")
    else:
        calmar = 0.0
    return {"days": int(len(rr)), "total_x": total_x, "cagr": float(cagr),
            "max_dd": max_dd, "calmar": calmar}


# ---- walk forward ----
def walk_forward(sym: str, dates: list[str], close: np.ndarray, fund_long: np.ndarray) -> dict[str, Any]:
    n = len(close)
    rule_g = {nm: fn(close, fund_long) for nm, fn in RULES.items()}
    rule_r = {nm: daily_returns(close, g, fund_long) for nm, g in rule_g.items()}

    last_year = int(dates[-1][:4])
    first_year = int(dates[0][:4])
    test_years = [y for y in range(2019, last_year + 1) if y >= first_year + 3]

    log: list[dict] = []
    chosen_xs: list[float] = []
    h_xs: list[float] = []
    x1v_xs: list[float] = []
    chosen_count: dict[str, int] = {nm: 0 for nm in RULES}

    for y in test_years:
        train_mask = np.array([(f"{y-3}" <= d < f"{y}") for d in dates])
        if train_mask.sum() < 200:
            log.append({"year": y, "chosen": None, "reason": f"train days {int(train_mask.sum())} < 200"})
            continue
        train_calmar: dict[str, float] = {}
        for nm in RULES:
            m = _slice_metrics(rule_r[nm], train_mask)
            c = m["calmar"]
            if c is not None and c != float("inf") or c == float("inf"):
                train_calmar[nm] = c
        if not train_calmar:
            log.append({"year": y, "chosen": None, "reason": "no rule produced a valid Calmar"})
            continue
        # 选最大 Calmar;tie-break 用 sum(returns)(总收益高的优先)
        chosen = max(train_calmar, key=lambda k: (train_calmar[k], float(rule_r[k].sum())))
        chosen_count[chosen] += 1
        year_mask = np.array([d.startswith(str(y)) for d in dates])
        entry: dict[str, Any] = {
            "year": y,
            "chosen": chosen,
            "train_calmar": {k: round(v, 3) for k, v in train_calmar.items()},
        }
        for nm in RULES:
            entry[f"{nm}_year"] = _slice_metrics(rule_r[nm], year_mask)
        log.append(entry)
        cy_x = entry[f"{chosen}_year"]["total_x"]
        hy_x = entry["H_year"]["total_x"]
        xv_x = entry["X1V_year"]["total_x"]
        if cy_x is not None:
            chosen_xs.append(cy_x)
        if hy_x is not None:
            h_xs.append(hy_x)
        if xv_x is not None:
            x1v_xs.append(xv_x)

    return {
        "sym": sym,
        "n_days": n,
        "first": dates[0],
        "last": dates[-1],
        "test_years": test_years,
        "log": log,
        "walk_forward_total_x": float(np.prod([x for x in chosen_xs if x is not None])) if chosen_xs else None,
        "H_total_x": float(np.prod([x for x in h_xs if x is not None])) if h_xs else None,
        "X1V_total_x": float(np.prod([x for x in x1v_xs if x is not None])) if x1v_xs else None,
        "wf_n_years": len(chosen_xs),
        "chosen_count": chosen_count,
    }


# ---- reporting ----
def _fmt_x(x):
    if x is None:
        return "—"
    if x >= 100:
        return f"{x:.0f}x"
    if x >= 10:
        return f"{x:.1f}x"
    return f"{x:.2f}x"


def _fmt_cagr(x, years):
    if x is None or years is None or years <= 0:
        return "—"
    return f"{(x ** (1 / years) - 1) * 100:.1f}%"


def write_md(results: dict[str, dict], path: Path) -> None:
    lines: list[str] = []
    lines.append("# T-119 — 走步自适应:每轮只挑一个 Calmar 最好")
    lines.append("")
    lines.append("**协议**:§S-602「模拟四」。每年 1 月 1 日只用过去 3 年训练数据,在 {H, F, FB, X1V, V, PD13} 6 套里挑 Calmar 最好,做下一整年。")
    lines.append("")
    lines.append("**规则来源**(不许重写):")
    lines.append("- `s600_tom_trader.trade_path(c, bear, short_size)` → F/FB")
    lines.append("- `s601_drawdown.path(c, exit_mode)` + `vol_scale(c)` → V/X1V")
    lines.append("- `s596_tom_pyramid.gross_path(c, cap, defend)` → PD13")
    lines.append("- 收益:`s596_tom_pyramid.daily_returns`(10 bp 成本,>1 付资金费)")
    lines.append("- 选:`max(calmar)`;tie-break = `sum(returns)`")
    lines.append("")
    lines.append("## 1. 总览:Walk-forward vs 固定 X1V vs H")
    lines.append("")
    lines.append("| 资产 | 数据起讫 | WF n 年 | **WF total_x** | H total_x | X1V total_x | WF CAGR | H CAGR | X1V CAGR | WF 超 H | WF 超 X1V |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for sym, r in results.items():
        wf_x = r["walk_forward_total_x"]
        h_x = r["H_total_x"]
        x_x = r["X1V_total_x"]
        n_y = r["wf_n_years"]
        wf_cagr = _fmt_cagr(wf_x, n_y)
        h_cagr = _fmt_cagr(h_x, n_y)
        x_cagr = _fmt_cagr(x_x, n_y)
        wf_vs_h = "—" if (wf_x is None or h_x is None) else f"{(wf_x - h_x) * 100:+.0f}%"
        wf_vs_x = "—" if (wf_x is None or x_x is None) else f"{(wf_x - x_x) * 100:+.0f}%"
        lines.append(f"| {sym} | {r['first']} → {r['last']} | {n_y} | **{_fmt_x(wf_x)}** | "
                     f"{_fmt_x(h_x)} | {_fmt_x(x_x)} | {wf_cagr} | {h_cagr} | {x_cagr} | {wf_vs_h} | {wf_vs_x} |")
    lines.append("")
    lines.append("## 2. 逐年:挑中了谁 / 年内 total_x")
    lines.append("")
    for sym, r in results.items():
        lines.append(f"### {sym}")
        lines.append("")
        lines.append("| 年 | 选中 | 训练期 Calmar (H/F/FB/PD13/V/X1V) | chosen total_x | H total_x | X1V total_x | chosen 超 H | chosen 超 X1V |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for entry in r["log"]:
            if entry.get("chosen") is None:
                lines.append(f"| {entry['year']} | — | skipped: {entry.get('reason','?')} | — | — | — | — | — |")
                continue
            cal = entry["train_calmar"]
            cal_s = " / ".join(f"{nm}={cal.get(nm, '—')}" for nm in ("H", "F", "FB", "PD13", "V", "X1V"))
            cy = entry[f"{entry['chosen']}_year"]["total_x"]
            hy = entry["H_year"]["total_x"]
            xv = entry["X1V_year"]["total_x"]
            vs_h = "—" if (cy is None or hy is None) else f"{(cy - hy) * 100:+.1f}%"
            vs_x = "—" if (cy is None or xv is None) else f"{(cy - xv) * 100:+.1f}%"
            lines.append(f"| {entry['year']} | **{entry['chosen']}** | {cal_s} | "
                         f"{_fmt_x(cy)} | {_fmt_x(hy)} | {_fmt_x(xv)} | {vs_h} | {vs_x} |")
        lines.append("")
    lines.append("## 3. 选中频次(各资产 / 各策略)")
    lines.append("")
    rules = list(RULES.keys())
    lines.append("| 资产 | " + " | ".join(rules) + " |")
    lines.append("|---|" + "|".join(["---"] * len(rules)) + "|")
    for sym, r in results.items():
        lines.append(f"| {sym} | " + " | ".join(str(r["chosen_count"].get(nm, 0)) for nm in rules) + " |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"数据:Mac 数据根 `research/w50_daily/close.json` + `research/crypto_daily/panel.json` + `research/s596/funding_monthly.txt`。")
    lines.append(f"成本:{COST*1e4:.0f} bp/边;无随机(种子标记 SEED={SEED});运行:`python3 docs/research/t119_walk_forward.py`。")
    path.write_text("\n".join(lines))


def main():
    research_dir = Path("/Volumes/CometCloudAI/cometcloud-local/research")
    out_json = Path("/Volumes/CometCloudAI/cometcloud-local/research/_reports/absorb_input/T-119_walk_forward.json")
    out_md = Path("/Volumes/CometCloudAI/cometcloud-local/research/_reports/absorb_input/T-119_walk_forward.md")

    assets = load_assets(research_dir)
    results: dict[str, dict] = {}
    for sym, info in assets.items():
        results[sym] = walk_forward(sym, info["dates"], info["close"], info["fund_long"])

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=float))
    write_md(results, out_md)

    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print()
    print("Summary:")
    for sym, r in results.items():
        print(f"  {sym}: WF={_fmt_x(r['walk_forward_total_x'])}  H={_fmt_x(r['H_total_x'])}  "
              f"X1V={_fmt_x(r['X1V_total_x'])}  n={r['wf_n_years']}  picked={r['chosen_count']}")


if __name__ == "__main__":
    main()