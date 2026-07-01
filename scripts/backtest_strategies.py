#!/usr/bin/env python3
"""
Strategy lab v2 — honest, net-of-cost, on real Supabase data.

Tests the thesis from the 4h engine (CIS=filter, trend=alpha, shorts to survive
bears) on the DAILY data we actually have (25 assets, 1yr). Market-neutral
long-short removes the −56% market beta so we can see if any factor has REAL
cross-sectional edge. Variants:
  1. CIS long-short (market-neutral)         — does CIS rank predict relative perf?
  2. Momentum long-short                      — does trend work cross-sectionally?
  3. Momentum + CIS-filter long-short         — the thesis (CIS gates trend)
  4. Combo (z(CIS)+z(mom)) long-short
  5. Long-only top-tercile + regime cash overlay (risk-off → cash)
Benchmarks: equal-weight hold, BTC hold.

Usage: SUPABASE_KEY=... python scripts/backtest_strategies.py
"""
import os
import numpy as np
import pandas as pd
import httpx

SB = "https://soupjamxlfsmgmmtoeok.supabase.co/rest/v1"
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
REBAL = "W-FRI"; ANN = 52; FEE = 20 / 1e4; MOM_LB = 8   # 8-week momentum lookback


def fetch(table, select):
    rows, off = [], 0
    while True:
        r = httpx.get(f"{SB}/{table}", params={"select": select, "limit": 1000, "offset": off}, headers=H, timeout=60)
        r.raise_for_status(); b = r.json(); rows += b
        if len(b) < 1000: break
        off += 1000
    return pd.DataFrame(rows)


def met(r):
    eq = (1 + r).cumprod(); yrs = len(r) / ANN
    return dict(tot=eq.iloc[-1] - 1, cagr=eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan,
                sharpe=(r.mean() * ANN) / (r.std() * np.sqrt(ANN)) if r.std() > 0 else np.nan,
                dd=(eq / eq.cummax() - 1).min())


def main():
    ohlcv = fetch("ohlcv_daily", "symbol,trade_date,close")
    cis = fetch("cis_scores", "symbol,recorded_at,score,macro_regime")
    ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
    ohlcv["close"] = pd.to_numeric(ohlcv["close"], errors="coerce")
    px = ohlcv.pivot_table(index="trade_date", columns="symbol", values="close").sort_index().resample(REBAL).last()

    cis["recorded_at"] = pd.to_datetime(cis["recorded_at"], format="ISO8601", utc=True).dt.tz_localize(None)
    cis["score"] = pd.to_numeric(cis["score"], errors="coerce")
    cis = cis.dropna(subset=["score"]).sort_values("recorded_at")
    cis_on = (cis.set_index("recorded_at").groupby("symbol")["score"].resample("D").last()
              .unstack(0).ffill().reindex(px.index, method="ffill"))
    # regime as-of each rebalance (most common across symbols that day)
    reg = (cis.dropna(subset=["macro_regime"]).set_index("recorded_at")["macro_regime"]
           .resample("D").last().ffill().reindex(px.index, method="ffill"))

    syms = sorted(set(px.columns) & set(cis_on.columns))
    px, cis_on = px[syms], cis_on[syms]
    ret = px.pct_change()
    fwd = ret.shift(-1)
    mom = px.pct_change(MOM_LB)            # trailing momentum (known at d)
    dates = px.index[MOM_LB:-1]
    print(f"universe={len(syms)} periods={len(dates)} ({dates.min().date()}→{dates.max().date()})")

    def zx(s):  # cross-sectional z-score
        return (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0

    def run_ls(factor_at, label, gate=None):
        prev = pd.Series(0.0, index=syms); rs, tu = [], []
        for d in dates:
            f = factor_at(d).dropna()
            f = f[[s for s in f.index if pd.notna(fwd.loc[d, s])]]
            if gate is not None:
                g = gate(d); f = f[[s for s in f.index if g.get(s, True)]]
            if len(f) < 6: rs.append(0.0); tu.append(0.0); continue
            n = max(1, len(f) // 3)
            longs = f.sort_values(ascending=False).head(n).index
            shorts = f.sort_values().head(n).index
            w = pd.Series(0.0, index=syms)
            w[longs] = 0.5 / len(longs); w[shorts] = -0.5 / len(shorts)
            tu.append((w - prev).abs().sum())
            rs.append((w * fwd.loc[d]).sum() - tu[-1] * FEE); prev = w
        r = pd.Series(rs, index=dates); m = met(r); m["turn"] = np.mean(tu)
        btc_corr = r.corr(fwd["BTC"].reindex(dates)) if "BTC" in px else np.nan
        print(f"\n[{label}]  net {m['tot']*100:+6.1f}%  Sharpe {m['sharpe']:+.2f}  "
              f"maxDD {m['dd']*100:5.1f}%  turn/wk {m['turn']*100:3.0f}%  βtoBTC {btc_corr:+.2f}")
        return m

    def run_longonly_regime(label):
        prev = pd.Series(0.0, index=syms); rs, tu = [], []
        for d in dates:
            risk_off = str(reg.get(d, "")).upper() in ("RISK_OFF", "TIGHTENING", "STAGFLATION")
            f = cis_on.loc[d].dropna(); f = f[[s for s in f.index if pd.notna(fwd.loc[d, s])]]
            w = pd.Series(0.0, index=syms)
            if not risk_off and len(f) >= 4:        # invested only when not risk-off
                n = max(1, len(f) // 3); top = f.sort_values(ascending=False).head(n).index
                w[top] = 1.0 / len(top)
            tu.append((w - prev).abs().sum()); rs.append((w * fwd.loc[d]).sum() - tu[-1] * FEE); prev = w
        r = pd.Series(rs, index=dates); m = met(r); m["turn"] = np.mean(tu)
        print(f"\n[{label}]  net {m['tot']*100:+6.1f}%  Sharpe {m['sharpe']:+.2f}  "
              f"maxDD {m['dd']*100:5.1f}%  turn/wk {m['turn']*100:3.0f}%")
        return m

    print("\n" + "=" * 70 + "\nLONG-SHORT market-neutral (removes market beta):")
    run_ls(lambda d: cis_on.loc[d], "1. CIS L/S")
    run_ls(lambda d: mom.loc[d], "2. Momentum L/S (8wk)")
    # 3. momentum, but only among CIS top-half (CIS as filter)
    def mom_cis_gate(d):
        c = cis_on.loc[d].dropna(); med = c.median()
        return {s: (c.get(s, -1e9) >= med) for s in syms}
    run_ls(lambda d: mom.loc[d], "3. Momentum L/S, CIS-filtered (top half)", gate=mom_cis_gate)
    run_ls(lambda d: zx(cis_on.loc[d]) + zx(mom.loc[d]), "4. Combo z(CIS)+z(mom) L/S")

    print("\n" + "=" * 70 + "\nLONG-ONLY with regime cash overlay:")
    run_longonly_regime("5. CIS top-tercile, cash in risk-off")

    print("\n" + "=" * 70 + "\nBENCHMARKS:")
    ew = ret.reindex(dates).mean(axis=1); m = met(ew)
    print(f"[equal-weight hold]  net {m['tot']*100:+6.1f}%  Sharpe {m['sharpe']:+.2f}  maxDD {m['dd']*100:5.1f}%")
    if "BTC" in px:
        b = ret["BTC"].reindex(dates); m = met(b)
        print(f"[BTC hold]           net {m['tot']*100:+6.1f}%  Sharpe {m['sharpe']:+.2f}  maxDD {m['dd']*100:5.1f}%")
    print("\nNOTE: 1yr/25 assets daily, in-sample, no borrow/funding cost on shorts. Directional only.")


if __name__ == "__main__":
    main()
