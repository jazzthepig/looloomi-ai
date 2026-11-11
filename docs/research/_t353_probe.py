#!/usr/bin/env python3
"""T-353 探针:核对继承来的假设 —— entry_px 是否 = entry_d 开盘;exit_px 是哪根价;r 的定义式。"""
import json
from collections import Counter

UM = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"
T197 = "/Users/sbb/Projects/looloomi-ai/docs/research/t197_results.json"

bars = {}
with open(UM) as f:
    for line in f:
        o = json.loads(line)
        if o.get("bars"):
            bars[o["symbol"]] = {r[0]: tuple(float(x) for x in r[1:5]) for r in o["bars"]}

A = json.load(open(T197))["tickets"]["A"]


def near(a, b):
    return abs(a - b) <= 1e-9 * max(1.0, abs(b))


# ---- 1) entry_px vs entry_d 开盘 / 收盘 ----
c_entry = Counter()
c_exit = Counter()
r_gap = []
for t in A:
    bb = bars.get(t["symbol"], {})
    e = bb.get(t["entry_d"])
    if e:
        if near(e[0], t["entry_px"]):
            c_entry["open"] += 1
        elif near(e[3], t["entry_px"]):
            c_entry["close"] += 1
        elif near(e[1], t["entry_px"]):
            c_entry["high"] += 1
        elif near(e[2], t["entry_px"]):
            c_entry["low"] += 1
        else:
            c_entry["nomatch"] += 1
            r_gap.append((t, e))
    else:
        c_entry["no_bar_on_entry_d"] += 1

    if t.get("exit_d"):
        x = bb.get(t["exit_d"])
        if x:
            tags = []
            if near(x[0], t["exit_px"]):
                tags.append("open")
            if near(x[1], t["exit_px"]):
                tags.append("high")
            if near(x[2], t["exit_px"]):
                tags.append("low")
            if near(x[3], t["exit_px"]):
                tags.append("close")
            if near(t["stop_px"], t["exit_px"]):
                tags.append("=stop")
            c_exit["+".join(tags) or "nomatch"] += 1
        else:
            c_exit["no_bar_on_exit_d"] += 1

print("entry_px 落在哪根价:", c_entry.most_common())
print("exit_px 落在哪根价 :", c_exit.most_common())

# ---- 2) r 的定义式 ----
forms = Counter()
gap_ex = []
for t in A:
    if not t.get("exit_d"):
        continue
    sd = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
    r_sd = (t["exit_px"] - t["entry_px"]) / (t["entry_px"] - t["stop_px"])   # R 口径
    r_pct = (t["exit_px"] / t["entry_px"] - 1.0) / sd                       # 百分比/sd
    if near(r_sd, t["r"]):
        forms["R=(exit-entry)/(entry-stop)"] += 1
    elif near(r_pct, t["r"]):
        forms["(exit/entry-1)/sd"] += 1
    else:
        forms["neither"] += 1
        if len(gap_ex) < 5:
            gap_ex.append((t, r_sd, r_pct))
print("r 定义式:", forms.most_common())
for t, a, b in gap_ex:
    print("  MISMATCH", t["symbol"], t["entry_d"], "entry", t["entry_px"], "stop", t["stop_px"],
          "exit", t["exit_px"], "r", round(t["r"], 6), "R-form", round(a, 6), "pct-form", round(b, 6))

# ---- 3) r vs 实际开盘价口径(若 entry_px 不是开盘,用真实开盘重算) ----
alt = Counter()
for t in A:
    if not t.get("exit_d"):
        continue
    bb = bars.get(t["symbol"], {})
    e = bb.get(t["entry_d"])
    x = bb.get(t["exit_d"])
    if not e or not x:
        continue
    o = e[0]
    # 若入场用开盘 o、止损按比例保持、退出用 exit_px
    stop_o = o * (1 - (t["entry_px"] - t["stop_px"]) / t["entry_px"])
    r_alt = (t["exit_px"] - o) / (o - stop_o)
    if near(r_alt, t["r"]):
        alt["open_entry_scaled_stop"] += 1
    else:
        alt["no"] += 1
print("r = f(真实开盘,按比例止损):", alt.most_common())

# ---- 4) 票的 universe 分布 / still / 同日进出数量 ----
print("universe:", Counter(t["universe"] for t in A).most_common())
print("still:", Counter(bool(t.get("still")) for t in A).most_common())
print("same-day exit tickets:", sum(1 for t in A if t.get("exit_d") == t["entry_d"]))
print("no exit_d:", sum(1 for t in A if not t.get("exit_d")))
sym_no_exit = Counter(t["symbol"] for t in A if not t.get("exit_d"))
print("still symbols:", sym_no_exit.most_common(5), "n=", len(sym_no_exit))
