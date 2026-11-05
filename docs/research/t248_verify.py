#!/usr/bin/env python3
"""T-248 独立复核:不读 perp_bv_daily 缓存,直接查 Supabase,核 t248_series_health.py 的结论。

只读。宇宙规则在本格子里**独立重写一遍**(不 import 主角色的 build_universe),传输层复用主角色的
get / count_rows。命中 FAIL 的项:

  V1 宇宙 = binance_hist 面板符号 ∩ perp_bv_pairs(kind='coin' 或 kind 为空且 dead_from 非空)
            + 1000X ↔ X —— 与 migrations/2026-11-05_r_tickets_universe_1000x.sql 的 uni CTE 同规则
  V2 2026-10-28 全市场缺(相邻日不缺)
  V3 空壳行:量额为 0 且 o=h=l=c;看 c 是不是 0(R-v2 的 b0 过滤 x.c > 0)
  V4 重复 (symbol, d)
  V5 与 HL 同日收盘相对差(取最大的那个符号日,双向手算)

用法: python3 t248_verify.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t248_series_health as T

OUT = []


def line(tag, ok, msg):
    OUT.append(dict(tag=tag, result="PASS" if ok else "FAIL", msg=msg))
    print(tag, "PASS" if ok else "FAIL", msg, flush=True)


# ── V1 宇宙(独立重写) ─────────────────────────────────────────────────────
panel = []
last = None
while True:
    f = {"source": "eq.binance_hist", "select": "symbol", "order": "symbol.asc", "limit": "1"}
    if last is not None:
        f["symbol"] = "gt." + last
    rows = T.get("ohlcv_daily", f)
    if not rows:
        break
    panel.append(rows[0]["symbol"])
    last = rows[0]["symbol"]
pset = set(panel)
pairs = T.fetch_all("perp_bv_pairs", {}, "symbol.asc", "symbol,kind,dead_from,active")
uni = []
for p in pairs:
    kind, dead = p.get("kind"), p.get("dead_from")
    if not (kind == "coin" or (kind is None and dead is not None)):
        continue
    s = p["symbol"]
    if s in pset or (s.startswith("1000") and len(s) > 4 and s[4:] in pset):
        uni.append(s)
uni = sorted(set(uni))
line("V1a universe size", len(uni) == 258, "n_universe=" + str(len(uni)) + " (期望 258)")
line("V1b 1000X 映射", all((s in pset) or (s.startswith("1000") and len(s) > 4 and s[4:] in pset) for s in uni),
     "1000X 条目 " + str([s for s in uni if s.startswith("1000")]))
line("V1c 面板规模", len(panel) > 0, "binance_hist 面板符号数=" + str(len(panel)) + " pairs=" + str(len(pairs)))

# ── V2 2026-10-28 全市场缺 ────────────────────────────────────────────────
inlist = "(" + ",".join(uni) + ")"
for d in ("2026-10-27", "2026-10-28", "2026-10-29"):
    c = T.count_rows("perp_bv_daily", {"symbol": "in." + inlist, "d": "eq." + d})
    line("V2 " + d, (c == 0) if d == "2026-10-28" else (c > 0), "rows=" + str(c))

# ── V3 空壳行 ──────────────────────────────────────────────────────────────
res = json.load(open("/Volumes/CometCloudAI/cometcloud-local/research/t248_cache/t248_results.json"))
sh = res["dead_marks"]["shell_but_unmarked_dead"]
sym0 = sh[0]["symbol"] if isinstance(sh[0], dict) else sh[0]
rows = T.get("perp_bv_daily", {"symbol": "eq." + sym0, "d": "gte.2026-01-01",
                               "select": "d,o,h,l,c,qv", "order": "d.asc", "limit": "1000"})
shrows = [r for r in rows if float(r["qv"]) == 0 and float(r["o"]) == float(r["c"])]
line("V3a 空壳存在", len(shrows) > 0, sym0 + " 空壳行=" + str(len(shrows)) + " / 2026 起总行=" + str(len(rows)))
if shrows:
    cvals = sorted(set(float(r["c"]) for r in shrows))
    last_real = [r for r in rows if float(r["qv"]) != 0]
    last_c = float(last_real[-1]["c"]) if last_real else None
    line("V3b 空壳 c = 最后一根真 bar 的收盘价(>0,价格冻结)",
         all(v == last_c for v in cvals) and last_c > 0,
         "c 取值集合=" + str(cvals[:5]) + " 最后一根真 bar 的 c=" + str(last_c) +
         " → R-v2 的 b0 只过滤 c>0,所以空壳行照样进面板(量额为 0)")
    if last_real:
        line("V3c 空壳起点在最后一根真 bar 之后", shrows[0]["d"] > last_real[-1]["d"],
             "最后一根真 bar=" + last_real[-1]["d"] + " 空壳首行=" + shrows[0]["d"])

# ── V4 重复 (symbol, d) —— 按 40 个一片取(单次 in.(…) 太长会被服务端慢慢排) ──
rows = []
for i in range(0, len(uni), 40):
    chunk = uni[i:i + 40]
    rows.extend(T.fetch_all("perp_bv_daily",
                            {"symbol": "in.(" + ",".join(chunk) + ")",
                             "d": "gte.2025-06-01", "or": "(d.lte.2026-11-04)"},
                            "symbol.asc,d.asc", "symbol,d"))
keys = [(r["symbol"], r["d"]) for r in rows]
line("V4a 无重复 (symbol,d)", len(keys) == len(set(keys)),
     "窗口内行=" + str(len(keys)) + " 唯一=" + str(len(set(keys))) + " 重复=" + str(len(keys) - len(set(keys))))

# ── V5 与 HL 同日收盘相对差(活 bar 与空壳行分开看) ─────────────────────────
# hl_map:永续名 → [HL 名, 乘数](乘数 1000 = 永续名是 1000X 面值,价格 ×1000)
hlmap = res["hl_map"]
worst_live = (0.0, None, None, None)
worst_shell = (0.0, None, None, None)
n_live = n_shell = 0
for perp_sym in list(hlmap.keys()):
    hl_name = hlmap[perp_sym][0]
    mult = float(hlmap[perp_sym][1])
    hrow = T.get("ohlcv_daily", {"symbol": "eq." + hl_name, "source": "eq.hyperliquid",
                                 "trade_date": "gte.2026-08-01",
                                 "select": "trade_date,close", "order": "trade_date.asc", "limit": "1000"})
    hrow = [r for r in hrow if str(r["trade_date"])[:10] <= "2026-08-31"]
    prow = T.get("perp_bv_daily", {"symbol": "eq." + perp_sym, "d": "gte.2026-08-01",
                                   "select": "d,o,h,l,c,qv", "order": "d.asc", "limit": "1000"})
    hd = dict((str(r["trade_date"])[:10], float(r["close"]) * mult) for r in hrow)
    for r in prow:
        d = str(r["d"])[:10]
        if d not in hd or hd[d] <= 0:
            continue
        c = float(r["c"])
        rel = abs(hd[d] - c) / hd[d]
        shell = (float(r["qv"]) == 0 and float(r["o"]) == c and float(r["h"]) == c and float(r["l"]) == c)
        if shell:
            n_shell += 1
            if rel > worst_shell[0]:
                worst_shell = (rel, perp_sym, hl_name, d)
        else:
            n_live += 1
            if rel > worst_live[0]:
                worst_live = (rel, perp_sym, hl_name, d)
rl, pl, hl_, dl = worst_live
line("V5a 活 bar 与 HL 的最大收盘相对差 < 5%", rl < 0.05,
     "活符号日=" + str(n_live) + " worst=" + str(pl) + "/" + str(hl_) + " @ " + str(dl) +
     " rel=" + str(round(rl, 6)))
rs, ps_, hs_, ds = worst_shell
line("V5b 空壳行(死名冻结价)与 HL 的偏离 > 0 是事实,只报不判", True,
     "空壳符号日=" + str(n_shell) + " worst=" + str(ps_) + "/" + str(hs_) + " @ " + str(ds) +
     " rel=" + str(round(rs, 6)) + "(冻结价 vs 活市价)")

json.dump(OUT, open("/Volumes/CometCloudAI/cometcloud-local/research/t248_cache/t248_verify.json", "w"),
          ensure_ascii=False, indent=1)
print("FAILS:", sum(1 for o in OUT if o["result"] == "FAIL"), "/", len(OUT))
