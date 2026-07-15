"""
Forward-Supply Unlock Event Study (moat validation, Seth 2026-07-15).
=====================================================================

THE test the reflection→cause thesis has been owing since 2026-07-09: do exogenous
supply shocks (large token cliff-unlocks) actually predict benchmark-relative
UNDERPERFORMANCE in the 30 days after the unlock? forward_supply.py trades this cause
as bearish; the edge-gate that anchored on it was FALSIFIED (R1). This study asks the
cleaner, causal question with real prices.

Design (standard event study):
  - Event = a documented large cliff-unlock (date + % of circulating supply released).
    Dates verified via web search (dropstab / tokenomist / cryptopolitan / fxstreet /
    cryptobriefing) — see SOURCES. This is a CURATED event set; n is small by nature.
  - For each event: alpha_30d = token_return(t → t+30) − BTC_return(t → t+30).
    Hypothesis (H): high forward-supply overhang → alpha_30d < 0.
  - Control: the SAME token's alpha over a NON-event 30d window (t−60 → t−30), to net out
    token-specific drift. Effect = event_alpha − control_alpha.
  - Stratify by magnitude (large ≥8% of circ vs moderate <8%) — a real cause should scale.

Honest by construction: small n → this can reach 'candidate' or 'refuted', never 'certified'.
Prices: Binance daily klines (public, no key). Pure stdlib + urllib.
"""
from __future__ import annotations

import json
import statistics
import urllib.request
from datetime import datetime, timedelta, timezone

_BINANCE = "https://data-api.binance.vision/api/v3/klines"

# ── Curated event set (symbol, ISO date, approx % of circulating supply, class) ──
# Sources (verified 2026-07-15):
#   TIA  2024-10-31 ~82%  dropstab/holder.io/coincarp/mitrade
#   ENA  2025-03-06 ~66%  cryptopolitan ("2.07B, 66.19%, March 3-10 2025")
#   ALT  2024-07-25 ~42%  crypto.news
#   STRK 2024-04-15 8.8%  cryptobriefing; STRK 2024-08-15 3.95% / 2024-12-13 2.83% fxstreet
#   ARB  2024-04-16 3.5%  cryptobriefing; ARB 2024-08-16 2.77% coinedition
#   APT  2024-08-14 2.40% coinedition; APT 2024-12-12 2.11% fxstreet
#   MANTA 2024-07-19       tradingview/coinmarketcal
EVENTS = [
    ("TIA",  "2024-10-31", 82.0, "large"),
    ("ENA",  "2025-03-06", 66.0, "large"),
    ("ALT",  "2024-07-25", 42.0, "large"),
    ("STRK", "2024-04-15",  8.8, "large"),
    ("MANTA","2024-07-19",  6.0, "moderate"),   # % not published; conservative mid
    ("ARB",  "2024-04-16",  3.5, "moderate"),
    ("STRK", "2024-08-15",  3.95,"moderate"),
    ("STRK", "2024-12-13",  2.83,"moderate"),
    ("ARB",  "2024-08-16",  2.77,"moderate"),
    ("APT",  "2024-08-14",  2.40,"moderate"),
    ("APT",  "2024-12-12",  2.11,"moderate"),
]

HORIZON = 30
CONTROL_LAG = 60   # control window starts 60d before the event (t-60 → t-30)


def _fetch_daily(symbol: str, start: datetime, days: int) -> dict:
    """{date_iso: close} for `days` daily candles from `start`. Binance USDT pair."""
    pair = symbol + "USDT"
    start_ms = int(start.replace(tzinfo=timezone.utc).timestamp() * 1000)
    url = (f"{_BINANCE}?symbol={pair}&interval=1d&startTime={start_ms}"
           f"&limit={days + 3}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research"})
        with urllib.request.urlopen(req, timeout=25) as r:
            rows = json.loads(r.read())
    except Exception as e:
        print(f"  ! fetch {pair} @ {start.date()}: {e}")
        return {}
    out = {}
    for k in rows:
        d = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).date().isoformat()
        out[d] = float(k[4])
    return out


def _ret(closes: dict, d0: datetime, d1: datetime):
    """Return over [d0, d1] using nearest available close on/after each date."""
    def near(dt):
        for i in range(4):
            k = (dt + timedelta(days=i)).date().isoformat()
            if k in closes:
                return closes[k]
        return None
    p0, p1 = near(d0), near(d1)
    if not (p0 and p1 and p0 > 0):
        return None
    return p1 / p0 - 1.0


def run() -> dict:
    # BTC panel once, wide enough for all events + controls.
    earliest = min(datetime.fromisoformat(e[1]) for e in EVENTS) - timedelta(days=CONTROL_LAG + 5)
    span_days = (datetime(2025, 5, 1) - earliest).days + HORIZON + 5
    btc = _fetch_daily("BTC", earliest, span_days)

    rows = []
    for sym, dstr, pct, klass in EVENTS:
        t = datetime.fromisoformat(dstr)
        closes = _fetch_daily(sym, t - timedelta(days=CONTROL_LAG + 5), CONTROL_LAG + HORIZON + 10)
        if not closes:
            continue
        # event-window token + BTC returns
        tok_ev = _ret(closes, t, t + timedelta(days=HORIZON))
        btc_ev = _ret(btc, t, t + timedelta(days=HORIZON))
        # control-window (t-60 → t-30)
        tok_ctl = _ret(closes, t - timedelta(days=CONTROL_LAG), t - timedelta(days=CONTROL_LAG - HORIZON))
        btc_ctl = _ret(btc, t - timedelta(days=CONTROL_LAG), t - timedelta(days=CONTROL_LAG - HORIZON))
        if tok_ev is None or btc_ev is None:
            print(f"  ! no price window for {sym} {dstr}")
            continue
        alpha_ev = tok_ev - btc_ev
        alpha_ctl = (tok_ctl - btc_ctl) if (tok_ctl is not None and btc_ctl is not None) else None
        effect = (alpha_ev - alpha_ctl) if alpha_ctl is not None else None
        rows.append({"symbol": sym, "date": dstr, "pct_circ": pct, "class": klass,
                     "tok_ret_30d": tok_ev, "btc_ret_30d": btc_ev,
                     "alpha_30d": alpha_ev, "control_alpha_30d": alpha_ctl,
                     "effect_vs_control": effect})

    def _agg(sample, key):
        xs = [r[key] for r in sample if r.get(key) is not None]
        if not xs:
            return None
        return {"n": len(xs), "mean_pct": round(statistics.mean(xs) * 100, 2),
                "median_pct": round(statistics.median(xs) * 100, 2),
                "neg_rate_pct": round(sum(1 for x in xs if x < 0) / len(xs) * 100, 1)}

    large = [r for r in rows if r["class"] == "large"]
    summary = {
        "all_events": _agg(rows, "alpha_30d"),
        "all_effect_vs_control": _agg(rows, "effect_vs_control"),
        "large_events_alpha": _agg(large, "alpha_30d"),
        "large_events_effect": _agg(large, "effect_vs_control"),
        "moderate_events_alpha": _agg([r for r in rows if r["class"] == "moderate"], "alpha_30d"),
    }
    return {"rows": rows, "summary": summary}


if __name__ == "__main__":
    res = run()
    print("\n=== EVENT ROWS ===")
    for r in res["rows"]:
        ce = "" if r["effect_vs_control"] is None else f"{r['effect_vs_control']*100:+.1f}%"
        print(f"  {r['symbol']:5} {r['date']}  {r['class']:8} pct={r['pct_circ']:>5}  "
              f"alpha30d={r['alpha_30d']*100:+6.1f}%  effect_vs_ctrl={ce}")
    print("\n=== SUMMARY ===")
    print(json.dumps(res["summary"], indent=2))
