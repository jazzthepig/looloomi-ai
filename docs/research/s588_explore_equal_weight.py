"""S-588 的探索部分(不在预注册里):同一质量信号放在等权篮子 / 只含山寨的篮子里。结果见台账 S-588 探索段。"""
import sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import s588_quality_tilt as q
from src.data.evaluation.apparatus import ab_test
data=q.build(sys.argv[1])   # 用法:python3 docs/research/s588_explore_equal_weight.py <crypto_daily 目录>
grid,syms,P,C,v13,v26,sup,wret=data
bi=syms.index('BTC')
def run(start,end,mode):
    t0=next(i for i,g in enumerate(grid) if g>=start); w={}; out=[]; since=q.EVERY
    for t in range(t0,len(grid)):
        if grid[t]>end: break
        if t>t0:
            av={i:wret[i,t] for i in w if np.isfinite(wret[i,t])}; tot=sum(w[i] for i in av)
            out.append(sum(w[i]*av[i] for i in av)/tot if tot>0 else 0.0)
            g={i:w[i]*(1+av.get(i,0.0)) for i in w}; s=sum(g.values()); w={i:v/s for i,v in g.items()} if s>0 else w; since+=1
        if since<q.EVERY: continue
        m=C[:,t]; ok=np.isfinite(m)&np.isfinite(P[:,t])&(v26[:,t]>=0.15); idx=np.where(ok)[0]; idx=idx[np.argsort(-m[idx])][:q.N]
        z=q.combo_z(idx,t,C,v13,sup)
        if mode=='EW': wt=np.ones(len(idx))
        elif mode=='EWxQ': wt=np.where(np.isfinite(z),q.tilt(np.nan_to_num(z)),1.0)
        elif mode=='CAP_drop_bottom': wt=m[idx]*np.where(np.isfinite(z)&(z<np.nanpercentile(z,33)),0.0,1.0)
        elif mode=='ALT_EW': wt=np.where(idx==bi,0.0,1.0)
        elif mode=='ALT_EWxQ': wt=np.where(idx==bi,0.0,np.where(np.isfinite(z),q.tilt(np.nan_to_num(z)),1.0))
        wt=wt/wt.sum(); new={int(i):float(x) for i,x in zip(idx,wt) if x>0}
        tv=sum(abs(new.get(i,0)-w.get(i,0)) for i in set(new)|set(w))
        if out: out[-1]=(1+out[-1])*(1-tv*q.COST)-1
        w=new; since=0
    return out
for name,(a,b) in q.WINDOWS.items():
    r={m:run(a,b,m) for m in ('EW','EWxQ','CAP_drop_bottom','ALT_EW','ALT_EWxQ')}
    print('==',name)
    for m,v in r.items(): s=q.stats(v); print(f"  {m:16s} CAGR {s['cagr']*100:6.1f}%  MDD {s['max_dd']*100:6.1f}%")
    for b2,a2 in (('EWxQ','EW'),('ALT_EWxQ','ALT_EW')):
        t=ab_test(r[a2],r[b2],mean_block=4,days_per_year=52); print(f"  {b2} vs {a2}: {t['verdict']} ratio {t['ratio_b_over_a']:.3f} p {t['p_b_le_a']:.3f}")
