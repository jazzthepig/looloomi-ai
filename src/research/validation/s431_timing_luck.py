"""S-431b — 周频再平衡的「星期几运气」:同一信号,7 个不同再平衡日各跑一本,再看 7 等份分批(每天调 1/7)。

8h 网格上现行信号周频 +11.4%,日线研究里 +17.2%,差别只在一周内哪天、几点成交 —— 头条数字里有择时运气。
分批(tranches)是标准解法:把书分 7 份、每份在不同的星期几再平衡,等价于每天调 1/7。
数据同 S-428(Binance 日线,/tmp/s428)。
"""
import numpy as np
import pandas as pd
from src.research.validation import s428_beta_plus_factor_tilt as m
from src.data.signals.beta_plus_momentum import combo_signal


def main():


    P, V = m.load()
    sig = combo_signal(P[m.PANEL])
    books = {}
    orig = m.rebalance_days
    for wd in range(7):
        m.rebalance_days = lambda idx, cad, wd=wd: set(idx[idx.dayofweek == wd])
        t, b, tt, tb = m.backtest(P, sig, "W", 1.0, "rank")
        books[wd] = (t, b, tt)
    m.rebalance_days = orig
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    for wd, (t, b, tt) in books.items():
        st = m.stats(t, b); so = m.stats(t["2024-01-01":], b["2024-01-01":])
        rows.append((names[wd], st["ann_ex"] * 100, st["t_wk"], so["ann_ex"] * 100, tt))
    # 分批:7 本各占 1/7 资金,各自按自己的星期几再平衡(组合收益 = 7 本 NAV 的平均)
    navs_t = pd.concat([(1 + books[w][0]).cumprod() for w in range(7)], axis=1).mean(axis=1)
    navs_b = pd.concat([(1 + books[w][1]).cumprod() for w in range(7)], axis=1).mean(axis=1)
    tt_ = navs_t.pct_change().fillna(0); tb_ = navs_b.pct_change().fillna(0)
    st = m.stats(tt_, tb_); so = m.stats(tt_["2024-01-01":], tb_["2024-01-01":])
    rows.append(("7 tranches", st["ann_ex"] * 100, st["t_wk"], so["ann_ex"] * 100, np.mean([books[w][2] for w in range(7)])))
    df = pd.DataFrame(rows, columns=["rebalance_day", "ann_ex_%", "t", "OOS_ex_%", "turnover_yr"]).set_index("rebalance_day")
    print(df.round(2).to_string())
    yr = ((1 + tt_).groupby(tt_.index.year).prod() / (1 + tb_).groupby(tb_.index.year).prod() - 1) * 100
    print("tranches yearly excess:", yr.round(1).to_dict())
    rel = (1 + tt_).cumprod() / (1 + tb_).cumprod(); r12 = (rel / rel.shift(365) - 1).dropna()
    print(f"tranches: beta {np.cov(tt_, tb_)[0,1]/np.var(tb_):.2f}  rel_maxdd {(rel/rel.cummax()-1).min()*100:.1f}%  worst_12m {r12.min()*100:.1f}%")



if __name__ == "__main__":
    main()
