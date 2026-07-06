#!/usr/bin/env python3
"""
D3 — Dune holder-concentration fetcher (CLI wrapper around holder_concentration.py).

Pulls per-day holder metrics (n_holders, HHI, top10) from a saved Dune query,
runs the diffusion-curve stage_series() to derive (stage, disp_accel, chuquan),
and writes per-token JSON to the local warehouse for Seth's cause_proximity
adapter to read.

The plug is here: pass --query-id when Jazz ships it from the Dune UI; until
then --dry-run validates the full pipeline against synthetic data.

Output layout:
  _data/dune_holders/
    raw/<query_id>_<token_addr>_<start>_<end>.json   ← Dune API response (cache)
    processed/<token_addr>.json                       ← stage + alert per date
    index.json                                        ← list of processed tokens

Usage:
  # Once Jazz hands over the query_id:
  DUNE_API_KEY=... python3 scripts/fetch_holder_concentration.py \
      --query-id 12345 --token 0xdAC17F958D2ee523a2206206994597C13D831ec7 \
      --start 2024-01-01

  # Or batch from a token list:
  python3 scripts/fetch_holder_concentration.py --query-id 12345 --tokens-file tokens.txt

  # Dry-run: validate pipeline without Dune (synthetic concentrated→dispersed)
  python3 scripts/fetch_holder_concentration.py --dry-run

  # Inspect a processed token (after fetch)
  python3 scripts/fetch_holder_concentration.py --show 0xdAC17F958D2ee523a2206206994597C13D831ec7
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Repo-relative import so this works both via Cowork + on the Mac drive
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

from holder_concentration import (  # noqa: E402
    dune_holder_metrics,
    snapshot_metrics,
    stage_series,
)


# ════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════

OUTPUT_ROOT = Path(
    os.getenv(
        "DUNE_HOLDERS_DIR",
        "/Volumes/CometCloudAI/cometcloud-local/_data/dune_holders/",
    )
)
RAW_DIR = OUTPUT_ROOT / "raw"
PROCESSED_DIR = OUTPUT_ROOT / "processed"
INDEX_FILE = OUTPUT_ROOT / "index.json"

DUNE_KEY = os.getenv("DUNE_API_KEY", "")
DUNE_QUERY_ID_DEFAULT = os.getenv("DUNE_QUERY_ID_HOLDERS", "")  # one-shot config

DUNE_BASE = "https://api.dune.com/api/v1"
REQUEST_TIMEOUT_S = 30


# ════════════════════════════════════════════════════════════════════════════
# IO HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _ensure_dirs() -> None:
    """Create the warehouse dirs (idempotent)."""
    for d in (OUTPUT_ROOT, RAW_DIR, PROCESSED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    """Read the index file; returns dict of {token_addr: {fetched_at, query_id, n_dates}}."""
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_index(idx: dict) -> None:
    INDEX_FILE.write_text(json.dumps(idx, indent=2, sort_keys=True))


def _cache_path(query_id: int, token_addr: str, start: str, end: str) -> Path:
    """Stable path for the raw Dune response (so reruns hit cache)."""
    name = f"q{query_id}_{token_addr}_{start}_{end}.json"
    return RAW_DIR / name


def _processed_path(token_addr: str) -> Path:
    return PROCESSED_DIR / f"{token_addr}.json"


def _write_json(path: Path, payload: dict) -> None:
    """Atomic write (tmp + rename) so partial files never appear."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    tmp.rename(path)


# ════════════════════════════════════════════════════════════════════════════
# FETCH
# ════════════════════════════════════════════════════════════════════════════

def fetch_one_token(
    query_id: int,
    token_addr: str,
    start: str,
    end: str,
    *,
    use_cache: bool = True,
    poll_interval_s: int = 5,
    timeout_s: int = 300,
) -> "pd.DataFrame":
    """Fetch a single token's per-day concentration metrics from Dune.

    Returns a DataFrame indexed by `day` with cols: n_holders, hhi, top10.
    Caches the raw API response to RAW_DIR so reruns skip the Dune round-trip.
    Raises on timeout or API failure.
    """
    import httpx
    import pandas as pd

    cache_file = _cache_path(query_id, token_addr, start, end)
    if use_cache and cache_file.exists():
        print(f"  [cache hit] {cache_file.name}")
        rows = json.loads(cache_file.read_text())
    else:
        if not DUNE_KEY:
            raise SystemExit("ERROR: DUNE_API_KEY env var not set. Cannot call Dune.")
        headers = {"X-Dune-API-Key": DUNE_KEY}
        body = {
            "query_parameters": {
                "token": token_addr,
                "start_date": start,
                "end_date": end,
            }
        }
        print(f"  [dune exec] query_id={query_id} token={token_addr[:10]}…")
        r = httpx.post(
            f"{DUNE_BASE}/query/{query_id}/execute",
            headers=headers, json=body, timeout=REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        eid = r.json()["execution_id"]
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            sr = httpx.get(
                f"{DUNE_BASE}/execution/{eid}/status",
                headers=headers, timeout=REQUEST_TIMEOUT_S,
            )
            sr.raise_for_status()
            state = sr.json().get("state")
            if state == "QUERY_STATE_COMPLETED":
                rr = httpx.get(
                    f"{DUNE_BASE}/execution/{eid}/results",
                    headers=headers, timeout=REQUEST_TIMEOUT_S,
                )
                rr.raise_for_status()
                rows = rr.json()["result"]["rows"]
                # Cache for replay
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                _write_json(cache_file, {"execution_id": eid, "rows": rows})
                print(f"  [dune ok]   {len(rows)} rows in {time.time()-t0:.1f}s, cached")
                break
            if state == "QUERY_STATE_FAILED":
                raise RuntimeError(f"Dune execution failed (eid={eid})")
            time.sleep(poll_interval_s)
        else:
            raise TimeoutError(f"Dune execution timed out after {timeout_s}s (eid={eid})")

    if not rows:
        raise RuntimeError(f"Dune returned 0 rows for {token_addr} — check params / query")

    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    return df.set_index("day").sort_index()


def _load_local_ohlcv_for_token(token_addr: str) -> "pd.DataFrame | None":
    """Try to load this token's OHLCV from the local warehouse. Returns None if
    the OHLCV pipeline hasn't populated data for this token yet (the common case
    while §11.8 OHLCV pipeline is still P1) — caller treats None as "no OHLCV,
    pre-出圈 falls back to 'pre'".

    Expected layout (once the OHLCV pipeline lands):
      /Volumes/CometCloudAI/cometcloud-local/_data/ohlcv/<addr>.csv
        columns: date, open, high, low, close, volume  (date as YYYY-MM-DD)

    Resolution order:
      1. By token address (lowercased, with/without 0x)
      2. (no other resolution — the address is the only stable key)

    The function NEVER raises. A missing/malformed file → None → stage_series()
    falls back to the 3-season contract (back-compat).
    """
    import pandas as pd

    ohlcv_root = Path(
        os.getenv(
            "OHLCV_DIR",
            "/Volumes/CometCloudAI/cometcloud-local/_data/ohlcv/",
        )
    )
    if not ohlcv_root.exists():
        return None
    addr_lc = (token_addr or "").lower().replace("0x", "").strip()
    if not addr_lc:
        return None
    # Try a few naming variants — the pipeline might emit "0x<addr>" or just "<addr>".
    candidates = [
        ohlcv_root / f"0x{addr_lc}.csv",
        ohlcv_root / f"{addr_lc}.csv",
        ohlcv_root / f"0x{addr_lc}.parquet",
        ohlcv_root / f"{addr_lc}.parquet",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.suffix == ".parquet":
                df = pd.read_parquet(path)
            else:
                df = pd.read_csv(path)
            # normalize columns
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
            elif "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp").sort_index()
            if "volume" not in df.columns:
                return None
            return df[["volume"]]
        except Exception:
            return None
    return None


def process_and_write(df, token_addr: str, query_id: int,
                      ohlcv: "pd.DataFrame | None" = None,
                      *, auto_load_ohlcv: bool = True) -> dict:
    """Run stage_series() on the concentration DF, write JSON, update index.

    Args:
        df: concentration metrics from Dune (index=date, cols=hhi/n_holders/top10).
        token_addr: 0x... address (used for JSON path + OHLCV lookup).
        query_id: Dune saved query id.
        ohlcv: optional OHLCV DataFrame (index=date, col=volume). When provided,
            stage_series() emits the full 7-season Wyckoff lifecycle in the
            pre-出圈 window. When None AND auto_load_ohlcv=True (default), tries
            to read it from the local warehouse at OHLCV_DIR. Falls back to the
            3-season contract ("pre"/"momentum"/"stale") if both are absent.
        auto_load_ohlcv: if True (default) and ohlcv is None, attempt the
            warehouse lookup. Set False to skip the lookup (e.g. in tests).

    Returns the dict written to index.json for this token.
    """
    if ohlcv is None and auto_load_ohlcv:
        ohlcv = _load_local_ohlcv_for_token(token_addr)
    st = stage_series(df, ohlcv=ohlcv)
    out = df.join(st)
    payload = {
        "token": token_addr,
        "query_id": query_id,
        "n_dates": int(len(out)),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dates": {
            d.strftime("%Y-%m-%d"): {
                "n_holders":         int(out.loc[d, "n_holders"]),
                "hhi":               float(out.loc[d, "hhi"]),
                "top10":             float(out.loc[d, "top10"]) if "top10" in out.columns else None,
                "stage":             round(float(out.loc[d, "stage"]), 4),
                "disp_accel":        round(float(out.loc[d, "disp_accel"]), 4),
                "chuquan":           bool(out.loc[d, "chuquan"]),
                "days_since_chuquan": int(out.loc[d, "days_since_chuquan"]),
                "season":            str(out.loc[d, "season"]),
            }
            for d in out.index
        },
    }
    _write_json(_processed_path(token_addr), payload)

    # Update index
    idx = _load_index()
    idx[token_addr] = {
        "query_id":   query_id,
        "fetched_at": payload["fetched_at"],
        "n_dates":    payload["n_dates"],
        "path":       str(_processed_path(token_addr).relative_to(OUTPUT_ROOT)),
    }
    _save_index(idx)
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# DRY-RUN (synthetic data)
# ═══════════════════════════════════════════════════════════════════════════

def dry_run_synthetic(token_addr: str = "0xSYNTHETIC", n_weeks: int = 80,
                      *, include_ohlcv: bool = True) -> dict:
    """Generate a synthetic concentrated→dispersed transition (mirrors the
    selftest in holder_concentration.py) and run the full pipeline end-to-end.

    This is what proves the plug works BEFORE Jazz hands over the Dune query_id.
    No network calls; safe to run anywhere.

    By default (`include_ohlcv=True`) the synthetic ALSO generates a 7-phase
    OHLCV feed so the full Wyckoff/VSA lifecycle is demonstrated end-to-end:
    capitulation → dry_up → spring_test → early_markup → pre → momentum → stale.
    Pass --no-ohlcv on the CLI to collapse the pre-出圈 window to "pre"
    (the back-compat path).
    """
    import numpy as np
    import pandas as pd

    dates = pd.date_range("2025-01-01", periods=n_weeks, freq="W")
    rows = []
    rng = np.random.default_rng(2026_07_06)
    MA30_BASE = 1_000.0
    for i, dt in enumerate(dates):
        # Phase label (same 7-phase schema as holder_concentration._selftest)
        if include_ohlcv:
            if 0 <= i <= 14:    phase = "steady"
            elif 15 <= i <= 17: phase = "capitulation"
            elif 18 <= i <= 25: phase = "dry_up"
            elif 26 <= i <= 28: phase = "spring"
            elif 29 <= i <= 34: phase = "markup"
            elif 35 <= i <= 44: phase = "steady2"
            else:               phase = "post_chuquan"
        else:
            phase = "flat"
        whales = [1000, 800, 600, 400, 300]            # fixed whale stock
        base_growth = int(10 * 1.06 ** i)
        if include_ohlcv:
            holder_mult = {
                "steady":       1.00, "capitulation": 0.55, "dry_up":  1.00,
                "spring":       0.98, "markup":       1.05, "steady2": 1.02,
                "post_chuquan": 1.10, "flat":         1.00,
            }[phase]
        else:
            holder_mult = 1.00
        n_small = max(5, int(base_growth * holder_mult))
        # chuquan fires around wk 30 when include_ohlcv (post_chuquan phase);
        # otherwise at the same point for back-compat
        flood = 6000 if (include_ohlcv and phase == "post_chuquan") or (
            not include_ohlcv and i == 30) else 0
        smalls = list(rng.exponential(2.0, n_small))
        m = snapshot_metrics(whales + smalls)
        m["date"] = dt
        if include_ohlcv:
            vol_mult = {
                "steady":       1.0, "capitulation": 3.2, "dry_up":     0.4,
                "spring":       0.7, "markup":       1.2, "steady2":    0.9,
                "post_chuquan": 1.8, "flat":         1.0,
            }[phase]
            m["volume"] = max(50.0, MA30_BASE * vol_mult + rng.normal(0, 80))
        rows.append(m)
    df = pd.DataFrame(rows).set_index("date")

    if include_ohlcv:
        ohlcv = df[["volume"]].copy()
        holder_df = df.drop(columns=["volume"])
    else:
        ohlcv = None
        holder_df = df

    # Process through the real stage_series() — no shortcuts
    payload = process_and_write(holder_df, token_addr, query_id=0, ohlcv=ohlcv,
                                auto_load_ohlcv=False)

    # Pretty-print summary so the operator sees what real output will look like
    st = stage_series(holder_df, ohlcv=ohlcv)
    out = holder_df.join(st)
    print(f"\n  [dry-run] synthetic token: 5 whales → mass retail flood")
    print(f"  [dry-run] {len(out)} weekly snapshots processed"
          + (" (WITH OHLCV — full 7-season lifecycle)" if include_ohlcv else
             " (no OHLCV — back-compat 3-season)"))

    if include_ohlcv:
        # show the full lifecycle
        print(f"\n  {'date':12} {'n_holders':>10} {'vol_ratio':>10} {'stage':>6} "
              f"{'chuquan':>8} {'days':>5} {'season':>14}")
        # every 3rd row of each phase window, plus key transitions
        sample_idx = list(range(0, 15, 3)) + list(range(15, 18)) \
                   + list(range(18, 26, 2)) + list(range(26, 29)) \
                   + list(range(29, 35, 2)) + [35, 40, 44, 45, 50, 54, 55, 59]
        sample_idx = sorted(set(i for i in sample_idx if i < len(out)))
        # The stage output dropped the 'volume' column (to avoid columns-overlap
        # on the join); read it from the OHLCV frame directly for display.
        ohlcv_volume = ohlcv["volume"] if ohlcv is not None else None
        for i in sample_idx:
            d = out.index[i]
            if ohlcv_volume is not None:
                vol_now = float(ohlcv_volume.iloc[i])
                vol_ma30 = float(ohlcv_volume.iloc[max(0, i - 30):i].mean()) if i >= 1 else vol_now
                vr = vol_now / vol_ma30 if vol_ma30 > 0 else 1.0
            else:
                vr = 1.0
            flag = "⚠ YES" if bool(out["chuquan"].iloc[i]) else "  -  "
            days_since = int(out["days_since_chuquan"].iloc[i])
            days_str = "  - " if days_since < 0 else f"{days_since:>4}d"
            print(f"  {d.strftime('%Y-%m-%d'):12} "
                  f"{int(out['n_holders'].iloc[i]):>10} "
                  f"{vr:>10.2f} "
                  f"{out['stage'].iloc[i]:>6.3f} "
                  f"{flag:>8} "
                  f"{days_str:>5} "
                  f"{out['season'].iloc[i]:>14}")
    else:
        print(f"\n  {'date':12} {'n_holders':>10} {'hhi':>8} {'stage':>6} "
              f"{'disp_accel':>11} {'chuquan':>8} {'days':>5} {'season':>9}")
        for d in out.index[::4]:  # every 4 weeks
            flag = "⚠ YES" if bool(out.loc[d, "chuquan"]) else "  -  "
            season = str(out.loc[d, "season"])
            days_since = int(out.loc[d, "days_since_chuquan"])
            days_str = "  - " if days_since < 0 else f"{days_since:>4}d"
            print(f"  {d.strftime('%Y-%m-%d'):12} "
                  f"{int(out.loc[d, 'n_holders']):>10} "
                  f"{out.loc[d, 'hhi']:>8.4f} "
                  f"{out.loc[d, 'stage']:>6.3f} "
                  f"{out.loc[d, 'disp_accel']:>11.3f} "
                  f"{flag:>8} "
                  f"{days_str:>5} "
                  f"{season:>9}")

    first_alert = out[out["chuquan"]].index.min()
    print(f"\n  [dry-run] first 出圈 alert: "
          f"{first_alert.strftime('%Y-%m-%d') if pd.notna(first_alert) else 'none'}")
    seasons_seen = set(out["season"])
    print(f"  [dry-run] seasons emitted: {sorted(seasons_seen)}")
    if include_ohlcv:
        expected_7 = {"capitulation", "dry_up", "spring_test", "early_markup",
                      "pre", "momentum", "stale"}
        missing = expected_7 - seasons_seen
        if missing:
            print(f"  [dry-run] ⚠ missing stages: {sorted(missing)} "
                  f"(synthetic window too short for this n_weeks)")
        else:
            print(f"  [dry-run] ✓ all 7 Wyckoff stages observed")
    momentum_dates = out[out["season"] == "momentum"].index
    stale_start = out[out["season"] == "stale"].index.min()
    if len(momentum_dates):
        print(f"  [dry-run] 'momentum' season: "
              f"{momentum_dates.min().strftime('%Y-%m-%d')} → "
              f"{momentum_dates.max().strftime('%Y-%m-%d')} "
              f"({len(momentum_dates)} weeks inside the tradeable window)")
    if pd.notna(stale_start):
        print(f"  [dry-run] 'stale' (post-season) starts: "
              f"{stale_start.strftime('%Y-%m-%d')}")

    last = out.iloc[-1]
    first = out.iloc[0]
    print(f"  [dry-run] stage trajectory: {first['stage']:.3f} (early) "
          f"→ {last['stage']:.3f} (final, current_season={last['season']!r})")

    assert out["stage"].iloc[-1] > out["stage"].iloc[0], \
        "stage must rise as holders disperse (sanity check)"
    print(f"\n  [dry-run] ✓ math validated; plug is ready for query_id")
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# INSPECT
# ═══════════════════════════════════════════════════════════════════════════

def show_token(token_addr: str) -> None:
    """Print a human-readable summary of a previously-processed token."""
    path = _processed_path(token_addr)
    if not path.exists():
        print(f"  [show] no processed file for {token_addr}; run fetch first.")
        return
    payload = json.loads(path.read_text())
    print(f"\n  Token:   {payload['token']}")
    print(f"  Query:   {payload['query_id']}")
    print(f"  Fetched: {payload['fetched_at']}")
    print(f"  Dates:   {payload['n_dates']}")
    print(f"  Path:    {path}")
    alerts = [d for d, v in payload["dates"].items() if v["chuquan"]]
    if alerts:
        print(f"  Alerts:  {len(alerts)} dates with chuquan=True")
        print(f"           first: {alerts[0]}, last: {alerts[-1]}")
    else:
        print(f"  Alerts:  none")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="D3 holder-concentration fetcher")
    p.add_argument("--query-id", type=int,
                   default=(int(DUNE_QUERY_ID_DEFAULT) if DUNE_QUERY_ID_DEFAULT else None),
                   help="Dune saved query id (or set DUNE_QUERY_ID_HOLDERS env)")
    p.add_argument("--token", default="0xdAC17F958D2ee523a2206206994597C13D831ec7",
                   help="Token address (default USDT for first run)")
    p.add_argument("--tokens-file", help="Newline-delimited list of token addresses")
    p.add_argument("--start", default="2024-01-01", help="Start date YYYY-MM-DD")
    p.add_argument("--end",   default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    p.add_argument("--no-cache", action="store_true",
                   help="Skip the raw-response cache, force a fresh Dune call")
    p.add_argument("--timeout", type=int, default=300,
                   help="Dune execution timeout in seconds (default 300)")
    p.add_argument("--dry-run", action="store_true",
                   help="Use synthetic data, no Dune calls — validates the plug")
    p.add_argument("--no-ohlcv", action="store_true",
                   help="(dry-run only) Skip synthetic OHLCV → back-compat 3-season path")
    p.add_argument("--show", metavar="TOKEN", help="Inspect a processed token")
    return p


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    _ensure_dirs()

    # --show path
    if args.show:
        show_token(args.show)
        return 0

    # --dry-run path
    if args.dry_run:
        print(f"  [init] dry-run mode (synthetic data, no Dune call)")
        payload = dry_run_synthetic(include_ohlcv=not args.no_ohlcv)
        print(f"\n  [ok] wrote {PROCESSED_DIR / '0xSYNTHETIC.json'}")
        print(f"  [ok] index updated at {INDEX_FILE}")
        return 0

    # Real fetch path
    if not args.query_id:
        print("ERROR: --query-id required (or set DUNE_QUERY_ID_HOLDERS env).", file=sys.stderr)
        print("       Or use --dry-run to validate the plug with synthetic data.", file=sys.stderr)
        return 2

    # Resolve token list
    if args.tokens_file:
        tokens = [
            line.strip() for line in Path(args.tokens_file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    else:
        tokens = [args.token]

    print(f"  [init] query_id={args.query_id} tokens={len(tokens)} "
          f"range={args.start}..{args.end}")

    success, failure = 0, 0
    for tok in tokens:
        try:
            df = fetch_one_token(
                query_id=args.query_id,
                token_addr=tok,
                start=args.start,
                end=args.end,
                use_cache=not args.no_cache,
                timeout_s=args.timeout,
            )
            payload = process_and_write(df, tok, args.query_id)
            print(f"  [ok] {tok}: {payload['n_dates']} dates written")
            success += 1
        except Exception as e:
            print(f"  [ERR] {tok}: {type(e).__name__}: {e}", file=sys.stderr)
            failure += 1

    print(f"\n  [done] {success} ok, {failure} failed")
    return 0 if failure == 0 else 1


if __name__ == "__main__":
    sys.exit(main())