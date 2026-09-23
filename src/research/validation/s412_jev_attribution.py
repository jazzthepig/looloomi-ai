"""S-412 事后归因(诊断,非预注册):用缓存的 Jev 回答逐项替换机械答案,看价值/损失来自哪一问。不产生新调用。"""
import json, random, math, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, '.')
from paper_trading import hl_book as hb
import paper_trading.jev_replay_s412 as rp
px, fd = hb.load_hl(Path('paper_trading/state/hl_cache'))
px = px[px.index <= '2026-09-22']; fd = fd.loc[px.index]
resps = [json.loads(l)['resp'] for l in open('paper_trading/state/jev_replay_s412/jev_cache.jsonl')]
days = px.index[px.index >= rp.START]; mondays = [d for d in days if d.weekday()==0]
rng = random.Random(412); J = {}; k = 0
for t in mondays:
    feats = hb.features_at(px, fd, t)
    if not feats: continue
    coins = list(feats); labels=[f"asset_{i}" for i in range(1,len(coins)+1)]; rng.shuffle(labels); ids=dict(zip(coins,labels))
    ans = resps[k]['answers']; k += 1
    J[t] = dict(tc={c: ans[f"{ids[c]}__trend_confirmed"]["noul"] >= hb.NOUL_YES for c in coins},
                cr={c: ans[f"{ids[c]}__crowded"]["noul"] >= hb.NOUL_YES for c in coins},
                cp={c: ans[f"{ids[c]}__capitulation"]["noul"] >= hb.NOUL_YES for c in coins},
                mode=ans["book_mode"]["choice"] if ans["book_mode"].get("confidence",0) >= hb.CHOICE_MIN_CONF else "neutral",
                p_tc={c: ans[f"{ids[c]}__trend_confirmed"]["noul"] for c in coins})
print("cache lines used", k, "of", len(resps))
def run(pick):
    W = pd.DataFrame(np.nan, index=days, columns=px.columns); N = pd.Series(np.nan, index=days); book={}
    for t in mondays:
        feats = hb.features_at(px, fd, t)
        if not feats: continue
        N.loc[t]=len(feats); m = hb.mechanical_answers(feats); j = J[t]
        a = pick(m, j)
        cur={c:v["w"] for c,v in book.items()}
        bs={c:{"w":v["w"],"ret_since":px[c].loc[t]/v["px"]-1} for c,v in book.items()}
        new = hb.apply_turnover_limits(hb.tom_targets(feats, a, bs), cur)
        for c in px.columns: W.loc[t,c]=new.get(c,0.0)
        book={c:{"w":w,"px":px[c].loc[t]} for c,w in new.items() if w!=0}
    net, ex = rp.pnl(W.ffill(), N.ffill(), px, fd); s = rp.stats(net)
    return s, ex
arms = {
 "机械(全部)": lambda m,j: m,
 "Jev(全部)": lambda m,j: hb.Answers(j["tc"], j["cr"], j["cp"], j["mode"]),
 "Jev 单币 + 机械模式": lambda m,j: hb.Answers(j["tc"], j["cr"], j["cp"], m.mode),
 "机械单币 + Jev 模式": lambda m,j: hb.Answers(m.trend_confirmed, m.crowded, m.capitulation, j["mode"]),
 "只换 Jev 趋势确认": lambda m,j: hb.Answers(j["tc"], m.crowded, m.capitulation, m.mode),
 "只换 Jev 拥挤": lambda m,j: hb.Answers(m.trend_confirmed, j["cr"], m.capitulation, m.mode),
 "只换 Jev 投降": lambda m,j: hb.Answers(m.trend_confirmed, m.crowded, j["cp"], m.mode),
}
for n,f in arms.items():
    s,ex = run(f)
    print(f"{n:16s} 总 {s['total']:7.1%} SR {s['sharpe']:5.2f} DD {s['maxdd']:6.1%} 仓位 {ex['gross']:.2f}")
# Jev 的 trend_confirmed 概率有没有信息:按概率分组看该币下一周收益
rows=[]
for t in J:
    nt = t + pd.Timedelta(days=7)
    if nt not in px.index: continue
    for c,p in J[t]["p_tc"].items():
        rows.append((p, px[c].loc[nt]/px[c].loc[t]-1, hb.mechanical_answers(hb.features_at(px,fd,t)).trend_confirmed[c]))
d=pd.DataFrame(rows,columns=["p","fwd7","mech"])
d["bin"]=pd.cut(d.p,[0,.2,.4,.6,.8,1.0],include_lowest=True)
print(d.groupby("bin",observed=True).fwd7.agg(["count","mean"]).round(4))
print("机械趋势确认:", d.groupby("mech").fwd7.agg(["count","mean"]).round(4).to_dict())
