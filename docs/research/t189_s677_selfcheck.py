#!/usr/bin/env python3
"""
T-189 自检 —— 把 r_v2_tickets.sql 逐行直译成 1-based 的纯 Python(与 t189_s677_replicate.py
的 0-based numpy 写法完全不同的代码路径),跑同一份数据,逐张比票。

目的:排除「实现层写错」这一类错(下标错位、窗口含不含当天、止损/出场次序)。
两份互不相干的写法对上 ⇒ 剩下的分歧只可能来自「规则读法」,那是 Seth 对票时要看的东西。

跑法:  python3 docs/research/t189_s677_selfcheck.py
"""
import csv
import json
import os

DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
BARS_PATH = os.path.join(DATA_ROOT, "research/s677/_bv_daily.jsonl")
GATE_PATH = os.path.join(DATA_ROOT, "research/s677/_gate_proxy.json")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_OUT = os.path.join(REPO_ROOT, "docs/research/t189_tickets.csv")

SIG_FROM, SIG_TO = "2018-01-01", "2020-02-29"
MIN_RN, ADV30_MIN, MINDD_MAX, RANGE_MAX = 220, 5e6, 0.5, 0.40
DV_MULT, ATR_MULT, COST, MAX_HOLD = 2.0, 2.5, 0.004, 120


def gate_lookup(runs, day):
    for r in runs:
        if r["start"] <= day <= r["end"]:
            return r["open"]
    return True


def run_symbol(sym, bars, runs):
    """1-based: a[k] = 第 k 根(SQL array_agg 的下标)。"""
    n = len(bars)
    ad = [""] + [b[0] for b in bars]
    ao = [0.0] + [b[1] for b in bars]
    ah = [0.0] + [b[2] for b in bars]
    al = [0.0] + [b[3] for b in bars]
    ac = [0.0] + [b[4] for b in bars]
    adv = [0.0] + [b[5] for b in bars]

    sma20 = [None] * (n + 1)
    sma200 = [None] * (n + 1)
    atr14 = [None] * (n + 1)
    adv30 = [None] * (n + 1)
    adv40p = [None] * (n + 1)
    hh40 = [None] * (n + 1)
    ll40 = [None] * (n + 1)
    dd = [None] * (n + 1)
    mindd120 = [None] * (n + 1)

    for rn in range(1, n + 1):
        pc = ac[rn - 1] if rn > 1 else ac[rn]
        tr = max(ah[rn] - al[rn], abs(ah[rn] - pc), abs(al[rn] - pc))
        lo20 = max(1, rn - 19)
        lo200 = max(1, rn - 199)
        lo14 = max(1, rn - 13)
        lo30 = max(1, rn - 29)
        lo40 = max(1, rn - 40)
        lo365 = max(1, rn - 365)
        lo120 = max(1, rn - 120)
        sma20[rn] = sum(ac[lo20:rn + 1]) / (rn + 1 - lo20)
        sma200[rn] = sum(ac[lo200:rn + 1]) / (rn + 1 - lo200)
        adv30[rn] = sum(adv[lo30:rn + 1]) / (rn + 1 - lo30)
        if rn >= 2:
            adv40p[rn] = sum(adv[lo40:rn]) / (rn - lo40)
            hh40[rn] = max(ah[lo40:rn])
            ll40[rn] = min(al[lo40:rn])
        peak = max(ac[lo365:rn + 1])
        dd[rn] = ac[rn] / peak
        mindd120[rn] = min(dd[lo120:rn + 1])

    # TR 第二遍
    trs = [0.0] * (n + 1)
    for rn in range(1, n + 1):
        pc = ac[rn - 1] if rn > 1 else ac[rn]
        trs[rn] = max(ah[rn] - al[rn], abs(ah[rn] - pc), abs(al[rn] - pc))
    for rn in range(1, n + 1):
        lo14 = max(1, rn - 13)
        atr14[rn] = sum(trs[lo14:rn + 1]) / (rn + 1 - lo14)

    # ---- 事件(SQL ev)
    ev = []
    for rn in range(1, n + 1):
        if rn < MIN_RN:
            continue
        if not (SIG_FROM <= ad[rn] <= SIG_TO):
            continue
        if rn + 1 > n:
            continue
        if not adv30[rn] >= ADV30_MIN:
            continue
        if not mindd120[rn] <= MINDD_MAX:
            continue
        if not (hh40[rn] - ll40[rn]) / hh40[rn] <= RANGE_MAX:
            continue
        if not ac[rn] > hh40[rn]:
            continue
        if not ac[rn] > sma200[rn]:
            continue
        if not adv[rn] >= DV_MULT * adv40p[rn]:
            continue
        if not atr14[rn] > 0:
            continue
        if not gate_lookup(runs, ad[rn]):
            continue
        ev.append(rn)

    # ---- sim / tr(SQL 一致)
    tr_rows = []
    for rn in ev:
        ei = rn + 1
        entry = ao[ei]
        stop = entry - ATR_MULT * atr14[rn]
        if not entry > stop:
            continue
        k = None
        for j in range(ei, min(rn + MAX_HOLD, n) + 1):
            if al[j] <= stop or ac[j] < sma20[j]:
                k = j
                break
        if k is None:
            xi = min(rn + MAX_HOLD, n)
            xp = ac[xi]
            still = (rn + MAX_HOLD) > n
            rule = "expiry"
        elif al[k] <= stop:
            xi = k
            xp = ao[k] if (k > ei and ao[k] <= stop) else stop
            still = False
            rule = "stop"
        else:
            if k + 1 <= n:
                xi = k + 1
                xp = ao[xi]
                still = False
                rule = "sma20"
            else:
                xi = k
                xp = ac[k]
                still = True
                rule = "sma20_lastbar"
        denom = entry - stop
        r = (xp - entry) / denom - COST * entry / denom
        tr_rows.append({"symbol": sym, "rn": rn, "d": ad[rn], "ei": ei, "xi": xi,
                        "entry": entry, "stop": stop, "xp": xp, "r": r,
                        "still": still, "rule": rule,
                        "entry_d": ad[ei], "exit_d": ad[xi]})

    # ---- rec(SQL 递归:同币不叠票)
    taken = []
    for t in sorted(tr_rows, key=lambda x: x["ei"]):
        if not taken:
            taken.append(t)
        elif t["ei"] > taken[-1]["xi"]:
            taken.append(t)
    return taken


def main():
    with open(GATE_PATH) as fh:
        runs = json.load(fh)["runs"]
    with open(BARS_PATH) as fh:
        rows = [json.loads(x) for x in fh]

    tickets = []
    for row in rows:
        tickets.extend(run_symbol(row["symbol"], row["bars"], runs))
    tickets.sort(key=lambda t: (t["d"], t["symbol"]))

    # ---- 与主脚本的 CSV 逐张比对
    with open(CSV_OUT) as fh:
        main_rows = list(csv.DictReader(fh))

    diffs = []
    if len(main_rows) != len(tickets):
        diffs.append("票数不同:主脚本 %d,自检 %d" % (len(main_rows), len(tickets)))
    for a, b in zip(main_rows, tickets):
        key = (a["symbol"], a["signal_d"], a["entry_d"], a["exit_d"], int(a["still"]))
        key2 = (b["symbol"], b["d"], b["entry_d"], b["exit_d"], int(b["still"]))
        if key != key2:
            diffs.append("票不同: %s vs %s" % (key, key2))
        if abs(float(a["r"]) - b["r"]) > 1e-8 * max(1.0, abs(b["r"])):
            diffs.append("R 不同: %s %s vs %s" % (a["symbol"], a["r"], b["r"]))
        for col, val in (("entry_px", b["entry"]), ("stop_px", b["stop"]), ("exit_px", b["xp"])):
            if abs(float(a[col]) - val) > 1e-8 * max(1.0, abs(val)):
                diffs.append("%s 不同: %s %s vs %s" % (col, a["symbol"], a[col], val))

    print("自检票数", len(tickets), " 主脚本票数", len(main_rows))
    if diffs:
        print("!! 差异 %d 条" % len(diffs))
        for d in diffs[:20]:
            print("  ", d)
        return 1
    print("两份独立实现逐张一致(票数 / 日期 / 价格 / R / still 全同)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
