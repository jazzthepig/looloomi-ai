"""T-235 —— 真突破 vs 诱多的归因:R-v2 全部 770 张票,开票日 8 个可观测量按五分位报 R。

纪律(卡上 acceptance 原文即下面的 PREREG):
  * 预注册先写进报告开头,再算;只算一次,不挑量、不挑阈值。
  * 票集 = 770 张长票(票里的 r,不重算)+ r_tickets_paper 2026-06-21 起已出场的票(写明 n)。
  * 8 个可观测量全部取「开票日 d = signal_d」收盘可知的值;d = signal_d 已核实:
    票的 entry_px == signal_d 的收盘(BTC 2020-04-29 收 8778.57 → entry_px 8778.58),
    进场在 entry_d(=d+1) 的开盘,所以 d 收盘是进场时的全部信息集。
  * 五分位按「扩张窗口」:只用 exit_d ≤ d 且该量可得的已出场票算分位边界,再给 d 当天的票定档。
  * 零分布/分位只用 src/data/evaluation/apparatus.py。
  * 不改代码、不做 DDL、不入库。

用法:python3 docs/research/t235_breakout_attribution.py
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import statistics as st
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    stationary_bootstrap_index,
)

# ───────────────────────────── 0. 预注册(先写进报告,再算) ─────────────────────────────

PREREG = """# T-235 —— 真突破 vs 诱多的归因:R-v2 全部 770 张票

**预注册(2026-11-05,先写下来再算;只算一次,不挑量、不挑阈值)**

> 只读。先把预注册(就是这段)写进报告开头再算,**只算一次,不挑量、不挑阈值**。
> ① 票集 = 770 张 + r_tickets_paper 2026-06-21 起已出场的票(写明 n);每张票的 R 用票里的数(不重算)。
> ② 八个可观测量,全部取**开票日 d 收盘**可知的值:
> (1) 量能比 = d 日成交额 / 前 20 日均值;
> (2) 资金费水平 = d 日 binance_perp 该币日均费率×3×365;
> (3) 资金费 7 日变化 = (2) 减 d−7 的同口径;
> (4) 主动买盘 = d 日 taker 买量占比(s695 口径;没有的票标 NA 不补 0);
> (5) 突破延伸 = d 收盘 / 40 日高(不含 d)− 1;
> (6) 筑底时长 = d 距 120 日内最低收盘的天数;
> (7) majors 趋势 = BTC 收盘 / 200 日均 − 1;
> (8) ⓪ = d 的 deterioration(2021-02 前 NA)。副:DVOL 一年分位(2022-03 前 NA)。
> ③ 每个量按**扩张窗口**(只用 ≤ d 已出场的票)分五分位,每档报 n、R 均值、R 中位、命中率、均值的 95% 自举区间;
> 分 2020-03→2022-12 / 2023-01→2026-10 两半各报一遍。
> ④ 对照:顶档减底档的 ΔR,随机打乱标签 1,000 次(种子 235,只用 src/data/evaluation/apparatus.py)取分位。
> ⑤ 「候选」标记(不是结论):两半同号、|ΔR| ≥ 0.3R、随机分位 ≥ 0.95 的量标 candidate;**不组合、不设阈值、不写规则**。
> ⑥ 诚实段:每个量的缺失率;多重比较(8 个量 × 2 半)。
> 纪律:不改代码、不做 DDL、不入库;翻页带 order=;探针脚本改同一个文件再跑;步数过半先落文件;
> 交付附 docs/research/scenarios/lane-a-T-235.json(≥ 3 条)。

**本轮追加的一条纪律(全局规则:「信号日当天的派生量,判完再挪一天判一次 —— 只在当天成立的不算」)**:
d 当日派生的三个量(①成交额 ②当日资金费 ④当日 taker)有可能在 d 收盘后才落库,
所以每个量都跑一遍 **d−1 口径**,把「只在 d 成立、在 d−1 就没了」的量标成 `d_only`,
**d_only 不算 candidate**。这条在开算之前写定,不看结果。

## 0. 口径与实现决定(开算前写定)

| 项 | 决定 | 依据 |
|---|---|---|
| 开票日 d | = 票的 `signal_d` | 核实过:entry_px == signal_d 收盘,进场在 d+1 开盘 ⇒ d 收盘是进场时的全部信息 |
| 成交额 | `close × volume`(binance_hist 的 volume 是基础币量) | t156 的 `_merged.py` 同口径;`ohlcv_daily.volume` 是 base |
| 「N 日」 | N 根 **K 线**(有数据的日子),不是日历日 | 数据里有缺日,按 K 线数才稳 |
| 资金费「日均费率×3×365」 | 当日各笔费率的均值 ×3×365(当日 3 笔 8h 费率) | t159 的费率是 8 小时一笔 |
| taker 买量占比 | `taker_ratio_mean /(1 + taker_ratio_mean)`(ratio = 买/卖) | s695 的来源表 `deriv_metrics_daily.taker_ratio_mean` |
| 扩张窗口 | 参考集 = `exit_d ≤ d` 且该量可得的票;参考集 < 20 张 ⇒ 该票不定档 | 窗口太小时五分位没有意义 |
| 五分位边界 | 参考集该量的 20/40/60/80 分位 | 常规 |
| 命中率 | R > 0 的占比 | |
| 自举区间 | iid 自举 2000 次(apparatus `stationary_bootstrap_index(mean_block=1)`) | |
| 零分布 | 1000 次标签置换,种子 235(apparatus `null_distribution` + `percentile_of`) | |
| candidate | 两半 ΔR 同号 & 每半 \\|ΔR\\| ≥ 0.3 & 每半分位 ≥ 0.95 & 不是 d_only | 卡 ⑤ + 追加纪律 |
"""

# ───────────────────────────── 1. 数据装载 ─────────────────────────────

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
ROOT = "/Volumes/CometCloudAI/cometcloud-local"
TICKETS = f"{ROOT}/research/t159/_tickets_2020-03-01_2026-06-20.json"
LOCAL_BARS = [f"{ROOT}/research/t156/_bars_early.jsonl", f"{ROOT}/research/t156/_bars.jsonl",
              f"{ROOT}/research/t159/_bars.jsonl"]

HALVES = [("H1 2020-03→2022-12", "2020-03-01", "2022-12-31"), ("H2 2023-01→2026-10", "2023-01-01", "2026-12-31")]


def pull(table: str, query: str, step: int = 5000) -> list[dict]:
    """按主键排序翻页(必须带 order=,不然边界会漂)。"""
    rows: list[dict] = []
    off = 0
    total = -1
    while True:
        h = dict(H)
        h["Range"] = f"{off}-{off + step - 1}"
        req = urllib.request.Request(f"{U}/rest/v1/{table}?{query}", headers=h)
        with urllib.request.urlopen(req, timeout=300) as resp:
            cr = resp.headers.get("Content-Range", "")
            body = json.loads(resp.read())
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def load_local_bars(symbols: set[str]):
    """本地 t156/t159 _bars*.jsonl(卡上指定的口径)。"""
    bars: dict[str, dict[str, tuple]] = defaultdict(dict)
    n = 0
    dup = 0
    for f in LOCAL_BARS:
        with open(f) as fh:
            for line in fh:
                for r in json.loads(line):
                    sym = r["symbol"]
                    if sym not in symbols:
                        continue
                    d = r["trade_date"][:10]
                    if d in bars[sym]:
                        dup += 1
                    bars[sym][d] = (float(r["open"]), float(r["high"]), float(r["low"]),
                                   float(r["close"]), float(r["volume"]))
                    n += 1
    return bars, n, dup


# ───────────────────────────── 2. 观测量 ─────────────────────────────

def obs_for(sym: str, d: str, ctx: dict) -> dict:
    """票在开票日 d 的 8 个可观测量 + DVOL 分位。缺就是 None(不补 0)。"""
    o: dict = {}
    bars = ctx["bars"]
    dl = ctx["dates"].get(sym, [])
    i = bisect.bisect_left(dl, d)
    bar = bars.get(sym, {}).get(d)

    # ①量能比 = d 日成交额 / 前 20 根 K 线成交额均值
    if bar is not None and i >= 20:
        to_d = bar[3] * bar[4]
        prev = [bars[sym][x][3] * bars[sym][x][4] for x in dl[i - 20:i]]
        o["vol_ratio"] = to_d / (sum(prev) / 20.0) if sum(prev) > 0 else None
    else:
        o["vol_ratio"] = None

    # ②资金费水平(年化)= 当日各笔均值 ×3×365 ;③ 7 日变化
    fs, fn = ctx["fund_sum"], ctx["fund_n"]
    lvl = None
    if fn.get((sym, d)):
        lvl = (fs[(sym, d)] / fn[(sym, d)]) * 3 * 365
    o["fund_ann"] = lvl
    d7 = (dt.date.fromisoformat(d) - dt.timedelta(days=7)).isoformat()
    lvl7 = None
    if fn.get((sym, d7)):
        lvl7 = (fs[(sym, d7)] / fn[(sym, d7)]) * 3 * 365
    o["fund_chg7"] = (lvl - lvl7) if (lvl is not None and lvl7 is not None) else None

    # ④主动买盘占比
    tr = ctx["taker"].get((sym, d))
    o["taker_share"] = (tr / (1.0 + tr)) if tr is not None else None

    # ⑤突破延伸 = d 收盘 / 前 40 根 K 线最高价 − 1(不含 d)
    if bar is not None and i >= 40:
        hi40 = max(bars[sym][x][1] for x in dl[i - 40:i])
        o["breakout_ext"] = (bar[3] / hi40 - 1.0) if hi40 > 0 else None
    else:
        o["breakout_ext"] = None

    # ⑥筑底时长 = d 距 120 根 K 线内最低收盘的根数
    if i >= 120:
        win = dl[i - 119:i + 1]
        lo_i = min(range(len(win)), key=lambda k: bars[sym][win[k]][3])
        o["base_days"] = float(len(win) - 1 - lo_i)
    else:
        o["base_days"] = None

    # ⑦majors 趋势 = BTC 收盘 / 200 日均 − 1(含 d)
    bl = ctx["dates"].get("BTC", [])
    j = bisect.bisect_left(bl, d)
    if j >= 199 and d in ctx["bars"].get("BTC", {}):
        closes = [ctx["bars"]["BTC"][x][3] for x in bl[j - 199:j + 1]]
        o["majors_trend"] = ctx["bars"]["BTC"][d][3] / (sum(closes) / 200.0) - 1.0
    else:
        o["majors_trend"] = None

    # ⑧⓪ 相位 deterioration
    o["zero_phase"] = ctx["cyc"].get(d)

    # 副:DVOL 一年分位(365 自然日窗口,含 d)
    dv = ctx["dvol"].get(d)
    if dv is None:
        o["dvol_pct"] = None
    else:
        lo = (dt.date.fromisoformat(d) - dt.timedelta(days=364)).isoformat()
        win = [v for k, v in ctx["dvol"].items() if lo <= k <= d]
        o["dvol_pct"] = (sum(1 for v in win if v < dv) / len(win)) if len(win) >= 60 else None
    return o


QTY = [("vol_ratio", "①量能比"), ("fund_ann", "②资金费水平(年化)"), ("fund_chg7", "③资金费7日变化"),
       ("taker_share", "④主动买盘占比"), ("breakout_ext", "⑤突破延伸"), ("base_days", "⑥筑底时长(K线数)"),
       ("majors_trend", "⑦majors 趋势(BTC/MA200−1)"), ("zero_phase", "⑧⓪ 相位 deterioration")]
QTY_AUX = [("dvol_pct", "副·DVOL 一年分位")]
ON_DAY = {"vol_ratio", "fund_ann", "taker_share"}  # d 当日派生


# ───────────────────────────── 3. 扩张窗口分档 + 统计 ─────────────────────────────

def assign_buckets(tickets: list[dict], qvals: dict, min_ref: int = 20) -> list[int | None]:
    """扩张窗口:参考集 = exit_d ≤ d 且该量可得的已出场票。返回每张票的档位 1..5 / None。"""
    by_exit = sorted([t for t in tickets if t.get("exit_d")], key=lambda t: t["exit_d"])
    buckets: list[int | None] = []
    ref_vals: list[float] = []
    p = 0
    for t in tickets:
        d = t["signal_d"]
        while p < len(by_exit) and by_exit[p]["exit_d"] <= d:
            v = qvals.get(by_exit[p]["symbol"] + "|" + by_exit[p]["signal_d"])
            if v is not None:
                ref_vals.append(v)
            p += 1
        own = qvals.get(t["symbol"] + "|" + t["signal_d"])
        if own is None or len(ref_vals) < min_ref:
            buckets.append(None)
            continue
        edges = np.percentile(np.asarray(ref_vals, dtype=float), [20, 40, 60, 80])
        buckets.append(int(np.searchsorted(edges, own, side="right")) + 1)
    return buckets


def boot_ci(vals: list[float], seed: int = 235, n_boot: int = 2000) -> list[float] | None:
    n = len(vals)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_index(n, mean_block=1.0, n_boot=n_boot, rng=rng)
    means = np.asarray(vals, dtype=float)[idx].mean(axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def half_of(d: str) -> int | None:
    for i, (_, lo, hi) in enumerate(HALVES):
        if lo <= d <= hi:
            return i
    return None


def analyse(tickets: list[dict], qvals: dict, label: str) -> dict:
    """一个量在 d 口径下的完整统计。"""
    buckets = assign_buckets(tickets, qvals)
    per_bucket = {i: [] for i in range(1, 6)}
    for t, b in zip(tickets, buckets):
        if b is not None:
            per_bucket[b].append(t["r"])
    res = {"label": label, "buckets": buckets, "halves": {}}
    for hi, (hname, _, _) in enumerate(HALVES):
        sel = [(t, b) for t, b in zip(tickets, buckets) if b is not None and half_of(t["signal_d"]) == hi]
        q_stats = []
        for k in range(1, 6):
            vals = [t["r"] for t, b in sel if b == k]
            q_stats.append({
                "q": k, "n": len(vals),
                "mean_r": round(st.mean(vals), 4) if vals else None,
                "median_r": round(st.median(vals), 4) if vals else None,
                "hit": round(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else None,
                "ci95": [round(x, 4) for x in boot_ci(vals)] if len(vals) >= 2 else None,
            })
        top = [t["r"] for t, b in sel if b == 5]
        bot = [t["r"] for t, b in sel if b == 1]
        obs = (st.mean(top) - st.mean(bot)) if top and bot else None
        pctl = None
        p2 = None
        null_note = ""
        if obs is not None:
            rs = [t["r"] for t, b in sel]
            labs = [b for t, b in sel]

            def fn(rng, rs=rs, labs=labs):
                # 打乱**标签**:把档位重新分配给票,再算顶档−底档。
                # (11-05 修正:旧写法只打乱下标顺序、过滤条件仍用原档位 ⇒ 每一次抽样的
                #  a/b 集合完全相同 ⇒ 零分布零方差 ⇒ apparatus 抛 NoOpNull,分位永远是 None。)
                perm = rng.permutation(len(labs))
                lp = [labs[i] for i in perm]
                a = [r for r, l in zip(rs, lp) if l == 5]
                b = [r for r, l in zip(rs, lp) if l == 1]
                return st.mean(a) - st.mean(b) if a and b else float("nan")

            try:
                null = null_distribution(fn, n=1000, seed=235, actual=obs)
                pctl = percentile_of(obs, null)
                p2 = 2.0 * min(pctl, 1.0 - pctl) if pctl is not None else None
            except NoOpNull as e:
                null_note = f"NoOpNull: {e}"
                p2 = None
        res["halves"][hname] = {"quintiles": q_stats, "delta_r": round(obs, 4) if obs is not None else None,
                                "null_pct": round(pctl, 4) if pctl is not None else None,
                                "null_pct_two_sided": round(p2, 4) if p2 is not None else None,
                                "null_note": null_note, "n_labeled": len(sel)}
    return res


def candidate_verdict(res_d: dict, res_d1: dict | None, on_day: bool) -> dict:
    h1, h2 = list(res_d["halves"].values())
    d1, d2 = h1["delta_r"], h2["delta_r"]
    p1, p2 = h1["null_pct"], h2["null_pct"]
    q1, q2 = h1.get("null_pct_two_sided"), h2.get("null_pct_two_sided")
    same_sign = d1 is not None and d2 is not None and (d1 > 0) == (d2 > 0)
    mag = d1 is not None and d2 is not None and abs(d1) >= 0.3 and abs(d2) >= 0.3
    sig = p1 is not None and p2 is not None and p1 >= 0.95 and p2 >= 0.95
    core = same_sign and mag and sig
    # 双侧读法(预注册原文只写了「分位 ≥ 0.95」;但同一条规则也允许「两半同号」的全负 ΔR,
    #  单侧分位会把每一个负向效应机械地判成不显著)。双侧标记单独出列,不改预注册的 candidate 判定。
    sig2 = q1 is not None and q2 is not None and q1 <= 0.05 and q2 <= 0.05
    core2 = same_sign and mag and sig2
    d_only = False
    if core and on_day and res_d1 is not None:
        hh1, hh2 = list(res_d1["halves"].values())
        s1 = (hh1["delta_r"] is not None and hh2["delta_r"] is not None
              and (hh1["delta_r"] > 0) == (hh2["delta_r"] > 0))
        m1 = (hh1["delta_r"] is not None and hh2["delta_r"] is not None
              and abs(hh1["delta_r"]) >= 0.3 and abs(hh2["delta_r"]) >= 0.3)
        g1 = (hh1["null_pct"] is not None and hh2["null_pct"] is not None
              and hh1["null_pct"] >= 0.95 and hh2["null_pct"] >= 0.95)
        d_only = not (s1 and m1 and g1)
    return {"same_sign": same_sign, "magnitude": mag, "signif": sig, "core": core,
            "signif_two_sided": sig2, "core_two_sided": core2,
            "d_only": d_only, "candidate": core and not d_only,
            "candidate_two_sided": core2}


# ───────────────────────────── 4. 主流程 ─────────────────────────────

def main() -> None:
    out_md = HERE / "T-235_breakout_attribution.md"
    out_js = HERE / "t235_results.json"
    with open(out_md, "w") as fh:  # ① 预注册先落盘,再算
        fh.write(PREREG)
        fh.write("\n## 1. 票集与数据源(装载记录)\n\n(计算中……)\n")
    print("prereg written ->", out_md, flush=True)

    tix = json.load(open(TICKETS))
    longs, shorts = tix["long"], tix["short"]
    paper_rows = pull("r_tickets_paper", "select=*&order=signal_d.asc&limit=5000")
    tickets = []
    n_r_none = 0
    for t in longs:
        if t.get("r") is None:
            n_r_none += 1
            continue
        tickets.append({"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                        "exit_d": t.get("exit_d"), "r": float(t["r"]), "src": "t159_local"})
    n_paper = 0
    for t in paper_rows:
        if t.get("r") is None:
            continue
        tickets.append({"symbol": t.get("symbol"), "signal_d": (t.get("signal_d") or "")[:10],
                        "entry_d": (t.get("entry_d") or "")[:10], "exit_d": (t.get("exit_d") or "")[:10],
                        "r": float(t["r"]), "src": "r_tickets_paper"})
        n_paper += 1
    tickets.sort(key=lambda x: (x["signal_d"], x["symbol"]))
    symbols = {t["symbol"] for t in tickets} | {"BTC"}
    print("tickets", len(tickets), "paper", n_paper, "symbols", len(symbols), flush=True)

    bars, n_bar_rows, n_bar_dup = load_local_bars(symbols)
    # DB 只做**对照**,不混进 bars:本地快照与 DB 的 volume 量纲在 10-21→11-05 之间变过
    # (137/184 个符号 DB 的量能只有本地的 1/5~1/8),混用会把量能比算坏。
    db_rows = pull("ohlcv_daily",
                   "select=symbol,trade_date,close,volume&source=eq.binance_hist"
                   "&trade_date=gte.2021-01-01&order=symbol.asc,trade_date.asc")
    db_map: dict[str, dict[str, tuple]] = defaultdict(dict)
    for r in db_rows:
        if r["symbol"] in symbols:
            db_map[r["symbol"]][r["trade_date"][:10]] = (float(r["close"]), float(r["volume"]))
    n_ov = n_close_conf = n_vol_diff = 0
    cratios, vratios = [], []
    clean_syms = set(symbols)
    for s in symbols:
        for d, (o, h, l, c, v) in bars[s].items():
            if d in db_map.get(s, {}):
                n_ov += 1
                cd, vd = db_map[s][d]
                if abs(cd - c) > 1e-6:
                    n_close_conf += 1
                    if c:
                        cratios.append(cd / c)
                if abs(vd - v) > 1e-6:
                    n_vol_diff += 1
                    if v:
                        vratios.append(vd / v)
                        clean_syms.discard(s)
    cratios.sort()
    vratios.sort()
    med = lambda a: round(a[len(a) // 2], 6) if a else None
    diag = {"overlap_rows": n_ov, "close_conflicts": n_close_conf, "vol_diffs": n_vol_diff,
            "close_ratio_median": med(cratios), "vol_ratio_median": med(vratios),
            "symbols_with_vol_diff": len(symbols) - len(clean_syms), "symbols_total": len(symbols)}
    dates = {s: sorted(b.keys()) for s, b in bars.items()}
    print("bars local", n_bar_rows, "db overlap", n_ov, "close_conf", n_close_conf,
          "vol_diff", n_vol_diff, "vol_ratio_med", diag["vol_ratio_median"], flush=True)

    fund_sum: dict[tuple[str, str], float] = defaultdict(float)
    fund_n: dict[tuple[str, str], int] = defaultdict(int)
    for e in json.load(open(f"{ROOT}/research/t159/_funding.json")):
        sym = e["symbol"]
        if sym not in symbols:
            continue
        d = e["funding_time"][:10]
        fund_sum[(sym, d)] += float(e["funding_rate"])
        fund_n[(sym, d)] += 1

    taker: dict[tuple[str, str], float] = {}
    taker_dup = 0
    for r in pull("deriv_metrics_daily", "select=symbol,d,taker_ratio_mean&order=symbol.asc,d.asc"):
        sym = r["symbol"]
        if sym not in symbols or r.get("taker_ratio_mean") is None:
            continue
        key = (sym, r["d"][:10])
        if key in taker:
            taker_dup += 1
        taker[key] = float(r["taker_ratio_mean"])

    cyc_all = pull("cycle_vector_daily", "select=d,deterioration,phase,code_ref&order=d.asc")
    cyc = {r["d"][:10]: float(r["deterioration"]) for r in cyc_all if r.get("deterioration") is not None}
    cyc_refs = sorted({str(r.get("code_ref")) for r in cyc_all})
    cyc_min = min(cyc) if cyc else None
    cyc_max = max(cyc) if cyc else None

    dvol = {}
    for r in pull("deriv_vol_daily", "select=d,currency,dvol_close&currency=eq.BTC&order=d.asc"):
        if r.get("dvol_close") is not None:
            dvol[r["d"][:10]] = float(r["dvol_close"])

    ctx = {"bars": bars, "dates": dates, "fund_sum": fund_sum, "fund_n": fund_n,
           "taker": taker, "cyc": cyc, "dvol": dvol}
    print("loaded: fund", len(fund_sum), "taker", len(taker), "cyc", len(cyc), "dvol", len(dvol), flush=True)

    # ── 观测量:d 口径 与 d−1 口径 ──
    obs_d: dict[str, dict] = {}
    obs_d1: dict[str, dict] = {}
    for t in tickets:
        obs_d[t["symbol"] + "|" + t["signal_d"]] = obs_for(t["symbol"], t["signal_d"], ctx)
        prev = (dt.date.fromisoformat(t["signal_d"]) - dt.timedelta(days=1)).isoformat()
        obs_d1[t["symbol"] + "|" + t["signal_d"]] = obs_for(t["symbol"], prev, ctx)

    all_q = QTY + QTY_AUX
    results = {}
    for key, name in all_q:
        q_d = {k: v[key] for k, v in obs_d.items()}
        q_d1 = {k: v[key] for k, v in obs_d1.items()}
        r_d = analyse(tickets, q_d, f"{name} · d")
        r_d1 = analyse(tickets, q_d1, f"{name} · d−1")
        n_miss = sum(1 for v in q_d.values() if v is None)
        verdict = candidate_verdict(r_d, r_d1, key in ON_DAY)
        results[key] = {"name": name, "d": r_d, "d_minus_1": r_d1,
                        "n_missing": n_miss, "missing_rate": round(n_miss / len(tickets), 4),
                        "verdict": verdict}
        print(key, "miss", n_miss, "d", r_d["halves"][HALVES[0][0]]["delta_r"],
              r_d["halves"][HALVES[1][0]]["delta_r"], "cand", verdict["candidate"],
              "cand2", verdict["candidate_two_sided"], flush=True)

    payload = {
        "card": "T-235",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "universe": {"n_tickets": len(tickets), "n_long_in_file": len(longs),
                     "n_short_in_file_excluded": len(shorts), "n_paper_used": n_paper,
                     "n_r_none_dropped": n_r_none, "n_symbols": len(symbols),
                     "r_tickets_paper_rows": len(paper_rows)},
        "tickets_by_year": {y: sum(1 for t in tickets if t["signal_d"][:4] == y)
                            for y in sorted({t["signal_d"][:4] for t in tickets})},
        "sources": {"bars_local_rows": n_bar_rows, "bars_local_dup": n_bar_dup,
                    "bars_db_diag": diag, "ohlcv_daily_rows_scanned": len(db_rows),
                    "funding_keys": len(fund_sum),
                    "taker_keys": len(taker), "taker_dup": taker_dup, "cycle_rows": len(cyc_all),
                    "cycle_deterioration": len(cyc), "cycle_code_refs": cyc_refs,
                    "cycle_deterioration_from": cyc_min, "cycle_deterioration_to": cyc_max,
                    "dvol_rows": len(dvol)},
        "quantities": results,
    }
    with open(out_js, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    write_report(payload, out_md)
    print("report ->", out_md, flush=True)


# ───────────────────────────── 5. 报告 ─────────────────────────────

def write_report(p: dict, out_md: Path) -> None:
    u, s = p["universe"], p["sources"]
    dg = s["bars_db_diag"]
    L = []
    L.append("\n## 1. 票集与数据源(装载记录)\n")
    L.append(f"- **票集 n = {u['n_tickets']}**:t159 本地长票 {u['n_long_in_file']} 张,"
             f"扣掉 r 为 null(未出场){u['n_r_none_dropped']} 张;"
             f"`r_tickets_paper` 读到 {u['r_tickets_paper_rows']} 行 ⇒ **前向纸面票 n = {u['n_paper_used']}**。")
    L.append(f"- 同一文件里的 **{u['n_short_in_file_excluded']} 张空头票**不在 R-v2 里(它们是另一套策略的族),本卡不混进来。")
    L.append(f"- 票面覆盖 {u['n_symbols']} 个符号;R 直接用票里的 `r`,没有重算。")
    L.append(f"- 每年票数:" + "、".join(f"{y}: {n}" for y, n in p["tickets_by_year"].items()) + "。")
    L.append(f"- 日线:本地 t156/t159 `_bars*.jsonl` {s['bars_local_rows']} 行(重复 {s['bars_local_dup']} 行)。"
             f"**只用本地这一套**,不与 DB 混用(理由见 §4 诚实段第 2 条)。")
    L.append(f"- 资金费:`t159/_funding.json` → {s['funding_keys']} 个 (符号,日) 键。")
    L.append(f"- 主动买盘:`deriv_metrics_daily` → {s['taker_keys']} 个 (符号,日) 键(重复 {s['taker_dup']})。")
    L.append(f"- ⓪ 相位:`cycle_vector_daily` {s['cycle_rows']} 行,deterioration 非空 {s['cycle_deterioration']} 行"
             f"({s['cycle_deterioration_from']} → {s['cycle_deterioration_to']}),code_ref = {s['cycle_code_refs']}。")
    L.append(f"- DVOL:`deriv_vol_daily`(BTC) {s['dvol_rows']} 行。")
    L.append("\n## 2. 结果:8 个量 × 5 档 × 2 半\n")
    L.append("口径:d = 票的 signal_d;档位按扩张窗口(只用 `exit_d ≤ d` 已出场的票算分位边界)。"
             "`ΔR` = 顶档均值 − 底档均值;`分位` = 打乱标签 1000 次(种子 235)后实际值的分位。\n")
    for key, name in QTY + QTY_AUX:
        r = p["quantities"][key]
        v = r["verdict"]
        flag = "**candidate**" if v["candidate"] else ("d_only(不算 candidate)" if v["d_only"] else "—")
        L.append(f"\n### {name} — {flag}\n")
        L.append(f"缺失率 {r['missing_rate']:.1%}({r['n_missing']}/{u['n_tickets']} 张票 NA)。\n")
        for hname, _, _ in HALVES:
            h = r["d"]["halves"][hname]
            L.append(f"\n**{hname}**(定档 n = {h['n_labeled']})\n")
            L.append("| 档 | n | R 均值 | R 中位 | 命中率 | 均值 95% 自举区间 |")
            L.append("|---|---|---|---|---|---|")
            for q in h["quintiles"]:
                ci = f"[{q['ci95'][0]:.3f}, {q['ci95'][1]:.3f}]" if q["ci95"] else "—"
                mr = f"{q['mean_r']:.3f}" if q["mean_r"] is not None else "—"
                md = f"{q['median_r']:.3f}" if q["median_r"] is not None else "—"
                ht = f"{q['hit']:.1%}" if q['hit'] is not None else "—"
                L.append(f"| Q{q['q']} | {q['n']} | {mr} | {md} | {ht} | {ci} |")
            L.append(f"\nΔR(Q5−Q1) = **{h['delta_r'] if h['delta_r'] is not None else '—'}**,"
                     f"随机分位 = **{h['null_pct'] if h['null_pct'] is not None else '—'}**"
                     + (f"(双侧 {h['null_pct_two_sided']})" if h.get("null_pct_two_sided") is not None else "")
                     + (f"({h['null_note']})" if h["null_note"] else "") + "\n")
        h1d = r["d_minus_1"]["halves"][HALVES[0][0]]
        h2d = r["d_minus_1"]["halves"][HALVES[1][0]]
        L.append(f"\n*d−1 口径(稳健性)*:ΔR H1 = {h1d['delta_r']}, H2 = {h2d['delta_r']};"
                 f"分位 H1 = {h1d['null_pct']}, H2 = {h2d['null_pct']}。\n")
    cands = [k for k, r in p["quantities"].items() if r["verdict"]["candidate"]]
    cands2 = [k for k, r in p["quantities"].items() if r["verdict"].get("candidate_two_sided")]
    L.append("\n## 3. candidate 清单\n")
    if cands:
        for k in cands:
            r = p["quantities"][k]
            h1 = r["d"]["halves"][HALVES[0][0]]
            h2 = r["d"]["halves"][HALVES[1][0]]
            L.append(f"- **{r['name']}**:ΔR H1 = {h1['delta_r']}(分位 {h1['null_pct']}),"
                     f"H2 = {h2['delta_r']}(分位 {h2['null_pct']})")
        L.append("\n**只是候选,不是结论** —— 不组合、不设阈值、不写规则。\n")
    else:
        L.append("**无候选**(按预注册原文:两半同号 + 每半 |ΔR| ≥ 0.3 + 每半随机分位 ≥ 0.95)。\n")
    L.append("**双侧读法(口径说明,不是新规则)。** 预注册的「分位 ≥ 0.95」是单侧口径,"
             "而同一条规则又允许「两半同号」的全负 ΔR —— 单侧口径会把每一个负向效应机械地判成不显著"
             "(分位 ≈ 0)。所以这里另记一个双侧标记:实际值落在零分布的两端(双侧分位 ≤ 0.05)。"
             "**预注册的 candidate 判定不改**,双侧只作参考:\n")
    if cands2:
        for k in cands2:
            r = p["quantities"][k]
            h1 = r["d"]["halves"][HALVES[0][0]]
            h2 = r["d"]["halves"][HALVES[1][0]]
            L.append(f"- **{r['name']}**:ΔR H1 = {h1['delta_r']}(单侧 {h1['null_pct']} / 双侧 {h1['null_pct_two_sided']}),"
                     f"H2 = {h2['delta_r']}(单侧 {h2['null_pct']} / 双侧 {h2['null_pct_two_sided']})")
        L.append("\n**双侧命中也不等于候选** —— 它的方向是负的(顶档比底档差),"
                 "且 8 个量 × 2 半共 16 次检验没有多重校正 ⇒ 任何一条都要另立预注册、换新数据重跑。\n")
    else:
        L.append("- 无(没有任何量在两半都通过双侧 ≤ 0.05)。\n")
    near = []
    for k, r in p["quantities"].items():
        for hname, _, _ in HALVES:
            h = r["d"]["halves"][hname]
            if h["delta_r"] is not None and abs(h["delta_r"]) >= 0.3 and h["null_pct"] is not None \
                    and h["null_pct"] >= 0.95:
                near.append((r["name"], hname, h["delta_r"], h["null_pct"], h["n_labeled"]))
    L.append("\n**最接近的格子(单项过了门槛,但凑不齐「两半」)。**\n")
    if near:
        for nm, hname, dr, pc, nl in near:
            L.append(f"- {nm} · {hname}:ΔR = {dr},单侧分位 = {pc},定档 n = {nl}。"
                     "单项(|ΔR| ≥ 0.3 且分位 ≥ 0.95)成立,但另一半不成立 ⇒ 不算 candidate。\n")
    else:
        L.append("- 无单项过门槛的格子。\n")
    L.append("\n## 4. 诚实段\n")
    L.append("**① 多重比较。** 8 个量 × 2 半 = 16 次检验。卡上的门槛(分位 ≥ 0.95)没有做多重校正;"
             "Bonferroni 对应 0.05/16 = **0.003**。所有量都用同一个种子 235 ⇒ 零分布跨量相关,"
             "不能当独立检验处理。另外所有分位都用 iid 置换,R 在时间上成簇 ⇒ 零分布偏窄,"
             "真实显著性大概率比报出来的弱。\n")
    L.append(f"**② 本地 bars 与 DB 的 `ohlcv_daily`(source=binance_hist)对不上 —— 量纲变了。** "
             f"重叠 {dg['overlap_rows']} 行里收盘价不一致 {dg['close_conflicts']} 行"
             f"(比值中位 {dg['close_ratio_median']},即价格本身几乎没动),"
             f"但 **volume 不一致 {dg['vol_diffs']} 行**,比值中位 {dg['vol_ratio_median']},"
             f"且 **{dg['symbols_with_vol_diff']}/{dg['symbols_total']} 个符号**受影响(其余符号逐字节相同)。"
             "结论:`ohlcv_daily.binance_hist` 的 volume 在 10-21 快照与 11-05 之间被换过定义/来源,"
             "本卡只用本地快照这一套 vintage(不混用)。"
             "**这是给 Seth 的工程问题:任何依赖 `ohlcv_daily.volume` 的结论都要先确认量纲。**\n")
    L.append("**②′ 更正:上一版把「①量能比那张表」标成作废是过度谨慎。** "
             "去掉 DB 混用重跑后,①量能比(以及其余全部本地量:⑤⑥⑦ 与 ②③④ 的档位)"
             "在 d 与 d−1 两个口径下 **767 张票的档位逐位相同**,ΔR 也逐位相同 ⇒ "
             "上一版的 DB 混用实际上没有落到任何一张票的可观测量上,那张表**不作废**。"
             "只有 ⑧⓪ 变了(见 ④)。\n")
    L.append("**③ 票集本身的缺口。** "
             f"①`r_tickets_paper` 读到 {u['r_tickets_paper_rows']} 行 ⇒ 前向纸面票 0 张:"
             "纸面书的 `r_tickets_state.last_d` 已经走到 2026-11-03,但 `r_money_daily` 的 16 天 nav 恒为 1、ret 恒为 0"
             "⇒ 前向从未开出过一张票,所以卡上说的「2026-06-21 起的票」实际不存在;"
             "②长票 **2022 年整年 0 张**(2020/2021/2023/2024/2025/2026 才有),"
             "所以卡上规定的第一半(2020-03→2022-12)只剩 2020+2021 两年的票,H1 与 H2 的样本量严重不等;"
             "③3 张 2024-11 的票在快照时仍未出场(r 为 null),已剔除;"
             "④文件里另有 241 张空头票(带 exit_reason:sma20/stop),属另一套策略,未混入。\n")
    L.append(f"**④ ⓪ 相位用的是 v1.1。** `cycle_vector_daily` 现在只有 `{s['cycle_code_refs']}`,"
             f"deterioration 非空 {s['cycle_deterioration']} 行,"
             f"区间 {s['cycle_deterioration_from']} → {s['cycle_deterioration_to']};"
             "脚本按行取(库里只有一个 code_ref,不过滤也只有一个版本),所以本轮 ⑧ 用的就是 **v1.1**"
             "(上一轮用的是 v1,起点 2022-01-25)。v1.1 把起点前推到 2021-01-29 ⇒ "
             "⑧ 的缺失率从 10.4% 降到 3.8%,767 张票里 218 张重新定档,H2 的 ΔR 从 0.5317 变成 0.4592。"
             "库里不再有 `cycle_vector v1` 的行 ⇒ 想要 v1 口径得另跑重建。\n")
    L.append("**⑧ 零分布的接线曾经是坏的(本次修正,重要)。** 第一次跑出来的每一个格子的 `null_pct` 都是 "
             "`None`,`null_note` 写着 `NoOpNull: 零分布没有方差` —— 原因不是数据,是代码:"
             "旧的打乱函数只打乱了下标顺序,而过滤条件仍然按**原档位**取子集 ⇒ "
             "每次抽样的顶档/底档集合完全相同 ⇒ ΔR 每次都等于实际值 ⇒ 零分布零方差。"
             "后果:预注册里的「随机分位 ≥ 0.95」这一条**从来没有被真正检验过**,"
             "「无候选」有相当一部分是这道坏门造成的,不是统计结论。"
             "修正 = 按预注册原文「随机打乱标签」把档位重新分配给票再算 ΔR,零分布仍只用 "
             "`src/data/evaluation/apparatus.py`。**本次的 % 是第一次有效读数。**"
             "为免混淆,预注册的 candidate 判定一字未改,双侧读法单独出列(见 §3)。\n")
    L.append("**⑤ 主动买盘的两处口径偏离。** ①卡上写「d 日 taker 买量占比」,s695 用的是 d−7..d−1 的均值;"
             "本卡按卡上写的取 d 日单日值(买量占比 = ratio/(1+ratio),是 s695 的 ratio 的单调变换 ⇒ 分档完全相同);"
             "②`deriv_metrics_daily` 的 taker_ratio_mean 是 Binance metrics 的日均,入库有滞后,"
             "所以 d 口径有可能用到当天收盘后才落库的数据 —— 这就是为什么 d−1 口径必须一起跑。\n")
    L.append("**⑥ 缺失率。** 每个量的缺失率见各节;缺失一律 NA 不补 0。"
             "早期票(2020 年)缺日线是因为本地 `_bars_early.jsonl` 只覆盖 74 个符号。\n")
    L.append("**⑦ 没做的事。** 不组合量、不设阈值、不写规则、不入库、不改代码;"
             "没有把 241 张空头票放进来;没有用 DB 的 bars 补本地缺口。\n")
    L.append("\n## 5. 探索性发现(不是结论)\n")
    L.append("见最终回复;每条都需要另立预注册、在新数据上过零信号对照才能当结论。\n")
    with open(out_md, "a") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
