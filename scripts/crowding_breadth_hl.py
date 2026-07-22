#!/usr/bin/env python3
"""
§CROWDING-BREADTH runner — Hyperliquid cache variant (Minimax-B → Minimax-A lane).

Per §CROWDING-BREADTH 2026-07-18 directive: the credit test needs ≥2y of cross-class
funding history on a 30-50 perp basket. The RWA smoke test (21 RWA perps × 84d)
validated the MECHANISM but couldn't credit (α_t = 1.59 < 1.96 on 17d OOS).

This runner is what to execute ONCE Minimax-A's HL fetch lands:

    python3 scripts/crowding_breadth_hl.py --source hyperliquid --out-dir reports/crowding_breadth/2026-XX-XX_hl_credit/

It will:
  1. Load `funding_crowding_breadth.load_hyperliquid_panel()` (auto-detects HL cache)
  2. Run the pooled breadth experiment with a-priori canonical config (thr=1.0, hold=10)
  3. Run the full signal gauntlet (PSR / factor_absorption / regime_robustness)
  4. Write per_trade.csv, summary.json, REPORT.md to the out-dir
  5. Print the verdict to stdout

Mac-side runtime estimate: ~30-60s (50 perps × ~2y of daily panels).

USAGE
    python3 scripts/crowding_breadth_hl.py                              # HL default
    python3 scripts/crowding_breadth_hl.py --source rwa                  # RWA fallback
    python3 scripts/crowding_breadth_hl.py --min-history-days 180       # relax threshold
    python3 scripts/crowding_breadth_hl.py --max-perps 30                # tighter universe

OUTCOMES (what to do with the verdict)
    α_t > 1.96 + full gauntlet passes → ★ ORTHOGONAL EDGE candidate, slot into the
        two-layer book as the market-neutral behavioral sleeve (per §TRADER_TOM_DOCTRINE).
        Update MINIMAX_SYNC §CROWDING-BREADTH reply block; archive RWA smoke as superseded.
    α_t still < 1.96 → honest R36 ("funding-crowding cross-class breadth is real but
        uncreditable at the available sample size"). Document and move on.

OWNER
  minimax-b (Austin). Mac-side execution by Minimax-A (per CLAUDE.md ownership).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.research.cis_regime_studies.funding_crowding_breadth import (
    load_hyperliquid_panel,
    load_rwa_perp_panel,
    run_pooled_breadth_experiment,
    format_verdict,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run §CROWDING-BREADTH on cached perp funding.")
    ap.add_argument("--source", choices=["hyperliquid", "rwa"], default="hyperliquid",
                    help="Which cached funding source to use")
    ap.add_argument("--min-history-days", type=int, default=None,
                    help="Override the loader default (HL=365, RWA=80)")
    ap.add_argument("--max-perps", type=int, default=None,
                    help="Override the loader default (HL=50, RWA=30)")
    ap.add_argument("--oos-frac", type=float, default=0.20,
                    help="OOS holdout fraction (default 0.20)")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output directory for verdict + summary")
    args = ap.parse_args()

    print(f"=== §CROWDING-BREADTH runner — source={args.source} ===")
    print(f"Output: {args.out_dir}")
    print()

    # 1. Load panel
    try:
        if args.source == "hyperliquid":
            min_hist = args.min_history_days if args.min_history_days is not None else 365
            max_perps = args.max_perps if args.max_perps is not None else 50
            print(f"Loading HL panel (min_history_days={min_hist}, max_perps={max_perps})...")
            panel = load_hyperliquid_panel(min_history_days=min_hist, max_perps=max_perps)
        else:
            min_hist = args.min_history_days if args.min_history_days is not None else 80
            max_perps = args.max_perps if args.max_perps is not None else 30
            print(f"Loading RWA panel (min_history_days={min_hist}, max_perps={max_perps})...")
            panel = load_rwa_perp_panel(min_history_days=min_hist, max_perps=max_perps)
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        print("\nThis is the load-bearing next step per §CROWDING-BREADTH 2026-07-18:")
        print("  python3 scripts/fetch_hyperliquid_funding.py --universe top50 --start 2023-01-01")
        return 1
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        return 1

    print(f"Loaded {len(panel.symbols)} perps: {panel.symbols[:10]}{'...' if len(panel.symbols) > 10 else ''}")
    print(f"Window: {panel.dates[0]} → {panel.dates[-1]} ({len(panel.dates)} days)")
    print()

    # 2. Run pooled breadth experiment
    print("Running pooled breadth experiment (canonical: thr=1.0, hold=10)...")
    out = run_pooled_breadth_experiment(panel, oos_frac=args.oos_frac)

    # 3. Run full gauntlet
    print("Running signal gauntlet...")
    from src.research.validation.signal_gauntlet import run_gauntlet, format_funnel
    g = run_gauntlet(
        f"crowding_breadth_{args.source}",
        out["pooled_ret_oos"],
        factors=out["factors_oos"],
        variants=out["variants_oos"],
        periods_per_year=365,
    )

    # 4. Format verdict
    verdict_text = format_verdict(out, g)
    funnel_text = format_funnel([g])

    print()
    print(verdict_text)
    print()
    print(funnel_text)

    # 5. Persist
    args.out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "source": args.source,
        "n_perps": out["n_perps"],
        "n_days": out["n_days"],
        "oos_days": out["oos_days"],
        "enb_input_assets": out["enb_input_assets"],
        "oos_alpha_t": out["oos_alpha_t"],
        "gauntlet_verdict": g["verdict"],
        "gauntlet_stages": g["stages"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = args.out_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    report_path = args.out_dir / "REPORT.md"
    report_path.write_text(f"""# §CROWDING-BREADTH — {args.source.upper()} credit test ({summary['timestamp_utc'][:10]})

**Source:** {args.source}
**Panel:** {out['n_perps']} perps × {out['n_days']} days (OOS {out['oos_days']}d)
**A-priori canonical config:** `crowding_signal(thr=1.0, hold=10, vol_mult=1.10, cost_bps=5.0)`

## Headline numbers

- **Input-asset ENB:** {out['enb_input_assets']:.2f} (breadth question: is the pool truly uncorrelated?)
- **Canonical OOS α_t (after f_market + f_momentum, NW):** {out['oos_alpha_t']['alpha_t']:+.2f}
- **α_ann_pct:** {out['oos_alpha_t']['alpha_ann_pct']:+.2f}%
- **Factor betas:** {out['oos_alpha_t']['betas']}

## Variant set (config sweep)

{chr(10).join(f"- `{name}`: ann Sharpe {_annualized_sharpe_helper(ret):+.2f}" for name, ret in out['variants_oos'].items())}

## Signal Gauntlet verdict

```
{g['verdict']}
```

{funnel_text}

## Files

- `summary.json` — machine-readable verdict
- `REPORT.md` — this file

## Next step

- If α_t > 1.96 + full gauntlet passes → promote to **★ ORTHOGONAL EDGE** candidate,
  update MINIMAX_SYNC §CROWDING-BREADTH reply block.
- If α_t < 1.96 → log honest R36, document why the mechanism doesn't survive the credit bar.
""")

    print()
    print(f"Summary: {summary_path}")
    print(f"Report:  {report_path}")

    # 6. Console verdict
    print()
    print(f"{'─' * 72}")
    if out["oos_alpha_t"]["alpha_t"] > 1.96 and "DIED" not in g["verdict"]:
        print(f"  ★ ★ ★  ORTHOGONAL EDGE CANDIDATE  ★ ★ ★")
        print(f"  α_t = {out['oos_alpha_t']['alpha_t']:+.2f} > 1.96 ship gate")
        print(f"  Gauntlet: {g['verdict']}")
        print(f"  → Promote to two-layer book (market-neutral behavioral sleeve)")
    elif out["oos_alpha_t"]["alpha_t"] > 1.0:
        print(f"  🟡 DIRECTIONALLY POSITIVE — α_t = {out['oos_alpha_t']['alpha_t']:+.2f} (below 1.96 ship gate)")
        print(f"  Mechanism real, sample insufficient for credit. Document + archive.")
    else:
        print(f"  🔴 NEGATIVE — α_t = {out['oos_alpha_t']['alpha_t']:+.2f}")
        print(f"  Mechanism doesn't survive on this sample. Log R36 honest.")
    print(f"{'─' * 72}")

    return 0


def _annualized_sharpe_helper(r, periods_per_year=365):
    """Local helper to avoid importing internals."""
    import math
    import numpy as np
    r = np.asarray(r)
    r = r[~np.isnan(r)]
    if len(r) < 5 or r.std() < 1e-12:
        return 0.0
    return float(r.mean() / r.std() * math.sqrt(periods_per_year))


if __name__ == "__main__":
    raise SystemExit(main())
