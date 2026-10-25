import json, os, sys, random
R="/sessions/magical-quirky-tesla/mnt/cometcloud-local"
os.environ["T156_DATA"]=R+"/research/t156/"; os.environ["T159_DATA"]=R+"/research/t159/"
sys.path.insert(0,"/sessions/magical-quirky-tesla/mnt/looloomi-ai"); sys.path.insert(0,"/sessions/magical-quirky-tesla/mnt/looloomi-ai/docs/research")
import t159_bear_short as t
gate=t.load_gate()
bars={}
for line in open(R+"/research/s681/_um_daily.jsonl"):
    x=json.loads(line); rows=sorted({tuple(b) for b in x["bars"] if b[4]>0})
    bars[x["symbol"]]=[(r[0],r[1],r[2],r[3],r[4],r[5]) for r in rows]
surv=set(json.load(open(R+"/research/s677/_survivor_symbols.json"))["symbols"])
def in_s(sym): return sym in surv or (sym.startswith("1000") and sym[4:] in surv) or ("1000"+sym) in surv
tk=t.run_long(bars, gate, "2020-01-01","2026-09-30")
def stats(ts):
    c=[x for x in ts if not x["still"]]; r=[x["r"] for x in c]
    by={}
    for x in c: by.setdefault(x["signal_d"][:7],[]).append(x["r"])
    ms=list(by); rng=random.Random(684); le=0
    for _ in range(2000):
        rs=[v for m in (rng.choice(ms) for _ in ms) for v in by[m]]; le+= (sum(rs)/len(rs))<=0
    return {"n":len(ts),"closed":len(c),"mean":round(sum(r)/len(r),4),"p":le/2000}
A=tk; S=[x for x in tk if in_s(x["symbol"])]; D=[x for x in tk if not in_s(x["symbol"])]
out={"A":stats(A),"S":stats(S),"D":stats(D)}
print(json.dumps(out))
json.dump({"stats":out,"tickets":[{k:x[k] for k in ("symbol","signal_d","entry_d","exit_d","r","still")} for x in tk]},open("/tmp/s684/seth_s684.json","w"))
