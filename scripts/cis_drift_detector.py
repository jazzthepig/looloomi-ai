#!/usr/bin/env python3
"""
CIS Drift Detector — silent-decay surveillance
================================================

Background (the HYPE case, 2026-07-30):
    HYPE decayed 40.9 (C, 2026-07-08) → 27.3 (D, today) over 23 days in
    cis_scores WITHOUT any system-level alarm. Universe inclusion is
    continuous, NOT binary in/out — silent drift through tier drops IS the
    failure mode this script makes visible.

    Reframing per Seth (in earlier session): HYPE was never excluded; it
    was always in the universe. The problem is silent drift through top-N
    tilt's natural filtering, leaving the asset invisible at the product
    surface while still nominally eligible. This detector is the alarm.

Detection signals (each independently flagged):
    1.  7d score delta drop    ≥ --drop-7d      (default 5.0 points)
    2.  30d score delta drop   ≥ --drop-30d     (default 10.0 points)
    3.  Tier drop(s) in last 30d                (C→D, D→F, B+→C, ...)
    4.  Signal flip in last 7d                  (OUTPERFORM → UNDERPERFORM-class)
    5.  Sustained UNDERWEIGHT  ≥ --sustain-days (default 7 days)

Severity:
    CRITICAL — 2+ signals fire, OR 30d drop ≥ 20, OR ≥2 tier drops in 30d
    HIGH     — any single signal fires

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/cis_drift_detector.py
    SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/cis_drift_detector.py --json
    SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/cis_drift_detector.py --days 30 --drop-7d 3

Exit codes:
    0 = no HIGH/CRITICAL drift detected
    1 = CRITICAL drift detected (CI-friendly; wire into scheduled probe)
    2 = missing env vars / supabase unreachable

Output:
    Console table — human-readable.
    --json dumps reports/cis_drift/<UTC-date>/drift.json for downstream tooling.

See:  docs/UNIVERSE_DECISION_HYPE.md §3 management plans (the first asset to use this).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import httpx


# ── Tier table (mirrors CIS_METHODOLOGY.md / CLAUDE.md hard-rule color map) ──
TIERS = [
    (85, "A+"),
    (75, "A"),
    (65, "B+"),
    (55, "B"),
    (45, "C+"),
    (35, "C"),
    (25, "D"),
    (0,  "F"),
]
GRADE_RANK = {g: i for i, (_, g) in enumerate(TIERS)}  # A+=0 ... F=7

OUTPERFORM_TOKENS = ("STRONG OUTPERFORM", "OUTPERFORM")
NEUTRAL_TOKENS    = ("NEUTRAL",)
UNDERPERFORM_TOKENS = ("UNDERPERFORM", "UNDERWEIGHT")


def grade_for(score: float) -> str:
    for threshold, g in TIERS:
        if score >= threshold:
            return g
    return "F"


def signal_class(signal: str | None) -> str:
    """Bucket raw signal text into 3 classes for flip detection."""
    s = (signal or "").upper()
    if any(t in s for t in OUTPERFORM_TOKENS):
        return "OUTPERFORM"
    if any(t in s for t in NEUTRAL_TOKENS):
        return "NEUTRAL"
    if any(t in s for t in UNDERPERFORM_TOKENS):
        return "UNDERPERFORM"
    return "UNKNOWN"


# ── Supabase REST fetch (sync; CLI tool) ─────────────────────────────────────
def fetch_cis_history(url: str, key: str, days: int) -> list[dict]:
    """GET /rest/v1/cis_scores?as_of_date=gte.<cutoff> — paginated if needed."""
    cutoff = (dt.datetime.utcnow().date() - dt.timedelta(days=days)).isoformat()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    out: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        params = {
            "select": "symbol,cis_score,grade,signal,as_of_date",
            "as_of_date": f"gte.{cutoff}",
            "order": "symbol.asc,as_of_date.asc",
            "limit": str(page_size),
            "offset": str(offset),
        }
        resp = httpx.get(
            f"{url}/rest/v1/cis_scores",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
        if offset > 200_000:  # safety cap
            break
    return out


# ── Detection logic ──────────────────────────────────────────────────────────
def detect_drift(history: list[dict], args) -> list[dict]:
    by_sym: dict[str, list[dict]] = {}
    for r in history:
        by_sym.setdefault(r["symbol"], []).append(r)

    findings: list[dict] = []
    for sym, rows in by_sym.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: r["as_of_date"])
        latest = rows[-1]
        latest_date = dt.datetime.fromisoformat(latest["as_of_date"]).date()
        latest_score = float(latest.get("cis_score") or 0)
        latest_grade = latest.get("grade") or grade_for(latest_score)
        latest_signal = latest.get("signal") or "UNKNOWN"
        latest_class = signal_class(latest_signal)

        # 7d and 30d lookback anchors (use the LATEST date as anchor, not today,
        # so a stale-data day doesn't artificially shrink the window).
        # Fallback: if no row exists within the window, use the EARLIEST row —
        # the asset's score is what it is, and under-sampled rows should NOT
        # hide drift (HYPE case: 23d of history should still trigger 30d drop).
        def score_n_days_ago(n: int) -> tuple[float | None, str]:
            cutoff_d = (latest_date - dt.timedelta(days=n)).isoformat()
            # first try: latest row whose date is <= cutoff
            for r in reversed(rows[:-1]):
                if r["as_of_date"] <= cutoff_d:
                    return float(r["cis_score"]), r["as_of_date"]
            # fallback: earliest row (window-under-sampled)
            return float(rows[0]["cis_score"]), rows[0]["as_of_date"]

        score_7d_val, _anchor_7d = score_n_days_ago(7)
        score_30d_val, _anchor_30d = score_n_days_ago(30)
        drop_7d = (score_7d_val - latest_score) if score_7d_val is not None else 0.0
        drop_30d = (score_30d_val - latest_score) if score_30d_val is not None else 0.0

        # Tier drops in last 30d (count transitions strictly downward).
        cutoff_30d = (latest_date - dt.timedelta(days=30)).isoformat()
        recent_30d = [r for r in rows if r["as_of_date"] >= cutoff_30d]
        tier_drops_30d = 0
        for i in range(1, len(recent_30d)):
            prev_g = recent_30d[i-1].get("grade") or grade_for(float(recent_30d[i-1]["cis_score"]))
            curr_g = recent_30d[i].get("grade") or grade_for(float(recent_30d[i]["cis_score"]))
            if prev_g != curr_g and GRADE_RANK.get(prev_g, 99) < GRADE_RANK.get(curr_g, 99):
                tier_drops_30d += 1

        # Signal flip in last 7d (first-class vs latest-class differs).
        # Use 30d window for flip detection — a 7d window is too tight for assets
        # that drift slowly (HYPE case: first crossed into UNDERPERFORM on day 8,
        # wouldn't be visible at 7d). 30d catches "the asset WAS outperform-class
        # a month ago and ISN'T now" — the most diagnostic flip.
        cutoff_flip = (latest_date - dt.timedelta(days=30)).isoformat()
        recent_flip = [r for r in rows if r["as_of_date"] >= cutoff_flip]
        signal_flip_7d = False
        if recent_flip:
            first_class = signal_class(recent_flip[0].get("signal"))
            signal_flip_7d = (first_class != latest_class and first_class != "UNKNOWN")

        # Sustained UNDERWEIGHT (count back from latest).
        consecutive_underweight = 0
        for r in reversed(rows):
            if signal_class(r.get("signal")) == "UNDERPERFORM":
                consecutive_underweight += 1
            else:
                break

        # Trigger detection
        signals_fired: list[str] = []
        if drop_7d >= args.drop_7d:
            signals_fired.append(f"7d_drop_{drop_7d:+.1f}")
        if drop_30d >= args.drop_30d:
            signals_fired.append(f"30d_drop_{drop_30d:+.1f}")
        if tier_drops_30d >= 1:
            signals_fired.append(f"tier_drop_x{tier_drops_30d}_30d")
        if signal_flip_7d:
            signals_fired.append("signal_flip_7d")
        if consecutive_underweight >= args.sustain_days:
            signals_fired.append(f"sustained_underweight_{consecutive_underweight}d")

        if not signals_fired:
            continue

        # Severity
        if len(signals_fired) >= 2 or drop_30d >= 20 or tier_drops_30d >= 2:
            severity = "CRITICAL"
        else:
            severity = "HIGH"

        findings.append({
            "symbol": sym,
            "as_of_date": latest["as_of_date"],
            "current_score": latest_score,
            "current_grade": latest_grade,
            "current_signal": latest_signal,
            "drop_7d": round(drop_7d, 2),
            "drop_30d": round(drop_30d, 2),
            "tier_drops_30d": tier_drops_30d,
            "signal_flip_7d": signal_flip_7d,
            "consecutive_underweight_days": consecutive_underweight,
            "signals_fired": signals_fired,
            "severity": severity,
        })

    # CRITICAL first, then by largest 30d drop
    findings.sort(key=lambda f: (f["severity"] != "CRITICAL", -f["drop_30d"]))
    return findings


# ── Output rendering ─────────────────────────────────────────────────────────
def render_console(findings: list[dict]) -> str:
    if not findings:
        return "✅ No CIS drift detected (all thresholds met).\n"

    header = (
        f"{'SYMBOL':<10} {'SEV':<10} {'SCORE':>6} {'GRADE':<5} {'SIGNAL':<28} "
        f"{'7d_Δ':>7} {'30d_Δ':>7} {'TIER_30d':>9} {'UW_DAYS':>8}  SIGNALS"
    )
    sep = "-" * len(header)
    lines = [
        f"⚠️  CIS DRIFT — {len(findings)} asset(s) flagged",
        "",
        header,
        sep,
    ]
    for f in findings:
        sig_short = (f["current_signal"] or "")[:28]
        signals = ", ".join(f["signals_fired"])
        lines.append(
            f"{f['symbol']:<10} {f['severity']:<10} {f['current_score']:>6.1f} "
            f"{f['current_grade']:<5} {sig_short:<28} "
            f"{f['drop_7d']:>+7.1f} {f['drop_30d']:>+7.1f} "
            f"{f['tier_drops_30d']:>9} {f['consecutive_underweight_days']:>8}  {signals}"
        )
    return "\n".join(lines) + "\n"


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="CIS drift detector — silent decay surveillance")
    ap.add_argument("--days", type=int, default=30, help="Lookback window (default 30)")
    ap.add_argument("--drop-7d", type=float, default=5.0,
                    help="7d score drop threshold (default 5.0 points)")
    ap.add_argument("--drop-30d", type=float, default=10.0,
                    help="30d score drop threshold (default 10.0 points)")
    ap.add_argument("--sustain-days", type=int, default=7,
                    help="Sustained UNDERWEIGHT days (default 7)")
    ap.add_argument("--json", action="store_true",
                    help="Dump JSON to reports/cis_drift/<UTC-date>/drift.json")
    ap.add_argument("--out-dir", default="reports/cis_drift",
                    help="JSON output dir (default reports/cis_drift)")
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_KEY) env vars required.",
              file=sys.stderr)
        print("Get URL+KEY from Railway dashboard → CometCloud service → Variables,",
              file=sys.stderr)
        print("or supabase.com project → Settings → API.", file=sys.stderr)
        return 2

    print(f"→ Fetching cis_scores history (last {args.days}d) from {url[:40]}...",
          file=sys.stderr)
    try:
        history = fetch_cis_history(url, key, args.days)
    except httpx.HTTPError as e:
        print(f"ERROR: Supabase REST failed: {e}", file=sys.stderr)
        return 2
    n_sym = len({r["symbol"] for r in history})
    print(f"  ✓ {len(history)} rows across {n_sym} symbols", file=sys.stderr)

    findings = detect_drift(history, args)
    print(render_console(findings))

    if args.json:
        today = dt.datetime.utcnow().date().isoformat()
        out_dir = Path(args.out_dir) / today
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "drift.json"
        out_path.write_text(json.dumps(
            {
                "as_of_utc": dt.datetime.utcnow().isoformat() + "Z",
                "as_of_date": today,
                "args": vars(args),
                "n_rows_scanned": len(history),
                "n_symbols_scanned": n_sym,
                "n_findings": len(findings),
                "n_critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
                "n_high": sum(1 for f in findings if f["severity"] == "HIGH"),
                "findings": findings,
            },
            indent=2,
            ensure_ascii=False,
        ))
        print(f"  ✓ JSON written to {out_path}", file=sys.stderr)

    n_critical = sum(1 for f in findings if f["severity"] == "CRITICAL")
    if n_critical > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
