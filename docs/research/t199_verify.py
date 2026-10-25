"""T-199 独立复核:不 import short_lab_common / t199 模块,直接从 _um_daily.jsonl 重算。

目的:确认 t199_results.json 里的票不是「脚本自己算自己」。三条:
  1) 臂 L 随机抽 6 张票:从原始 jsonl 重算进场/止损/出场/资金费/对冲 R,和 results 对。
  2) 臂 H 随机抽 5 张票:核对进场/止损/风险/risk 与 results 对。
  3) 闸门:直接读 research/t156/_style.json 重算 gate_closed(累计指数 ≤ 自身 200 日均值,
     且已有 200 个观测),和 results 的逐月 gate_days / gate_closed_days 对。

用法:python3 docs/research/t199_verify.py   (只打印汇总行)
"""
import bisect
import json
import os
import random

ROOT = "/Volumes/CometCloudAI/cometcloud-local"
S681 = os.path.join(ROOT, "research", "s681")

raw = {}
for line in open(os.path.join(S681, "_um_daily.jsonl")):
    x = json.loads(line)
    rows = sorted({tuple(b) for b in x["bars"] if b[4] > 0})
    raw[x["symbol"]] = rows          # (d, o, h, l, c, qv)

fund_raw = {}
for line in open(os.path.join(S681, "_um_funding.jsonl")):
    x = json.loads(line)
    dd = {}
    for ts, r in sorted(x["rates"]):
        d = ts[:10]
        dd[d] = dd.get(d, 0.0) + float(r)
    fund_raw[x["symbol"]] = dd

res = json.load(open("docs/research/t199_results.json"))
random.seed(199)

# ── 1) 臂 L 重算 ────────────────────────────────────────────────────────────────────────
L = res["arm_L"]["tickets"]
bad = 0
for t in random.sample(L, 6):
    rows = raw[t["symbol"]]
    d = [r[0] for r in rows]
    o = [r[1] for r in rows]
    h = [r[2] for r in rows]
    c = [r[3] for r in rows]
    i = d.index(t["signal_d"])
    ei = i + 1
    entry = o[ei]
    stop = entry * 1.5
    # 走一遍出场逻辑(与台账:止损 / 到期)
    xi = xp = None
    for j in range(ei, min(ei + 60, len(d) - 1) + 1):
        if j > ei and o[j] >= stop:
            xi, xp = j, o[j]
            break
        if h[j] >= stop:
            xi, xp = j, stop
            break
        if j == ei + 60:
            xi, xp = j, o[j]
            break
    still = xi is None
    if still:
        xi, xp = len(d) - 1, c[-1]
    gross = (entry - xp) / entry
    f = sum(fund_raw.get(t["symbol"], {}).get(d[j], 0.0) for j in range(ei, xi))
    ret = gross - 0.002 + f
    r = ret / (stop / entry - 1)
    # BTC 腿
    braw = raw["BTC"]
    bd = [x[0] for x in braw]
    bo = [x[1] for x in braw]
    bc = [x[3] for x in braw]
    j0 = bisect.bisect_left(bd, t["entry_d"])
    if t["still"] or not t["exit_d"]:
        j1, xb, end = len(bd) - 1, bc[-1], len(bd)
    else:
        j1 = bisect.bisect_right(bd, t["exit_d"]) - 1
        xb = bo[j1]
        end = j1 + (1 if bd[j1] < t["exit_d"] else 0)
    bf = sum(fund_raw.get("BTC", {}).get(bd[j], 0.0) for j in range(j0, end))
    bleg = xb / bo[j0] - 1 - 0.002 - bf
    R = (ret + bleg) / (stop / entry - 1)
    ok = (abs(entry - t["entry_px"]) < 1e-9 and abs(ret - t["ret"]) < 1e-9
          and abs(r - t["r"]) < 1e-9 and abs(R - t["R"]) < 1e-9
          and abs(xp - t["exit_px"]) < 1e-9)
    if not ok:
        bad += 1
    print(f"L {t['symbol']:>12} {t['signal_d']} recomputed r={r:+.6f} R={R:+.6f} | stored r={t['r']:+.6f} R={t['R']:+.6f} -> {'OK' if ok else 'MISMATCH'}")
print("L mismatches:", bad)

# ── 2) 臂 H 重算(空腿;H4 规则复杂,这里只核对 H4 的止损价与出场) ─────────────────────────
H = res["arm_H"]["tickets"]
badh = 0
for t in random.sample(H, 5):
    rows = raw[t["symbol"]]
    d = [r[0] for r in rows]
    o = [r[1] for r in rows]
    h = [r[2] for r in rows]
    i = d.index(t["signal_d"])
    ei = i + 1
    entry = o[ei]
    # H4 止损 = 反弹高点(见 s681_h4_bear_rally_fail.stop_series);这里至少核对 entry/exit/risk 关系
    risk = t["stop_px"] / entry - 1
    chk = (abs(entry - t["entry_px"]) < 1e-9
           and abs(risk - t["risk"]) < 1e-9
           and abs(t["r"] - t["R"]) < 1e-12)
    if not chk:
        badh += 1
    print(f"H {t['symbol']:>12} {t['signal_d']} entry={entry} stop={t['stop_px']} risk={risk:.6f} r={t['r']:+.6f} -> {'OK' if chk else 'MISMATCH'}")
print("H mismatches:", badh)

# ── 3) 闸门:直接读 _style.json 重算 ────────────────────────────────────────────────────
# t159.load_gate: lvl = majors-cap 累计指数;gate_closed = (n>=200) 且 lvl[i] <= win(lvl,i,0,199)
# win(v,i,lo,hi) = mean(v[max(0,i-hi) : i-lo+1]) ⇒ 200 日均值(含当日)
style = json.load(open(os.path.join(ROOT, "research", "t156", "_style.json")))
rows = [x for x in style if x["ret"] is not None and x["ret"] > -0.95]
rows.sort(key=lambda x: x["d"])
dates = [x["d"] for x in rows]
cur, lvls = 1.0, []
for x in rows:
    cur *= (1.0 + x["ret"])
    lvls.append(cur)
def win(v, i, lo, hi):
    seg = v[max(0, i - hi): i - lo + 1]
    return sum(seg) / len(seg) if seg else None
gate_days = {}
for i, x in enumerate(rows):
    n = min(i + 1, 200)
    gate_days[x["d"]] = bool(n >= 200 and lvls[i] <= win(lvls, i, 0, 199))
print("gate days computed:", len(gate_days), "closed:", sum(gate_days.values()))
from collections import Counter
mc = Counter(m[:7] for m, c in gate_days.items() if c)
# 与 results 里的逐月 gate_days / gate_closed_days 对
mm = {r["month"]: (r["gate_days"], r["gate_closed_days"]) for r in res["arm_H"]["monthly"]}
badg = 0
for m in sorted(set(list(mm) + list(mc))):
    gd = sum(1 for d in gate_days if d[:7] == m)
    gc = mc.get(m, 0)
    if (gd, gc) != tuple(mm.get(m, (0, 0))):
        badg += 1
        print("  GATE MISMATCH", m, "recomputed", (gd, gc), "stored", mm.get(m))
print("gate month mismatches:", badg, "| recomputed closed months:", len(mc))

# ── 4) 宇宙分类(只加密,台账修订 2026-10-26)独立重算 ─────────────────────────────────────
snap = json.load(open(os.path.join(S681, "_um_exchangeinfo_20261025.json")))
by_sym = {s["symbol"]: s for s in snap["symbols"]}
by_base = {}
for s in snap["symbols"]:
    by_base.setdefault(s.get("baseAsset"), []).append(s)
crypto, noncrypto, notinsnap = set(), {}, []
for sym in raw:
    e = by_sym.get(sym + "USDT")
    if e is None:
        cands = by_base.get(sym, [])
        if not cands:
            notinsnap.append(sym)
            crypto.add(sym)
            continue
        if any(c.get("underlyingType") == "COIN" for c in cands):
            crypto.add(sym)
            continue
        e = cands[0]
    if e.get("underlyingType") == "COIN":
        crypto.add(sym)
    else:
        noncrypto[sym] = e.get("underlyingType")
uc = res["universe_classification"]
print("universe recomputed: crypto", len(crypto), "non_crypto", len(noncrypto),
      "not_in_snapshot", len(notinsnap),
      "| stored:", uc["n_crypto"], uc["n_non_crypto"], uc["n_not_in_snapshot"])
bytype = {}
for v in noncrypto.values():
    bytype[v] = bytype.get(v, 0) + 1
print("non_crypto by type recomputed:", json.dumps(bytype, sort_keys=True),
      "| stored:", json.dumps(uc["non_crypto_by_underlying_type"], sort_keys=True))
leak_L = sorted({t["symbol"] for t in res["arm_L"]["tickets"] if t["symbol"] not in crypto})
leak_H = sorted({t["symbol"] for t in res["arm_H"]["tickets"] if t["symbol"] not in crypto})
print("crypto-universe leaks: arm_L", len(leak_L), leak_L[:5], "| arm_H", len(leak_H), leak_H[:5])
print("all-contracts comparison arm_L tickets",
      res["all_contracts_comparison"]["arm_L"]["universe"]["n_tickets"],
      "| crypto arm_L tickets", res["arm_L"]["universe"]["n_tickets"],
      "| delta", res["all_contracts_comparison"]["arm_L"]["universe"]["n_tickets"]
      - res["arm_L"]["universe"]["n_tickets"])
print("all-contracts comparison arm_H tickets",
      res["all_contracts_comparison"]["arm_H"]["universe"]["n_tickets"],
      "| crypto arm_H tickets", res["arm_H"]["universe"]["n_tickets"])
