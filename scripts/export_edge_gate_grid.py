#!/usr/bin/env python3
"""
Export the (shrunk) edge-map grid to a JSON snapshot the strategies load offline.

The bridge from intelligence → execution: `src/research/strategies/edge_gate.py` needs a
`{signal_tier: {risk_band: shrunk_alpha}}` grid. In LIVE the strategy can hit
`GET /api/v1/signals/edge-map` (already returns shrunk `avg_alpha_pct`); for BACKTEST it loads
this static snapshot. Same grid, same `gate()` call.

Usage:
  # from the live API (default) — works anywhere, no DB creds needed:
  python3 scripts/export_edge_gate_grid.py --out reports/edge_gate_grid.json
  # from a custom base:
  EDGE_MAP_URL=https://looloomi.ai/api/v1/signals/edge-map python3 scripts/export_edge_gate_grid.py
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

URL = os.getenv("EDGE_MAP_URL", "https://looloomi.ai/api/v1/signals/edge-map")


def fetch_grid(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-edge-gate-export/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    grid_full = data.get("grid") or {}
    # collapse {tier: {band: {avg_alpha_pct(shrunk), ...}}} → {tier: {band: shrunk_alpha}}
    grid = {}
    for tier, bands in grid_full.items():
        for band, cell in bands.items():
            grid.setdefault(tier, {})[band] = cell.get("avg_alpha_pct")
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": url,
        "shrinkage": data.get("shrinkage"),
        "risk_bands": data.get("risk_bands"),
        "grid": grid,
        "note": "shrunk expected 30d benchmark-relative alpha %; feed to edge_gate.gate().",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/edge_gate_grid.json")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args(argv)
    try:
        snap = fetch_grid(args.url)
    except Exception as e:
        print(f"ERROR fetching {args.url}: {e}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(snap, f, indent=2)
    tiers = snap["grid"]
    print(f"wrote {args.out}  ({len(tiers)} tiers, "
          f"{sum(len(b) for b in tiers.values())} cells)  K={snap.get('shrinkage', {}).get('K')}")
    for t, bands in tiers.items():
        print(f"  {t:18} " + "  ".join(f"{b.split('_')[0]}:{v:+.1f}" for b, v in sorted(bands.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
