#!/usr/bin/env python3
"""
CIS Historical Reconstruction — Ingest
=======================================
Reads `cis_historical_11yr.csv` (output of `reconstruct_cis_history.py --local-output`)
and bulk-loads it into either:

  1. The local SQLite `cis_history` table at
     /Volumes/CometCloudAI/cometcloud-local/_data/cis_history.db
     (Mac Mini side — Minimax-owned; ingest from Cowork via FUSE works as it's read-write)

  2. The Supabase `cis_scores` table at $SUPABASE_URL
     (requires SUPABASE_SERVICE_KEY — anon key is RLS-blocked from write)

  3. Both — default if both are available.

The CSV is header-less in the build output (the build pre-touches the file and
Path.exists() is True at first append). This script detects that case and prepends
the canonical header before parsing.

CLI usage:
    python3 scripts/cis_historical_ingest.py --dry-run           # preview only
    python3 scripts/cis_historical_ingest.py --target local      # local SQLite
    python3 scripts/cis_historical_ingest.py --target supabase   # Supabase
    python3 scripts/cis_historical_ingest.py                     # both, if available

The local ingest uses INSERT OR REPLACE keyed on (run_id, asset, timestamp) so
re-runs are idempotent — useful when rebuilding after a partial failure.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# Canonical CSV column order — sourced from src/research/data_align/cis_history_schema
# (single source of truth — Jazz §DATA-ALIGN directive 2026-07-24).
from src.research.data_align.cis_history_schema import CSV_COLUMNS  # noqa: E402, F401

LOCAL_DB = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history.db")
LOCAL_TABLE = "cis_history"

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")


# ── CSV reader (header-tolerant) ───────────────────────────────────────────────

def read_csv_rows(csv_path: Path) -> list[dict]:
    """Read all rows as dicts; prepend canonical header if the file lacks one."""
    with csv_path.open("r", newline="") as f:
        first = f.readline().strip()
        f.seek(0)
        if first.split(",")[0] != "symbol":
            reader = csv.DictReader(f, fieldnames=CSV_COLUMNS)
        else:
            reader = csv.DictReader(f)
        return list(reader)


def derive_run_id(csv_path: Path) -> str:
    """Derive a deterministic run_id from filename + mtime — idempotency key for local ingest."""
    stat = csv_path.stat()
    return f"historical_11yr_{datetime.fromtimestamp(stat.st_mtime).strftime('%Y%m%d_%H%M%S')}"


def to_local_row(csv_row: dict, run_id: str) -> dict:
    """Map CSV columns → local cis_history table schema."""
    # recommended_weight: signal → weight proxy (matches base portfolio sizing used in Quant GP)
    weight_map = {
        "STRONG OUTPERFORM": 0.05,
        "OUTPERFORM":        0.03,
        "NEUTRAL":           0.015,
        "UNDERPERFORM":      0.005,
        "UNDERWEIGHT":       0.0,
    }
    signal = csv_row.get("signal", "NEUTRAL")
    return {
        "run_id":             run_id,
        "timestamp":          csv_row["recorded_at"],
        "asset":              csv_row["symbol"],
        "asset_name":         csv_row.get("name") or csv_row["symbol"],
        "asset_class":        csv_row.get("asset_class") or "Crypto",
        "cis_score":          float(csv_row["score"]) if csv_row["score"] else None,
        "grade":              csv_row.get("grade"),
        "signal":             signal,
        "recommended_weight": weight_map.get(signal, 0.015),
        "macro_regime":       csv_row.get("macro_regime"),
        "las":                float(csv_row["las"]) if csv_row.get("las") else None,
        "source":             csv_row.get("source", "historical_reconstruction"),
        "data_tier":          csv_row.get("data_tier"),
    }


# ── Local SQLite ingest ────────────────────────────────────────────────────────

def ingest_local(csv_path: Path, dry_run: bool) -> dict:
    """Bulk insert into local cis_history.db. Idempotent on (run_id, asset, timestamp)."""
    rows = read_csv_rows(csv_path)
    run_id = derive_run_id(csv_path)
    print(f"  CSV rows: {len(rows)} | run_id: {run_id}")

    if not LOCAL_DB.exists():
        return {"status": "skipped", "reason": f"local DB not found at {LOCAL_DB}",
                "rows": len(rows)}

    if dry_run:
        sample = to_local_row(rows[0], run_id)
        print(f"  [dry-run] sample row → {LOCAL_TABLE}: {sample}")
        return {"status": "dry_run", "rows": len(rows), "sample": sample}

    con = sqlite3.connect(str(LOCAL_DB))
    try:
        # Schema check — confirm required columns exist (create migration for new ones)
        existing_cols = {c[1] for c in con.execute(f"PRAGMA table_info({LOCAL_TABLE})").fetchall()}

        # Migration: add optional new columns if missing (idempotent — try/except per col)
        for col, decl in [
            ("macro_regime", "TEXT"),
            ("las",          "REAL"),
            ("source",       "TEXT"),
            ("data_tier",    "TEXT"),
        ]:
            if col not in existing_cols:
                try:
                    con.execute(f"ALTER TABLE {LOCAL_TABLE} ADD COLUMN {col} {decl}")
                    print(f"  [migrate] added column {col} {decl}")
                except Exception as e:
                    print(f"  [migrate] {col} add failed: {e}")

        # Re-read after migration
        existing_cols = {c[1] for c in con.execute(f"PRAGMA table_info({LOCAL_TABLE})").fetchall()}
        needed = {"run_id", "timestamp", "asset", "asset_name", "asset_class",
                  "cis_score", "grade", "signal", "recommended_weight"}
        missing = needed - existing_cols
        if missing:
            return {"status": "schema_mismatch",
                    "missing_columns": sorted(missing),
                    "existing_columns": sorted(existing_cols),
                    "rows": len(rows)}

        # Idempotency: delete prior rows from this run_id first
        deleted = con.execute(
            f"DELETE FROM {LOCAL_TABLE} WHERE run_id = ?", (run_id,)).rowcount
        print(f"  cleared {deleted} prior rows with same run_id (idempotent re-run)")

        # Insert in batches
        BATCH = 500
        inserted = 0
        cols = ["run_id", "timestamp", "asset", "asset_name", "asset_class",
                "cis_score", "grade", "signal", "recommended_weight",
                "macro_regime", "las", "source", "data_tier"]
        placeholders = ", ".join(["?"] * len(cols))
        insert_sql = (f"INSERT INTO {LOCAL_TABLE} ({', '.join(cols)}) "
                      f"VALUES ({placeholders})")
        for i in range(0, len(rows), BATCH):
            batch = [tuple(to_local_row(r, run_id).get(c) for c in cols) for r in rows[i:i + BATCH]]
            con.executemany(insert_sql, batch)
            inserted += len(batch)
        con.commit()

        # Per-asset counts (for the report)
        per_asset = con.execute(
            f"SELECT asset, COUNT(*) FROM {LOCAL_TABLE} WHERE run_id = ? GROUP BY asset",
            (run_id,)).fetchall()
        return {"status": "ok", "rows": inserted, "run_id": run_id,
                "per_asset": {a: n for a, n in per_asset}}
    finally:
        con.close()


# ── Supabase ingest ────────────────────────────────────────────────────────────

async def ingest_supabase(csv_path: Path, dry_run: bool) -> dict:
    """Bulk insert into Supabase cis_scores via REST POST."""
    rows = read_csv_rows(csv_path)
    print(f"  CSV rows: {len(rows)}")

    if not SUPABASE_URL or not SUPABASE_KEY or SUPABASE_KEY == "your-anon-key-here":
        return {"status": "skipped",
                "reason": "Supabase creds missing or placeholder (need SUPABASE_SERVICE_KEY)",
                "rows": len(rows)}

    if dry_run:
        print(f"  [dry-run] would POST {len(rows)} rows to {SUPABASE_URL}/rest/v1/cis_scores")
        return {"status": "dry_run", "rows": len(rows)}

    # Supabase requires the asset_class column for the index — keep schema-true
    out_rows = []
    for r in rows:
        out_rows.append({
            "symbol":         r["symbol"],
            "name":           r.get("name") or r["symbol"],
            "score":          _safe_float(r.get("score")),
            "raw_cis_score":  _safe_float(r.get("raw_cis_score")),
            "grade":          r.get("grade"),
            "signal":         r.get("signal"),
            "pillar_f":       _safe_float(r.get("pillar_f")),
            "pillar_m":       _safe_float(r.get("pillar_m")),
            "pillar_o":       _safe_float(r.get("pillar_o")),
            "pillar_s":       _safe_float(r.get("pillar_s")),
            "pillar_a":       _safe_float(r.get("pillar_a")),
            "asset_class":    r.get("asset_class"),
            "macro_regime":   r.get("macro_regime"),
            "data_tier":      2 if r.get("data_tier") == "T2_historical" else None,
            "las":            _safe_float(r.get("las")),
            "confidence":     _safe_float(r.get("confidence")),
            "score_delta":    _safe_float(r.get("score_delta")),
            "score_zscore":   _safe_float(r.get("score_zscore")),
            "source":         r.get("source"),
            "recorded_at":    r.get("recorded_at"),
        })

    BATCH = 100  # Supabase URL length + RLS check overhead
    async with httpx.AsyncClient(timeout=60) as client:
        inserted = 0
        for i in range(0, len(out_rows), BATCH):
            batch = out_rows[i:i + BATCH]
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/cis_scores",
                json=batch,
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
            )
            if r.status_code in (200, 201, 204):
                inserted += len(batch)
            else:
                print(f"  [Supabase] batch {i // BATCH} failed: {r.status_code} — {r.text[:200]}")
                return {"status": "partial", "rows_inserted": inserted,
                        "rows_total": len(out_rows), "error": r.text[:500]}
            if (i // BATCH) % 10 == 0:
                print(f"  …{inserted}/{len(out_rows)} inserted")
    return {"status": "ok", "rows_inserted": inserted, "rows_total": len(out_rows)}


def _safe_float(v) -> float | None:
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CIS Historical Reconstruction — Ingest")
    parser.add_argument("--csv", type=str,
                        default="_data/cis_historical/cis_historical_11yr.csv",
                        help="Path to the CSV output of reconstruct_cis_history.py")
    parser.add_argument("--target", choices=["local", "supabase", "both"], default="both")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no writes")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path.resolve()}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  CIS Historical Ingest")
    print(f"  CSV: {csv_path} ({csv_path.stat().st_size / 1024:.1f} KB)")
    print(f"  Target: {args.target} | Dry run: {args.dry_run}")
    print(f"{'='*60}\n")

    results = {}

    if args.target in ("local", "both"):
        print("[1/2] Local SQLite ingest…")
        results["local"] = ingest_local(csv_path, args.dry_run)
        print(f"  → {results['local']}\n")

    if args.target in ("supabase", "both"):
        print("[2/2] Supabase ingest…")
        results["supabase"] = asyncio.run(ingest_supabase(csv_path, args.dry_run))
        print(f"  → {results['supabase']}\n")

    print("Summary:")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
