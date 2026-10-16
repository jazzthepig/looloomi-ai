"""T-109 replay per S-589 preregistration, descriptive only (no verdict).

只用 apparatus 的接口,盈亏/零分布/对照不自己写一份。
"""
import json, os, sqlite3, sys
from datetime import date, timedelta
from collections import defaultdict

import numpy as np

# 把同仓的 src/ 放到 sys.path
WORKTREE = "/Users/sbb/Projects/looloomi-ai-lane-a-t109"
sys.path.insert(0, WORKTREE + "/src")

from data.evaluation.apparatus import (
    long_return, price_on_or_after, ab_test, percentile_of,
)

MAC = "/Volumes/CometCloudAI/cometcloud-local"
PANEL = MAC + "/research/crypto_daily/panel.json"
CISDB = MAC + "/_data/cis_history.db"
OUT = MAC + "/_reports/absorb_input"
os.makedirs(OUT, exist_ok=True)

VW, CW = 91, 91         # 13 周窗口
COST = 0.0020          # 20 bp 单边

# 稳定币 / 包装启发式:与原脚本一致(S-589 prereg 用同样的剔除)
KWS = ("USD", "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD", "EUR",
       "PAXG", "XAUT", "USDY", "OUSG", "BUIDL", "USTB", "USYC", "JAAA",
       "JTRSY", "SAFO", "EURSAFO", "STABLE", "TBTC", "WBTC", "PSTUSDC",
       "SYRUPUSDC", "THBILL", "EUTBL", "USTBL", "FIGR_HELOC", "MSTRX", "STRCX")


def is_stable_or_wrapped(s):
    u = s.upper()
    for k in KWS:
        if u == k:
            return True
        if u.startswith(k) or u.endswith(k):
            return True
    return False


def main():
    print("[1/6] panel.json ...")
    p = json.load(open(PANEL))
    dates = p["dates"]
    d_idx = {d: i for i, d in enumerate(dates)}
    PRICE = p["price"]
    MCAP = p["mcap"]
    print(f"  panel: {len(dates)} days {dates[0]} -> {dates[-1]}, {len(PRICE)} symbols")

    print("[2/6] cis F/O (Crypto + L1 + L2 + DeFi + Gaming + Infrastructure + Memecoin) ...")
    con = sqlite3.connect(CISDB)
    # 注意:同一资产可能在多个 class 出现(例如 LINK 既在 L1 也在 Infrastructure)—— 用 dict 覆盖就行
    q = ("SELECT date(timestamp), asset, pillar_f, pillar_o "
         "FROM cis_history "
         "WHERE asset_class IN ('Crypto','L1','L2','DeFi','Gaming','Infrastructure','Memecoin') "
         "AND pillar_f IS NOT NULL AND pillar_o IS NOT NULL "
         "ORDER BY date(timestamp), asset, id")
    F = defaultdict(dict)
    O = defaultdict(dict)
    n_rows = 0
    first_d = None
    last_d = None
    for d_, a, fv, ov in con.execute(q):
        # 同一 (date, asset) 出现多次时取最后一条;同 SQL 排序里 id DESC 通常更安全
        F[d_][a] = fv
        O[d_][a] = ov
        n_rows += 1
        if first_d is None or d_ < first_d:
            first_d = d_
        if last_d is None or d_ > last_d:
            last_d = d_
    print(f"  rows: {n_rows}; dates: {first_d} -> {last_d}")

    # 每日更新资产的并集 = 实际能用的候选宇宙
    print("[3/6] universe ...")
    cand = sorted(set(a for dd in F for a in F[dd]))
    UNIV = [s for s in cand if s != "BTC" and not is_stable_or_wrapped(s)]
    print(f"  unique assets with F/O: {len(cand)}; after removing BTC + stable/wrapped: {len(UNIV)}")

    print("[4/6] rebalance dates (28-day spacing, Friday-anchored starting 2023-01-06) ...")
    start = date(2023, 1, 6)
    end = date(2026, 10, 9)
    reb = []
    d = start
    while d <= end:
        reb.append(d.isoformat())
        d += timedelta(days=28)

    # 跳过没有 F/O 的调仓日(S-589 接受 26 次调仓 ≈ 2 年的最低门槛 —— 我们跑到的全部调仓列表)
    print("[5/6] walk rebalances ...")
    per_year = defaultdict(list)  # yyyy -> list of records

    for i, day in enumerate(reb):
        # 市值候选(只取在 panel + CIS 宇宙里的)
        mc = {}
        for s in UNIV:
            v = price_on_or_after(dates, MCAP.get(s, []), day)
            if v is not None and v > 0:
                mc[s] = float(v)
        if len(mc) < 20:
            continue
        if day not in F:
            continue

        # 13w annual vol (对价格序列;apparatus 是日期 → 收盘价 → return,这里直接落 numpy 算)
        v13 = {}
        for s in mc:
            closes = [float(v) for v in PRICE.get(s, []) if v is not None and v > 0]
            # 找到 day 或之后第一个有效日,取 i
            i0 = d_idx.get(day)
            if i0 is None:
                continue
            window = closes[max(0, i0 - VW + 1): i0 + 1]
            if len(window) < 60:
                continue
            rets = np.diff(np.log(window))
            if len(rets) < 30:
                continue
            v13[s] = float(np.std(rets, ddof=1) * np.sqrt(365.25))

        # 13w 流通量变化 = (mc / price)_now vs 13w 前
        circ = {}
        for s in mc:
            i0 = d_idx.get(day)
            j0 = max(0, i0 - CW)
            p_now = price_on_or_after(dates, PRICE.get(s, []), day)
            m_now = price_on_or_after(dates, MCAP.get(s, []), day)
            p_prev = price_on_or_after(dates, PRICE.get(s, []), dates[j0])
            m_prev = price_on_or_after(dates, MCAP.get(s, []), dates[j0])
            if None in (p_now, m_now, p_prev, m_prev):
                continue
            if p_now <= 0 or p_prev <= 0:
                continue
            cn = m_now / p_now
            co = m_prev / p_prev
            if co <= 0:
                continue
            circ[s] = (cn, co)

        if len(v13) < 8:
            continue

        # top 15 mcap (在 mc ∩ v13 里)
        ranked = sorted(mc.items(), key=lambda kv: -kv[1])
        top15_set = set(s for s, _ in ranked[:15])

        # 宇宙 vol 中位数(只在 mc ∩ v13 里算 —— S-589 写「宇宙中位数」,最贴近的解读是
        # 「当次待选宇宙」而不是全 market)
        v_med = float(np.median([v13[s] for s in mc if s in v13]))

        elig = set()
        for s in top15_set:
            if s not in v13:
                continue
            if v13[s] > v_med * 1.5:
                continue
            if s not in circ:
                continue
            cn, co = circ[s]
            if (cn / co) - 1.0 > 0.10:
                continue
            elig.add(s)
        if len(elig) < 6:
            continue

        # 打分
        fv = {s: F[day][s] for s in elig if s in F[day]}
        ov = {s: O[day][s] for s in elig if s in O[day]}
        cset = set(fv) & set(ov) & set(mc) & set(v13)
        if len(cset) < 6:
            continue

        def rk(vals):
            order = sorted(vals, key=lambda k: -vals[k])
            return {k: i + 1 for i, k in enumerate(order)}

        rf = rk({s: fv[s] for s in cset})
        ro_ = rk({s: ov[s] for s in cset})
        rm = rk({s: mc[s] for s in cset})
        rv = rk({s: v13[s] for s in cset})
        score = {s: rf[s] + ro_[s] + rm[s] - rv[s] for s in cset}
        pA = sorted(cset, key=lambda x: -score[x])[:6]
        pB = sorted(cset)

        # 4 周前瞻收益
        fA_list = [long_return(price_on_or_after(dates, PRICE.get(s, []), day),
                               price_on_or_after(dates, PRICE.get(s, []), day, max_gap_days=3)) for s in pA]
        # 上面的 max_gap_days 写法会同时影响入 / 出;改成各算一次
        fA_list = []
        for s in pA:
            p0 = price_on_or_after(dates, PRICE.get(s, []), day)
            # 出场:day + 28 天 ± 5 天
            target_exit_iso = (date.fromisoformat(day) + timedelta(days=28)).isoformat()
            p1 = price_on_or_after(dates, PRICE.get(s, []), target_exit_iso)
            fA_list.append(long_return(p0, p1))

        fB_list = []
        for s in pB:
            p0 = price_on_or_after(dates, PRICE.get(s, []), day)
            target_exit_iso = (date.fromisoformat(day) + timedelta(days=28)).isoformat()
            p1 = price_on_or_after(dates, PRICE.get(s, []), target_exit_iso)
            fB_list.append(long_return(p0, p1))

        fC = long_return(price_on_or_after(dates, PRICE.get(s_p := 'ETH', []), day),
                          price_on_or_after(dates, PRICE.get('ETH', []), (date.fromisoformat(day) + timedelta(days=28)).isoformat())) if 'ETH' in PRICE else None
        if fC is None:
            continue
        if any(x is None for x in fA_list) or any(x is None for x in fB_list):
            continue

        rA = np.array(fA_list, dtype=float)
        rB = np.array(fB_list, dtype=float)

        # 200 条随机路径
        rng = np.random.default_rng(0x5321_0000 + i)
        el_list = sorted(cset)
        if len(el_list) < 6:
            continue
        random_r6 = []
        for _ in range(200):
            pick = rng.choice(el_list, size=6, replace=False)
            fw = []
            ok = True
            for s in pick:
                p0 = price_on_or_after(dates, PRICE.get(s, []), day)
                p1 = price_on_or_after(dates, PRICE.get(s, []), (date.fromisoformat(day) + timedelta(days=28)).isoformat())
                if p0 is None or p1 is None:
                    ok = False
                    break
                fw.append(long_return(p0, p1))
            if ok:
                random_r6.append(float(np.mean(fw)))

        nA, nB = set(pA), set(pB)
        # 换手 / 成本放在第一次调仓之后再算
        per_year[day[:4]].append(dict(
            date=day,
            n_eligible=len(cset),
            picks_A=pA,
            picks_B=pB,
            fwd_A_raw=float(np.mean(rA)),
            fwd_B_raw=float(np.mean(rB)),
            fwd_C_raw=float(fC),
            random_r6=random_r6,
            scores=score,
        ))

    # 应用换手成本
    prevA, prevB = None, None
    for y, rs in per_year.items():
        for r in rs:
            nA, nB = set(r['picks_A']), set(r['picks_B'])
            if prevA is None:
                tA, tB = 0.0, 0.0
                cA, cB = 0.0, 0.0
            else:
                tA = len(prevA ^ nA) / max(len(prevA), 1)
                tB = len(prevB ^ nB) / max(len(prevB), 1)
                # COST 化在「单边换手总和」 上,平摊到 6 名上
                cA = COST * (len(prevA - nA) + len(nA - prevA)) / 6.0
                cB = COST * (len(prevB - nB) + len(nB - prevB)) / max(len(prevB), 1)
            r['turnover_A'] = tA
            r['turnover_B'] = tB
            r['fwd_A'] = r['fwd_A_raw'] - cA
            r['fwd_B'] = r['fwd_B_raw'] - cB
            r['fwd_C'] = r['fwd_C_raw']
            prevA, prevB = nA, nB

    n_total = sum(len(v) for v in per_year.values())
    print(f"  processed rebalances: {n_total}")

    print("[6/6] summary (descriptive only) ...")
    YEARS = ['2023', '2024', '2025', '2026']

    def mdd(rs):
        e = np.cumprod(1 + np.array(rs, dtype=float))
        p = np.maximum.accumulate(e)
        return float(((e - p) / p).min())

    def ann(rs, py=13):
        if not rs:
            return None
        v = float(np.prod([1 + r for r in rs]))
        return v ** (py / len(rs)) - 1

    summary = {}
    for y in YEARS:
        rs = per_year.get(y, [])
        if not rs:
            summary[y] = None
            continue
        rA = [r['fwd_A'] for r in rs]
        rB = [r['fwd_B'] for r in rs]
        rC = [r['fwd_C'] for r in rs]
        pcts = [percentile_of(r['fwd_A'], r['random_r6']) for r in rs]
        n_elig = [r['n_eligible'] for r in rs]
        row = dict(
            n=len(rs),
            first=rs[0]['date'],
            last=rs[-1]['date'],
            A_tr=float(np.prod([1 + r for r in rA]) - 1),
            A_an=ann(rA),
            A_dd=mdd(rA),
            B_tr=float(np.prod([1 + r for r in rB]) - 1),
            B_an=ann(rB),
            B_dd=mdd(rB),
            C_tr=float(np.prod([1 + r for r in rC]) - 1),
            C_an=ann(rC),
            C_dd=mdd(rC),
            dB=float((np.prod([1 + r for r in rA]) - np.prod([1 + r for r in rB]))),
            dC=float((np.prod([1 + r for r in rA]) - np.prod([1 + r for r in rC]))),
            nE=float(np.mean(n_elig)),
            tA=float(np.mean([r['turnover_A'] for r in rs])),
            tB=float(np.mean([r['turnover_B'] for r in rs])),
            pct_mean=float(np.mean([p for p in pcts if p is not None])) if any(p is not None for p in pcts) else None,
            pct_median=float(np.median([p for p in pcts if p is not None])) if any(p is not None for p in pcts) else None,
        )
        # apparatus.ab_test 用 4 周收益节奏:days_per_year=13
        if len(rA) >= 6:
            row['ab_vs_B'] = ab_test(rA, rB, mean_block=3, days_per_year=13, n_boot=2000, seed=int(y) * 1000 + i)
        else:
            row['ab_vs_B'] = None
        summary[y] = row

    # 全段
    all_rs = []
    for y in YEARS:
        all_rs.extend(per_year.get(y, []))
    rA_all = [r['fwd_A'] for r in all_rs]
    rB_all = [r['fwd_B'] for r in all_rs]
    rC_all = [r['fwd_C'] for r in all_rs]
    rnd_all = []
    for r in all_rs:
        rnd_all.extend(r['random_r6'])
    pct_all = [percentile_of(r['fwd_A'], r['random_r6']) for r in all_rs]
    summary['FULL'] = dict(
        n=len(all_rs),
        first=all_rs[0]['date'],
        last=all_rs[-1]['date'],
        A_tr=float(np.prod([1 + r for r in rA_all]) - 1),
        A_an=ann(rA_all),
        A_dd=mdd(rA_all),
        B_tr=float(np.prod([1 + r for r in rB_all]) - 1),
        B_an=ann(rB_all),
        B_dd=mdd(rB_all),
        C_tr=float(np.prod([1 + r for r in rC_all]) - 1),
        C_an=ann(rC_all),
        C_dd=mdd(rC_all),
        dB=float((np.prod([1 + r for r in rA_all]) - np.prod([1 + r for r in rB_all]))),
        dC=float((np.prod([1 + r for r in rA_all]) - np.prod([1 + r for r in rC_all]))),
        nE=float(np.mean([r['n_eligible'] for r in all_rs])),
        tA=float(np.mean([r['turnover_A'] for r in all_rs])),
        pct_mean=float(np.mean([p for p in pct_all if p is not None])) if any(p is not None for p in pct_all) else None,
        pct_median=float(np.median([p for p in pct_all if p is not None])) if any(p is not None for p in pct_all) else None,
    )
    if rnd_all:
        arr_rnd = np.array(rnd_all)
        summary['FULL']['rnd_p5'] = float(np.percentile(arr_rnd, 5))
        summary['FULL']['rnd_p50'] = float(np.percentile(arr_rnd, 50))
        summary['FULL']['rnd_p95'] = float(np.percentile(arr_rnd, 95))
    if len(rA_all) >= 6:
        summary['FULL']['ab_vs_B'] = ab_test(rA_all, rB_all, mean_block=3, days_per_year=13, n_boot=2000, seed=589)

    # === 写 Markdown 报告(描述性,不进判定) ===
    def pc(x):
        if x is None:
            return "—"
        return ("%+.2f%%" % (x * 100))

    L = []
    L.append("# T-109 — 山寨龙头腿 v1 描述性回放(S-589 前向预注册)")
    L.append("")
    L.append(f"- 回放窗口(F/O 实际可达):**{summary['FULL']['first']} -> {summary['FULL']['last']}**")
    L.append(f"- 调仓次数:**{summary['FULL']['n']}**(每 28 天一次,周五近似,起 2023-01-06)")
    L.append(f"- 候选宇宙(去 BTC + 稳定/包装启发式):**{len(UNIV)}** 名加密名")
    L.append(f"- 成本:**{COST*10000:.0f} bp** 单边;换手按 (上一调仓 − 本调仓)| ∪ |(本 − 上一)| 计入")
    L.append("- 数据:CIS F/O 取自 `_data/cis_history.db`;价格/市值取自 `research/crypto_daily/panel.json`(Mac 数据根)")
    L.append("- 脚本:`docs/research/T-109_alt_leaders_replay.py`;零分布 / 盈亏 / A-B 用 `src/data/evaluation/apparatus.py`")
    L.append("")
    L.append("**规则(逐字照 S-589 prereg,未改):**")
    L.append("- 龙头门槛:当日市值前 15 **且** 13 周年化波动 ≤ 宇宙中位数 × 1.5 **且** 13 周流通量增幅 ≤ 10%")
    L.append("- 打分 = 秩(F) + 秩(O) + 秩(市值) − 秩(vol13);取前 6 等权(单名 ≤ 20%)")
    L.append("- 对照:**B** = 同门槛全部等权;**C** = 只持 ETH;**D** = 同门槛内随机 6 名(每调仓 200 条路径)")
    L.append("")
    L.append("> **只描述,不写通过/不通过。** 2023–2026 已被 S-587 / S-589 探索看过,本表不进入判定;判据由 §S-589 前向预注册规定(满 26 次调仓 ≈ 2 年),本回放只把规则历史跑一遍。")
    L.append("")
    L.append("## 0. 数据覆盖(描述性)")
    L.append("- CIS F / O 实际最早覆盖 **2024-01-30**(cis_history.db),所以 **2023 整段没有可调仓日**——不是「策略筛掉」,是「评分缺」。")
    L.append("- 与 S-589 探索窗口(2023-01 → 2026-09)的差异已照实登记;若未来 F/O 回填至 2023,本回放需要重跑。")
    L.append("")
    L.append("## 1. 汇总表(描述性)")
    L.append("")
    L.append("| 段 | n | A 累计 | A 年化 | A maxDD | B 累计 | B 年化 | B maxDD | C 累计 | C 年化 | C maxDD | A−B 总差 | A−C 总差 | 平均合格 | A 换手 | A 在随机6 中位分位 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    def mrow(p, s):
        if s is None:
            return f"| {p} | 0 | — | — | — | — | — | — | — | — | — | — | — | — | — | — |"
        parts = [f"| {p}", str(s['n']), pc(s['A_tr']), pc(s['A_an']), pc(s['A_dd']),
                 pc(s['B_tr']), pc(s['B_an']), pc(s['B_dd']),
                 pc(s['C_tr']), pc(s['C_an']), pc(s['C_dd']),
                 pc(s['dB']), pc(s['dC']),
                 "%.1f" % s['nE'], pc(s['tA'])]
        pct = s.get('pct_median')
        parts.append("%.1f%%" % (pct * 100) if pct is not None else "—")
        parts.append("|")
        return " | ".join(parts)

    for y in YEARS:
        L.append(mrow(y, summary.get(y)))
    L.append(mrow("FULL", summary['FULL']))
    L.append("")
    L.append("### 1.1 A vs B 的 apparatus.ab_test(4 周节奏,mean_block=3,days_per_year=13)")
    L.append("")
    L.append("| 段 | n | cumA | cumB | log_diff_total | ratio_b/a | ci95_log_diff | p_B≤A | verdict | underpowered |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for y in YEARS + ['FULL']:
        k = summary.get(y)
        ab = (k or {}).get('ab_vs_B') if k else None
        if ab is None:
            L.append(f"| {y} | 0 | — | — | — | — | — | — | 不可算 | — |")
            continue
        if ab.get('verdict') == '不可算':
            L.append(f"| {y} | {ab['n_days']} | — | — | — | — | — | — | 不可算 | — |")
            continue
        lo, hi = ab['ci95_log_diff']
        L.append("| %s | %d | %s | %s | %+.4f | %.3f | (%.3f, %.3f) | %.3f | %s | %s |" % (
            y, ab['n_days'], pc(ab['cum_a']), pc(ab['cum_b']),
            ab['log_diff_total'], ab['ratio_b_over_a'],
            lo, hi, ab['p_b_le_a'], ab['verdict'], str(ab['underpowered'])
        ))
    L.append("")
    L.append("- **verdict 字段进表只作数值报告,不代表本研究对其作任何通过/不通过的解读。**")
    L.append("")
    L.append("### 1.2 A vs 随机 6(全段)")
    sf = summary['FULL']
    if 'rnd_p5' in sf:
        L.append(f"- 随机 6 名 4 周收益分布:p5 = {pc(sf['rnd_p5'])}, p50 = {pc(sf['rnd_p50'])}, p95 = {pc(sf['rnd_p95'])}")
    L.append(f"- A 在 200 条随机路径里的中位分位:**{pc(sf.get('pct_median'))}**;平均分位 {pc(sf.get('pct_mean'))}")
    L.append("- 该分位同样只作描述;S-589 预设的过门槛是 ≥ 0.90 出现频次,留待前向账本自己算。")
    L.append("")
    L.append("## 2. 每次调仓选中的名字(按综合分降序)")
    L.append("")
    L.append("| 调仓日 | 合格数 | A 的 6 名(综合分) | A 综合分列表 |")
    L.append("|---|---|---|---|")
    for y in YEARS:
        for r in per_year.get(y, []):
            parts = []
            for s in r['picks_A']:
                parts.append(f"{s}({int(r['scores'][s])})")
            L.append("| %s | %d | %s | %s |" % (
                r['date'], r['n_eligible'], ", ".join(r['picks_A']), ", ".join(parts)
            ))
    L.append("")
    L.append("## 3. 备注(描述性,非判定)")
    L.append("")
    L.append("- 2023 整段无调仓是数据缺口(F/O 评分缺),不是策略判断 —— 这一点不能被解读为「策略在 2023 表现差」。")
    L.append("- 本回放 26 次调仓门槛未达 → §S-589 prereg 写明「满 26 次调仓 ≈ 2 年后评,中途只描述不评」 —— 这里 **只把样本数据摆出来,不写解读 / 不写通过 / 不写不通过**。")
    L.append("- 全段 / 分段 A vs B 的 apparatus.ab_test 的 verdict 是数值结果,被登记在这里给后续的前向账本交叉对照用,但**不构成本研究的结论**。")
    L.append("")
    L.append("## 4. 透明性")
    L.append("")
    L.append("- 脚本里的随机种子:`np.random.default_rng(0x53210000 + i)`(i 是调仓序号)—— 同 i + 同 seed 永远同 200 条路径")
    L.append("- 与已有 `docs/research/T-109_alt_leaders_replay.py`(lane-a/T-107 分支)结构相同,但用具名 `apparatus.ab_test / percentile_of / long_return / price_on_or_after` 取代手写的均值检验与零分布;数据路径与签名同")
    L.append("- 不动 `src/`(本次 allowed_paths 只含 `docs/research/`)")

    md_path = OUT + "/T-109_alt_leaders_replay.md"
    open(md_path, "w").write("\n".join(L))
    print("wrote", md_path)
    jp = OUT + "/T-109_alt_leaders_replay.json"
    out_json = {
        "summary": summary,
        "universe_count": len(UNIV),
        "rebalances": [],
    }
    for y in YEARS:
        for r in per_year.get(y, []):
            out_json["rebalances"].append(dict(
                date=r['date'],
                year=y,
                picks_A=r['picks_A'],
                picks_B=r['picks_B'],
                n_eligible=r['n_eligible'],
                fwd_A=r['fwd_A'],
                fwd_B=r['fwd_B'],
                fwd_C=r['fwd_C'],
                fwd_A_raw=r['fwd_A_raw'],
                fwd_B_raw=r['fwd_B_raw'],
                fwd_C_raw=r['fwd_C_raw'],
                turnover_A=r['turnover_A'],
                turnover_B=r['turnover_B'],
                scores=r['scores'],
            ))
    json.dump(out_json, open(jp, "w"), indent=2, default=str)
    print("wrote", jp)

    print("\nFULL summary:")
    for k, v in summary['FULL'].items():
        if isinstance(v, dict):
            print(" ", k, "= {ab_test result}")
        else:
            print(f"  {k} = {v}")


if __name__ == "__main__":
    main()
