"""T-085 7-day sweep aggregator — merge multiple t085_sweep_*.json snapshots
and recompute the per-symbol median venue depth + verdict (vs S-544).

Acceptance per T-085 card:
  报告:每个名字的可下单场所数、深度中位数、深度 / 全市场报告成交额的比例;
        按 S-544 的口径(5% 仓位、10% 参与率、5 天)重算 $30M 与 $500M 下每个名字与每本账能否建满

Behavior:
  - Reads t085_sweep_<UTC_date>_H<s>.json files (one per slot)
  - Reads latest t085_sleeves_<ts>.json for S-544 baseline
  - For each (symbol, venue), aggregates the multiple depth snapshots
    and computes median ±1% / ±2% depth in USD (both sides)
  - Recomputes per-AUM verdict at $30M target and $500M design
  - Writes t085_report_7d_<ts>.json
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/research/t085")

POSITION_PCT = 0.05
PARTICIPATION = 0.10
BUILD_DAYS = 5
TARGET_AUM = 30_000_000
DESIGN_AUM = 500_000_000


def median_or_zero(vals):
    vals = [v for v in vals if v is not None and v > 0]
    if not vals:
        return 0.0
    return statistics.median(vals)


def median_pair(bid_vals, ask_vals):
    """Symmetric ±pct depth = median of (bid+ask) per snapshot, then take median across snapshots.

    A single depth = bid_usd + ask_usd within ±pct of mid. We compute that per snapshot,
    then take the median across snapshots for stability.
    """
    pairs = []
    n = max(len(bid_vals), len(ask_vals))
    for i in range(n):
        b = bid_vals[i] if i < len(bid_vals) else 0.0
        a = ask_vals[i] if i < len(ask_vals) else 0.0
        if b + a > 0:
            pairs.append(b + a)
    return median_or_zero(pairs)


def median_sym_depth(grouped_snapshots):
    """grouped_snapshots = list of dicts each with depth_1pct_bid_usd etc per (sym, venue).
    Returns median (per-side + combined) across snapshots.
    """
    if not grouped_snapshots:
        return {"bid_usd": 0.0, "ask_usd": 0.0, "combined_usd": 0.0,
                "spread_bps": 0.0, "n_snapshots": 0,
                "n_snapshots_with_ob": 0}
    bid_1 = [s.get("depth_1pct_bid_usd", 0) or 0 for s in grouped_snapshots]
    ask_1 = [s.get("depth_1pct_ask_usd", 0) or 0 for s in grouped_snapshots]
    bid_2 = [s.get("depth_2pct_bid_usd", 0) or 0 for s in grouped_snapshots]
    ask_2 = [s.get("depth_2pct_ask_usd", 0) or 0 for s in grouped_snapshots]
    spr = [s.get("spread_bps", 0) or 0 for s in grouped_snapshots
           if s.get("spread_bps") is not None]
    return {
        "depth_1pct_bid_usd_median": median_or_zero(bid_1),
        "depth_1pct_ask_usd_median": median_or_zero(ask_1),
        "depth_2pct_bid_usd_median": median_or_zero(bid_2),
        "depth_2pct_ask_usd_median": median_or_zero(ask_2),
        "depth_1pct_combined_usd_median": median_pair(bid_1, ask_1),
        "depth_2pct_combined_usd_median": median_pair(bid_2, ask_2),
        "spread_bps_median": median_or_zero(spr),
        "n_snapshots_with_ob": sum(1 for s in grouped_snapshots if (s.get("depth_2pct_bid_usd") or 0) > 0),
        "n_snapshots_total": len(grouped_snapshots),
    }


def build_capacity_adv(adv_per_day):
    if adv_per_day <= 0:
        return 0.0
    return (adv_per_day * PARTICIPATION * BUILD_DAYS) / POSITION_PCT


def main():
    sweep_files = sorted(OUT_DIR.glob("t085_sweep_*.json"))
    # Also accept legacy 1-snapshot file t085_depth_*.json (no slot field — treat as H15 of that date)
    legacy_files = sorted(OUT_DIR.glob("t085_depth_*.json"))
    sleeves_files = sorted(OUT_DIR.glob("t085_sleeves_*.json"))
    if not (sweep_files or legacy_files):
        print("ERROR: no t085_sweep_*.json or t085_depth_*.json files found")
        return 1
    if not sleeves_files:
        print("ERROR: no t085_sleeves_*.json files found — run fetch_universe.py first")
        return 1

    sleeves = json.loads(sleeves_files[-1].read_text())
    n_snapshots = len(sweep_files) + len(legacy_files)
    print(f"=== T-085 7-day sweep aggregate ===")
    print(f"sweep snapshots: {len(sweep_files)}, legacy: {len(legacy_files)}")
    for p in sweep_files:
        print(f"  - {p.name}")
    for p in legacy_files:
        print(f"  - {p.name} (legacy, 1-snapshot)")

    # Group (symbol, venue) across snapshots
    grouped = defaultdict(list)
    snapshots_meta = []
    for p in sweep_files:
        j = json.loads(p.read_text())
        snapshots_meta.append({
            "file": p.name,
            "slot_utc": j.get("slot_utc"),
            "slot_hour_utc": j.get("slot_hour_utc"),
            "n_ob_hit": j.get("n_ob_hit"),
            "n_ob_miss": j.get("n_ob_miss"),
            "source": "sweep",
        })
        for d in j.get("depths", []):
            grouped[(d["symbol"], d["venue"])].append(d)

    # Legacy 1-snapshot depth files (no slot field — synthesize from filename + treat as H15)
    for p in legacy_files:
        j = json.loads(p.read_text())
        # filename pattern t085_depth_YYYYMMDD_HHMM.json
        stem = p.stem.replace("t085_depth_", "")
        date_part, time_part = stem.split("_")
        slot_h = 15  # legacy 1-snapshot was H15:46 — synthesize slot H15
        slot_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        snapshots_meta.append({
            "file": p.name,
            "slot_utc": f"{slot_date}T{slot_h:02d}:00:00Z",
            "slot_hour_utc": slot_h,
            "n_ob_hit": j.get("n_ob_hit"),
            "n_ob_miss": j.get("n_ob_miss"),
            "source": "legacy",
        })
        for d in j.get("depths", []):
            # Tag slot info so the median treats it like any other snapshot
            d_tagged = dict(d)
            d_tagged["slot_utc"] = f"{slot_date}T{slot_h:02d}:00:00Z"
            d_tagged["slot_hour_utc"] = slot_h
            grouped[(d["symbol"], d["venue"])].append(d_tagged)

    # Per-(sym, venue) median across snapshots
    per_pair_median = {k: median_sym_depth(v) for k, v in grouped.items()}

    # Per-symbol aggregation: pick max venue 2pct combined (best venue per symbol),
    # then sum across venues for the cross-venue tradable size
    per_sym = defaultdict(lambda: {"venues": [], "depth_2pct_combined_usd_sum": 0.0,
                                   "depth_2pct_combined_usd_max": 0.0,
                                   "n_venues": 0,
                                   "n_snapshots_per_sym": 0})
    for (sym, venue), med in per_pair_median.items():
        d2 = med["depth_2pct_combined_usd_median"]
        per_sym[sym]["venues"].append({
            "venue": venue,
            "depth_2pct_combined_usd_median": d2,
            "depth_2pct_bid_usd_median": med["depth_2pct_bid_usd_median"],
            "depth_2pct_ask_usd_median": med["depth_2pct_ask_usd_median"],
            "depth_1pct_combined_usd_median": med["depth_1pct_combined_usd_median"],
            "spread_bps_median": med["spread_bps_median"],
            "n_snapshots_used": med["n_snapshots_total"],
            "n_snapshots_with_ob": med["n_snapshots_with_ob"],
        })
        per_sym[sym]["depth_2pct_combined_usd_sum"] += d2
        per_sym[sym]["depth_2pct_combined_usd_max"] = max(
            per_sym[sym]["depth_2pct_combined_usd_max"], d2)
        per_sym[sym]["n_venues"] += 1 if d2 > 0 else 0
        per_sym[sym]["n_snapshots_per_sym"] = max(
            per_sym[sym]["n_snapshots_per_sym"], med["n_snapshots_total"])

    # Per-(sym, AUM): tradable_5d_at_10pct = depth_one_side * (5d × 10% participation)
    # We take MAX venue 2pct one-side (≈ bid OR ask side, conservative) as the
    # 'fillable in 5d' assumption per S-544 (5% pos + 10% participation + 5-day).
    # venue_capacity_aum = (max_one_side * 2 / participation / build_days / position_pct)
    # = max_combined * 2 / (0.10 * 5 * 0.05) where *2 enters because we want both sides.
    # Simplification following S-544: per-day buyable = adv * 0.10; 5-day buildable = adv * 0.5.
    # AUM at 5% position: 5-day buildable / 0.05 = adv * 10. Equivalently:
    # venue_cap_aum = max_combined / (0.10 × 5 × 0.05) = max_combined / 0.025
    # Actually: position_pct = 0.05 means each slot is 5% of book, so to fill one slot we need
    # 5% × AUM. Per day buyable per slot = one-sided depth (since we sweep both bid & ask through
    # a 5d × 10% participation cycle). So AUM_capacity = one_side * 10 (5d × 10% × 1/5%).
    # We use combined / 2 as the conservative single-side view.
    s544_baseline = {}
    for a in sleeves.get("crypto_assets", []):
        sym = a["symbol"]
        s544_baseline[sym] = {
            "asset_class": a["asset_class"],
            "adv_usd": a["adv_usd"] or 0,
            "s544_capacity_aum_usd": a["capacity_aum_usd"] or 0,
            "s544_ok_at_target": a["ok_at_target"],
            "s544_ok_at_design": a["ok_at_design"],
        }

    per_sym_cross = {}
    for sym, agg in sorted(per_sym.items()):
        max_combined = agg["depth_2pct_combined_usd_max"]
        one_side = max_combined / 2.0  # conservative
        venue_cap_aum = one_side * (BUILD_DAYS / POSITION_PCT)  # 5d/5% = 100 × one_side
        # equivalently: 5d × 10% participation buyable = 0.5 × one_side per day per venue.
        # To fill 5% slot via 10% participation over 5d on the BEST venue only.
        s5 = s544_baseline.get(sym, {})
        adv = s5.get("adv_usd") or 0
        s544_cap = s5.get("s544_capacity_aum_usd") or 0
        per_sym_cross[sym] = {
            "asset_class": s5.get("asset_class"),
            "n_venues": agg["n_venues"],
            "n_snapshots_per_sym": agg["n_snapshots_per_sym"],
            "max_venue_2pct_combined_usd": max_combined,
            "sum_venue_2pct_combined_usd": agg["depth_2pct_combined_usd_sum"],
            "venue_capacity_aum_usd": venue_cap_aum,
            "s544_adv_usd": adv,
            "s544_capacity_aum_usd": s544_cap,
            "binding": "venue" if (s544_cap == 0 or venue_cap_aum < s544_cap) and venue_cap_aum > 0 else (
                "adv" if s544_cap > 0 else "no-adv-data"),
            "venue_to_s544_ratio": (venue_cap_aum / s544_cap) if s544_cap > 0 else None,
            "venue_details": agg["venues"],
        }

    def at_aum(usd_aum):
        n_ok_venue = 0
        n_ok_adv = 0
        n_failed_venue = 0
        n_failed_adv = 0
        n_total = 0
        for sym, c in per_sym_cross.items():
            n_total += 1
            venue_ok = c["venue_capacity_aum_usd"] >= usd_aum * POSITION_PCT
            adv_ok = c["s544_capacity_aum_usd"] >= usd_aum
            if venue_ok:
                n_ok_venue += 1
            else:
                n_failed_venue += 1
            if adv_ok:
                n_ok_adv += 1
            else:
                n_failed_adv += 1
        return {
            "aum_usd": usd_aum,
            "position_pct": POSITION_PCT,
            "n_total": n_total,
            "n_ok_venue_depth": n_ok_venue,
            "n_ok_s544_adv": n_ok_adv,
            "n_failed_venue": n_failed_venue,
            "n_failed_adv": n_failed_adv,
        }

    target_verdict = at_aum(TARGET_AUM)
    design_verdict = at_aum(DESIGN_AUM)

    book_verdicts = []
    for b in sleeves.get("books", []):
        bsym = b.get("binding_symbol")
        if not bsym or bsym not in per_sym_cross:
            continue
        c = per_sym_cross[bsym]
        # venue_depth_ok uses the 5% slot size: spot[pos_pct × AUM] must be fillable in 5d at 10% participation
        # = AUM × pos_pct × 10% × 5d / one_side venue depth ≤ venue_capacity_aum (BOOK side cap)
        # We compare against one_side venue capacity (which IS the book cap, not the symbol cap).
        # Use raw AUM × pos_pct divided by 0.025 = the notional USD the venue must serve per slot.
        venue_ok_target = c["venue_capacity_aum_usd"] >= TARGET_AUM
        venue_ok_design = c["venue_capacity_aum_usd"] >= DESIGN_AUM
        binding = "venue" if (not venue_ok_design or (c["venue_to_s544_ratio"] is not None and c["venue_to_s544_ratio"] < 1.0)) else "adv"
        if c["venue_to_s544_ratio"] is None:
            binding = "adv (no adv data)"
        book_verdicts.append({
            "book": b["book"],
            "binding_symbol": bsym,
            "binding_weight": b.get("binding_weight"),
            "s544_ok_at_target": b.get("ok_at_target"),
            "s544_ok_at_design": b.get("ok_at_design"),
            "venue_depth_ok_at_target": venue_ok_target,
            "venue_depth_ok_at_design": venue_ok_design,
            "venue_to_s544_ratio": c["venue_to_s544_ratio"],
            "binding_constraint": binding,
        })

    summary = {
        "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "params": {
            "position_pct": POSITION_PCT,
            "participation_rate": PARTICIPATION,
            "build_days": BUILD_DAYS,
            "target_aum_usd": TARGET_AUM,
            "design_aum_usd": DESIGN_AUM,
        },
        "snapshots_used": snapshots_meta,
        "n_snapshots": n_snapshots,
        "venue_verdict": {
            "at_target_aum_30M": target_verdict,
            "at_design_aum_500M": design_verdict,
        },
        "s544_baseline": {
            "books_ok_at_target": sleeves.get("summary", {}).get("assets_ok_at_target"),
            "books_ok_at_design": sleeves.get("summary", {}).get("assets_ok_at_design"),
        },
        "book_verdicts": book_verdicts,
        "per_symbol": per_sym_cross,
    }
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M")
    out_path = OUT_DIR / f"t085_report_7d_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWROTE {out_path} ({out_path.stat().st_size} bytes)")
    print(f"\n@ $30M target AUM: venue {target_verdict['n_ok_venue_depth']}/{target_verdict['n_total']} OK, "
          f"S-544 ADV {target_verdict['n_ok_s544_adv']}/{target_verdict['n_total']} OK")
    print(f"@ $500M design AUM: venue {design_verdict['n_ok_venue_depth']}/{design_verdict['n_total']} OK, "
          f"S-544 ADV {design_verdict['n_ok_s544_adv']}/{design_verdict['n_total']} OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
