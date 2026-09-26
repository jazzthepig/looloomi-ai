"""S-428 候选深挖:β、相对最大回撤、最差 12 个月、分年。数据同 s428_beta_plus_factor_tilt(/tmp/s428)。"""
import sys; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from src.research.validation import s428_beta_plus_factor_tilt as m


def main():
    P,V=m.load(); S=m.signals(P,V)
    rk=lambda X: X.rank(axis=1,pct=True)
    S['mom+52w']=(rk(S['mom_combo'])+rk(S['high52w']))/2
    btc_bull=(P['BTC']>P['BTC'].rolling(200).mean()).shift(1)
    cands=[('mom_combo','W','rank',1.0),('mom_combo','M','rank',1.0),('high52w','M','rank',1.0),('high52w','M','top_half',None),
           ('mom+52w','W','rank',1.0),('mom+52w','M','rank',1.0),('mom+52w','M','top_half',None),('mom+52w','M','rank',0.5)]
    rows=[];yr={}
    for f,cad,mode,k in cands:
        t,b,tt,tb=m.backtest(P,S[f],cad,k or 1.0,mode)
        ex=t-b; beta=np.cov(t,b)[0,1]/np.var(b)
        rel=(1+t).cumprod()/(1+b).cumprod(); rdd=(rel/rel.cummax()-1).min()
        r12=(rel/rel.shift(365)-1).dropna()
        bull=btc_bull.reindex(t.index).fillna(False).astype(bool)
        oos=slice('2024-01-01',None)
        st=m.stats(t,b); so=m.stats(t[oos],b[oos])
        key=f"{f}|{cad}|{mode}|k={k}"
        rows.append(dict(v=key, ann_ex=st['ann_ex']*100, t=st['t_wk'], OOS_ex=so['ann_ex']*100, OOS_t=so['t_wk'],
            bull=m.stats(t[bull],b[bull])['ann_ex']*100, bear=m.stats(t[~bull],b[~bull])['ann_ex']*100,
            beta=beta, rel_maxdd=rdd*100, worst_12m=r12.min()*100, pct_12m_pos=(r12>0).mean()*100, turnover=tt,
            tilt_cum=st['tilt']*100, bench_cum=st['bench']*100))
        yr[key]=((1+t).groupby(t.index.year).prod()/(1+b).groupby(b.index.year).prod()-1)*100
    pd.set_option('display.width',250)
    print(pd.DataFrame(rows).set_index('v').round(2).to_string()); print()
    print(pd.DataFrame(yr).T.round(1).to_string())


if __name__ == "__main__":
    main()
