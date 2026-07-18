"""
Crowd Clock — retroactive backtest (Seth, 2026-07-17). Refutation Ledger R24.
==============================================================================
Instead of waiting 60-90 days for live snapshots, reconstruct the crowd phase from HISTORY
(Fear&Greed 2018→ + BTC daily trend) and measure the forward 30d BTC return per phase. Tests
the core claim NOW: does the behavioral phase carry forward asymmetry?

RESULT (2018-03 → 2026-06, 3026 days; reduced inputs — FNG + BTC trend only, no live
crowding/dispersion, so `euphoria` never fires here):

    unconditional baseline: mean fwd-30d +3.83%, hit 53.5%
      capitulation   n= 908   +1.00%   hit 52.6%   vs base -2.84%   ← REFUTED as a 30d long
      accumulation   n=1102   +3.09%   hit 52.5%   vs base -0.74%   ~ baseline
      markup         n= 935   +7.78%   hit 56.3%   vs base +3.95%   ← VALIDATED (press)
      distribution   n=  81   +0.11%   hit 45.7%   vs base -3.72%   ← VALIDATED (defend/bearish)
    FNG-only: FNG<25 +2.91% (BELOW base) | FNG>75 +13.11% (WAY above)

VERDICT — nuanced, honest:
  · The TREND phases carry real forward asymmetry: markup (+3.95% vs base) and distribution
    (−3.72% vs base, negative median). The Crowd Clock IS informative — as a TREND compass.
  · The CONTRARIAN claim is REFUTED at 30d: "buy capitulation / buy fear" did NOT beat
    buy-and-hold. FNG<25 (+2.91%) trailed baseline; FNG>75 (+13.11%) crushed it. In crypto,
    at a 30d horizon, MOMENTUM dominates reversal (consistent with R22) — extreme fear is
    usually mid-downtrend (more downside), extreme greed usually mid-bull (more upside).
  · Consequence for the two-layer book: capitulation is NOT a clean 30d long. The mean-reversion
    sleeve must earn its keep with its OWN deeper-extreme entries + faster exit (MultiFactorV2:
    MVRV<0.9 + price<10%, exit RSI>65), NOT the broad "capitulation phase." The clock's usable
    edge is press-in-markup / defend-in-distribution. crowd_phase_book recalibrated accordingly.

Caveats: reduced inputs (no funding-crowding / CIS-dispersion history → euphoria untested, and
the contrarian phases may sharpen with crowding); single asset (BTC); fixed 30d horizon (a bounce
edge on a 3-5d horizon is not tested here). Re-run with live crowding once history accrues.
"""
from __future__ import annotations

import datetime as dt
import statistics as st

import httpx

from src.data.market.crowd_clock import compute_crowd_clock


def _day(ts_ms: int) -> str:
    return dt.datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


def run(fwd_days: int = 30) -> dict:
    """Fetch FNG + BTC daily, reconstruct phase per day, measure forward return per phase.
    Returns the aggregate table + verdict. Network — run offline/research, not in the request path."""
    fng = {}
    d = httpx.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]
    for row in d:
        fng[_day(int(row["timestamp"]) * 1000)] = float(row["value"])

    closes = {}
    start = 1502928000000  # 2017-08
    while True:
        kl = httpx.get("https://api.binance.com/api/v3/klines",
                       params={"symbol": "BTCUSDT", "interval": "1d", "startTime": start, "limit": 1000},
                       timeout=30).json()
        if not kl:
            break
        for k in kl:
            closes[_day(k[0])] = float(k[4])
        start = kl[-1][0] + 86400000
        if len(kl) < 1000:
            break

    dates = sorted(set(fng) & set(closes))
    price = [closes[x] for x in dates]
    rows = []
    for i in range(30, len(dates) - fwd_days):
        c0 = price[i]
        ph = compute_crowd_clock(fng[dates[i]], (c0 / price[i - 30] - 1) * 100,
                                 (c0 / price[i - 7] - 1) * 100, None, None, None)["phase"]
        rows.append((ph, (price[i + fwd_days] / c0 - 1) * 100))

    allf = [r[1] for r in rows]
    base = st.mean(allf)
    out = {"window": f"{dates[30]}..{dates[-fwd_days-1]}", "n": len(rows),
           "baseline_mean_fwd": round(base, 2), "fwd_days": fwd_days, "phases": {}}
    for ph in ["capitulation", "accumulation", "markup", "euphoria", "distribution"]:
        f = [r[1] for r in rows if r[0] == ph]
        if not f:
            out["phases"][ph] = {"n": 0}
            continue
        m = st.mean(f)
        out["phases"][ph] = {"n": len(f), "mean_fwd": round(m, 2), "median_fwd": round(st.median(f), 2),
                             "hit_pct": round(100 * sum(1 for x in f if x > 0) / len(f), 1),
                             "vs_base": round(m - base, 2)}
    out["verdict"] = ("TREND phases (markup/distribution) carry forward asymmetry; contrarian "
                      "'buy capitulation' REFUTED at this horizon — momentum > reversal in crypto.")
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
