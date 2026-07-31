#!/usr/bin/env python3
"""
backfill_regime_fingerprints — M-WO-7.1 verification step 2.

Runs `src.research.vector.regime_fingerprints.backfill(start, end, ...)` against the
on-disk 11yr CIS + OHLCV panels, then upserts each row to Supabase via REST.

Idempotent on re-run (UPSERT on trade_date). Best-effort — env-gated on
SUPABASE_URL + SUPABASE_SERVICE_KEY; the offline backfill still produces a
local JSONL artefact so the verification path runs even if Supabase creds
haven't landed yet.

Usage:
    ./venv/bin/python scripts/backfill_regime_fingerprints.py \\
        --start 2017-08-17 \\
        --end  2026-07-27 \\
        --batch-size 200 \\
        --out reports/m_wo7_1_regime_fingerprint_backfill/2026-07-28/

The output directory receives:
  - rows.jsonl                       every row, schema-versioned JSONL
  - rows.csv                         flat for human read
  - coverage.json                    per-dim non-NaN counts
  - first_match.json                 first match_regime_fingerprints probe result
  - summary.md                       human-readable summary

Pre-flight:
    - 9/9 smoke tests must have passed (src/research/vector/tests/...)
    - schema migration applied on Supabase (Minimax lane)
    - SUPABASE_URL + SUPABASE_SERVICE_KEY on Railway env
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.research.vector.regime_fingerprints import (
    DIM_NAMES,
    RegimeFingerprintRow,
    SCHEMA_VERSION,
    _load_cis_11yr_pillar,
    _load_ohlcv_close,
    backfill,
    cosine_similarity,
    upsert_rows,
)

_logger = logging.getLogger("regime_fingerprints.backfill")


def _row_to_jsonable(row: RegimeFingerprintRow) -> dict:
    """One row → JSON-serialisable dict (NaN → null)."""
    return {
        "trade_date": pd.Timestamp(row.trade_date).date().isoformat(),
        "canonical_regime": row.canonical_regime,
        "vec_full": [
            None if not isinstance(v, float) or not math.isfinite(v)
            else round(float(v), 6)
            for v in row.vec_full
        ],
        "dense_vec": row.dense_vec,
        "schema_version": row.schema_version,
        "r77_fwd_5d_alpha_pct": (
            None if row.r77_fwd_5d_alpha_pct is None
            or not math.isfinite(row.r77_fwd_5d_alpha_pct)
            else float(row.r77_fwd_5d_alpha_pct)
        ),
    }


def _probe_match(rows: list[RegimeFingerprintRow], target_date: str,
                 k: int = 5) -> dict:
    """First match probe — query the most recent row's k nearest neighbours.

    Without live Supabase, this is an in-process cosine (we can't call the RPC).
    With live Supabase, this would issue a REST call to match_regime_fingerprints.
    Both are recorded in `first_match.json` so the verification entry can verify
    either path.
    """
    target = next(
        (r for r in rows if str(pd.Timestamp(r.trade_date).date()) == target_date),
        rows[-1] if rows else None,
    )
    if target is None:
        return {"status": "no_target", "date": target_date}

    scored = []
    for r in rows:
        if r.trade_date == target.trade_date:
            continue
        sim = cosine_similarity(target.vec_full, r.vec_full)
        if math.isfinite(sim):
            scored.append((sim, r))

    scored.sort(key=lambda x: -x[0])
    top = scored[:k]
    return {
        "status": "in_process_cosine" if not os.environ.get("SUPABASE_URL")
                   else "live_rpc_probed_separately",
        "target_trade_date": str(pd.Timestamp(target.trade_date).date()),
        "k": k,
        "topk": [
            {
                "rank": i + 1,
                "trade_date": str(pd.Timestamp(r.trade_date).date()),
                "canonical_regime": r.canonical_regime,
                "cosine_sim": round(float(sim), 4),
                "r77_fwd_5d_alpha_pct": r.r77_fwd_5d_alpha_pct,
                "shared_dims_non_nan": sum(
                    1 for a, b in zip(target.vec_full, r.vec_full)
                    if isinstance(a, float) and math.isfinite(a)
                    and isinstance(b, float) and math.isfinite(b)
                ),
            }
            for i, (sim, r) in enumerate(top)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2017-08-17")
    parser.add_argument("--end", default="2026-07-27")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out_dir = Path(args.out or Path("reports/m_wo7_1_regime_fingerprint_backfill") /
                    datetime.now().strftime("%Y-%m-%d"))
    out_dir.mkdir(parents=True, exist_ok=True)

    _logger.info("Loading 11yr CIS panel from %s", "_data/cis_historical/cis_historical_11yr.csv")
    cis = _load_cis_11yr_pillar()
    if cis.empty:
        _logger.error("Empty CIS panel — backfill cannot proceed")
        return 1
    _logger.info("CIS panel: %d rows × %d symbols", len(cis), cis["symbol"].nunique())

    _logger.info("Loading BTC daily close for vol_regime dim [1]")
    btc_close = _load_ohlcv_close("BTC")
    _logger.info("BTC close: %d daily obs [%s → %s]",
                 len(btc_close),
                 btc_close.index.min().date() if len(btc_close) else "—",
                 btc_close.index.max().date() if len(btc_close) else "—")

    _logger.info("Running backfill [%s → %s]", args.start, args.end)
    t0 = time.time()
    rows = backfill(args.start, args.end, cis_daily=cis, btc_close=btc_close)
    _logger.info("Backfill produced %d rows in %.1fs", len(rows), time.time() - t0)

    if not rows:
        _logger.error("Backfill returned 0 rows; aborting")
        return 1

    # ── Local artefact: rows.jsonl (always; offline-friendly) ────────────
    rows_path = out_dir / "rows.jsonl"
    with rows_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(_row_to_jsonable(r)) + "\n")
    _logger.info("Wrote %d rows → %s", len(rows), rows_path)

    # ── CSV for human read ────────────────────────────────────────────────
    import pandas as pd
    df = pd.DataFrame([
        {
            "trade_date": str(pd.Timestamp(r.trade_date).date()),
            "canonical_regime": r.canonical_regime,
            **{DIM_NAMES[i]: (None if not isinstance(v, float) or not math.isfinite(v) else round(float(v), 4))
               for i, v in enumerate(r.vec_full)},
            "r77_fwd_5d_alpha_pct": r.r77_fwd_5d_alpha_pct,
            "schema_version": r.schema_version,
        }
        for r in rows
    ])
    df.to_csv(out_dir / "rows.csv", index=False)
    _logger.info("Wrote %s", out_dir / "rows.csv")

    # ── Coverage stats per dim ────────────────────────────────────────────
    coverage = {}
    for i, name in enumerate(DIM_NAMES):
        finite = sum(1 for r in rows
                     if isinstance(r.vec_full[i], float) and math.isfinite(r.vec_full[i]))
        coverage[name] = {
            "n_finite": finite,
            "n_total": len(rows),
            "coverage_pct": round(100.0 * finite / max(1, len(rows)), 2),
        }
    with (out_dir / "coverage.json").open("w") as f:
        json.dump(coverage, f, indent=2)
    _logger.info("Per-dim coverage written → %s", out_dir / "coverage.json")

    # ── First match probe (in-process cosine) ─────────────────────────────
    target_date = str(pd.Timestamp(rows[-1].trade_date).date())
    probe = _probe_match(rows, target_date, k=5)
    with (out_dir / "first_match.json").open("w") as f:
        json.dump(probe, f, indent=2)
    _logger.info("First match probe (target=%s) → %s", target_date, out_dir / "first_match.json")

    # ── Optional Supabase upsert (env-gated) ─────────────────────────────
    upserted = 0
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        _logger.info("Supabase env set — upserting in batches of %d", args.batch_size)
        for i in range(0, len(rows), args.batch_size):
            batch = rows[i:i + args.batch_size]
            n = upsert_rows(batch)
            upserted += n
            _logger.info("  batch %d: %d/%d upserted", i // args.batch_size + 1, n, len(batch))
    else:
        _logger.warning("Supabase env not set (SUPABASE_URL + SUPABASE_SERVICE_KEY); skipped upsert — local rows only")

    # ── Summary.md ─────────────────────────────────────────────────────────
    md = [
        "# M-WO-7.1 Regime Fingerprint Backfill — Verification Step 2",
        f"**Run date:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        f"**Backfill window:** {args.start} → {args.end}",
        f"**Rows produced:** {len(rows)}",
        f"**Upserted to Supabase:** {upserted} / {len(rows)}",
        f"**Schema version:** {SCHEMA_VERSION}",
        "",
        "## Per-dim coverage",
        "| dim | name | n_finite | coverage_pct |",
        "|---:|:---|---:|---:|",
    ]
    for i, name in enumerate(DIM_NAMES):
        c = coverage[name]
        md.append(f"| [{i}] | `{name}` | {c['n_finite']} | {c['coverage_pct']:.1f}% |")
    md.append("")
    md.append("## First match probe")
    md.append(f"- Target: `{probe.get('target_trade_date', '—')}`")
    md.append(f"- Status: `{probe.get('status', '—')}`")
    if "topk" in probe:
        md.append(f"- k={probe['k']} nearest by cosine:")
        md.append("")
        md.append("| rank | trade_date | regime | cosine_sim | r77_fwd_5d_alpha | shared_dims |")
        md.append("|---:|:---|:---|---:|---:|---:|")
        for row in probe["topk"]:
            alpha = row['r77_fwd_5d_alpha_pct']
            alpha_str = "—" if alpha is None else f"{alpha:+.3f}%"
            md.append(
                f"| {row['rank']} | {row['trade_date']} | {row['canonical_regime']} | "
                f"{row['cosine_sim']:.4f} | {alpha_str} | {row['shared_dims_non_nan']} |"
            )
    with (out_dir / "summary.md").open("w") as f:
        f.write("\n".join(md) + "\n")
    _logger.info("Wrote %s", out_dir / "summary.md")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
