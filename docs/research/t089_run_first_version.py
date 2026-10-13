"""T-089 first-version runner — 把 (panel_loader + simulator) 接成一条线,跑通 W1/W2 两段,
   把「真实的那组数字」写到一个 JSON + markdown(本地只读,不入 Supabase)。

为什么这么写:
  - 临时单跑的「跑通证明」就摆在仓库里 —— Seth / Jazz 可以 `python3 docs/research/t089_run_first_version.py`
    复演。后端 P / 后端 M 任何一个通了之后,改 --backend 一行即可重跑。
  - 后端 S 是当前的「数字骨架」(priors 锁定、可重现);后端 D 接入了一支真 BTC(Mac 之前 t060 缓存)。
    后端 P 等授权(详 t089_panel_loader.py 顶文)。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# 同目录
sys.path.insert(0, str(Path(__file__).parent))
from t089_panel_loader import LOADERS, panel_from_synthetic            # noqa: E402
from t089_fund_simulation import (                                      # noqa: E402
    SimEvidence, SimEvidencePack, simulate_from_panel, WINDOWS, WINDOW_HALF,
)


# T-089 接受标准里 W3 = 「10-12 起前向」。v2 当前只有回放面板,前向会触发
# W3(single day = 2026-10-13)在 `_metrics` 里的 IndexError;本轮直接用 W1/W2 两段,
# 真前向等 M-558-a(Supabase 后端)接入后再开。WINDOW_HALF 封存留出段稍后接入。
T089_V2_WINDOWS = tuple(w for w in WINDOWS if w[0] in ("W1", "W2"))  # type: ignore[assignment]


# M-558 预注册的 SimEvidence — 仅作 demo:实跑由每本账 loop_attempt.detail 注入
def _demo_sim_pack() -> SimEvidencePack:
    """数字是 docs/research/t089_fund_simulation.py 顶端注释「M-558 预注册的
    A 路证据样例」 —— 用 priors(SIM_PCT=0.95 截门、shrunken mu_post、封存)的最小合规组合。
    真跑时这里改为读 allocation.bucket_attempts('multiplier') 之 poke。"""
    return SimEvidencePack(
        multiplier=SimEvidence(sealed=True, pct_vs_random=0.96, holdout_n=200,
                               mu_post_ann=0.07, sigma_ann=0.18),
        portfolio_layer=SimEvidence(sealed=True, pct_vs_random=0.95, holdout_n=180,
                                    mu_post_ann=0.04, sigma_ann=0.14),
    )


def render_markdown(report: dict, provenance: dict, argv: list[str]) -> str:
    """数字 + provenance → 一张表,贴在仓库的 docs/research/t089_first_version_report.md 上
    供 Seth/Jazz 在合并前对照。"""
    lines = ["# T-089 v2 First-Version Report\n",
             f"_{datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n",
             "## Panel provenance\n",
             "```json", json.dumps(provenance, indent=2, default=str), "```\n",
             "## 命令行\n", "```\n", " ".join(argv), "\n```\n",
             "## 三段总收益 / 回撤 / 夏普(模拟基金 vs BTC vs ① vs 随机对照)\n"]
    rows = []
    rows.append("| window | metric | fund | core_u (①) | BTC | random_p50 | random_p95 | excess_vs_① | pct_vs_random |")
    rows.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for win_name, win in report["windows"].items():
        if "error" in win:
            rows.append(f"| {win_name} | _ERR_ | {win['error']} |  |  |  |  |  |  |")
            continue
        fund = win["fund"]; core = win["core_cap"]; btc = win["btc"]
        lines.append("")
        rows.append(
            f"| {win_name} | total_return | {fund['total_return']:+.2%} | {core['total_return']:+.2%} | "
            f"{btc['total_return']:+.2%} | "
            f"{win['random_p50_total']:+.2%} | {win['random_p95_total']:+.2%} | "
            f"{(fund.get('ann_return') or 0) - (core.get('ann_return') or 0):+.2%} | "
            f"{win['pct_vs_random']:.0%} |"
        )
        rows.append(
            f"| {win_name} | max_dd       | {fund['max_dd']:+.2%} | {core['max_dd']:+.2%} | "
            f"{btc['max_dd']:+.2%} |  |  |  |  |"
        )
        sharpe = f"{fund['sharpe']:+.2f}" if fund.get("sharpe") is not None else "—"
        sharpe_core = f"{core['sharpe']:+.2f}" if core.get("sharpe") is not None else "—"
        sharpe_btc = f"{btc['sharpe']:+.2f}" if btc.get("sharpe") is not None else "—"
        rows.append(
            f"| {win_name} | sharpe       | {sharpe} | {sharpe_core} | {sharpe_btc} |  |  |  |  |"
        )
    lines.extend(rows)
    lines.append("")
    lines.append("## 随机对照(500 次,Dirichlet α=1,固定 avg=1 - w_core[D])\n")
    sample = report.get("portfolio_decisions_sample", [])
    if sample:
        lines.append("- 取 6 个决策日的 weights / evidence_path 抽样(只用来定性核对合成器对不对,不参与统计):\n")
        for s in sample:
            lines.append(f"  - {s['d']}: weights = {s['weights']}\n    path = {s['evidence_path']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=list(LOADERS), default="synthetic")
    ap.add_argument("--csv-dir", default="research/t060/raw")
    ap.add_argument("--start", default="2023-01-02")
    ap.add_argument("--end",   default="2026-10-12")
    ap.add_argument("--random-trials", type=int, default=500)
    # 默认带 backend 的后缀,免得 --backend 切的时候覆盖
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md",   default=None)
    args = ap.parse_args()
    argv = sys.argv[1:]
    if args.out_json is None:
        args.out_json = f"docs/research/t089_first_version_results_{args.backend}.json"
    if args.out_md is None:
        args.out_md = f"docs/research/t089_first_version_report_{args.backend}.md"

    # 1) 装载面板
    if args.backend == "supabase":
        try:
            panel, prov = LOADERS[args.backend](args.start, args.end)
        except NotImplementedError as exc:
            print(f"[fatal] {exc}"); return 2
    elif args.backend == "csv":
        panel, prov = LOADERS[args.backend](Path(args.csv_dir), args.start, args.end)
    else:
        panel, prov = panel_from_synthetic(args.start, args.end, seed=20261013)

    # 2) 跑模拟 — CSV 后端只有 2025-01 起的 BTC,故只跑 W2
    if args.backend == "csv":
        windows = tuple(w for w in T089_V2_WINDOWS if w[0] in ("W2",))
    else:
        windows = T089_V2_WINDOWS
    sim_pack = _demo_sim_pack()
    report = simulate_from_panel(
        panel, sim_pack=sim_pack,
        random_trials=args.random_trials,
        windows=windows,
        rng_seed=20261013,
    )

    # 3) 写报告
    out_report = {
        "panel_first": report["panel_first"],
        "panel_last":  report["panel_last"],
        "windows":     report["windows"],
        "sample_decisions": report.get("portfolio_decisions_sample", []),
        "provenance":  {
            "backend": prov.backend,
            "start": prov.start, "end": prov.end, "n_days": prov.n_days,
            "sources": prov.sources,
            "demo_sim_pack": {
                "multiplier":     {"pct_vs_random": 0.96, "mu_post_ann": 0.07, "sigma_ann": 0.18},
                "portfolio_layer": {"pct_vs_random": 0.95, "mu_post_ann": 0.04, "sigma_ann": 0.14},
                "cis_tilt_note": "无 A 路证据(没有 holdout) — 走纯 B 路, evidence = 超额 ≥ MIN_DAYS",
            },
        },
    }
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(out_report, indent=2, default=str))
    md = render_markdown(report, out_report["provenance"], argv)
    Path(args.out_md).write_text(md)

    # 4) 控制台一段直给(便于本机核对)
    print(f"[ok] panel {prov.start} → {prov.end} ({prov.n_days} 天; backend={prov.backend})")
    for w_name, w in report["windows"].items():
        if "error" in w:
            print(f"  {w_name}: ERR  {w['error']}"); continue
        fund = w["fund"]; p50 = w["random_p50_total"]; p95 = w["random_p95_total"]
        sharpe = f"{fund['sharpe']:+.2f}" if "sharpe" in fund else "—"
        print(f"  {w_name}: 总收益 {fund['total_return']:+.2%} (① {w['core_cap']['total_return']:+.2%}; BTC "
              f"{w['btc']['total_return']:+.2%}); maxDD {fund['max_dd']:+.2%}; Sharpe {sharpe}; "
              f"random_p50/p95 {p50:+.2%}/{p95:+.2%}; pct_vs_random {w['pct_vs_random']:.0%}")
    print(f"[ok] JSON → {args.out_json};  md → {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
