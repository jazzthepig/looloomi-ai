#!/usr/bin/env python3
"""
H2a — Benchmark-Relative Regime-Conditional IC (Seth/Austin, 2026-07-06)
========================================================================

H1 found the composite-CIS *absolute* 7d forward-return IC flips sign by regime
(positive Tightening, negative Risk-On/Risk-Off/Stagflation). The design question
(docs/H2_REGIME_GATE_DESIGN_2026-07-06.md §3): is that a genuine cross-sectional
REVERSAL, or just a BETA-timing artifact — high-CIS crypto names are higher-beta,
so they fall more in absolute terms when the market falls, even while their ALPHA
(return minus benchmark) is fine?

This script re-runs the H1 IC per regime on BENCHMARK-RELATIVE forward returns
(asset fwd return − benchmark fwd return; BTC for crypto, SPY for TradFi) and puts
the absolute-IC and relative-IC side by side.

Decision:
  - If the negative sign-flips SHRINK toward zero / flip positive under relative
    returns → CIS is a valid cross-sectional RANKING signal; the regime layer owns
    beta timing. (Safest, most likely — collapses H2 to "don't invert CIS.")
  - If they PERSIST under relative returns → genuine reversal (interpretation B);
    the gate direction really is regime-conditional and must be modelled.

Runs where the OHLCV panel lives (Mac / drive). Read-only. Analysis, no prod change.

Usage:
  python3 -m src.research.cis_regime_studies.h2a_relative_ic            # writes report
  BENCH_CRYPTO=BTC BENCH_TRADFI=SPY python3 -m ...h2a_relative_ic
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.cis_regime_studies.common.data_loader import (
    load_cis_history,
    load_ohlcv_panel,
    build_research_panel,
)
from src.research.cis_regime_studies.common.metrics import ic_table

logger = logging.getLogger(__name__)

PILLARS = ["cis_score", "pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a"]
_TRADFI = {"US Equity", "US Bond", "EM Equity", "DM Equity", "Commodity", "TradFi", "FX", "Real Estate"}

BENCH_CRYPTO = os.getenv("BENCH_CRYPTO", "BTC").upper()
BENCH_TRADFI = os.getenv("BENCH_TRADFI", "SPY").upper()
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))

# CIS history dir — default raw, can be overridden to smoothed for H1.5 re-runs
CIS_HISTORY_DIR = Path(os.getenv(
    "H2A_CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
))


def _add_relative_returns(panel: pd.DataFrame, horizons=(7, 30)) -> pd.DataFrame:
    """For each horizon add fwd_rel_<h>d = fwd_<h>d(asset) − fwd_<h>d(benchmark),
    benchmark chosen per asset_class (BTC crypto / SPY TradFi), matched by timestamp."""
    p = panel.copy()
    has_class = "asset_class" in p.columns
    for h in horizons:
        col = f"fwd_{h}d"
        if col not in p.columns:
            continue
        # per-date benchmark forward returns
        bench_c = (p[p["asset"] == BENCH_CRYPTO][["timestamp", col]]
                   .drop_duplicates("timestamp").rename(columns={col: "_bc"}))
        p = p.merge(bench_c, on="timestamp", how="left")
        if (p["asset"] == BENCH_TRADFI).any():
            bench_t = (p[p["asset"] == BENCH_TRADFI][["timestamp", col]]
                       .drop_duplicates("timestamp").rename(columns={col: "_bt"}))
            p = p.merge(bench_t, on="timestamp", how="left")
        else:
            p["_bt"] = np.nan
        if has_class:
            bench = np.where(p["asset_class"].isin(_TRADFI), p["_bt"], p["_bc"])
        else:
            bench = p["_bc"]
        p[f"fwd_rel_{h}d"] = p[col] - pd.Series(bench, index=p.index)
        p = p.drop(columns=[c for c in ("_bc", "_bt") if c in p.columns])
    return p


def _composite(ic_df: pd.DataFrame) -> pd.DataFrame:
    c = ic_df[(ic_df["pillar"] == "cis_score") & (ic_df["regime"] != "_overall")].copy()
    return c.set_index("regime")[["n", "ic", "t_stat"]]


def run_h2a(horizons=(7, 30), write_reports: bool = True,
          cis_dir: Optional[Path] = None) -> dict:
    cis = load_cis_history(cis_dir or CIS_HISTORY_DIR)
    ohlcv = load_ohlcv_panel()
    panel = build_research_panel(cis, ohlcv, horizons=horizons)
    panel = _add_relative_returns(panel, horizons)

    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "bench": {"crypto": BENCH_CRYPTO, "tradfi": BENCH_TRADFI},
           "n_rows": int(len(panel)), "by_horizon": {}}
    md = ["# H2a — Absolute vs Benchmark-Relative CIS IC by Regime\n",
          f"_Generated {out['generated']} — benchmark: crypto={BENCH_CRYPTO}, tradfi={BENCH_TRADFI}_\n",
          "Tests whether H1's negative absolute-IC sign-flips are a BETA artifact "
          "(vanish under benchmark-relative returns) or a genuine reversal (persist).\n"]

    for h in horizons:
        abs_col, rel_col = f"fwd_{h}d", f"fwd_rel_{h}d"
        if rel_col not in panel.columns:
            continue
        abs_ic = _composite(ic_table(panel.dropna(subset=[abs_col]), PILLARS, abs_col))
        rel_ic = _composite(ic_table(panel.dropna(subset=[rel_col]), PILLARS, rel_col))
        cmp = abs_ic.join(rel_ic, lsuffix="_abs", rsuffix="_rel", how="outer")
        rows = []
        md.append(f"\n## {h}d horizon\n")
        md.append("| regime | n | IC abs | t abs | IC rel | t rel | verdict |")
        md.append("|---|---:|---:|---:|---:|---:|---|")
        for regime, r in cmp.sort_values("ic_abs").iterrows():
            ia, ta = r.get("ic_abs"), r.get("t_stat_abs")
            ir, tr = r.get("ic_rel"), r.get("t_stat_rel")
            n = int(r.get("n_abs") or r.get("n_rel") or 0)
            # verdict: did a significant negative absolute IC vanish/flip under relative?
            v = "—"
            if pd.notna(ia) and pd.notna(ir):
                if ia < 0 and abs(ta or 0) >= 2:
                    if ir >= 0 or abs(ir) < abs(ia) * 0.5:
                        v = "BETA artifact (relative-IC recovers)"
                    else:
                        v = "genuine reversal (persists)"
                elif ia > 0 and abs(ta or 0) >= 2:
                    v = "consistent (both positive)" if (ir or 0) > 0 else "abs+ only"
            rows.append({"regime": regime, "n": n,
                         "ic_abs": None if pd.isna(ia) else round(ia, 4),
                         "t_abs": None if pd.isna(ta) else round(ta, 2),
                         "ic_rel": None if pd.isna(ir) else round(ir, 4),
                         "t_rel": None if pd.isna(tr) else round(tr, 2),
                         "verdict": v})
            md.append(f"| {regime} | {n} | {_f(ia)} | {_f(ta,2)} | {_f(ir)} | {_f(tr,2)} | {v} |")
        out["by_horizon"][f"{h}d"] = rows

    # headline: count how many regimes' negative abs-IC recover under relative
    h7 = out["by_horizon"].get("7d", [])
    recovered = sum(1 for r in h7 if r["verdict"].startswith("BETA"))
    persisted = sum(1 for r in h7 if r["verdict"].startswith("genuine"))
    md.insert(3, f"\n**Headline (7d):** {recovered} regime(s) BETA-artifact (relative-IC recovers → "
                 f"CIS ranking intact), {persisted} genuine reversal (persists → gate direction is real).\n")
    out["headline_7d"] = {"beta_artifact": recovered, "genuine_reversal": persisted}

    if write_reports:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "cis_regime_relative_ic_2026-07-06.md").write_text("\n".join(md))
        (REPORTS_DIR / "cis_regime_relative_ic_2026-07-06.json").write_text(json.dumps(out, indent=2))
        logger.info("wrote reports/cis_regime_relative_ic_2026-07-06.{md,json}")
    return out


def _f(x, nd=4):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:+.{nd}f}"


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cis-dir", type=Path, default=None,
                        help="CIS history dir (default: raw; use smoothed/ for H1.5).")
    args = parser.parse_args()
    res = run_h2a(cis_dir=args.cis_dir)
    print(json.dumps(res.get("headline_7d", {}), indent=2))
    for r in res["by_horizon"].get("7d", []):
        print(f"  {r['regime']:12} IC_abs={_f(r['ic_abs'])} IC_rel={_f(r['ic_rel'])}  {r['verdict']}")
