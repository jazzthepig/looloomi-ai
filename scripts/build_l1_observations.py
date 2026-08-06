#!/usr/bin/env python3
"""
Build the L1 observation panel (2022-01-01 onward) into a LOCAL sqlite artifact.

L1 is the data-collection layer: raw daily observations, ragged, nulls preserved.
It is deliberately NOT written to Supabase yet — the dim set will churn while it
is settled, and rewriting a system-of-record on every iteration is how a schema
becomes something nobody trusts. Ingest is the Mac lane (MINIMAX_SYNC D1/D2)
once the shape is stable.

Sources wired here (panel + CIS). Funding, stablecoin supply and OI land in
separate passes so a failure in one never truncates the others:
    ohlcv_daily (Supabase)     -> risk_appetite, liquidity, vol_structure, trend_phase
    cis_history.db (Shadow)    -> cross_quality
    hyperliquid_funding CSV    -> leverage (2023-05 onward)
    CoinGecko                  -> stable_supply_chg (2022-03-17 onward)
    OPEN INTEREST              -> slot reserved, vendor pending

Usage:
    python scripts/build_l1_observations.py                 # full 2022+ build
    python scripts/build_l1_observations.py --start 2024-01-01
    python scripts/build_l1_observations.py --report        # coverage only
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.data.vector.market_state import (  # noqa: E402
    breadth_above_ma, downside_ratio, herfindahl, mean_pairwise_corr,
    realized_vol, skew, stdev, trend_phase,
)
from src.data.vector.state_l1 import (  # noqa: E402
    DEFAULT_OUT, START_DATE, coverage_report, open_db, record_build, write_observations,
)

load_dotenv(ROOT / ".env")

SB_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SB_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or ""
SHADOW_CIS = ROOT / "Shadow" / "cometcloud-local" / "_data" / "cis_history.db"

CRYPTO_CLASSES = ("L1", "L2", "DeFi", "Crypto", "RWA", "Infrastructure", "AI", "Memecoin", "Gaming")
VOL_WINDOW = 30
LONG_MA = 200
WARMUP = LONG_MA + 40


def fetch_panel(start: str) -> dict[str, dict[str, tuple[float, float]]]:
    """{symbol: {date: (close, volume)}} for crypto only.

    Warmup is pulled BEFORE `start` because a 200-day MA computed from a panel
    that begins on the start date is not a 200-day MA — it is a shorter mean
    wearing the same name, and it would silently corrupt trend_phase for the
    first 200 rows of every build.
    """
    warm = (date.fromisoformat(start) - timedelta(days=WARMUP)).isoformat()
    out: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    offset, page = 0, 10000
    hdr = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
    cls = ",".join(CRYPTO_CLASSES)
    with httpx.Client(timeout=120) as c:
        while True:
            r = c.get(
                f"{SB_URL}/rest/v1/ohlcv_daily",
                params={
                    "select": "symbol,trade_date,close,volume",
                    "trade_date": f"gte.{warm}",
                    "asset_class": f"in.({cls})",
                    "order": "trade_date.asc",
                    "limit": page, "offset": offset,
                },
                headers=hdr,
            )
            r.raise_for_status()
            batch = r.json()
            for row in batch:
                cl, vol = row.get("close"), row.get("volume")
                if cl is None:
                    continue
                out[row["symbol"]][row["trade_date"][:10]] = (float(cl), float(vol or 0))
            if len(batch) < page:
                break
            offset += page
            print(f"  ... {offset} rows", flush=True)
    return dict(out)


SHADOW_PANEL = ROOT / "Shadow" / "cometcloud-local" / "_data" / "hyperliquid_funding"
# The 11-year panel already lives on disk (scripts/fetch_ohlcv_11yr_binance.py).
# Reading it over the Supabase REST API was a straightforwardly wrong choice:
# it adds a network dependency and a credential dependency to a job whose data
# is local, and it fails with a DNS traceback instead of a sentence.
LOCAL_11YR = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
LOCAL_OHLCV = Path("/tmp/cometcloud_data/ohlcv.db")


def fetch_panel_sqlite(start: str, db: Path) -> dict[str, dict[str, tuple[float, float]]]:
    """Panel from a local sqlite OHLCV store — the preferred source.

    Handles both the 11yr schema (ohlcv_11yr_daily) and the rolling one
    (ohlcv_daily); whichever table is present wins, 11yr first since only it
    reaches the 2022 start date.
    """
    warm = (date.fromisoformat(start) - timedelta(days=WARMUP)).isoformat()
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    tbl = "ohlcv_11yr_daily" if "ohlcv_11yr_daily" in tables else (
        "ohlcv_daily" if "ohlcv_daily" in tables else None)
    if tbl is None:
        con.close()
        raise RuntimeError(f"{db} has no ohlcv table (found: {sorted(tables) or 'none'})")

    out: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    for sym, d, close, vol in con.execute(
        f"select symbol, trade_date, close, volume from {tbl}"
        f" where trade_date >= ? and close is not null order by trade_date", (warm,)
    ):
        out[str(sym).upper()][str(d)[:10]] = (float(close), float(vol or 0))
    con.close()
    return dict(out)


def resolve_panel_source(explicit: str) -> tuple[str, str]:
    """(source_name, detail). Auto mode prefers depth, then locality, then network."""
    if explicit != "auto":
        return explicit, ""
    if LOCAL_11YR.exists() and LOCAL_11YR.stat().st_size > 1_000_000:
        return "sqlite11yr", str(LOCAL_11YR)
    if LOCAL_OHLCV.exists() and LOCAL_OHLCV.stat().st_size > 1_000_000:
        return "sqlite", str(LOCAL_OHLCV)
    # Only offer Supabase if its host actually resolves. Selecting a source and
    # then discovering it is unreachable turns a config error into a stack
    # trace; the first Mac run failed exactly this way, on a .env holding the
    # placeholder host "xxxxx.supabase.co".
    if SB_URL.startswith("http") and SB_KEY:
        try:
            import socket
            socket.getaddrinfo(SB_URL.split("//", 1)[-1].split("/")[0], 443)
            return "supabase", SB_URL
        except Exception:                                         # noqa: BLE001
            pass
    if SHADOW_PANEL.exists():
        return "local", str(SHADOW_PANEL)
    return "none", ""


def diagnose() -> int:
    """Say what is reachable, in one screen, before anything tries to run.

    Added because the first Mac run of this script produced a 60-line httpx
    traceback ending in a DNS error, which says nothing about the actual
    problem — a config value that was never validated. A script that cannot
    explain its own preconditions is not finished.
    """
    print("panel sources")
    for label, p in (("11yr sqlite", LOCAL_11YR), ("rolling sqlite", LOCAL_OHLCV)):
        if p.exists():
            try:
                con = sqlite3.connect(p)
                t = [r[0] for r in con.execute(
                    "select name from sqlite_master where type='table'")]
                tbl = "ohlcv_11yr_daily" if "ohlcv_11yr_daily" in t else (
                    "ohlcv_daily" if "ohlcv_daily" in t else None)
                if tbl:
                    n, lo, hi, syms = con.execute(
                        f"select count(*), min(trade_date), max(trade_date),"
                        f" count(distinct symbol) from {tbl}").fetchone()
                    print(f"  OK   {label:16} {p}")
                    print(f"       {n:,} rows · {syms} symbols · {lo} .. {hi}")
                else:
                    print(f"  BAD  {label:16} {p} — no ohlcv table, has {t}")
                con.close()
            except Exception as e:                                # noqa: BLE001
                print(f"  BAD  {label:16} {p} — {type(e).__name__}: {e}")
        else:
            print(f"  --   {label:16} {p} (absent)")

    n_csv = len(list(SHADOW_PANEL.glob('*_1d_ohlcv.csv'))) if SHADOW_PANEL.exists() else 0
    print(f"  {'OK  ' if n_csv else '--  '} shadow csv       {SHADOW_PANEL} ({n_csv} files, 2023+ only)")

    print("\nsupabase rest")
    if not SB_URL:
        print("  BAD  SUPABASE_URL is empty — .env not loaded, or key missing from it")
    elif not SB_URL.startswith("http"):
        print(f"  BAD  SUPABASE_URL is not a URL: {SB_URL!r}")
    else:
        host = SB_URL.split("//", 1)[-1].split("/")[0]
        try:
            import socket
            socket.getaddrinfo(host, 443)
            print(f"  OK   {host} resolves")
        except Exception as e:                                    # noqa: BLE001
            print(f"  BAD  {host} does not resolve ({e}) — offline, DNS, or wrong host")
        else:
            # A key that DECODES is not a key that VERIFIES, and a key that
            # authenticates is not a key that can READ.
            #
            # 2026-08-02: .env held a forged service_role token — the anon key's
            # signature spliced onto a payload whose role claim had been edited to
            # "service_role". It decoded perfectly (right ref, right role, 2036
            # expiry), so the old check here — `key {'set' if SB_KEY else ...}` —
            # called it OK. Only the server disagreed: 401 Invalid API key.
            # Separately, the real anon key returns 200 with ZERO rows on every
            # table since the S-94 RLS hardening, so HTTP 200 alone means nothing
            # either. Probe for rows, not for status.
            if not SB_KEY:
                print("  BAD  SUPABASE_KEY is empty — dashboard > Project Settings > API Keys")
            else:
                try:
                    r = httpx.get(
                        f"{SB_URL}/rest/v1/ohlcv_daily",
                        params={"select": "symbol", "limit": 1},
                        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"},
                        timeout=15,
                    )
                    if r.status_code == 401:
                        print("  BAD  key rejected (401 Invalid API key) — the token is not one "
                              "Supabase signed for this project; re-copy it from the dashboard")
                    elif r.status_code != 200:
                        print(f"  BAD  key probe returned HTTP {r.status_code}: {r.text[:120]}")
                    elif not r.json():
                        print("  BAD  key authenticates but reads 0 rows — this is the anon key "
                              "under RLS, not service_role; ohlcv_daily is not readable with it")
                    else:
                        print("  OK   key verified against ohlcv_daily (200, rows > 0)")
                except Exception as e:                            # noqa: BLE001
                    print(f"  BAD  key probe failed — {type(e).__name__}: {e}")

    print(f"\ncis history   {'OK' if SHADOW_CIS.exists() else 'MISSING'}  {SHADOW_CIS}")
    src, detail = resolve_panel_source("auto")
    print(f"\nauto would use: {src} {detail}")
    return 0 if src != "none" else 1


def fetch_panel_local(start: str) -> dict[str, dict[str, tuple[float, float]]]:
    """Panel from Shadow's local 1d OHLCV CSVs — 47 crypto, 2023-01-01 onward.

    A FALLBACK, not the primary source. It cannot reach the 2022 start date the
    strategy window requires: 2023-01 is exactly the window vector_mine Round 6
    used, and its own notes record the consequence — eight k-means clusters that
    all shared HIGH_VOL + RISK_ON + HIGH_DISP, because one macro environment
    cannot be partitioned into distinct regimes no matter how good the
    clustering is. Use this to validate the pipeline; use Supabase for the
    real build.
    """
    import csv as _csv
    from datetime import timezone

    warm = (date.fromisoformat(start) - timedelta(days=WARMUP)).isoformat()
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for f in sorted(SHADOW_PANEL.glob("*_1d_ohlcv.csv")):
        sym = f.name.replace("_1d_ohlcv.csv", "").upper()
        ser: dict[str, tuple[float, float]] = {}
        for row in _csv.DictReader(f.open()):
            try:
                d = datetime.fromtimestamp(int(row["openTime"]) / 1000,
                                           tz=timezone.utc).date().isoformat()
                if d < warm:
                    continue
                ser[d] = (float(row["close"]), float(row.get("quoteVolume") or 0))
            except (ValueError, TypeError, KeyError):
                continue
        if ser:
            out[sym] = ser
    return out


def fetch_cis_daily(start: str) -> dict[str, dict[str, float]]:
    """{date: {cis_mean, cis_disp, cis_skew, pct_grade_A, stability_OS}} from the
    Shadow local history (162,693 rows, deeper than Supabase's copy)."""
    if not SHADOW_CIS.exists():
        print(f"  ! {SHADOW_CIS} missing — cross_quality block will be empty")
        return {}
    con = sqlite3.connect(SHADOW_CIS)
    q = """
      select substr(timestamp,1,10) d, cis_score, grade, pillar_o, pillar_s
      from cis_history
      where substr(timestamp,1,10) >= ? and cis_score is not null
    """
    by_day: dict[str, list[tuple]] = defaultdict(list)
    for d, sc, grade, po, ps in con.execute(q, (start,)):
        by_day[d].append((sc, grade, po, ps))
    con.close()

    out: dict[str, dict[str, float]] = {}
    for d, rows in by_day.items():
        # A cross-sectional statistic on a handful of assets is arithmetic on
        # noise. 12 is the floor below which dispersion/skew are not reported —
        # the value would exist and mean nothing, which is worse than a null.
        if len(rows) < 12:
            continue
        scores = [r[0] for r in rows]
        m = sum(scores) / len(scores)
        rec = {
            "cis_mean": m,
            "cis_disp": stdev(scores) or 0.0,
            "cis_skew": skew(scores),
            "pct_grade_A": sum(1 for r in rows if (r[1] or "").startswith("A")) / len(rows),
        }
        os_pairs = [(r[2], r[3]) for r in rows if r[2] is not None and r[3] is not None]
        if len(os_pairs) >= 12:
            o = [p[0] for p in os_pairs]
            s = [p[1] for p in os_pairs]
            so, ss = stdev(o), stdev(s)
            # R63b stability premium: pool-level S relative to O dispersion.
            rec["stability_OS"] = (sum(s) / len(s)) / (so + 1e-9) if so else None
            rec["_ss"] = ss
        out[d] = {k: v for k, v in rec.items() if not k.startswith("_")}
    return out


def compute_panel_series(panel: dict[str, dict[str, tuple[float, float]]],
                         start: str) -> dict[str, dict[str, float]]:
    """Panel-derived series per date. Price contributes ONLY second moments and
    phase (vol_mkt, vol_of_vol, downside_ratio, trend_strength, trend_age_days);
    everything else here is cross-sectional structure, not level or direction."""
    all_dates = sorted({d for s in panel.values() for d in s})
    dates = [d for d in all_dates if d >= start]
    closes = {s: {d: v[0] for d, v in ser.items()} for s, ser in panel.items()}
    vols = {s: {d: v[1] for d, v in ser.items()} for s, ser in panel.items()}

    def ret_series(sym: str, upto: str, n: int) -> list[float]:
        ds = [d for d in sorted(closes[sym]) if d <= upto][-(n + 1):]
        c = [closes[sym][d] for d in ds]
        return [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1]]

    btc = "BTC"
    out: dict[str, dict[str, float]] = {}
    vol_hist: list[float] = []

    for d in dates:
        live = [s for s in panel if d in closes[s]]
        if len(live) < 12:
            continue
        rec: dict[str, float] = {}

        # ── cross-section: risk appetite ─────────────────────────────────────
        r1 = {s: ret_series(s, d, 1) for s in live}
        day_rets = [v[0] for v in r1.values() if v]
        if len(day_rets) >= 12:
            rec["disp_return"] = stdev(day_rets)
            if btc in r1 and r1[btc]:
                alts = [v[0] for s, v in r1.items() if s != btc and v]
                if alts:
                    rec["alt_btc_spread"] = sum(alts) / len(alts) - r1[btc][0]

        hist_c = {s: [closes[s][x] for x in sorted(closes[s]) if x <= d] for s in live}
        b = breadth_above_ma(hist_c, LONG_MA)
        if b is not None:
            rec["breadth_200ma"] = b

        r30 = {s: ret_series(s, d, VOL_WINDOW) for s in live}
        cm = mean_pairwise_corr({s: v for s, v in r30.items() if len(v) >= 20})
        if cm is not None:
            rec["corr_mean"] = cm

        # ── liquidity ────────────────────────────────────────────────────────
        vtoday = [vols[s].get(d, 0) for s in live]
        h = herfindahl(vtoday)
        if h is not None:
            rec["adv_concentration"] = h
        tot_now = sum(vtoday)
        prior = [d2 for d2 in sorted({x for s in live for x in vols[s]}) if d2 < d][-30:]
        if prior and tot_now > 0:
            base = [sum(vols[s].get(p, 0) for s in live) for p in prior]
            base = [x for x in base if x > 0]
            if base:
                rec["volume_trend"] = tot_now / (sum(base) / len(base))

        # ── price block: second moments + phase only ─────────────────────────
        if btc in hist_c and len(hist_c[btc]) > VOL_WINDOW:
            br = ret_series(btc, d, VOL_WINDOW)
            v = realized_vol(br)
            if v is not None:
                rec["vol_mkt"] = v
                vol_hist.append(v)
                if len(vol_hist) > 30:
                    vv = stdev(vol_hist[-30:])
                    if vv is not None:
                        rec["vol_of_vol"] = vv
            dr = downside_ratio(br)
            if dr is not None:
                rec["downside_ratio"] = dr
            ts, ta = trend_phase(hist_c[btc], LONG_MA)
            if ts is not None:
                rec["trend_strength"] = ts
            if ta is not None:
                rec["trend_age_days"] = ta

        if rec:
            out[d] = rec
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=START_DATE)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--panel-source",
                    choices=["auto","sqlite11yr","sqlite","supabase","local"], default="auto",
                    help="auto prefers the local 11yr sqlite; 'local' = Shadow CSVs, 2023+ only")
    ap.add_argument("--diagnose", action="store_true",
                    help="report which sources are reachable, then exit")
    args = ap.parse_args()

    if args.report:
        import json
        print(json.dumps(coverage_report(), indent=2))
        return 0

    if args.diagnose:
        return diagnose()

    src, detail = resolve_panel_source(args.panel_source)
    print(f"[1/4] panel source = {src} {detail} (warmup {WARMUP}d before {args.start})", flush=True)
    try:
        if src == "sqlite11yr":
            panel = fetch_panel_sqlite(args.start, LOCAL_11YR)
        elif src == "sqlite":
            panel = fetch_panel_sqlite(args.start, LOCAL_OHLCV)
        elif src == "supabase":
            if not SB_URL.startswith("http") or not SB_KEY:
                print("FAIL SUPABASE_URL/KEY missing or malformed. Run --diagnose.", file=sys.stderr)
                return 2
            panel = fetch_panel(args.start)
        elif src == "local":
            panel = fetch_panel_local(args.start)
        else:
            print("FAIL no panel source reachable. Run --diagnose.", file=sys.stderr)
            return 2
    except Exception as e:
        # One sentence, then the remedy. A stack trace is not a diagnosis.
        print(f"FAIL panel fetch via {src}: {type(e).__name__}: {e}", file=sys.stderr)
        print("     run: python3 scripts/build_l1_observations.py --diagnose", file=sys.stderr)
        return 2

    if not panel:
        print(f"FAIL panel source {src} returned 0 symbols for start={args.start}", file=sys.stderr)
        return 2
    print(f"      {len(panel)} crypto symbols")

    print("[2/4] panel-derived series ...", flush=True)
    panel_series = compute_panel_series(panel, args.start)
    print(f"      {len(panel_series)} dates")

    print("[3/4] CIS cross-section from Shadow local history ...", flush=True)
    cis_series = fetch_cis_daily(args.start)
    print(f"      {len(cis_series)} dates")

    rows: list[tuple] = []
    for d, rec in panel_series.items():
        rows += [(d, k, v, "ohlcv_daily") for k, v in rec.items()]
    for d, rec in cis_series.items():
        rows += [(d, k, v, "cis_history.db") for k, v in rec.items()]

    print(f"[4/4] writing {len(rows)} observations -> {args.out}", flush=True)
    con = open_db(Path(args.out))
    write_observations(con, rows)
    ds = sorted({r[0] for r in rows})
    bid = record_build(con, ds[0] if ds else args.start, ds[-1] if ds else args.start,
                       len(ds), len({r[1] for r in rows}))

    print(f"\nbuild {bid}: {len(ds)} days {ds[0]}..{ds[-1]}, {len({r[1] for r in rows})} series")
    print("\nper-series coverage:")
    for series, n, first, last in con.execute(
        "select series, count(value), min(d), max(d) from l1_observations"
        " group by series order by count(value) desc"
    ):
        print(f"  {series:20} {n:5}  {first} .. {last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
