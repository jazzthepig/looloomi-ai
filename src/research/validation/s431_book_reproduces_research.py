"""S-431c:前向账本 compute_path 跑 2020-07 → 2026-09 的历史,与研究脚本的分批/月频结果逐位一致(16.7%/t 3.12;15.6%/t 2.62)。数据 /tmp/s428。"""
import numpy as np, pandas as pd
from src.research.validation import s428_beta_plus_factor_tilt as m
from src.data.signals import beta_plus_momentum as bp


def main():
    P,V = m.load()
    start = pd.Timestamp("2020-07-01")
    bp.INCEPTION = start
    px = P[m.PANEL].loc[:"2026-09-25"]
    rows = bp.compute_path(px, tuple(m.PANEL), "binance", end=pd.Timestamp("2026-09-25"))
    df = pd.DataFrame(rows); df["d"] = pd.to_datetime(df["d"])
    r = df.pivot(index="d", columns="arm", values="ret")
    for tilt, base in (("momentum_52w_w","panel_hold_w"),("momentum_52w_m","panel_hold_m")):
        ex = r[tilt]-r[base]; wk = ex.groupby(ex.index.to_period("W")).sum()
        print(f"BOOK  {tilt}: ann_ex {ex.mean()*365*100:.1f}%  t {wk.mean()/wk.std()*np.sqrt(len(wk)):.2f}")
    # research, same start: tranche weekly and monthly
    sig = bp.combo_signal(P[m.PANEL])
    books=[]
    orig=m.rebalance_days
    for wd in range(7):
        m.rebalance_days = lambda idx, cad, wd=wd: set(idx[idx.dayofweek == wd])
        t,b,_,_ = m.backtest(P, sig, "W", 1.0, "rank", start="2020-07-01", end="2026-09-25"); books.append((t,b))
    m.rebalance_days = orig
    nt = pd.concat([(1+t).cumprod() for t,_ in books],axis=1).mean(axis=1).pct_change().fillna(0)
    nb = pd.concat([(1+b).cumprod() for _,b in books],axis=1).mean(axis=1).pct_change().fillna(0)
    ex=nt-nb; wk=ex.groupby(ex.index.to_period("W")).sum()
    print(f"RESEARCH tranche W: ann_ex {ex.mean()*365*100:.1f}%  t {wk.mean()/wk.std()*np.sqrt(len(wk)):.2f}")
    t,b,_,_ = m.backtest(P, sig, "M", 1.0, "rank", start="2020-07-01", end="2026-09-25"); ex=t-b; wk=ex.groupby(ex.index.to_period("W")).sum()
    print(f"RESEARCH monthly:   ann_ex {ex.mean()*365*100:.1f}%  t {wk.mean()/wk.std()*np.sqrt(len(wk)):.2f}")



if __name__ == "__main__":
    main()
