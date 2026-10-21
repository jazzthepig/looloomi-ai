"""S-649:用风格矢量做「大币行情」开关(山寨风格相对 majors 走弱时,R-v2 只开 BTC / ETH)—— 结果 ❌,方向相反。

开关数据 docs/research/s649_flags.json = style_index_pit_daily(cap、tier 维)算出的逐日开关,按「起始日」游程编码:
  RS = 等权(top_l1, second_l1_l2, app)累计 ÷ majors 累计;f50 = RS > 50 日均,f30 = RS 30 日变化 > 0,f100 = RS > 100 日均。
  核对:三条的「开」天数 1,052 / 1,094 / 942 与库里逐日重算一致(2026-10-21)。
模拟 = S-647 引擎(HL 宇宙、钱全留 HL、$100k、L = 3 与 1);票与数据 = C 道 T-159 缓存。
用法:python3 docs/research/s649_style_gate.py(--root 默认 /Volumes/CometCloudAI/cometcloud-local)
"""
import sys, os, json, datetime as dt, importlib.util, statistics as stt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
ROOT = sys.argv[sys.argv.index('--root') + 1] if '--root' in sys.argv else '/Volumes/CometCloudAI/cometcloud-local'
spec=importlib.util.spec_from_file_location('s647', os.path.join(HERE, 's647_sim_r_v2.py')); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from src.exec_host import sim_tickets as st
bars,fund,tix=m.load(ROOT)
tk,meta=m.build_tickets(bars,fund,tix)
F=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 's649_flags.json')))
END=dt.date(2026,10,20)
def expand(s):
    runs=[(x[0], dt.date.fromisoformat(x[1:])) for x in s.split(',')]
    out={}
    for i,(v,d0) in enumerate(runs):
        d1=runs[i+1][1] if i+1<len(runs) else END+dt.timedelta(days=1)
        d=d0
        while d<d1: out[d]=v; d+=dt.timedelta(days=1)
    return out
paper={f"{t['symbol']}:{t['signal_d']}":t for t in tix}
s0=(m.HIST_START-st.EPOCH).days; s1=(m.HIST_END-st.EPOCH).days
def run(tks, lev):
    r=st.simulate(tks,1e5,lev,executable=lambda t:m.hl_listed(t.symbol),apy_for_day=m._apy_hist,start_day=s0,end_day=s1,collateral_mult=float('inf'))
    s=st.stats(r.equity,1e5); return s, r
def window_dd(r, a, b):
    i0=(a-m.HIST_START).days; i1=(b-m.HIST_START).days
    seg=r.equity[i0:i1+1]; pk=seg[0]; mdd=0
    for e in seg: pk=max(pk,e); mdd=min(mdd,e/pk-1)
    return mdd
top10=sorted([t for t in tix if t['r'] is not None],key=lambda t:-t['r'])[:10]; top10ids={f"{t['symbol']}:{t['signal_d']}" for t in top10}
base={}
for lev in (3.0,1.0):
    base[lev]=run(tk,lev)
print('BASE L3', {k:round(v,4) for k,v in base[3.0][0].items()}, 'L1', {k:round(v,4) for k,v in base[1.0][0].items()})
for name in ('f50','f30','f100'):
    fl=expand(F[name])
    def blocked(t): 
        sd=st.EPOCH+dt.timedelta(days=t.signal_day)
        return t.symbol not in ('BTC','ETH') and fl.get(sd,'1')=='0'
    keep=[t for t in tk if not blocked(t)]; blk=[t for t in tk if blocked(t)]
    alts_keep=[(paper[t.tid]['r'] or 0.0) for t in keep if t.symbol not in ('BTC','ETH')]; alts_blk=[(paper[t.tid]['r'] or 0.0) for t in blk]
    res={}
    for lev in (3.0,1.0):
        s,r=run(keep,lev); res[lev]=(s,r)
    sb,rb=base[3.0]; sf,rf=res[3.0]
    print('==',name,'blocked',len(blk),'sumR blocked',round(sum(alts_blk),1),'kept alt sumR',round(sum(alts_keep),1),'top10 blocked',len([t for t in blk if t.tid in top10ids]))
    print('  L3 base cagr/mdd',round(sb['cagr']*100,1),round(sb['mdd']*100,1),'-> filt',round(sf['cagr']*100,1),round(sf['mdd']*100,1),
          '| mdd rel improve',round((1-sf['mdd']/sb['mdd'])*100,1),'% cagr diff',round((sf['cagr']-sb['cagr'])*100,1),'pp')
    s1_,_=res[1.0]; print('  L1 base',round(base[1.0][0]['cagr']*100,1),round(base[1.0][0]['mdd']*100,1),'-> filt',round(s1_['cagr']*100,1),round(s1_['mdd']*100,1))
    for lo,hi,lab in ((dt.date(2020,1,1),dt.date(2023,1,1),'<2023'),(dt.date(2023,1,1),dt.date(2027,1,1),'>=2023')):
        k=[(paper[t.tid]['r'] or 0.0) for t in keep if t.symbol not in ('BTC','ETH') and lo<=st.EPOCH+dt.timedelta(days=t.signal_day)<hi]
        b=[(paper[t.tid]['r'] or 0.0) for t in blk if lo<=st.EPOCH+dt.timedelta(days=t.signal_day)<hi]
        print('  half',lab,'kept alt n',len(k),'meanR',round(stt.mean(k),3) if k else None,'| blocked n',len(b),'meanR',round(stt.mean(b),3) if b else None)
    print('  window 2024-12-08..2025-09-25 DD: base',round(window_dd(rb,dt.date(2024,12,8),dt.date(2025,9,25))*100,1),'filt',round(window_dd(rf,dt.date(2024,12,8),dt.date(2025,9,25))*100,1))
    sep=[t for t in blk if dt.date(2025,9,1)<=st.EPOCH+dt.timedelta(days=t.entry_day)<dt.date(2025,10,1)]
    print('  2025-09 entries blocked',len(sep),'their R',round(sum((paper[t.tid]['r'] or 0.0) for t in sep),1), '| all 2025-09 entries', len([t for t in tk if dt.date(2025,9,1)<=st.EPOCH+dt.timedelta(days=t.entry_day)<dt.date(2025,10,1)]))
