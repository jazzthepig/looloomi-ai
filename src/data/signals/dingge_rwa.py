"""
顶格 (funding-at-cap) monitor + backtest for tokenized-RWA perps (Seth, 2026-07-11).
====================================================================================

Jazz-derived signal, validated (experiment_runs: funding_dingge_reversal). The setup:

  Tokenized stock/commodity perps (MSTR, COIN, NVDA, TSLA, gold, silver, crude, ...)
  trade 24/7 on-chain, but their UNDERLYING is closed on weekends / after-hours. When a
  move hits while TradFi is shut, all directional demand piles into the only open venue —
  the on-chain perp — with no arbitrage back to the closed underlying to relieve it, and
  funding pins at the exchange cap (顶格): 500–1170% annualized. That extreme, unsustainable
  carry forces the crowded side to unwind → the OLD trend exhausts → a NEW trend forms.

  The new trend's DIRECTION is not the reversal and not price-momentum — it's set by 量能
  (VOLUME/energy): volume expands → it trends up; volume dead → it doesn't rise. Validated
  n=24 episodes: vol-expand forward-trend beat vol-dead in BOTH IS and OOS halves; corr
  noisy at this n (young instrument class). Real, moderate, accumulate-forward candidate.

This module: (1) the live monitor — which RWA perps are AT 顶格 now + the volume read +
direction lean; (2) the backtest — reproduce/extend the episode study as data accumulates.
Data: Binance fapi funding + klines (RWA perps are USDT-margined futures). Pure numpy.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict

import numpy as np

# Tokenized equity/commodity perps — the structural home of 顶格 (24/7 vs closed underlying).
RWA_PERPS = [
    "MSTRUSDT", "COINUSDT", "NVDAUSDT", "TSLAUSDT", "HOODUSDT", "INTCUSDT", "AMDUSDT",
    "MUUSDT", "SKHYNIXUSDT", "SNDKUSDT", "SOXLUSDT", "SAMSUNGUSDT", "CBRSUSDT", "KORUUSDT",
    "CRCLUSDT", "LITEUSDT", "XAUUSDT", "XAGUSDT", "CLUSDT", "BZUSDT", "METAUSDT",
    "AAPLUSDT", "GOOGLUSDT", "AMZNUSDT", "SPXUSDT", "EWYUSDT", "MARAUSDT", "PLTRUSDT",
]

# 热点行业 / sector-thematic ETF perps (24/7 on-chain) — the industry-rotation tracking layer we
# lacked. Distinct from single-name RWA: these are clean SECTOR / REGION / INDEX exposure, the
# right unit for industry rotation (multi_asset_study: adds an independent bet, ENB 3.87; sector
# sleeve orthogonal to crypto 0.13 / commodity −0.13). Tracked on the board + funding monitor.
SECTOR_ETF_PERPS = [
    "XLEUSDT",   # energy sector
    "XBIUSDT",   # biotech
    "URNMUSDT",  # uranium / nuclear
    "EWZUSDT",   # Brazil
    "EWJUSDT",   # Japan
    "QQQUSDT",   # Nasdaq-100 (tech)
    "IWMUSDT",   # small-cap (Russell 2000)
    "DIAUSDT",   # Dow / large-cap value
]
RWA_PERPS = RWA_PERPS + SECTOR_ETF_PERPS

_FAPI = "https://fapi.binance.com/fapi/v1"
CAP_FUNDING = 0.004          # ≥0.4% / 8h (~440%+ annualized) = 顶格 territory (near the 0.5% clamp)
_VOL_WINDOW = 15             # days for the 量能 read (post-event vs pre-event)


def _client():
    import httpx
    return httpx.Client(timeout=25, headers={"User-Agent": "cometcloud"})


def _funding(client, sym: str, limit: int = 1000) -> list[tuple[int, float]]:
    r = client.get(f"{_FAPI}/fundingRate", params={"symbol": sym, "limit": limit})
    j = r.json()
    return [(int(x["fundingTime"]), float(x["fundingRate"])) for x in j] if isinstance(j, list) else []


def _klv(client, sym: str, limit: int = 500) -> dict:
    r = client.get(f"{_FAPI}/klines", params={"symbol": sym, "interval": "1d", "limit": limit})
    j = r.json()
    return ({dt.date.fromtimestamp(int(k[0]) / 1000): (float(k[4]), float(k[7])) for k in j}
            if isinstance(j, list) else {})


def _episodes(funding: list[tuple[int, float]], gap_days: int = 14) -> list[tuple[dt.date, int]]:
    """顶格 episodes in BOTH directions. side +1 = funding at POSITIVE cap (longs pay max =
    crowded longs → flush risk); side -1 = NEGATIVE cap (shorts pay max = crowded shorts →
    squeeze risk). Returns [(date, side), ...], de-clustered within `gap_days`."""
    caps = sorted((dt.date.fromtimestamp(ts / 1000), (1 if v >= CAP_FUNDING else -1))
                  for ts, v in funding if abs(v) >= CAP_FUNDING)
    ep: list[tuple[dt.date, int]] = []
    for d, side in caps:
        if not ep or (d - ep[-1][0]).days >= gap_days:
            ep.append((d, side))
    return ep


# ── Live monitor ─────────────────────────────────────────────────────────────

@dataclass
class DinggeState:
    symbol: str
    at_cap: bool                 # funding pinned at either cap in the last ~3 days
    side: str                    # "long_crowded" (+cap, flush risk) / "short_crowded" (-cap, squeeze) / "—"
    peak_abs_funding_annualized_pct: float
    days_since_cap: int | None
    volume_ratio: float | None   # recent vol vs pre-window — the 量能 read
    lean: str                    # up_bias / down_bias / neutral
    note: str


def monitor_symbol(client, sym: str) -> DinggeState | None:
    fu = _funding(client, sym, limit=200)          # ~66 days of 8h funding
    K = _klv(client, sym, limit=120)
    if not fu or not K:
        return None
    recent = fu[-9:]                                # last ~3 days (9×8h)
    cap_now = [v for _, v in recent if abs(v) >= CAP_FUNDING]
    at_cap = bool(cap_now)
    peak_abs_ann = max((abs(v) for _, v in fu), default=0.0) * 3 * 365 * 100
    ep = _episodes(fu)
    today = dt.date.today()
    last_date, last_side = (ep[-1] if ep else (None, 0))
    days_since = (today - last_date).days if last_date else None
    side_str = "long_crowded" if last_side > 0 else ("short_crowded" if last_side < 0 else "—")
    kd = sorted(K)
    vol_ratio = None
    if len(kd) >= 2 * _VOL_WINDOW:
        volpre = np.mean([K[x][1] for x in kd[-2 * _VOL_WINDOW:-_VOL_WINDOW]])
        volpost = np.mean([K[x][1] for x in kd[-_VOL_WINDOW:]])
        vol_ratio = round(volpost / volpre, 2) if volpre > 0 else None
    lean = "neutral"
    note = "no recent 顶格"
    if last_date and days_since is not None and days_since <= 45:
        vol_up = vol_ratio is not None and vol_ratio > 1.1
        vol_dead = vol_ratio is not None and vol_ratio < 0.9
        # short-crowded → squeeze up (esp. w/ volume); long-crowded → flush down unless volume comes in
        if last_side < 0:      # crowded shorts
            lean = "up_bias" if not vol_dead else "neutral"      # squeeze; dead volume dampens
        else:                   # crowded longs
            lean = "up_bias" if vol_up else ("down_bias" if vol_dead else "neutral")
        note = (f"顶格 {days_since}d ago ({side_str}) — new trend forming; "
                f"量能 {'expanding' if vol_up else 'dead' if vol_dead else 'neutral'} → {lean}")
    elif at_cap:
        s = "shorts" if cap_now[-1] < 0 else "longs"
        note = f"AT 顶格 now (crowded {s}) — old trend exhausting; wait for reset, then read 量能"
    return DinggeState(sym, at_cap, side_str, round(peak_abs_ann, 0), days_since, vol_ratio, lean, note)


def scan_live(symbols: list[str] | None = None) -> list[dict]:
    """Live 顶格 board across the RWA perps. Returns states, active/recent first."""
    syms = symbols or RWA_PERPS
    out: list[DinggeState] = []
    with _client() as client:
        for s in syms:
            try:
                st = monitor_symbol(client, s)
                if st:
                    out.append(st)
            except Exception:
                continue
    out.sort(key=lambda s: (not s.at_cap, s.days_since_cap if s.days_since_cap is not None else 999))
    return [asdict(s) for s in out]


# ── Backtest (reproduce + extend the episode study) ─────────────────────────

def backtest(symbols: list[str] | None = None) -> dict:
    """Episode study: after each 顶格, does 量能 (post-event volume ratio) predict the new
    trend [+15..+35d]? Returns per-half (IS/OOS) vol-gated economics."""
    syms = symbols or RWA_PERPS
    rows = []
    with _client() as client:
        for s in syms:
            fu = _funding(client, s); K = _klv(client, s)
            if not fu or not K:
                continue
            kd = sorted(K)
            for d, side in _episodes(fu):
                fut = [x for x in kd if x >= d]; pre = [x for x in kd if x < d]
                if len(fut) < 36 or len(pre) < 15:
                    continue
                volpre = np.mean([K[x][1] for x in pre[-15:]]); volpost = np.mean([K[x][1] for x in fut[1:16]])
                if volpre <= 0:
                    continue
                rows.append((d, side, volpost / volpre, (K[fut[35]][0] - K[fut[15]][0]) / K[fut[15]][0]))
    rows.sort(key=lambda r: r[0])
    if len(rows) < 6:
        return {"n": len(rows), "status": "insufficient_episodes"}
    vr = np.array([r[2] for r in rows]); nt = np.array([r[3] for r in rows]); sd = np.array([r[1] for r in rows])

    def leg(v, t):
        hi = v > np.median(v)
        return {"n": int(len(t)), "corr": round(float(np.corrcoef(v, t)[0, 1]), 2),
                "vol_expand_newtrend_pct": round(float(t[hi].mean() * 100), 1),
                "vol_dead_newtrend_pct": round(float(t[~hi].mean() * 100), 1),
                "gated_strat_mean_pct": round(float(np.where(hi, t, -t).mean() * 100), 1)}

    sp = int(len(rows) * 0.6)
    out = {"n": len(rows), "n_long_crowded": int((sd > 0).sum()), "n_short_crowded": int((sd < 0).sum()),
           "all": leg(vr, nt), "IS": leg(vr[:sp], nt[:sp]), "OOS": leg(vr[sp:], nt[sp:])}
    # by side: crowded shorts should skew squeeze-up, crowded longs flush
    out["short_crowded_newtrend_pct"] = round(float(nt[sd < 0].mean() * 100), 1) if (sd < 0).any() else None
    out["long_crowded_newtrend_pct"] = round(float(nt[sd > 0].mean() * 100), 1) if (sd > 0).any() else None
    return out


if __name__ == "__main__":
    import json, sys
    if "--backtest" in sys.argv:
        print(json.dumps(backtest(), indent=2))
    else:
        board = scan_live()
        print(f"顶格 board — {len(board)} RWA perps\n")
        for s in board[:16]:
            flag = "🔴AT-CAP" if s["at_cap"] else (f"{s['days_since_cap']}d" if s["days_since_cap"] is not None else "—")
            print(f"  {s['symbol']:<12} {flag:<8} {s['side']:<14} volR={s['volume_ratio']} "
                  f"lean={s['lean']:<9} — {s['note']}")
