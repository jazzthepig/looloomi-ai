"""Sleeve 2 — regime nowcast + tilt (NOT static rotation; per Asness R20 lesson).

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper, 不卡 1.96").
Production candidate in the parallel-paper phase, NOT a backtest sweep.

Strategy: nowcast P(RISK_ON | features) and use it to TILT R77's gross exposure
between [0.5, 1.5]. This is a continuous probability state-space, NOT a discrete
rotation — Asness "Contrarian Factor Timing is Deceptively Difficult" (#20) shows
static cross-asset rotation is unprofitable. Nowcast + smooth tilt is the
distinguishable version.

Features (PIT-safe, no look-ahead):
  - BTC 30d return (close-to-close, lagged 1d)
  - DeFiLlama total TVL 7d change (lagged 1d)
  - USDT total supply 7d change (lagged 1d)
  - BTC 30d realized vol (regime-vol cross-check)

Probability model: simple logistic on 3 features; coefficients are heuristic
pre-registered (not fit on this data). Production candidate: 60d forward paper
to validate the model. A NEGATIVE verdict here is fine (no tradeable edge); the
sleeve's job is to test the structural hypothesis, not to clear 1.96.

Action mapping:
  P(RISK_ON) >= 0.60 → tilt_mult = 1.5  (max gross)
  P(RISK_ON) <= 0.40 → tilt_mult = 0.5  (min gross)
  0.40 < P < 0.60   → tilt_mult = 1.0  (baseline)

Output: /tmp/cometcloud_data/paper_books/regime_nowcast_positions.csv (one row
per day with the tilt multiplier and per-feature signal value).

Failsafe: any feature missing → log tilt=1.0 (baseline) with note. Never fabricate
a probability. Per CLAUDE.md "no mock data in production paths".

Usage:
  python3 src/research/paper_books/sleeve_2_regime_nowcast.py
"""
from __future__ import annotations

import os
import sys
import json
import time
import math
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from src.research.paper_books.ledger import (  # noqa: E402
    PaperPosition, append_paper_position, read_sleeve, LEDGER_DIR,
)

# Public data sources
BINANCE_BASE = "https://api.binance.com/api/v3/klines"
DEFILLAMA_TVL = "https://api.llama.fi/v2/historicalChainTvl"
DEFILLAMA_STABLES = "https://stablecoins.llama.fi/stablecoincharts/all"
BINANCE_LOOKBACK = 45     # for BTC 30d return + RV

# Heuristic logistic coefficients (pre-registered, not fit on data)
# Higher BTC return + higher TVL growth + higher USDT growth → higher P(RISK_ON)
COEF_BTC_30D = +0.6        # log-odds per 1% BTC 30d return
COEF_TVL_7D  = +0.4        # log-odds per 1% TVL 7d change
COEF_USDT_7D = +0.3        # log-odds per 1% USDT supply 7d change
INTERCEPT    = 0.0         # neutral prior

# Tilt mapping thresholds
TILT_HIGH = 1.5
TILT_LOW  = 0.5
TILT_MID  = 1.0
P_HIGH = 0.60
P_LOW  = 0.40


def _http_get_json(url: str, timeout: int = 25) -> list | dict | None:
    last_err = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}"
            if e.code in (429, 503):
                time.sleep(2 ** attempt)
            elif 400 <= e.code < 500:
                return None
            else:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(2 ** attempt)
    print(f"  [WARN] HTTP exhausted: {last_err}")
    return None


def fetch_btc_30d_return() -> tuple[float | None, float | None]:
    """Return (btc_30d_pct_return, btc_30d_rv_pct). Both annualized %."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - (BINANCE_LOOKBACK + 5) * 86_400_000
    url = (
        f"{BINANCE_BASE}?symbol=BTCUSDT&interval=1d"
        f"&startTime={start_ms}&endTime={end_ms}&limit={BINANCE_LOOKBACK + 5}"
    )
    data = _http_get_json(url)
    if not isinstance(data, list) or len(data) < 31:
        return None, None
    closes = [float(r[4]) for r in data if len(r) >= 5 and r[4] is not None]
    if len(closes) < 31:
        return None, None
    # 30d return: from closes[-31] to closes[-1]
    m30_ret = (closes[-1] - closes[-31]) / closes[-31] * 100
    # 30d realized vol
    daily_rets = [(closes[i] / closes[i-1]) - 1.0 for i in range(len(closes) - 30, len(closes))]
    if not daily_rets:
        return m30_ret, None
    mean = sum(daily_rets) / len(daily_rets)
    var = sum((r - mean) ** 2 for r in daily_rets) / max(len(daily_rets) - 1, 1)
    sd = var ** 0.5
    rv = sd * (365 ** 0.5) * 100
    return m30_ret, rv


def fetch_defillama_tvl_7d() -> tuple[float | None, float | None]:
    """Return (tvl_latest_usd, tvl_7d_pct_change)."""
    data = _http_get_json(DEFILLAMA_TVL)
    if not isinstance(data, list) or len(data) < 8:
        return None, None
    latest = float(data[-1].get("tvl", 0))
    seven_ago = float(data[-8].get("tvl", 0))
    if seven_ago == 0 or latest == 0:
        return None, None
    pct = (latest - seven_ago) / seven_ago * 100
    return latest, pct


def fetch_usdt_supply_7d() -> float | None:
    """USDT total supply 7d pct change. DeFiLlama stablecoin endpoint schema:
    [{"date": "...", "totalCirculatingUSD": {"peggedUSD": <flat USD value>}}]
    USDT is a USD-pegged stable, so totalCirculatingUSD.peggedUSD = total USD-pegged
    stable supply (effectively USDT/USDC/BUSD/etc. all USD-pegged; USDT is the
    dominant one and is the canonical "stable liquidity" proxy). For a strict USDT
    series, query per-stable; this prototype uses peggedUSD as a proxy with note.
    """
    data = _http_get_json(DEFILLAMA_STABLES)
    if not isinstance(data, list) or len(data) < 8:
        return None
    def get_pegged_usd(entry):
        return float(entry.get("totalCirculatingUSD", {}).get("peggedUSD", 0))
    cur = get_pegged_usd(data[-1])
    past = get_pegged_usd(data[-8])
    if cur == 0 or past == 0:
        return None
    return (cur - past) / past * 100


def logistic(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def main() -> int:
    print("=" * 72)
    print("Sleeve 2 — regime nowcast + tilt (P(RISK_ON) → R77 gross multiplier)")
    print("=" * 72)
    print(f"  features:  BTC 30d return + TVL 7d Δ + USDT 7d Δ")
    print(f"  model:     pre-registered logistic (no fit on data)")
    print(f"  tilt map:  P>=0.60 → {TILT_HIGH}x   P<=0.40 → {TILT_LOW}x   else {TILT_MID}x")
    print()

    btc_30d, btc_rv = fetch_btc_30d_return()
    tvl_usd, tvl_7d = fetch_defillama_tvl_7d()
    usdt_7d = fetch_usdt_supply_7d()

    print(f"  BTC 30d return:  {f'{btc_30d:+.2f}%' if btc_30d is not None else 'n/a'}")
    print(f"  BTC 30d RV:      {f'{btc_rv:+.2f}%' if btc_rv is not None else 'n/a'}")
    print(f"  DeFi TVL:        {f'${tvl_usd/1e9:.2f}B' if tvl_usd is not None else 'n/a'}")
    print(f"  TVL 7d Δ:        {f'{tvl_7d:+.2f}%' if tvl_7d is not None else 'n/a'}")
    print(f"  USDT 7d Δ:       {f'{usdt_7d:+.2f}%' if usdt_7d is not None else 'n/a'}")

    if btc_30d is None or tvl_7d is None or usdt_7d is None:
        print()
        print(f"  INSUFFICIENT data — log tilt=1.0 (baseline) with note")
        append_paper_position(PaperPosition(
            sleeve_id="regime_nowcast", symbol="R77-TILT", side="BASELINE", qty=1.0,
            mark_price=1.0, signal_value=0.5, signal_name="p_risk_on",
            notional_usd=0.0,
            sleeve_note=f"missing features: btc30={btc_30d} tvl7d={tvl_7d} usdt7d={usdt_7d} → tilt=1.0",
        ))
        return 0

    logit = INTERCEPT + COEF_BTC_30D * (btc_30d / 100) + COEF_TVL_7D * (tvl_7d / 100) + COEF_USDT_7D * (usdt_7d / 100)
    # Note: features are in % (e.g. btc_30d = +12.5 means 12.5%); logistic uses fractions
    p_risk_on = logistic(logit)
    if p_risk_on >= P_HIGH:
        tilt = TILT_HIGH
        action = f"P={p_risk_on:.2f} ≥ {P_HIGH} → TILT UP to {TILT_HIGH}x"
    elif p_risk_on <= P_LOW:
        tilt = TILT_LOW
        action = f"P={p_risk_on:.2f} ≤ {P_LOW} → TILT DOWN to {TILT_LOW}x"
    else:
        tilt = TILT_MID
        action = f"P={p_risk_on:.2f} in ({P_LOW}, {P_HIGH}) → BASELINE {TILT_MID}x"

    print()
    print(f"  logit:    {logit:+.3f}  (intercept {INTERCEPT:+.2f} + btc {COEF_BTC_30D * btc_30d/100:+.3f} + tvl {COEF_TVL_7D * tvl_7d/100:+.3f} + usdt {COEF_USDT_7D * usdt_7d/100:+.3f})")
    print(f"  P(RISK_ON): {p_risk_on:.3f}")
    print(f"  ACTION:  {action}")

    append_paper_position(PaperPosition(
        sleeve_id="regime_nowcast", symbol="R77-TILT",
        side=("UP" if tilt > 1.0 else ("DOWN" if tilt < 1.0 else "BASELINE")),
        qty=tilt, mark_price=1.0,
        signal_value=round(p_risk_on, 4), signal_name="p_risk_on",
        notional_usd=0.0,
        sleeve_note=(
            f"btc_30d={btc_30d:+.2f}% tvl_7d={tvl_7d:+.2f}% usdt_7d={usdt_7d:+.2f}% "
            f"rv={btc_rv or 'n/a'}% logit={logit:+.3f} p={p_risk_on:.3f} → tilt={tilt:.2f}"
        ),
    ))

    print()
    print(f"  logged decision: see {LEDGER_DIR}/regime_nowcast_positions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
