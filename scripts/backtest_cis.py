#!/usr/bin/env python3
"""
CIS cross-sectional backtest — the honest ruler.

Joins point-in-time CIS scores (signal, as-of date, no lookahead) to forward
OHLCV returns, simulates a cross-sectional strategy net of trading cost, and
compares to buy-and-hold benchmarks. First read on whether CIS adds beta+ — or
admits beta-. Cross-sectional selection (which assets) over market timing
(when in/out), continuous sizing, turnover-aware — by design avoids the
binary-regime-timing failure mode that produces beta-.

Usage: SUPABASE_KEY=... python scripts/backtest_cis.py
"""
import os, sys
import httpx
import numpy as np
import pandas as pd

SB_URL = "https://soupjamxlfsmgmmtoeok.supabase.co/rest/v1"
SB_KEY = os.environ["SUPABASE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

REBAL = "W-FRI"          # weekly rebalance
TOP_FRAC = 0.25          # hold top quartile by CIS
FEE_BPS = 20             # cost per side, basis points
ANN = 52                 # periods per year (weekly)


def fetch(table, select, extra=""):
    rows, off = [], 0
    while True:
        r = httpx.get(f"{SB_URL}/{table}",
                      params={"select": select, "limit": 1000, "offset": off},
                      headers=HEAD, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows += batch
        if len(batch) < 1000:
            break
        off += 1000
    return pd.DataFrame(rows)


def metrics(returns):
    """returns: per-period simple returns (pd.Series)."""
    eq = (1 + returns).cumprod()
    total = eq.iloc[-1] - 1
    yrs = len(returns) / ANN
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    vol = returns.std() * np.sqrt(ANN)
    sharpe = (returns.mean() * ANN) / (returns.std() * np.sqrt(ANN)) if returns.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return dict(total=total, cagr=cagr, vol=vol, sharpe=sharpe, maxdd=dd)


def main():
    print("Fetching data…")
    ohlcv = fetch("ohlcv_daily", "symbol,trade_date,close")
    cis = fetch("cis_scores", "symbol,recorded_at,score", "")
    print(f"  ohlcv rows={len(ohlcv)} syms={ohlcv.symbol.nunique()}")
    print(f"  cis   rows={len(cis)} syms={cis.symbol.nunique()}")

    # ── price panel (symbol × date), resampled to rebalance dates ──
    ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
    ohlcv["close"] = pd.to_numeric(ohlcv["close"], errors="coerce")
    px = ohlcv.pivot_table(index="trade_date", columns="symbol", values="close").sort_index()
    px = px.resample(REBAL).last().dropna(how="all")

    # ── CIS panel as-of each rebalance date (no lookahead) ──
    cis["recorded_at"] = pd.to_datetime(cis["recorded_at"], format="ISO8601", utc=True).dt.tz_localize(None)
    cis["score"] = pd.to_numeric(cis["score"], errors="coerce")
    cis = cis.dropna(subset=["score"]).sort_values("recorded_at")
    # daily last score per symbol, then forward-fill onto rebalance dates
    cis_daily = (cis.set_index("recorded_at").groupby("symbol")["score"]
                 .resample("D").last().unstack(0).ffill())
    cis_on = cis_daily.reindex(px.index, method="ffill")

    # universe = assets with BOTH price and CIS
    syms = sorted(set(px.columns) & set(cis_on.columns))
    px, cis_on = px[syms], cis_on[syms]
    print(f"  backtest universe = {len(syms)} assets, {len(px)} weekly periods "
          f"({px.index.min().date()} → {px.index.max().date()})")

    fwd = px.pct_change().shift(-1)        # return realized over NEXT period
    fee = FEE_BPS / 1e4

    def run(weight_fn, label):
        prev_w = pd.Series(0.0, index=syms)
        rets, turns = [], []
        for d in px.index[:-1]:
            scores = cis_on.loc[d].dropna()
            avail = [s for s in scores.index if pd.notna(fwd.loc[d, s])]
            scores = scores[avail]
            if len(scores) < 4:
                rets.append(0.0); turns.append(0.0); continue
            w = weight_fn(scores).reindex(syms).fillna(0.0)
            turnover = (w - prev_w).abs().sum()
            gross = (w * fwd.loc[d]).sum()
            net = gross - turnover * fee
            rets.append(net); turns.append(turnover); prev_w = w
        r = pd.Series(rets, index=px.index[:-1])
        m = metrics(r); m["turnover"] = float(np.mean(turns))
        print(f"\n[{label}]")
        print(f"  net total {m['total']*100:6.1f}%   CAGR {m['cagr']*100:6.1f}%   "
              f"Sharpe {m['sharpe']:.2f}   maxDD {m['maxdd']*100:6.1f}%   "
              f"avg turnover/wk {m['turnover']*100:.0f}%")
        return m, r

    def topq_ciswt(scores):
        k = max(1, int(len(scores) * TOP_FRAC))
        top = scores.sort_values(ascending=False).head(k)
        return top / top.sum()

    def topq_eqwt(scores):
        k = max(1, int(len(scores) * TOP_FRAC))
        top = scores.sort_values(ascending=False).head(k)
        return pd.Series(1.0 / len(top), index=top.index)

    def eqw_all(scores):
        return pd.Series(1.0 / len(scores), index=scores.index)

    # ── Rank-IC: does CIS predict forward return cross-sectionally? ──
    ics = []
    for d in px.index[:-1]:
        s = cis_on.loc[d].dropna()
        f = fwd.loc[d].reindex(s.index).dropna()
        common = s.index.intersection(f.index)
        if len(common) >= 5:
            ics.append(s[common].rank().corr(f[common].rank()))  # spearman = pearson of ranks
    ics = pd.Series(ics).dropna()
    ic_mean = ics.mean(); ic_t = ic_mean / (ics.std() / np.sqrt(len(ics))) if ics.std() > 0 else np.nan
    print("\n" + "=" * 64)
    print(f"RANK-IC (CIS vs forward weekly return): mean={ic_mean:+.3f}  "
          f"t-stat={ic_t:+.2f}  n={len(ics)}  hit-rate={(ics>0).mean()*100:.0f}%")
    print("  (IC>0 = signal has cross-sectional edge; ~0 = no predictive power)")

    print("\n" + "=" * 64)
    s1, r1 = run(topq_ciswt, "STRATEGY: top-quartile CIS, CIS-weighted")
    s2, r2 = run(topq_eqwt, "STRATEGY: top-quartile CIS, equal-weighted")
    b1, rb = run(eqw_all, "BENCHMARK: equal-weight all (hold)")

    # BTC buy-hold benchmark
    if "BTC" in px.columns:
        btc = px["BTC"].pct_change().shift(-1).reindex(px.index[:-1]).fillna(0.0)
        mb = metrics(btc)
        print(f"\n[BENCHMARK: BTC buy & hold]")
        print(f"  net total {mb['total']*100:6.1f}%   CAGR {mb['cagr']*100:6.1f}%   "
              f"Sharpe {mb['sharpe']:.2f}   maxDD {mb['maxdd']*100:6.1f}%")

    print("\n" + "=" * 64)
    print("VERDICT (excess vs equal-weight-all benchmark):")
    for lbl, m in [("top-q CIS-wt", s1), ("top-q eq-wt", s2)]:
        ex = (m["total"] - b1["total"]) * 100
        tag = "beta+ ✅" if ex > 0 else "beta- ❌"
        print(f"  {lbl:16s} excess {ex:+6.1f}%   Sharpe {m['sharpe']:.2f} vs {b1['sharpe']:.2f}   {tag}")
    print("\nNOTE: 1yr / 25 assets — small sample, in-sample, no slippage model. Directional only.")


if __name__ == "__main__":
    main()
