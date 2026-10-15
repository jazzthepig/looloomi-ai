"""T-089 整只基金完整模拟 — 一键 wrapper。

T-089 v3 验收要求整只基金的按时点模拟(① + 倾斜 + 推力 + 组合层 + 配置层 + W3 +
随机对照)。Public endpoint 在 sandbox 内不可达,本 wrapper 直接用 v3 loader 10-14
落地的 panel CSV(`_reports/absorb_input/t089_series_2026-10-14.csv`)喂入 simulator,
跑全三段 + 500 random trials,落 JSON + markdown 进同一目录。

不是 v3 loader 的后端(§Seth-1014a #2 删了 csv 后端);这是 Mac-side 一次性 wrapper
——  复用 v3 loader **真实**输出(不是 priors),不引入任何新数据。Seth 同意后下次
可以重拉 v3 loader 替换 panel CSV,本 wrapper 路径不变。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from t089_fund_simulation import (                                      # noqa: E402
    SimEvidence, SimEvidencePack, simulate_from_panel, WINDOWS,
)


PANEL_CSV = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t089_series_2026-10-14.csv")
ABSORB = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/")


def _load_panel() -> pd.DataFrame:
    df = pd.read_csv(PANEL_CSV, parse_dates=["d"]).sort_values("d").reset_index(drop=True)
    df["d"] = pd.to_datetime(df["d"]).dt.tz_localize(None)
    return df


def _demo_sim_pack() -> SimEvidencePack:
    # M-558 预注册 — 复用 v3.1 runner 的同一组 priors 作为合成规则示例
    return SimEvidencePack(
        multiplier=SimEvidence(sealed=True, pct_vs_random=0.96, holdout_n=200,
                               mu_post_ann=0.07, sigma_ann=0.18),
        portfolio_layer=SimEvidence(sealed=True, pct_vs_random=0.95, holdout_n=180,
                                    mu_post_ann=0.04, sigma_ann=0.14),
    )


def main() -> int:
    panel = _load_panel()
    sim_pack = _demo_sim_pack()
    report = simulate_from_panel(
        panel, sim_pack=sim_pack,
        random_trials=500, windows=WINDOWS, rng_seed=20261013,
    )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    json_path = ABSORB / f"t089_full_sim_{ts}_results.json"
    md_path = ABSORB / f"t089_full_sim_{ts}_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str))

    lines = [f"# T-089 full sim — {ts}Z\n", "## Panel meta\n",
             f"- source: {PANEL_CSV}", f"- rows: {len(panel)}",
             f"- first: {panel['d'].iloc[0].date()}", f"- last: {panel['d'].iloc[-1].date()}\n",
             "## Windows\n"]
    for w_name, w in report["windows"].items():
        if "error" in w:
            lines.append(f"- **{w_name}**: ERR  {w['error']}")
            continue
        if w.get("not_computable"):
            lines.append(f"- **{w_name}**: NC  {w.get('reason', '?')}")
            continue
        fund = w["fund"]
        lines.append(
            f"- **{w_name}**: 总收益 {fund['total_return']:+.2%} (① {w['core_cap']['total_return']:+.2%}; "
            f"BTC {w['btc']['total_return']:+.2%}); maxDD {fund['max_dd']:+.2%}; "
            f"random p50/p95 {w['random_p50_total']:+.2%}/{w['random_p95_total']:+.2%}; "
            f"pct_vs_random {w['pct_vs_random']:.0%}"
        )
    md_path.write_text("\n".join(lines) + "\n")

    print(f"[ok] panel {len(panel)} rows from {PANEL_CSV}")
    print(f"[ok] {json_path}")
    print(f"[ok] {md_path}")
    for w_name, w in report["windows"].items():
        if w.get("not_computable"):
            print(f"  {w_name}: NC")
        elif "error" in w:
            print(f"  {w_name}: ERR")
        else:
            f = w["fund"]
            print(f"  {w_name}: total {f['total_return']:+.2%} maxDD {f['max_dd']:+.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
