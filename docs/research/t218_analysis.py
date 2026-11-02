#!/usr/bin/env python3
"""T-218 分析:② 两个分支的季度判别 + ③ 命题的基准率。

只读:全部基于 t218_table.json(已落盘的源)与 state_daily。只描述,不判胜负。
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
d = json.loads((HERE / "t218_table.json").read_text())
rows = d["table"]
RAILS = ["COIN", "HOOD", "CRCL"]
TOKB = ["ETH", "SOL", "TRX", "HYPE"]

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}


def sb(path, params):
    q = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read().decode()
        return json.loads(b) if b else []


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main():
    # ── 分支判别(阈值先写死,再逐季套用)────────────────────────────────
    # A「轨道与代币一起赢」:代币篮子 ≥ +10% 且 轨道篮子 ≥ +10%
    # B「轨道赢、代币跑输」:轨道篮子 ≥ +10% 且 (代币篮子 − 轨道篮子) ≤ −10pp
    # 其余 = 都不像
    print("== ② 逐季分支描述(等权篮子,当季有数据才算) ==")
    print("季度 | 代币篮子% | 轨道篮子% | 代币−轨道(pp) | 分支")
    classified = {"A": 0, "B": 0, "none": 0}
    rails_cum, tok_cum = 1.0, 1.0
    series = []
    for r in rows:
        tk = [r.get(f"{s}_ret_pct") for s in TOKB]
        rl = [r.get(f"{s}_ret_pct") for s in RAILS]
        tkm, rlm = mean(tk), mean(rl)
        if tkm is None or rlm is None:
            branch, diff = "—", None
        else:
            diff = tkm - rlm
            if tkm >= 10 and rlm >= 10:
                branch = "A"
            elif rlm >= 10 and diff <= -10:
                branch = "B"
            else:
                branch = "none"
            classified[branch] += 1
            series.append((r["quarter"], tkm, rlm, diff, branch))
        print(f"{r['quarter']} | {'—' if tkm is None else f'{tkm:+.1f}'} | "
              f"{'—' if rlm is None else f'{rlm:+.1f}'} | "
              f"{'—' if diff is None else f'{diff:+.1f}'} | {branch}")
        if tkm is not None and rlm is not None:
            rails_cum *= (1 + rlm / 100)
            tok_cum *= (1 + tkm / 100)
    print("分支计数:", classified)
    if rails_cum is not None:
        print(f"累计(首季起,季度等权再平衡,基数 1.0):轨道篮子 {rails_cum:.3f} vs 代币篮子 {tok_cum:.3f} "
              f"(差 {rails_cum - tok_cum:+.3f})")

    # 代币篮子 vs 轨道篮子 的季度收益相关
    xs = [s[1] for s in series]
    ys = [s[2] for s in series]
    if len(xs) > 2:
        mx, my = mean(xs), mean(ys)
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs)
        sx = (sum((a - mx) ** 2 for a in xs) / len(xs)) ** 0.5
        sy = (sum((b - my) ** 2 for b in ys) / len(ys)) ** 0.5
        print(f"季度收益相关(等权篮子, n={len(xs)}): r = {cov / (sx * sy):+.3f}")

    # ── 发行方 vs 持币人:收入归属 ───────────────────────────────────────
    print()
    print("== 收入归属:发行方 vs 公链持币人(季度合计 $M) ==")
    print("季度 | 发行方(T+C) | 持币人(ETH+SOL+TRX+HYPE) | 倍数 | 发行方年化收益率/供应 | 供应合计($B)")
    for r in rows:
        iss = r["tether_rev"] + r["circle_rev"] if (r["tether_rev"] is not None and r["circle_rev"] is not None) else None
        if r["tether_rev"] is not None and r["circle_rev"] is None:
            iss = r["tether_rev"]
        hold = None
        parts = [r.get(k) for k in ("eth_holders_rev", "sol_holders_rev", "trx_holders_rev", "hype_holders_rev")]
        if any(p is not None for p in parts):
            hold = sum(p or 0 for p in parts)
        sup = r["stable_total"]
        rate = (iss * 4 / sup * 100) if (iss is not None and sup) else None
        ratio = (iss / hold) if (iss and hold) else None
        print(f"{r['quarter']} | {'—' if iss is None else f'{iss/1e6:,.0f}'} | "
              f"{'—' if hold is None else f'{hold/1e6:,.0f}'} | "
              f"{'—' if ratio is None else f'{ratio:.1f}x'} | "
              f"{'—' if rate is None else f'{rate:.2f}%'} | "
              f"{'—' if sup is None else f'{sup/1e9:,.1f}'}")

    # ── ③ 命题的基准率(历史季度频率)────────────────────────────────────
    print()
    print("== 基准率:历史季度(2021Q1-2026Q3)达到某个阈值的频率 ==")

    def freq(name, getret, thr, ge=True):
        vals = [getret(r) for r in rows]
        vals = [v for v in vals if v is not None]
        hit = [v for v in vals if (v >= thr if ge else v <= thr)]
        print(f"  {name}: {len(hit)}/{len(vals)} = {len(hit)/len(vals):.0%} "
              f"(阈值 {'≥' if ge else '≤'} {thr})")
        return len(hit) / len(vals)

    eth = lambda r: r.get("ETH_ret_pct")
    sol = lambda r: r.get("SOL_ret_pct")
    freq("ETH 季度 ≥ +25%", eth, 25)
    freq("ETH 季度 ≥ +40%", eth, 40)
    freq("SOL 季度 ≥ +25%", sol, 25)
    freq("代币篮子(ETH+SOL+TRX+HYPE)季度 ≥ +10%", lambda r: mean([r.get(f"{s}_ret_pct") for s in TOKB]), 10)
    freq("代币篮子季度 ≤ −10%", lambda r: mean([r.get(f"{s}_ret_pct") for s in TOKB]), -10, ge=False)
    freq("BTC 季度 ≥ 0%", lambda r: r.get("BTC_ret_pct"), 0)

    # 稳定币供应环比
    sup_q = [r.get("stable_qoq_pct") for r in rows if r.get("stable_qoq_pct") is not None]
    pos = [x for x in sup_q if x > 0]
    print(f"  稳定币合计环比 > 0: {len(pos)}/{len(sup_q)} = {len(pos)/len(sup_q):.0%}")
    neg3 = [x for x in sup_q if x < -3]
    print(f"  稳定币合计环比 < −3%: {len(neg3)}/{len(sup_q)} = {len(neg3)/len(sup_q):.0%}")

    # ── state:breadth_above_ma50 最近 15 天(核对 0 是否异常)──────────────
    print()
    br = sb("state_daily", {"feature": "eq.breadth_above_ma50", "order": "d.desc", "limit": "15"})
    print("breadth_above_ma50 最近 15 天:", [(r["d"], r["value"]) for r in br])
    mom20 = sb("state_daily", {"feature": "eq.mom_20", "order": "d.desc", "limit": "8"})
    print("mom_20 最近 8 天:", [(r["d"], r["value"]) for r in mom20])

    # ── ETH 持币人收入的构成:是否一次性尖峰 ─────────────────────────────
    import datetime as dt
    from pathlib import Path as _P
    p = _P("/Volumes/CometCloudAI/cometcloud-local/research/s661/_llama_rev.jsonl")
    vals = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            dd = json.loads(line)
            if dd.get("slug") != "ethereum":
                continue
            ser = dd.get("dailyHoldersRevenue") or []
            for ts, v in ser:
                if v:
                    vals.append((dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat(), float(v)))
    vals.sort(key=lambda x: -x[1])
    print()
    print("ETH dailyHoldersRevenue 单日最大的 8 天(检查是否一次性):")
    for dd, v in vals[:8]:
        print("  ", dd, f"{v:,.0f}")
    y2021 = [v for dd, v in vals if dd.startswith("2021")]
    print(f"  2021 全年合计 ${sum(y2021):,.0f},非零天数 {len(y2021)},"
          f"中位数 {sorted(y2021)[len(y2021)//2]:,.0f}")
    print(f"  全序列合计 ${sum(v for _, v in vals):,.0f},天数 {len(vals)}")
    # 季度合计的构成:去掉最大 8 天后还剩多少(2021 各季)
    top = set(dd for dd, _ in vals[:8])
    per_q = {}
    for dd, v in vals:
        k = dd[:4] + "Q" + str((int(dd[5:7]) - 1) // 3 + 1)
        per_q.setdefault(k, [0.0, 0])
        per_q[k][0] += v
        if dd not in top:
            per_q[k][1] += v
    print("  各年合计 vs 去掉最大 8 天后:")
    for y in ("2021", "2022", "2023", "2024", "2025", "2026"):
        tot = sum(v for k, (v, _) in per_q.items() if k.startswith(y))
        ex = sum(v2 for k, (_, v2) in per_q.items() if k.startswith(y))
        print(f"   {y}: ${tot:,.0f} → ${ex:,.0f}")


if __name__ == "__main__":
    main()
