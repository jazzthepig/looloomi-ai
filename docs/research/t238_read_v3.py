"""T-238 v3 本轮独立核对 —— 不复用报告里的数,自己从原始文件 / DB 重算。

跑法:python3 docs/research/t238_read_v3.py
四件事:
  1) 复现:同脚本再跑一遍(从缓存的 bar 文件,不重拉 DB)→ judge 块逐字一致?
  2) 覆盖:DB `perp_bv_daily` 行数(Prefer: count=exact) vs 本地 _bars_pbv.jsonl 行数
  3) 序列:断点前 perp vs cache 的「收盘相对差中位」「成交额比值中位」—— 自己算
  4) 前向:HOT 2026-11-03 的信号输入(close/hh40/sma200/adv30/adv40p/dv)自己从原始 bar 重算
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict
from statistics import median

REPO = "/Users/sbb/Projects/looloomi-ai-lane-b"
MAC = "/Volumes/CometCloudAI/cometcloud-local"
PBV = os.path.join(MAC, "research/t238/_bars_pbv.jsonl")
RES_A = os.path.join(REPO, "docs/research/t238_results.json")
RES_B = os.path.join(MAC, "research/t238/_recheck_results.json")
SPLIT = "2026-08-08"


def rest_head(table):
    """只读:取 Content-Range 里的总行数。不打印任何 key。"""
    url = os.environ["SUPABASE_URL"] + "/rest/v1/" + table + "?select=symbol&limit=1"
    k = os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(url, headers={"apikey": k, "Authorization": "Bearer " + k,
                                               "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=90) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.split("/")[-1]) if "/" in cr else None


def read_pbv():
    by = defaultdict(list)
    n = 0
    with open(PBV) as f:
        for line in f:
            x = json.loads(line)
            if isinstance(x, dict) and "_meta" in x:
                continue
            for r in (x if isinstance(x, list) else [x]):
                by[r["symbol"]].append((r["d"], float(r["o"] or 0), float(r["h"] or 0),
                                        float(r["l"] or 0), float(r["c"] or 0), float(r["qv"] or 0)))
                n += 1
    return {s: sorted(v) for s, v in by.items()}, n


def read_cache():
    by = defaultdict(list)
    for d in ("research/t156/", "research/t159/"):
        for fn in (f"{d}_bars_early.jsonl", f"{d}_bars.jsonl"):
            p = os.path.join(MAC, fn)
            if not os.path.exists(p):
                continue
            for line in open(p):
                for x in json.loads(line):
                    by[x["symbol"]].append((x["trade_date"], float(x["open"]), float(x["high"]),
                                            float(x["low"]), float(x["close"]),
                                            float(x["close"]) * float(x["volume"])))
    return {s: sorted(set(v)) for s, v in by.items()}


def main():
    A = json.load(open(RES_A))
    B = json.load(open(RES_B))

    # 1) 复现
    print("[1] 复现 judge 逐字一致:", A["judge"] == B["judge"])
    print("    judge:", json.dumps(B["judge"], ensure_ascii=False))
    for sec in ("selfcheck_cache", "money", "oos_s677"):
        a, b = A[sec], B[sec]
        if sec == "oos_s677":
            a = {k: v for k, v in a.items() if not k.startswith("tickets_")}
            b = {k: v for k, v in b.items() if not k.startswith("tickets_")}
        print(f"    {sec} 一致:", a == b)
    ca = {k: v for k, v in A["tickets"]["compare"].items() if not k.endswith("_list")}
    cb = {k: v for k, v in B["tickets"]["compare"].items() if not k.endswith("_list")}
    print("    tickets.compare 一致:", ca == cb)
    print("    tickets.pbv 一致:", A["tickets"]["pbv"] == B["tickets"]["pbv"])

    # 2) 覆盖
    pbv, n_file = read_pbv()
    try:
        n_db = rest_head("perp_bv_daily")
    except Exception as e:  # noqa: BLE001
        n_db = f"ERR {type(e).__name__}"
    print(f"[2] perp_bv_daily: DB 行数={n_db} 本地 jsonl 行数={n_file} 符号={len(pbv)} "
          f"meta.expected_rows={A['data']['pbv_universe'].get('expected_rows')}")
    print("    DB 行数 == 本地行数:", n_db == n_file)

    # 3) 序列(自己算):perp vs cache,按 (symbol, d) 对齐,断点前后分开
    cache = read_cache()
    rows = []
    for s, pr in pbv.items():
        cr = {r[0]: r for r in cache.get(s, [])}
        for d, o, h, l, c, qv in pr:
            if d in cr:
                rows.append((s, d, c, cr[d][4], qv, cr[d][5]))
    pre = [r for r in rows if r[1] < SPLIT]
    post = [r for r in rows if r[1] >= SPLIT]
    for name, seg in (("pre", pre), ("post", post)):
        rel = [abs(r[2] - r[3]) / r[3] for r in seg if r[3]]
        rat = [r[4] / r[5] for r in seg if r[5]]
        print(f"[3] perp vs cache {name}: n={len(seg)} 收盘相对差中位={median(rel):.8f} "
              f"成交额比值中位={median(rat):.4f}")
    print("    报告值 pre: 收盘相对差中位 0.00000000 / 成交额比值中位 1.0086")

    # 4) 前向 HOT 2026-11-03 的信号输入(自己从原始 bar 重算)
    pr = pbv.get("HOT")
    if pr:
        c = [r[4] for r in pr]
        h = [r[2] for r in pr]
        l = [r[3] for r in pr]
        dv = [r[5] for r in pr]
        d = [r[0] for r in pr]
        i = d.index("2026-11-03")
        sma200 = sum(c[i - 199:i + 1]) / 200
        adv30 = sum(dv[i - 29:i + 1]) / 30
        adv40p = sum(dv[i - 40:i]) / 40
        hh40 = max(h[i - 40:i])
        ll40 = min(l[i - 40:i])
        pc = c[i - 1]
        tr = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(1, i + 1)]
        atr14 = sum(tr[-14:]) / 14
        print(f"[4] HOT {d[i]}: close={c[i]:.7f} hh40={hh40:.7f} sma200={sma200:.7f} "
              f"adv30=${adv30:,.0f} adv40p=${adv40p:,.0f} dv=${dv[i]:,.0f} atr14={atr14:.8f}")
        print(f"    c>hh40:{c[i] > hh40} c>sma200:{c[i] > sma200} adv30>=5M:{adv30 >= 5e6} "
              f"dv>=2*adv40p:{dv[i] >= 2 * adv40p} (hh40-ll40)/hh40={((hh40 - ll40) / hh40):.4f}")
        print(f"    次日进场 bar {d[i+1]} close={c[i+1]:.7f};再次日 {d[i+2]} close={c[i+2]:.7f}")
        print(f"    报告: 进场 0.0005488 / 出场 0.00043273 ⇒ −1.02R;止损位 = 进场 − 2.5×ATR = "
              f"{c[i+1] - 2.5 * atr14:.7f}")


if __name__ == "__main__":
    main()
