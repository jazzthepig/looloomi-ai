"""
Miner-Economics (Mining-Cost) Anchor Study — upstream-cause test (Seth 2026-07-15).
==================================================================================

Jazz flagged mining cost (挖矿成本) as a key upstream anchor I'd been dodging. This tests
it as a real CAUSE (production economics), not a price reflection:

  H: when miners are stressed — revenue depressed vs their trailing year (LOW Puell
     Multiple) / price near the difficulty-implied production cost — forward returns are
     ELEVATED (capitulation → difficulty drop → supply relief → cycle bottom). When miners
     are flush (HIGH Puell), forward returns are muted/negative (distribution).

Two independent measures of the same cause:
  1. PUELL MULTIPLE = daily issuance value (USD) / 365d MA of it. Exact from price +
     the known block-reward schedule; NO cost estimate, NO rig-efficiency confound.
  2. DIFFICULTY COST PROXY = price / (difficulty / reward), trend-normalised — a
     "hashprice"-like distance-to-production-cost. Robustness cross-check (efficiency
     drift handled by normalising against a trailing mean).

Test: Spearman IC(signal, forward-return) + quintile bucket means + IS/OOS split.
BTC only (mining cost is a PoW/BTC-cycle lens → a gross-scale / risk timing overlay, not
cross-sectional selection). Real data: Binance daily + blockchain.com difficulty. Pure stdlib.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

_BINANCE = "https://data-api.binance.vision/api/v3/klines"
_DIFF = "https://api.blockchain.info/charts/difficulty?timespan=all&format=json&sampled=true"

# Block-reward schedule (halvings within our data window)
HALVINGS = [
    (datetime(2016, 7, 9), 12.5),
    (datetime(2020, 5, 11), 6.25),
    (datetime(2024, 4, 20), 3.125),
]
BLOCKS_PER_DAY = 144.0


def _reward(d: datetime) -> float:
    r = 12.5
    for dt_h, rw in HALVINGS:
        if d >= dt_h:
            r = rw
    return r


def _btc_daily() -> list[tuple[datetime, float]]:
    """Full BTC daily close history from Binance (paged)."""
    out = []
    start = int(datetime(2017, 8, 17, tzinfo=timezone.utc).timestamp() * 1000)
    while True:
        u = f"{_BINANCE}?symbol=BTCUSDT&interval=1d&startTime={start}&limit=1000"
        rows = json.loads(urllib.request.urlopen(u, timeout=25).read())
        if not rows:
            break
        for k in rows:
            d = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).replace(tzinfo=None)
            out.append((d, float(k[4])))
        if len(rows) < 1000:
            break
        start = rows[-1][0] + 86400000
    # dedupe by date
    seen = {}
    for d, p in out:
        seen[d.date()] = (d, p)
    return [seen[k] for k in sorted(seen)]


def _difficulty() -> dict:
    """{date: difficulty} from blockchain.com."""
    d = json.loads(urllib.request.urlopen(urllib.request.Request(_DIFF, headers={"User-Agent": "r"}), timeout=25).read())
    out = {}
    for pt in d.get("values", []):
        dt_ = datetime.fromtimestamp(pt["x"], tz=timezone.utc).date()
        out[dt_] = float(pt["y"])
    return out


def _spearman(xs, ys) -> float:
    n = len(xs)
    if n < 10:
        return float("nan")
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for i, idx in enumerate(order):
            r[idx] = i
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = (sum((rx[i] - mx) ** 2 for i in range(n)) * sum((ry[i] - my) ** 2 for i in range(n))) ** 0.5
    return num / den if den else float("nan")


def _buckets(sig, fwd, q=5):
    pairs = sorted(zip(sig, fwd))
    n = len(pairs)
    out = []
    for b in range(q):
        lo, hi = b * n // q, (b + 1) * n // q
        chunk = pairs[lo:hi]
        rets = [f for _, f in chunk]
        out.append({"bucket": b + 1, "n": len(chunk),
                    "sig_range": (round(chunk[0][0], 2), round(chunk[-1][0], 2)),
                    "mean_fwd_pct": round(sum(rets) / len(rets) * 100, 1) if rets else None,
                    "win_pct": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 0) if rets else None})
    return out


def run(horizon_days: int = 90):
    btc = _btc_daily()
    dates = [d for d, _ in btc]
    px = [p for _, p in btc]
    n = len(px)
    print(f"[data] BTC {dates[0].date()} → {dates[-1].date()}  ({n} days)")

    # ── Puell Multiple ──
    issuance_usd = [_reward(dates[i]) * BLOCKS_PER_DAY * px[i] for i in range(n)]
    puell = [None] * n
    for i in range(n):
        if i >= 365:
            ma = sum(issuance_usd[i - 365:i]) / 365
            puell[i] = issuance_usd[i] / ma if ma else None

    # ── Difficulty cost proxy (trend-normalised) ──
    diff = _difficulty()
    cost_ratio = [None] * n     # price / (difficulty/reward), normalised by 200d MA
    raw = [None] * n
    for i in range(n):
        dd = diff.get(dates[i].date())
        # nearest earlier difficulty within 7d
        j = 0
        while dd is None and j < 7:
            j += 1
            dd = diff.get((dates[i].date().replace() ), None)
            from datetime import timedelta
            dd = diff.get((dates[i].date() - timedelta(days=j)))
        if dd:
            raw[i] = px[i] / (dd / _reward(dates[i]))
    for i in range(n):
        if raw[i] is not None and i >= 200:
            window = [raw[k] for k in range(i - 200, i) if raw[k] is not None]
            if len(window) > 100:
                ma = sum(window) / len(window)
                cost_ratio[i] = raw[i] / ma if ma else None

    # ── forward returns ──
    fwd = [None] * n
    for i in range(n - horizon_days):
        fwd[i] = px[i + horizon_days] / px[i] - 1.0

    def _pair(sig):
        xs, ys = [], []
        for i in range(n):
            if sig[i] is not None and fwd[i] is not None:
                xs.append(sig[i]); ys.append(fwd[i])
        return xs, ys

    results = {}
    for name, sig in [("puell", puell), ("difficulty_cost_ratio", cost_ratio)]:
        xs, ys = _pair(sig)
        if len(xs) < 50:
            results[name] = {"status": "insufficient", "n": len(xs)}
            continue
        ic = _spearman(xs, ys)
        # IS/OOS split at 2022-01-01
        split_i = next((k for k in range(n) if dates[k] >= datetime(2022, 1, 1)), n // 2)
        is_xy = [(sig[i], fwd[i]) for i in range(split_i) if sig[i] is not None and fwd[i] is not None]
        oos_xy = [(sig[i], fwd[i]) for i in range(split_i, n) if sig[i] is not None and fwd[i] is not None]
        ic_is = _spearman([a for a, _ in is_xy], [b for _, b in is_xy]) if len(is_xy) > 30 else None
        ic_oos = _spearman([a for a, _ in oos_xy], [b for _, b in oos_xy]) if len(oos_xy) > 30 else None
        results[name] = {
            "n": len(xs), "horizon_d": horizon_days,
            "spearman_ic_full": round(ic, 3),
            "spearman_ic_IS_pre2022": round(ic_is, 3) if ic_is is not None else None,
            "spearman_ic_OOS_2022plus": round(ic_oos, 3) if ic_oos is not None else None,
            "buckets_low_to_high": _buckets(xs, ys),
        }
    return {"horizon_days": horizon_days, "results": results, "as_of": dates[-1].date().isoformat()}


if __name__ == "__main__":
    for H in (30, 90, 180):
        print(f"\n================  HORIZON {H}d  ================")
        res = run(H)
        for name, r in res["results"].items():
            if r.get("status") == "insufficient":
                print(f"\n[{name}] insufficient data (n={r['n']})"); continue
            print(f"\n[{name}] n={r['n']}  IC_full={r['spearman_ic_full']}  "
                  f"IC_IS={r['spearman_ic_IS_pre2022']}  IC_OOS={r['spearman_ic_OOS_2022plus']}")
            print("  bucket (low→high signal) → mean fwd return / win%:")
            for b in r["buckets_low_to_high"]:
                print(f"    Q{b['bucket']} sig{b['sig_range']}  n={b['n']:>4}  "
                      f"fwd={b['mean_fwd_pct']:>7}%  win={b['win_pct']}%")
