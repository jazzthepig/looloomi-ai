import json, math
from collections import defaultdict
from datetime import datetime, timezone
rows=json.load(open("panel.json"))
px=defaultdict(dict); vol=defaultdict(dict)
for s,t,c,qv in rows:
    d=datetime.fromtimestamp(t/1000,timezone.utc).date()
    px[s][d]=c; vol[s][d]=qv
dates=sorted({d for s in px for d in px[s]})
syms=sorted(px)

def adv30(s,d,ds):  # 30日均额,PIT
    xs=[vol[s][x] for x in ds if x<d and x in vol[s]][-30:]
    return sum(xs)/len(xs) if len(xs)>=20 else 0
def hist_len(s,d): return sum(1 for x in px[s] if x<d)

def run(mode, bps):
    nav=1.0; w={}; navs=[]; prev={}; turn_tot=0; rebals=0
    ds=dates
    for i,d in enumerate(ds):
        # 日收益
        if w:
            r=0
            for s,wt in w.items():
                p0=prev.get(s); p1=px[s].get(d)
                if p0 and p1: r+=wt*(p1/p0-1)
                elif p0 and not p1: r+=wt*(-1.0)   # 退市→归零(诚实)
            nav*=(1+r)
        navs.append((d,nav))
        # 月初再平衡
        if i==0 or d.month!=ds[i-1].month:
            elig=[s for s in syms if hist_len(s,d)>=180 and adv30(s,d,ds)>=5e6 and d in px[s]]
            if elig:
                if mode=="ew": nw={s:1/len(elig) for s in elig}
                else:
                    mc={s:adv30(s,d,ds) for s in elig}  # 用成交额作规模代理(无市值历史)
                    tot=sum(mc.values()); nw={s:mc[s]/tot for s in elig}
                    for _ in range(5):  # 30% 封顶迭代
                        ex={s:v for s,v in nw.items() if v>0.30}
                        if not ex: break
                        sp=sum(v-0.30 for v in ex.values()); rest=[s for s in nw if s not in ex]
                        rt=sum(nw[s] for s in rest) or 1
                        nw={s:(0.30 if s in ex else nw[s]+sp*nw[s]/rt) for s in nw}
                to=sum(abs(nw.get(s,0)-w.get(s,0)) for s in set(nw)|set(w))/2
                nav*=(1-to*bps/10000); turn_tot+=to; rebals+=1
                w=nw
        prev={s:px[s].get(d,prev.get(s)) for s in w}
    return navs, turn_tot, rebals

def stats(navs,label):
    v=[n for _,n in navs]; d0,d1=navs[0][0],navs[-1][0]
    yrs=(d1-d0).days/365.25
    tot=(v[-1]-1)*100; cagr=((v[-1])**(1/yrs)-1)*100
    rets=[v[i]/v[i-1]-1 for i in range(1,len(v))]
    mu=sum(rets)/len(rets); sd=(sum((x-mu)**2 for x in rets)/(len(rets)-1))**.5
    sh=mu/sd*math.sqrt(365) if sd else 0
    pk=-1e9; dd=0
    for x in v:
        pk=max(pk,x); dd=min(dd,x/pk-1)
    print(f"{label:16s} 总收益 {tot:>9.0f}%  CAGR {cagr:>6.1f}%  Sharpe {sh:>5.2f}  maxDD {dd*100:>6.1f}%")
    return v

print(f"面板 {len(syms)} 币 · {dates[0]} → {dates[-1]}\n")
for mode in ("ew","cw"):
    for bps in (0,10):
        navs,tt,rb=run(mode,bps)
        stats(navs,f"①{mode.upper()} {bps}bps")
        if bps==10: print(f"                 (再平衡 {rb} 次, 年化换手 {tt/((dates[-1]-dates[0]).days/365.25)*100:.0f}%)")
# 对照:BTC / ETH 单一持有
for s in ("BTC","ETH"):
    ds=[d for d in dates if d in px[s]]
    stats([(d,px[s][d]/px[s][ds[0]]) for d in ds], f"持有{s}")
