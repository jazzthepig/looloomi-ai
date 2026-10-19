"""T-114:T-092 R3(30 名外暴涨名做空、等额多 BTC)的独立复算 —— 先看尾部(S-608)。

用 lane-b 的 T-092_cache.pkl(z30 已按 M-559 / S-594 修正;本脚本先抽 200 个点自己重算 z30 对齐,max|diff| = 0)。
规则照 t092_slow_contrarian.py 的 R3:周一 d,d−1 的 z30 ≥ 3 且 d 的排名 > 30(不在 24 名宇宙里)⇒ d+7 收盘入场做空,
持 30 个交易日,同期等额多 BTC,成本 20bp。
用法:python3 docs/research/t114_r3_replication.py <T-092_cache.pkl> <输出目录>
"""
import sys, os
CACHE, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
os.chdir(OUT)
import pickle, math, datetime as dt, numpy as np, json, collections
c=pickle.load(open(CACHE,'rb'))
close=c['close_by_sym']; z30c=c['z30']; rank=c['rank_by_dsym']
U={"BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK","DOT","LTC","TRX","ATOM","NEAR","APT","ARB","OP","SUI","UNI","AAVE","INJ","FIL","ETC","BCH"}
COST=0.0020
dates={s:sorted(v) for s,v in close.items()}
def z30_mine(sym, d):
    ds=dates[sym]; 
    try: i=ds.index(d)
    except ValueError: return None
    if i<31+30: return None
    cl=np.array([close[sym][x] for x in ds],float)
    js=np.arange(max(30,i-730), i-30)   # j in [i-730, i-31]
    if len(js)<200: return None
    r=np.log(cl[js]/cl[js-30]); r=r[np.isfinite(r)]
    if len(r)<200 or r.std(ddof=1)==0: return None
    return (math.log(cl[i]/cl[i-30])-r.mean())/r.std(ddof=1)
# validate z30 on a sample
rng=np.random.default_rng(1); keys=list(z30c.keys()); diffs=[]
for k in rng.choice(len(keys),200,replace=False):
    s,d=keys[k]; m=z30_mine(s,d)
    if m is not None: diffs.append(abs(m-z30c[(s,d)]))
print('z30 check n=%d max|diff|=%.2e'%(len(diffs),max(diffs)))
def mondays(lo,hi):
    d=dt.date.fromisoformat(lo); d+=dt.timedelta(days=(7-d.weekday())%7); out=[]
    while d.isoformat()<=hi: out.append(d.isoformat()); d+=dt.timedelta(days=7)
    return out
def first_on_or_before(ds,target):
    import bisect
    i=bisect.bisect_right(ds,target)-1
    return i
trades=[]
for d in mondays('2020-01-01','2026-10-14'):
    d1=(dt.date.fromisoformat(d)-dt.timedelta(days=1)).isoformat()
    for s in close:
        if s in U: continue
        z=z30c.get((s,d1))
        if z is None or z<3.0: continue
        rk=rank.get((d,s))
        if rk is None or rk<=30: continue
        ds=dates[s]; tgt=(dt.date.fromisoformat(d)+dt.timedelta(days=7)).isoformat()
        ie=first_on_or_before(ds,tgt)
        if ie<0 or ds[ie]<d: continue          # entry must be on/after signal week start
        ix=min(ie+30,len(ds)-1)
        if ix<=ie: continue
        bd=dates['BTC']; ib=first_on_or_before(bd,ds[ie]); jb=min(ib+30,len(bd)-1)
        pe,px=close[s][ds[ie]],close[s][ds[ix]]; be,bx=close['BTC'][bd[ib]],close['BTC'][bd[jb]]
        sh=1-px/pe; lg=bx/be-1
        trades.append(dict(sym=s,week=d,entry=ds[ie],exit=ds[ix],days=(dt.date.fromisoformat(ds[ix])-dt.date.fromisoformat(ds[ie])).days,
                           short=sh,long=lg,net=sh+lg-COST,peak_up=max(close[s][x] for x in ds[ie:ix+1])/pe-1))
json.dump(trades,open('trades.json','w'))
print('trades',len(trades))
for lo,hi,name in (('2020-01-01','2022-12-31','W1'),('2023-01-01','2024-12-31','W2'),('2025-01-01','2026-10-14','W3')):
    t=[x for x in trades if lo<=x['week']<=hi]
    if not t: print(name,0); continue
    n=np.array([x['net'] for x in t]); s_=np.array([x['short'] for x in t]); l=np.array([x['long'] for x in t])
    print(name,'n=%d mean_net=%.1f%% excess_vs_btc=%.1f%% win=%.0f%% p5=%.1f%% p1=%.1f%% worst=%.1f%% (%s %s) worst_peak_up=%.0f%% median_days=%d'%(
        len(t),n.mean()*100,(n-l).mean()*100,(n>0).mean()*100,np.percentile(n,5)*100,np.percentile(n,1)*100,n.min()*100,
        t[int(n.argmin())]['sym'],t[int(n.argmin())]['entry'],max(x['peak_up'] for x in t)*100,np.median([x['days'] for x in t])))

# ── 日序列 ──
trades=[t for t in json.load(open('trades.json')) if t['week']>='2023-01-01']
days=[(dt.date(2023,1,1)+dt.timedelta(days=i)).isoformat() for i in range((dt.date(2026,10,14)-dt.date(2023,1,1)).days+1)]
def px(s,d):
    v=close[s].get(d); return v
def run(slots, cost=0.002):
    nav=1.0; navs=[]; rets=[]; prev={}
    for i,d in enumerate(days):
        open_=[t for t in trades if t['entry']<d<=t['exit']]
        w=1.0/max(len(open_),slots) if open_ else 0
        r=0.0
        for t in open_:
            dp=days[i-1]
            pa,pb=px(t['sym'],d),px(t['sym'],dp); ba,bb=px('BTC',d),px('BTC',dp)
            pe,be=close[t['sym']][t['entry']],close['BTC'][t['entry']] if t['entry'] in close['BTC'] else None
            if None in (pa,pb,ba,bb) or not be: continue
            dpnl=-(pa-pb)/pe+(ba-bb)/be
            r+=w*dpnl
        entering=[t for t in trades if t['entry']==d]
        r-=cost*len(entering)/max(len(open_)+len(entering),slots) if entering else 0
        nav*=(1+r); navs.append(nav); rets.append(r)
    navs=np.array(navs); rets=np.array(rets)
    dd=(navs/np.maximum.accumulate(navs)-1).min(); yrs=len(days)/365.25
    return navs[-1]**(1/yrs)-1, dd, rets
b=np.array([close['BTC'][d] for d in days]); bret=np.r_[0,b[1:]/b[:-1]-1]
print('BTC hold: cagr=%.1f%% dd=%.1f%%'%(((b[-1]/b[0])**(1/(len(days)/365.25))-1)*100,(b/np.maximum.accumulate(b)-1).min()*100))
for slots in (5,10,20):
    cagr,dd,rets=run(slots)
    print('R3 daily book slots=%d: cagr=%.1f%% maxdd=%.1f%% worst_day=%.1f%% days_in_mkt=%.0f%% corr_btc=%.2f'%(slots,cagr*100,dd*100,rets.min()*100,(rets!=0).mean()*100,np.corrcoef(rets,bret)[0,1]))
    np.save(f'rets_{slots}.npy',rets)
np.save('btc.npy',bret)
