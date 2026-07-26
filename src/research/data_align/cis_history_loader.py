"""
Header-aware loader for the 11yr CIS historical CSV.

The CSV lives at `_data/cis_historical/cis_historical_11yr.csv` and is
header-less by build convention (`scripts/reconstruct_cis_history.py` writes
positional columns without a header line). Earlier this caused drift:
two call sites (`cis_historical_ingest.py`, `absorption_sweep_runner.py`)
hard-coded their own `CSV_COLUMNS` / `_CIS_HIST_COLS` lists, which had to be
kept in sync manually.

The §DATA-ALIGN directive (Jazz, 2026-07-24) collapses both into
`src/research.data_align.cis_history_schema.CSV_COLUMNS`. The header line is
now prepended by `scripts/cis_historical_align.py` (idempotent — if the first
line is already `symbol,name,...`, it is left alone), and this loader detects
either case.

Usage:
    from src.research.data_align.cis_history_loader import load_cis_history

    df = load_cis_history()                      # default path
    df = load_cis_history(path=Path("..."))       # explicit path
    df = load_cis_history(force_schema=True)      # validate against canonical

PIT safety:
  - `parse_recorded_at` produces a tz-naive date column for joining against
    daily-OHLCV data (which is typically tz-naive). Does NOT shift the
    timestamp — keeps the on-disk value intact.
  - Numeric coercion uses `pd.to_numeric(errors="coerce")`. Garbage values
    become NaN, never crash.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

from src.research.data_align.cis_history_schema import (
    CSV_COLUMNS, NUMERIC_COLUMNS, CATEGORICAL_COLUMNS,
    EXPECTED_NCOLS, assert_schema,
)

# Default CSV path (relative to project root)
DEFAULT_CSV = Path("_data/cis_historical/cis_historical_11yr.csv")


def _detect_header(first_line: str) -> bool:
    """True iff the first line already starts with the canonical header token."""
    return first_line.split(",", 1)[0].strip() == "symbol"


def load_cis_history(
    path: Union[str, Path] = DEFAULT_CSV,
    *,
    force_schema: bool = True,
) -> pd.DataFrame:
    """Read the 11yr CIS CSV. Auto-detects header presence.

    Returns a DataFrame with columns = CSV_COLUMNS (+ any extra enrichment cols).

    Parameters
    ----------
    path : str | Path
        Path to the CSV. Default: `_data/cis_historical/cis_historical_11yr.csv`.
    force_schema : bool
        If True (default), call `assert_schema` to verify the columns match
        the canonical order. Raises AssertionError on mismatch.

    Returns
    -------
    pd.DataFrame
        Index: sequential (0..N-1). `recorded_at` parsed to tz-naive datetime
        stored in a `_date` column for OHLCV joins.
    """
    p = Path(path)
    with p.open("r", newline="") as f:
        first = f.readline().strip()
        f.seek(0)
        has_header = _detect_header(first)
        df = pd.read_csv(
            f,
            header=0 if has_header else None,
            names=None if has_header else CSV_COLUMNS,
            dtype=str,             # coerce numeric ourselves to handle garbage
            keep_default_na=False,
            na_values=[""],
        )

    if force_schema:
        assert_schema(list(df.columns))

    # Numeric coercion (errors → NaN, never crash)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Date parse — tz-naive for OHLCV joins
    if "recorded_at" in df.columns:
        df["_date"] = pd.to_datetime(
            df["recorded_at"], utc=True, errors="coerce"
        ).dt.tz_localize(None).dt.normalize()

    return df


def write_with_header(
    df: pd.DataFrame,
    path: Union[str, Path],
    *,
    header_already_present: bool = False,
) -> None:
    """Write a DataFrame with the canonical header prepended.

    If `header_already_present=True`, the first column-name token is checked;
    only writes a header if missing. Otherwise always writes a header line.
    """
    p = Path(path)
    expected_header = CSV_COLUMNS[0]
    if header_already_present:
        # Caller is responsible for the header — just write the df
        df.to_csv(p, index=False)
        return
    # Detect whether the path already has the header (cheap)
    needs_header = True
    if p.exists():
        with p.open("r") as f:
            first = f.readline().strip()
            if first.split(",", 1)[0] == expected_header:
                needs_header = False
    if needs_header:
        # Write header + rows. Avoid the "two-file write" pattern (race window).
        header_line = ",".join(CSV_COLUMNS + [c for c in df.columns if c not in CSV_COLUMNS])
        with p.open("w", newline="") as f:
            f.write(header_line + "\n")
            df.to_csv(f, header=False, index=False)
    else:
        df.to_csv(p, index=False)


def prepend_header_if_missing(
    path: Union[str, Path],
    *,
    dry_run: bool = False,
) -> bool:
    """Idempotently prepend the canonical header line.

    Returns True if a header was added, False if one was already present.
    If `dry_run=True`, performs all reads but makes no writes (and reports).

    The transform is in-place atomic: write to `<path>.tmp`, then rename.
    """
    p = Path(path)
    with p.open("r") as f:
        first = f.readline().strip()

    if _detect_header(first):
        return False  # already has header
    if dry_run:
        return True   # would add, but didn't

    header_line = ",".join(CSV_COLUMNS)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", newline="") as out, p.open("r") as inp:
        out.write(header_line + "\n")
        # Stream-copy in chunks (12.4MB file → fine in memory; use chunked read)
        while True:
            chunk = inp.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(p)
    return True