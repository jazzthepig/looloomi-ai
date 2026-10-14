"""S-578:World50 加权方案的探索性比较(月度,11 个资产)。用法:python3 s578_world50_weighting.py <月末收盘文件>"""
import numpy as np
D={}
import sys
PATH = sys.argv[1] if len(sys.argv) > 1 else 'm2.txt'  # 月末收盘(供应商数据,不进公开仓库;私有副本在 looloomi-private/research_data/)
for line in open(PATH):
    s,x=line.strip().split('|'); D[s]={k:float(v) for k,v in (p.split(':') for p in x.split(';'))}
U=['AAPL','AMZN','GOOGL','META','MSFT','NVDA','TSLA','GLD','SLV','BTC','ETH']
months=sorted(set.intersection(*[set(D[s]) for s in U+['SPY','TLT','EEM']]))
P={s:np.array([D[s][m] for m in months]) for s in D}
R={s:P[s][1:]/P[s][:-1]-1 for s in P}; M=months[1:]; n=len(M); start=12
def mom(s,i,k):  # k-month return skipping most recent month, using returns up to i-1
    return np.prod(1+R[s][i-k:i-1])-1
def vol(s,i): return np.std(R[s][i-12:i],ddof=1)*np.sqrt(12)
def z(x):
    a=np.array(list(x.values())); m,sd=a.mean(),a.std(ddof=1); return {k:(v-m)/sd for k,v in x.items()}
def msci_score(i):
    r6={s:mom(s,i,7)/vol(s,i) for s in U}; r12={s:mom(s,i,12)/vol(s,i) for s in U}
    z6,z12=z(r6),z(r12); c=z({s:.5*z6[s]+.5*z12[s] for s in U})
    out={}
    for s in U:
        q=max(-3,min(3,c[s])); out[s]=1+q if q>0 else 1/(1-q)
    return out
def W_ew(i): return {s:1/len(U) for s in U}
def W_iv(i):
    v={s:1/vol(s,i) for s in U}; t=sum(v.values()); return {s:v[s]/t for s in U}
def W_msci_ew(i):
    sc=msci_score(i); t=sum(sc.values()); return {s:sc[s]/t for s in U}
def W_msci_iv(i):
    sc=msci_score(i); iv=W_iv(i); x={s:sc[s]*iv[s] for s in U}; t=sum(x.values()); return {s:x[s]/t for s in U}
def W_raw_mom(i):
    m={s:max(0,mom(s,i,12)) for s in U}; t=sum(m.values())
    return {s:(m[s]/t if t>0 else 0) for s in U}
def W_top5(i):
    sc={s:(mom(s,i,7)/vol(s,i)+mom(s,i,12)/vol(s,i)) for s in U}
    top=sorted(U,key=lambda s:-sc[s])[:5]; return {s:(0.2 if s in top else 0) for s in U}
def run(wf, every=1, voltarget=None):
    rets=[];W=[];w=None;turn=0
    for j,i in enumerate(range(start,n)):
        if w is None or j%every==0:
            nw=wf(i)
            if voltarget:
                # scale by trailing 6m realized vol of the unlevered book (Barroso–Santa-Clara style), cap 1x
                past=[sum(nw[s]*R[s][k] for s in U) for k in range(i-6,i)]
                rv=np.std(past,ddof=1)*np.sqrt(12); sc=min(1.0, voltarget/rv) if rv>0 else 1.0
                nw={s:nw[s]*sc for s in U}
            if w is not None: turn+=sum(abs(nw[s]-w.get(s,0)) for s in U)/2
            w=nw
        r=sum(w[s]*R[s][i] for s in U); rets.append(r); W.append(w)
        # drift
        g=sum(w[s]*(1+R[s][i]) for s in U)+ (1-sum(w.values()))
        w={s:w[s]*(1+R[s][i])/g for s in U}
    return np.array(rets),W,turn
yrs=(n-start)/12
def report(name,res):
    r,W,turn=res; nav=np.cumprod(1+r); dd=(nav/np.maximum.accumulate(nav)-1).min(); cagr=nav[-1]**(1/yrs)-1; v=r.std(ddof=1)*np.sqrt(12)
    mx=[max(w.values()) for w in W]; effn=[1/sum(x*x for x in w.values()) if sum(w.values())>0 else 0 for w in W]
    print(f"{name:28s} 年化 {cagr:+6.1%} 波动 {v:4.0%} 夏普 {cagr/v:4.2f} 回撤 {dd:+5.0%} 卡玛 {cagr/abs(dd):4.2f} 最差月 {r.min():+5.0%} | 单一最大权重 均 {np.mean(mx):4.0%} 峰 {max(mx):4.0%} | 有效个数 均 {np.mean(effn):4.1f} 最低 {min(effn):4.1f} | 换手/年 {turn/yrs:4.0%}")
    return r
print("评估", M[start], "→", M[-1], n-start, "个月;资产 11 个(今天的赢家:幸存者偏差,偏向动量)")
res={}
res['EW']=report("等权(月)",run(W_ew))
res['IV']=report("逆波动(月)",run(W_iv))
res['MSCI_EW']=report("动量分 × 等权(月,无上限)",run(W_msci_ew))
report("动量分 × 等权(季)",run(W_msci_ew,every=3))
res['MSCI_IV']=report("动量分 × 逆波动(月,无上限)",run(W_msci_iv))
res['RAW']=report("纯动量比例(月,无上限)",run(W_raw_mom))
res['TOP5']=report("动量前 5 等权(月)",run(W_top5))
res['MSCI_EW_VT']=report("动量分 × 等权 + 波动目标 20%",run(W_msci_ew,voltarget=0.20))
res['RAW_VT']=report("纯动量比例 + 波动目标 20%",run(W_raw_mom,voltarget=0.20))
# reference benchmarks
def single(s): return np.array([R[s][i] for i in range(start,n)])
for s in ['SPY','BTC']:
    r=single(s); nav=np.cumprod(1+r); dd=(nav/np.maximum.accumulate(nav)-1).min(); cagr=nav[-1]**(1/yrs)-1; v=r.std(ddof=1)*np.sqrt(12)
    print(f"{s:28s} 年化 {cagr:+6.1%} 波动 {v:4.0%} 夏普 {cagr/v:4.2f} 回撤 {dd:+5.0%} 卡玛 {cagr/abs(dd):4.2f}")
r=np.array([0.6*R['SPY'][i]+0.4*R['TLT'][i] for i in range(start,n)]); nav=np.cumprod(1+r); dd=(nav/np.maximum.accumulate(nav)-1).min(); cagr=nav[-1]**(1/yrs)-1; v=r.std(ddof=1)*np.sqrt(12)
print(f"{'60/40 SPY/TLT':28s} 年化 {cagr:+6.1%} 波动 {v:4.0%} 夏普 {cagr/v:4.2f} 回撤 {dd:+5.0%} 卡玛 {cagr/abs(dd):4.2f}")
# crash months: worst 5 months for EW and how momentum versions did
mo=M[start:]
idx=np.argsort(res['EW'])[:5]
print("\n等权最差的 5 个月 —— 各方案同月:")
for k in idx: print(" ", mo[k], " ".join(f"{nm} {res[nm][k]:+.0%}" for nm in res))
