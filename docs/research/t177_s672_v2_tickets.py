"""S-672:CIS v2 的慢维度合成(规模 + 稳定 + 供给)在开票当时,是不是比「只看稀释」更能分开 R-v2 的好票与坏票。

照台账 S-672 预注册原文一字不改。票 = S-665 同一批(t159_bear_short.run_long 经 s657_s658_breadth_second_leg 复现的
770 张,仍持有的按最后收盘盯市,import 不复制)。三维与合成 = src.data.cis.v2 的 crypto_inputs / score_group(import 不复制)。
打乱只走 src/data/evaluation/apparatus.py(shuffle_within);A/B 用 ab_test。

截面(写死):信号日 t;宇宙 = 这 770 张票出现过的全部 symbol;每个 symbol 的三维由 crypto_inputs(≤ t 的行, t) 算,
合成 = score_group("crypto", raw) 的 score,在 t 当天这个宇宙里排(F / O 不给;≥ 2 维才有分)。

用法:set -a; source .env; set +a; python3 docs/research/t177_s672_v2_tickets.py --fetch [--root …];然后不带 --fetch 再跑一次
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import random
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root
sys.path.insert(0, HERE)
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
OUT = os.path.join(ROOT, "research", "t177")
SEED = 672
SPLIT = "2023-01-01"
CHUNK = 30

from src.data.cis import v2                                                    # noqa: E402  唯一内核,不复制
from src.data.evaluation import apparatus                                      # noqa: E402  打乱只走这里

_spec = importlib.util.spec_from_file_location("s657", os.path.join(HERE, "docs", "research", "s657_s658_breadth_second_leg.py"))
s657 = importlib.util.module_from_spec(_spec)
sys.modules["s657"] = s657
_spec.loader.exec_module(s657)
t159 = s657.t159


# ── 取数(publishable key,只读;不打印任何 key)─────────────────────────────────────────────────────
def rest(path: str, lo: int, hi: int) -> list:
    u, k = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(u + "/rest/v1/" + path,
                                 headers={"apikey": k, "Authorization": "Bearer " + k,
                                          "Range": f"{lo}-{hi}"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())


def fetch(symbols: list[str], max_s: float = 600.0):
    """按 30 个 symbol 一块抓,每块一个文件,可断点续跑;全部块都在才合并成 _mcap.json。"""
    os.makedirs(OUT, exist_ok=True)
    t0, chunks = time.time(), [symbols[k:k + CHUNK] for k in range(0, len(symbols), CHUNK)]
    for i, ch in enumerate(chunks):
        fn = os.path.join(OUT, f"_part{i:02d}.json")
        if os.path.exists(fn):
            continue
        if time.time() - t0 > max_s:
            break
        q = (f"asset_mcap_daily?select=symbol,coin_id,d,price,mcap"
             f"&symbol=in.({','.join(ch)})&d=gte.2019-06-01"
             f"&price=not.is.null&mcap=not.is.null"
             f"&order=symbol.asc,coin_id.asc,d.asc")          # T-170/T-173:翻页必须带 order,否则边界漂
        got, off = [], 0
        while True:
            b = rest(q, off, off + 999)
            got += b
            if len(b) < 1000:
                break
            off += 1000
        json.dump(got, open(fn, "w"))
    parts = [os.path.join(OUT, f"_part{i:02d}.json") for i in range(len(chunks))]
    done = [p for p in parts if os.path.exists(p)]
    if len(done) == len(parts):
        allrows = [x for p in parts for x in json.load(open(p))]
        json.dump(allrows, open(os.path.join(OUT, "_mcap.json"), "w"))
    print(json.dumps({"symbols": len(symbols), "chunks": len(parts), "done": len(done)}))


def completeness(rows: list) -> dict:
    """硬断言:每个 symbol 的 (coin_id, d) 无重复(翻页边界漂掉键时 rows 计数一次不差,键数才报警)。"""
    seen, dup = set(), 0
    for x in rows:
        k = (str(x["symbol"]).upper(), str(x["coin_id"]), str(x["d"])[:10])
        if k in seen:
            dup += 1
        seen.add(k)
    per = defaultdict(set)
    for sym, _cid, d in seen:
        per[sym].add(d)
    return {"rows": len(rows), "keys": len(seen), "dup_keys": dup,
            "symbols": len(per), "days_min": min((len(v) for v in per.values()), default=0),
            "days_max": max((len(v) for v in per.values()), default=0)}


def price_mcap_series() -> dict[str, list[tuple[dt.date, float, float]]]:
    """asset_mcap_daily → {symbol: [(d, price, mcap)] 升序};同 symbol 多个 coin_id 取最近一天市值最大的那个(同 S-665)。"""
    by: dict[tuple[str, str], list] = defaultdict(list)
    for x in json.load(open(os.path.join(OUT, "_mcap.json"))):
        if x["price"] and x["mcap"] and float(x["price"]) > 0 and float(x["mcap"]) > 0:
            by[(str(x["symbol"]).upper(), str(x["coin_id"]))].append(
                (dt.date.fromisoformat(str(x["d"])[:10]), float(x["price"]), float(x["mcap"])))
    best: dict[str, tuple[float, list]] = {}
    for (sym, _cid), ser in by.items():
        ser.sort()
        if sym not in best or ser[-1][2] > best[sym][0]:
            best[sym] = (ser[-1][2], ser)
    return {s: v[1] for s, v in best.items()}


# ── 判据工具(同一切法)─────────────────────────────────────────────────────────────────────────────
def within_year_median(rows: list, key) -> None:
    """年内中位数切两半:in place 写 low 标记(照 S-665 的写法,中位数取上中位)。"""
    by_y = defaultdict(list)
    for r in rows:
        by_y[r["signal_d"][:4]].append(r)
    for _y, rs in by_y.items():
        med = sorted(r[key] for r in rs)[len(rs) // 2]
        for r in rs:
            r["low"] = r[key] < med


def diff(rows: list) -> float | None:
    """① 差 = 高一半平均 R − 低一半平均 R。"""
    lo = [r["r"] for r in rows if r["low"]]
    hi = [r["r"] for r in rows if not r["low"]]
    return (sum(hi) / len(hi) - sum(lo) / len(lo)) if lo and hi else None


def perm_p(rows: list, n: int = 2000) -> tuple[float | None, dict]:
    """年内打乱高低标签 n 次(apparatus.shuffle_within:组内打乱归属,组间不混),单侧 p = P(null ≥ obs)。"""
    import numpy as np
    obs = diff(rows)
    if obs is None:
        return None, []
    labs = [r["low"] for r in rows]
    grp = [r["signal_d"][:4] for r in rows]
    null = []
    for i in range(n):
        sh = apparatus.shuffle_within(labs, grp, np.random.default_rng(SEED + i))
        lo, hi = [], []
        for r, lab in zip(rows, sh):
            (lo if lab else hi).append(r["r"])
        null.append(sum(hi) / len(hi) - sum(lo) / len(lo))
    ns = sorted(null)
    summ = {"n_null": len(null), "null_mean": sum(null) / len(null),
            "null_sd": (sum((x - sum(null) / len(null)) ** 2 for x in null) / (len(null) - 1)) ** 0.5,
            "null_max": ns[-1], "null_p99": ns[int(0.99 * (len(ns) - 1))], "obs": obs,
            "obs_z_vs_null": (obs - sum(null) / len(null)) /
            ((sum((x - sum(null) / len(null)) ** 2 for x in null) / (len(null) - 1)) ** 0.5)}
    return sum(1 for x in null if x >= obs) / len(null), summ


def halves(rows: list) -> dict:
    return {h: diff([r for r in rows if (r["signal_d"] < SPLIT) == (h == "lt2023")]) for h in ("lt2023", "ge2023")}


# ── 主流程 ────────────────────────────────────────────────────────────────────────────────────────
def main():
    panel = t159.load_bars()
    gate = t159.load_gate()
    tickets = s657.mtm(t159.run_long(panel, gate, "2020-03-01", "2026-10-19"), panel)
    assert len(tickets) == 770, len(tickets)
    syms = sorted({t["symbol"].upper() for t in tickets} | {t["symbol"].upper().replace("1000", "") for t in tickets})
    if "--fetch" in sys.argv:
        fetch(syms)
        return

    comp = completeness(json.load(open(os.path.join(OUT, "_mcap.json"))))
    assert comp["dup_keys"] == 0, f"asset_mcap_daily 抓重复键 {comp['dup_keys']} 条 —— 翻页边界漂了,重抓"

    ser = price_mcap_series()
    universe = [s for s in syms if s in ser]
    by_date: dict[str, list] = defaultdict(list)
    for t in tickets:
        by_date[t["signal_d"]].append(t)
    # 每个信号日 t:全宇宙算三维 → score_group 排位(写死:在 t 当天这个宇宙里排)
    per_date_raw, per_date_score = {}, {}
    for ds, ts in sorted(by_date.items()):
        t0 = dt.date.fromisoformat(ds)
        raw = {s: v2.crypto_inputs(ser[s], t0) for s in universe}
        per_date_raw[ds] = raw
        per_date_score[ds] = v2.score_group("crypto", raw)

    rows, unscored = [], []
    for t in tickets:
        ds, s = t["signal_d"], t["symbol"].upper()
        raw = per_date_raw[ds].get(s)
        sc = per_date_score[ds].get(s)
        if raw is None or sc is None or sc["score"] is None:
            unscored.append(t)
            continue
        rows.append({**t, "composite": sc["score"], "n_dims": sc["n_dims"],
                     "raw_size": raw["size"], "raw_stability": raw["stability"], "raw_supply": raw["supply"]})
    assert rows, "没有一张票拿到 v2 合成分"
    within_year_median(rows, "composite")        # ③ 用的是合成分的高/低两半 ⇒ 标记落在 rows 上

    res: dict = {"n_tickets": len(tickets), "n_universe": len(universe), "n_unscored": len(unscored),
                 "unscored_mean_r": (sum(t["r"] for t in unscored) / len(unscored)) if unscored else None,
                 "unscored_symbols": sorted({t["symbol"] for t in unscored}),
                 "completeness": comp, "signal_dates": len(by_date),
                 "n_dims_hist": {str(k): v for k, v in sorted(
                     (lambda d: d)(__import__("collections").Counter(r["n_dims"] for r in rows)).items())}}

    for key, label in (("composite", "①_合成"), ("raw_supply", "④_只用供给维"),
                       ("raw_size", "只报_规模维"), ("raw_stability", "只报_稳定维")):
        sub = [dict(r) for r in rows if r[key] is not None]
        within_year_median(sub, key)
        p, null = perm_p(sub)
        res[label] = {"n": len(sub), "diff_high_minus_low": diff(sub), "p_perm_within_year": p,
                      "halves": halves(sub), "null": null}
        res[label]["mean_r"] = sum(r["r"] for r in sub) / len(sub)

    # ④ 增量:同一批有合成分的票上,合成的 ① 差 > 只用供给维的 ① 差,两段都是
    comp_half, sup_half = res["①_合成"]["halves"], res["④_只用供给维"]["halves"]
    inc_ab = None
    res["④_increment"] = {"full_ok": (res["①_合成"]["diff_high_minus_low"] > res["④_只用供给维"]["diff_high_minus_low"]),
                          "halves_ok": all(comp_half[h] is not None and sup_half[h] is not None
                                           and comp_half[h] > sup_half[h] for h in ("lt2023", "ge2023")),
                          "delta_full": (res["①_合成"]["diff_high_minus_low"] - res["④_只用供给维"]["diff_high_minus_low"])
                          if res["①_合成"]["diff_high_minus_low"] is not None else None,
                          "delta_halves": {h: (comp_half[h] - sup_half[h]) if comp_half[h] is not None
                                             and sup_half[h] is not None else None for h in ("lt2023", "ge2023")}}

    # ③ 高分一半总 R ≥ 有分票总 R 的 50%
    tot = sum(r["r"] for r in rows)
    tot_hi = sum(r["r"] for r in rows if not r["low"])
    res["③_total_r_share_high_half"] = tot_hi / tot if tot else None

    # 判
    c1 = res["①_合成"]
    c2 = res["①_合成"]["halves"]
    ok = (c1["diff_high_minus_low"] is not None and c1["diff_high_minus_low"] > 0
          and c1["p_perm_within_year"] < 0.05
          and all(v is not None and v > 0 for v in c2.values())
          and res["③_total_r_share_high_half"] >= 0.5
          and res["④_increment"]["full_ok"] and res["④_increment"]["halves_ok"])

    # 只报:合成三分位
    srt = sorted(rows, key=lambda r: r["composite"])
    k = len(srt) // 3
    res["只报_合成三分位"] = {n: {"n": len(seg), "mean_r": sum(r["r"] for r in seg) / len(seg),
                                  "win": sum(r["r"] > 0 for r in seg) / len(seg),
                                  "comp_range": (round(seg[0]["composite"], 2), round(seg[-1]["composite"], 2))}
                              for n, seg in (("low", srt[:k]), ("mid", srt[k:2 * k]), ("high", srt[2 * k:]))}
    top10 = sorted(rows, key=lambda r: -r["r"])[:10]
    res["只报_top10落在哪档"] = [(r["symbol"], r["signal_d"], round(r["r"], 1), round(r["composite"], 2),
                                 "high" if r["composite"] >= srt[2 * k]["composite"]
                                 else "mid" if r["composite"] >= srt[k]["composite"] else "low") for r in top10]

    res["verdict"] = "过" if ok else "不过"
    res["criteria"] = {"①": c1["diff_high_minus_low"] is not None and c1["diff_high_minus_low"] > 0
                             and c1["p_perm_within_year"] < 0.05,
                       "②": all(v is not None and v > 0 for v in c2.values()),
                       "③": res["③_total_r_share_high_half"] >= 0.5,
                       "④": res["④_increment"]["full_ok"] and res["④_increment"]["halves_ok"]}
    json.dump(res, open(os.path.join(HERE, "docs", "research", "t177_results.json"), "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()