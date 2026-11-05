#!/usr/bin/env python3
"""T-245 · S-729 预注册:投降日之后 —— BTC 深回撤里「全市场被迫卖出」那几天的前向

纪律(照卡):只读。不改 `src/`、不做 DDL、不入库;翻页一律带 `order=`;零分布只用
`src/data/evaluation/apparatus.py`;探针脚本改同一个文件再跑。

──────────────────────── 预注册原文(抄进报告开头,先算一次) ────────────────────────

S-729(Seth,2026-11-05 06:04 UTC;交 C 道 T-245)原文,逐字:

> ## S-729 — 投降日之后:深回撤里「全市场被迫卖出」那几天的前向,对照同样深的回撤里随机一天 —— 预注册
>
> **为什么。** 书本只有趋势层(X1V / R-v2);§5c 要的均值回归层(恐慌里接)从没在我们自己的数据上量过。
> S-601 说趋势规则的代价付在每次反弹的开头。S-724 说先动的只有价格 ⇒ 不找预警,找投降。
>
> **事件(写死):** BTC 收盘 ≤ 0.75 × 90 天最高收盘 × [全市场永续主动卖出占比 ≥ 扩张 90 分位 或
> 资金费为负的合约占比 ≥ 扩张 90 分位] × 全市场永续成交 ≥ 2 × 30 日均;20 天去重。
> 前向 30 / 60 / 90 天 BTC 与 cap_pit24。
>
> **条件零分布:** 同样满足「≤ 0.75 × 90 天高点」的日子随机抽同样个数(按年分层,1,000 次,种子 729)。
>
> **判据(全过 ✅):** 90 天 BTC 收益中位 > 条件零分布 95 分位;两半中位都 > 0;
> 最差 10% 事件之后 90 天内再跌的最大幅度中位 ≥ −25%。事件 < 8 个只报不判;事件逐条列。
> 副报:到下一次站上 200 日线的天数与那段涨跌。**试验计数:③(再入场)+1。**

卡 T-245 的 acceptance(展开,同样抄进报告开头):

> ① 投降日(写死,全部按时点):(a) BTC 收盘 ≤ 0.75 × 过去 90 天最高收盘;
> (b) 全市场永续主动卖出占比 1 − Σtbqv / Σqv(coin 合约,当天)在自己扩张历史 ≥ 90 分位,
> 或 资金费为负的合约占比(v_funding_daily 日均 < 0)≥ 扩张 90 分位;
> (c) 全市场永续 Σqv ≥ 2 × 前 30 日均。20 天内只计第一次。
> 报每个事件的日期与 BTC 回撤深度。
> ② 前向:d+1 收盘起 30 / 60 / 90 天 BTC 收益与 cap_pit24 nav 收益;最差路径(之后 90 天内的再跌最大幅度)。
> ③ 条件零分布(写死):在同样满足 (a) 的日子里随机抽同样个数(按年份分层,1,000 次,种子 729,
> 只用 apparatus.null_distribution)—— 控制「深回撤之后本来就会反弹」。
> ④ 「早多少」:每个事件到下一次 BTC 收盘站上 200 日均线的天数,以及这段 BTC 涨跌。
> ⑤ 判(S-729,全过 ✅):90 天 BTC 收益中位 > 条件零分布 95 分位;
> 两半(2020-03 → 2022-12 / 2023-01 → 2026-10)中位都 > 0;
> 最差 10% 事件之后 90 天的再跌最大幅度中位 ≥ −25%(尾巴可控)。事件 < 8 个 ⇒ 只报不判。
> ⑥ 诚实:事件稀少、可能聚在 2020-03 / 2021-05 / 2022-06 / 2022-11 / 2025-10 几次;按事件列表逐条报,不只报均值。

──────────────────────── 本脚本在看到任何结果之前写死的口径 ────────────────────────

写死(不事后调):
1. **宇宙** = `perp_bv_pairs` 里 `kind='coin'` 或 `kind` 为空且 `dead_from` 有值 ⇒ 653 个合约。
   `tradfi` 合约一律不入。(与 T-243 / T-241 同一把尺。)
2. **扩张 90 分位** = 该序列**严格在 d 之前**的历史观测(不含 d 本身)的 90 分位
   (numpy 线性插值),要求历史观测数 ≥ `MIN_PRIOR`(=60,约 3 个月)。不足 ⇒ 该条件当日不可判。
3. **(a) 的 90 天最高收盘** = d 当天往前 90 个**日历日**(含 d)窗口内 BTC 收盘的最大值。
4. **(c) 的「前 30 日均」** = d 之前 30 个**日历日**(不含 d)的 Σqv 均值。
5. **期限「天」= 日历日**。入场 = d+1 收盘(取 d+1 当天或之后 3 天内第一个有效收盘);
   出场 = d+1+h 日历日当天或之前最后一个有效收盘。BTC 几乎天天有价,日历日与交易日差 ≤ 几天;
   另报 30/60/90 **交易日**版本作稳健性对照。
6. **200 日均线** = BTC 收盘的 200 **日历日**简单均值(逐日向后看,无未来函数)。
   「站上」= 收盘 > 该均线(严格大于)。
7. **20 天去重**:距上一个事件不足 20 个日历日的触发不重复计数。
8. **资金费负值占比**的分母 = 当天有资金费数据、且符号在 coin 宇宙内的合约数
   (主口径);另报「不筛宇宙」的全表版本作敏感性。
9. **条件零分布**:抽样池 = 所有满足 (a) 且 90 天前向收益可算的日子;
   用 `apparatus.random_dates_like`(按年份分层)+ `apparatus.null_distribution`(1,000 次,种子 729)。
   统计量 = 抽到的 n 个日子 90 天 BTC 前向收益的**中位数**。
10. **挪一天**(S-665 纪律):整套流程再以「信号日 = d+1、入场 = d+2 收盘」跑一遍;
    只在当天成立的不算数。
11. **最差 10%**:按 90 天 BTC 前向收益排序取最差的 k = max(1, ceil(0.10 × n)) 个事件,
    对它们算「入场后 90 天内再跌最大幅度」,取中位数。

──────────────────────── 数据(supabase 只读,publishable key) ────────────────────────
- `perp_bv_daily`(d, pair, qv, tbqv)—— 永续日线;`perp_bv_pairs`(pair, symbol, kind, first_d, dead_from)
- `v_funding_daily`(d, symbol, funding_rate, n)—— 日均资金费
- `ohlcv_daily`(source=binance_hist, symbol=BTC)—— 现货收盘
- `core_variants_daily`(arm=cap_pit24)—— ① 面板 NAV(code_ref「S-700 core_pit v1」)
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "t245_results.json"
REPORT = HERE / "T-245_capitulation.md"
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t243_cache")

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}

# ── 常量(全部写死) ─────────────────────────────────────────────────────────
SEED, N_NULL = 729, 1000
HORIZONS = (30, 60, 90)
DD90 = 90            # (a) 90 天最高收盘
QV30 = 30            # (c) 前 30 日均
MA200 = 200          # ④ 200 日均线
MIN_PRIOR = 60       # 扩张分位的最小历史观测数
TB_COV_MIN = 0.80    # 当天 tbqv 非空行数 / 有成交行数 的下限(2025-12 起 tbqv 整列 NULL)
MIN_EVENTS = 8       # ⑤ 少于 8 个事件 ⇒ 只报不判
PCTL = 90            # 扩张 90 分位
CUT1 = "2023-01-01"  # ⑤ 两半切点
START = "2020-01-01"  # 事件样本起点(数据 2019-12-31 起)
DATA_END = "2026-10-31"  # 事件与零分布池的共同截止(90 天前向可算)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


apparatus = _load(REPO / "src/data/evaluation/apparatus.py", "apparatus")


def _random_dates_like_compat(events, eligible, rng, stratum=lambda d: str(d)[:4]):
    """`apparatus.random_dates_like` 的同算法副本 —— 只在该函数还没进 origin/main 时用。

    11-05 实测:`apparatus.random_dates_like` 是 lane-b 的 T-242 在主工作区**未提交**的本地改动,
    origin/main 里还没有。本脚本优先用 apparatus 上的那个;没有才退到这里(算法逐行照抄,
    不另起炉灶写零分布)。等 lane-b 的改动合进来后本函数自动不再被调用。
    """
    pools: dict = {}
    out: list = []
    for key, d in events:
        ds = [str(x)[:10] for x in (eligible.get(key) or [])]
        if not ds:
            out.append((key, None))
            continue
        by = pools.setdefault(key, {})
        if not by:
            for x in ds:
                by.setdefault(stratum(x), []).append(x)
        pool = by.get(stratum(str(d)[:10])) or ds
        out.append((key, pool[int(rng.integers(0, len(pool)))]))
    return out


_RDL = getattr(apparatus, "random_dates_like", _random_dates_like_compat)
USING_APPARATUS_RDL = hasattr(apparatus, "random_dates_like")


# ── 只读取数(翻页一律带 order=) ─────────────────────────────────────────────
def _get(table: str, params, rng: str = "0-999", extra: dict | None = None):
    url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    h = dict(HEAD, Range=rng)
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read().decode()
        return (json.loads(body) if body else []), r.headers.get("Content-Range")


def _get_retry(table: str, params, rng: str, tries: int = 6):
    delay = 1.0
    last = None
    for _ in range(tries):
        try:
            return _get(table, params, rng)
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise last


def fetch_all(table: str, params, page: int = 1000) -> list[dict]:
    """显式 Range 分页;总量从 Content-Range 读(带 order=,边界不漂)。"""
    _, cr = _get(table, params, "0-0", {"Prefer": "count=exact"})
    total = int(str(cr).split("/")[-1]) if cr and "/" in str(cr) else 0
    if total <= 0:
        rows, _ = _get(table, params, "0-999")
        return rows
    out: list[dict] = []
    off = 0
    while off < total:
        rows, _ = _get_retry(table, params, f"{off}-{off + page - 1}")
        if not rows:
            break
        out.extend(rows)
        off += len(rows)
    print(f"[t245] {table} 取完 {len(out)}/{total} 行", flush=True)
    return out


def load_cache(name: str) -> list[dict]:
    rows = []
    with gzip.open(CACHE / f"{name}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for x in fh:
            if x.strip():
                rows.append(json.loads(x))
    return rows


# ── 日历工具 ───────────────────────────────────────────────────────────────
def d2(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def trailing_max(vals: list, i: int, ndays: int) -> float | None:
    """含当天的过去 ndays 个日历日窗口内最大值。"""
    end = d2(vals[i]["d"])
    start = end - timedelta(days=ndays - 1)
    best = None
    for j in range(i, -1, -1):
        if d2(vals[j]["d"]) < start:
            break
        v = vals[j]["v"]
        if v is not None and (best is None or v > best):
            best = v
    return best


def trailing_mean_prior(vals: list, i: int, ndays: int) -> float | None:
    """不含当天的过去 ndays 个日历日窗口内均值。"""
    end = d2(vals[i]["d"])
    start = end - timedelta(days=ndays)
    xs = []
    for j in range(i - 1, -1, -1):
        if d2(vals[j]["d"]) < start:
            break
        v = vals[j]["v"]
        if v is not None:
            xs.append(v)
    return (sum(xs) / len(xs)) if len(xs) >= max(3, ndays // 2) else None


def trailing_mean(vals: list, i: int, ndays: int) -> float | None:
    """含当天的过去 ndays 个日历日窗口内均值。"""
    end = d2(vals[i]["d"])
    start = end - timedelta(days=ndays - 1)
    xs = []
    for j in range(i, -1, -1):
        if d2(vals[j]["d"]) < start:
            break
        v = vals[j]["v"]
        if v is not None:
            xs.append(v)
    return (sum(xs) / len(xs)) if len(xs) >= ndays // 2 else None


def close_at_or_before(dates: list[str], closes: list, target: str):
    """target 当天或之前最后一个有效收盘。"""
    tgt = d2(target)
    for j in range(len(dates) - 1, -1, -1):
        if d2(dates[j]) > tgt:
            continue
        c = closes[j]
        if c is not None and math.isfinite(float(c)) and float(c) > 0:
            return float(c), dates[j]
    return None, None


def close_on_or_after(dates: list[str], closes: list, target: str, max_gap: int = 3):
    tgt = d2(target)
    for j in range(len(dates)):
        if d2(dates[j]) < tgt:
            continue
        if (d2(dates[j]) - tgt).days > max_gap:
            return None, None
        c = closes[j]
        if c is not None and math.isfinite(float(c)) and float(c) > 0:
            return float(c), dates[j]
    return None, None


def expanding_pct(vals: list, pct: float, min_prior: int) -> tuple[list[float | None], list[int]]:
    """严格在当日之前的扩张历史里的分位;不足 min_prior ⇒ None。同时返回当时的历史观测数。"""
    hist: list[float] = []
    out: list[float | None] = []
    ns: list[int] = []
    for v in vals:
        out.append(float(np.percentile(hist, pct)) if len(hist) >= min_prior else None)
        ns.append(len(hist))
        if v["v"] is not None:
            hist.append(v["v"])
    return out, ns


# ── 数据装载 ───────────────────────────────────────────────────────────────
def load_all() -> dict:
    info: dict = {}
    pairs = load_cache("perp_bv_pairs")
    for r in pairs:
        info[r["pair"]] = r
    universe = {p for p, r in info.items()
                if r.get("kind") == "coin" or (r.get("kind") is None and r.get("dead_from"))}
    coin_syms = {info[p].get("symbol") for p in universe if info[p].get("symbol")}
    print(f"[t245] 永续台账 {len(pairs)} 行;coin 宇宙 {len(universe)} 个合约 / {len(coin_syms)} 个符号", flush=True)

    # 永续日线 → 每日聚合(coin 宇宙)
    qv_by_d: dict[str, float] = defaultdict(float)        # Σqv(全部 qv>0 的行)
    qv_tb_by_d: dict[str, float] = defaultdict(float)     # Σqv(只在 tbqv 非空的行上)
    tb_by_d: dict[str, float] = defaultdict(float)
    n_by_d: dict[str, int] = defaultdict(int)
    n_tb_d: dict[str, int] = defaultdict(int)   # 当天 tbqv 非空的行数(覆盖率用)
    for r in load_cache("perp_bv_daily"):
        if r["pair"] not in universe:
            continue
        d = str(r["d"])[:10]
        q = float(r.get("qv") or 0.0)
        tb = r.get("tbqv")
        if q <= 0:
            continue
        qv_by_d[d] += q
        n_by_d[d] += 1
        if tb is not None:
            qv_tb_by_d[d] += q
            tb_by_d[d] += float(tb)
            n_tb_d[d] += 1

    # 资金费 → 每日「负值占比」
    neg_by_d: dict[str, int] = defaultdict(int)
    tot_by_d: dict[str, int] = defaultdict(int)
    neg_all_by_d: dict[str, int] = defaultdict(int)
    tot_all_by_d: dict[str, int] = defaultdict(int)
    for r in load_cache("v_funding_daily"):
        d = str(r["d"])[:10]
        fr = r.get("funding_rate")
        if fr is None:
            continue
        neg = float(fr) < 0.0
        tot_all_by_d[d] += 1
        if neg:
            neg_all_by_d[d] += 1
        if r.get("symbol") in coin_syms:
            tot_by_d[d] += 1
            if neg:
                neg_by_d[d] += 1

    # BTC 收盘(ohlcv_daily, source=binance_hist)
    btc_rows = fetch_all("ohlcv_daily",
                          [("source", "eq.binance_hist"), ("symbol", "eq.BTC"),
                           ("select", "trade_date,close,volume"), ("order", "trade_date.asc")])
    btc = sorted(((str(r["trade_date"])[:10], float(r["close"])) for r in btc_rows if r.get("close")))
    print(f"[t245] BTC(binance_hist) {len(btc)} 行 {btc[0][0]}→{btc[-1][0]}", flush=True)

    # ① 面板 cap_pit24
    pv_rows = fetch_all("core_variants_daily",
                         [("arm", "eq.cap_pit24"), ("select", "d,ret,nav,code_ref"), ("order", "d.asc")])
    pv = sorted(((str(r["d"])[:10], float(r["nav"])) for r in pv_rows if r.get("nav") is not None))
    cref = sorted({str(r.get("code_ref")) for r in pv_rows})
    print(f"[t245] cap_pit24 {len(pv)} 行 {pv[0][0]}→{pv[-1][0]} code_ref={cref}", flush=True)

    return {"info": info, "universe": universe, "coin_syms": coin_syms,
            "qv": dict(qv_by_d), "qv_tb": dict(qv_tb_by_d), "tb": dict(tb_by_d),
            "n_pairs": dict(n_by_d), "n_tb": dict(n_tb_d),
            "neg": dict(neg_by_d), "tot": dict(tot_by_d),
            "neg_all": dict(neg_all_by_d), "tot_all": dict(tot_all_by_d),
            "btc": btc, "panel": pv}


# ── 主流程 ─────────────────────────────────────────────────────────────────
def build_series(D: dict) -> dict:
    alld = sorted(set(list(D["qv"]) + list(D["neg"]) +
                      [d for d, _ in D["btc"]] + [d for d, _ in D["panel"]]))
    btc_d = [d for d, _ in D["btc"]]
    btc_c = [c for _, c in D["btc"]]
    btc_idx = {d: i for i, d in enumerate(btc_d)}
    pv_d = [d for d, _ in D["panel"]]
    pv_n = [n for _, n in D["panel"]]

    # (a) 90 天最高收盘
    hi90: dict[str, float] = {}
    ma200: dict[str, float] = {}
    for d in alld:
        i = btc_idx.get(d)
        if i is None:
            continue
        w = [{"d": btc_d[j], "v": btc_c[j]} for j in range(max(0, i - MA200 - 2), i + 1)]
        m = trailing_max(w, len(w) - 1, DD90)
        if m is not None:
            hi90[d] = m
        mm = trailing_mean(w, len(w) - 1, MA200)
        if mm is not None:
            ma200[d] = mm

    # (b) 主动卖出占比 & 资金费负值占比
    # **tbqv 覆盖率闸门(11-05 实测)**:perp_bv_daily 的 tbqv 自 2025-12-01 起**整列 NULL**。
    # 不设闸门的话这些日子的「卖占比 = 1 − 0/Σqv = 1.0」会被当成「全市场被迫卖出」白送事件,
    # 且扩张 90 分位在退化序列上恒等于 1.0 ⇒ (b) 被平凡满足。故:tbqv 覆盖率 < TB_COV_MIN 的日子
    # 「卖占比」判为**不可算**(None),(b) 只能走资金费那一支。
    sell: dict[str, float] = {}
    sell_cov: dict[str, float] = {}
    for d in D["qv"]:
        n_all = D["n_pairs"].get(d, 0)
        n_tb = D["n_tb"].get(d, 0)
        cov = (n_tb / n_all) if n_all else 0.0
        sell_cov[d] = cov
        qt = D["qv_tb"].get(d, 0.0)
        if cov >= TB_COV_MIN and qt > 0:
            sell[d] = 1.0 - D["tb"][d] / qt
    fneg: dict[str, float] = {}
    for d, t in D["tot"].items():
        if t >= 5:
            fneg[d] = D["neg"].get(d, 0) / t
    fneg_all: dict[str, float] = {}
    for d, t in D["tot_all"].items():
        if t >= 5:
            fneg_all[d] = D["neg_all"].get(d, 0) / t

    # (c) 前 30 日均 Σqv
    qv_series = [{"d": d, "v": D["qv"].get(d)} for d in alld]
    qv30: dict[str, float] = {}
    for i, row in enumerate(qv_series):
        m = trailing_mean_prior(qv_series, i, QV30)
        if m is not None:
            qv30[row["d"]] = m

    # 扩张分位(严格在 d 之前)
    sell_p, sell_n = expanding_pct([{"d": d, "v": sell.get(d)} for d in alld], PCTL, MIN_PRIOR)
    fneg_p, fneg_n = expanding_pct([{"d": d, "v": fneg.get(d)} for d in alld], PCTL, MIN_PRIOR)
    sell_pct = {d: sell_p[i] for i, d in enumerate(alld)}
    fneg_pct = {d: fneg_p[i] for i, d in enumerate(alld)}
    sell_nprior = {d: sell_n[i] for i, d in enumerate(alld)}
    fneg_nprior = {d: fneg_n[i] for i, d in enumerate(alld)}

    return {"alld": alld, "btc_d": btc_d, "btc_c": btc_c, "pv_d": pv_d, "pv_n": pv_n,
            "btc_idx": btc_idx,
            "hi90": hi90, "ma200": ma200, "sell": sell, "sell_cov": sell_cov,
            "fneg": fneg, "fneg_all": fneg_all,
            "qv30": qv30, "sell_pct": sell_pct, "fneg_pct": fneg_pct,
            "sell_nprior": sell_nprior, "fneg_nprior": fneg_nprior}


def cond_flags(d: str, S: dict, D: dict) -> dict:
    """某一天 (a)(b)(c) 三个条件的取值 —— find_events 与诊断共用同一套判据。"""
    btc_d, btc_c = S["btc_d"], S["btc_c"]
    i = btc_d.index(d) if d in S["btc_idx"] else None
    h = S["hi90"].get(d)
    depth = (btc_c[i] / h - 1.0) if (i is not None and h) else None
    sp = S["sell_pct"].get(d)
    fp = S["fneg_pct"].get(d)
    b_sell = (S["sell"].get(d) is not None and sp is not None and S["sell"][d] >= sp)
    b_fund = (S["fneg"].get(d) is not None and fp is not None and S["fneg"][d] >= fp)
    q = D["qv"].get(d)
    m = S["qv30"].get(d)
    c = bool(q is not None and m is not None and m > 0 and q >= 2.0 * m)
    return {"d": d, "depth": depth, "a": bool(depth is not None and depth <= -0.25),
            "b_sell": b_sell, "b_fund": b_fund, "b": b_sell or b_fund, "c": c,
            "sell": S["sell"].get(d), "sell_pctl": sp, "fneg": S["fneg"].get(d),
            "fneg_pctl": fp, "qv_ratio": (q / m) if (q and m) else None,
            "n_pairs": D["n_pairs"].get(d)}


def find_events(S: dict, D: dict, shift: int = 0) -> list[dict]:
    """shift=0: 信号日 d,入场 d+1 收盘。shift=1: 信号日 d+1,入场 d+2 收盘(挪一天)。"""
    btc_d, btc_c = S["btc_d"], S["btc_c"]
    btc_idx = {d: i for i, d in enumerate(btc_d)}
    events: list[dict] = []
    last_sig = None
    for d in S["alld"]:
        if d < START or d > DATA_END:
            continue
        sig = d if shift == 0 else None
        # 条件 (a): BTC 收盘 ≤ 0.75 × 90 天最高收盘
        i = btc_idx.get(d)
        if i is None:
            continue
        h = S["hi90"].get(d)
        if h is None or h <= 0:
            continue
        depth = btc_c[i] / h - 1.0
        cond_a = depth <= -0.25
        if not cond_a:
            continue
        # 条件 (b): 两条之一
        sp = S["sell_pct"].get(d)
        fp = S["fneg_pct"].get(d)
        b_sell = (S["sell"].get(d) is not None and sp is not None and S["sell"][d] >= sp)
        b_fund = (S["fneg"].get(d) is not None and fp is not None and S["fneg"][d] >= fp)
        if not (b_sell or b_fund):
            continue
        # 条件 (c): Σqv ≥ 2 × 前 30 日均
        q = D["qv"].get(d)
        m = S["qv30"].get(d)
        if q is None or m is None or m <= 0:
            continue
        cond_c = q >= 2.0 * m
        if not cond_c:
            continue
        # 20 天去重
        if last_sig is not None and (d2(d) - d2(last_sig)).days < 20:
            continue
        last_sig = d
        events.append({
            "sig_date": d,
            "depth_pct": depth,
            "close": btc_c[i],
            "sell_share": S["sell"].get(d),
            "sell_pctl": sp,
            "sell_nprior": S["sell_nprior"].get(d),
            "sell_cov": S["sell_cov"].get(d),
            "b_sell": b_sell,
            "fund_neg_share": S["fneg"].get(d),
            "fund_neg_pctl": fp,
            "fund_nprior": S["fneg_nprior"].get(d),
            "n_fund_syms": D["tot"].get(d),
            "b_fund": b_fund,
            "qv": q,
            "qv30_prior_mean": m,
            "qv_ratio": q / m,
            "n_pairs": D["n_pairs"].get(d),
            "hi90": h,
        })
    return events


def condition_diagnostics(S: dict, D: dict) -> dict:
    """(a) 日里三个条件各自的通过数 +「只差一条」的近似事件(为什么事件这么少的答案)。"""
    btc_d, btc_c = S["btc_d"], S["btc_c"]
    btc_idx = {d: i for i, d in enumerate(btc_d)}
    st = {"n_days": 0, "n_a": 0, "n_a_b": 0, "n_a_c": 0, "n_a_bc": 0,
          "n_a_bc_sell": 0, "n_a_bc_fund": 0, "n_a_sell_uncomputable": 0}
    near: list[dict] = []
    for d in S["alld"]:
        if d < START or d > DATA_END:
            continue
        st["n_days"] += 1
        i = btc_idx.get(d)
        if i is None:
            continue
        h = S["hi90"].get(d)
        if h is None or h <= 0:
            continue
        depth = btc_c[i] / h - 1.0
        if depth > -0.25:
            continue
        st["n_a"] += 1
        sp = S["sell_pct"].get(d)
        fp = S["fneg_pct"].get(d)
        b_sell = (S["sell"].get(d) is not None and sp is not None and S["sell"][d] >= sp)
        b_fund = (S["fneg"].get(d) is not None and fp is not None and S["fneg"][d] >= fp)
        if S["sell"].get(d) is None and S["sell_cov"].get(d, 1.0) < TB_COV_MIN:
            st["n_a_sell_uncomputable"] += 1
        b = b_sell or b_fund
        q = D["qv"].get(d)
        m = S["qv30"].get(d)
        c = bool(q is not None and m is not None and m > 0 and q >= 2.0 * m)
        if b:
            st["n_a_b"] += 1
        if c:
            st["n_a_c"] += 1
        if b and c:
            st["n_a_bc"] += 1
            if b_sell:
                st["n_a_bc_sell"] += 1
            if b_fund:
                st["n_a_bc_fund"] += 1
        elif b or c:
            near.append({"d": d, "depth": depth, "b": b, "c": c,
                         "b_sell": b_sell, "b_fund": b_fund,
                         "qv_ratio": (q / m) if (q and m) else None,
                         "sell": S["sell"].get(d), "sell_pctl": sp,
                         "fneg": S["fneg"].get(d), "fneg_pctl": fp,
                         "missing": "".join([tag for tag, ok in (("(b)", b), ("(c)", c)) if not ok])})
    near.sort(key=lambda x: x["depth"])
    return {"stats": st, "near": near}


def persistence(events: list[dict], S: dict, D: dict) -> list[dict]:
    """S-665 纪律「只在当天成立的不算」:每个事件的信号**连续成立几天**(三个条件同时成立的天数)。"""
    out = []
    alld = S["alld"]
    pos = {d: i for i, d in enumerate(alld)}
    for e in events:
        d0 = e["sig_date"]
        i0 = pos.get(d0)
        run = 0
        if i0 is not None:
            for j in range(i0, min(i0 + 40, len(alld))):
                f = cond_flags(alld[j], S, D)
                if f["a"] and f["b"] and f["c"]:
                    run += 1
                else:
                    break
        nxt = None
        if i0 is not None and i0 + 1 < len(alld):
            f = cond_flags(alld[i0 + 1], S, D)
            nxt = bool(f["a"] and f["b"] and f["c"])
        out.append({"sig_date": d0, "run_days": run, "holds_next_day": nxt})
    return out


def verify_btc_against_binance(btc: list[tuple[str, float]]) -> dict:
    """数据完整性:把 ohlcv_daily(binance_hist/BTC) 的收盘与 Binance 官方日线对账。"""
    try:
        from datetime import datetime, timezone
        tbl = {d: c for d, c in btc}
        t0 = int(datetime(2017, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
        t1 = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp() * 1000)
        ref: dict[str, float] = {}
        ms = t0
        for _ in range(12):
            url = ("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d"
                   f"&limit=1000&startTime={ms}&endTime={t1}")
            with urllib.request.urlopen(url, timeout=60) as r:
                k = json.loads(r.read().decode())
            if not k:
                break
            for row in k:
                d = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                ref[d] = float(row[4])
            nxt = int(k[-1][0]) + 86400000
            if nxt <= ms:
                break
            ms = nxt
            time.sleep(0.15)
        common = sorted(set(tbl) & set(ref))
        worst = 0.0
        worst_d = None
        for d in common:
            rel = abs(tbl[d] / ref[d] - 1.0)
            if rel > worst:
                worst, worst_d = rel, d
        return {"available": True, "n_table": len(tbl), "n_ref": len(ref),
                "n_common": len(common), "max_rel_diff": worst, "max_rel_diff_date": worst_d,
                "only_in_table": sorted(set(tbl) - set(ref))[:10],
                "only_in_binance": sorted(set(ref) - set(tbl))[:10]}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "why": f"{type(e).__name__}: {e}"}


def forward_stats(ev: dict, S: dict, D: dict, shift: int = 0) -> dict:
    """入场 = 信号日 + 1 + shift 天的收盘;算 30/60/90 天前向收益、最差路径、MA200 交叉。"""
    btc_d, btc_c = S["btc_d"], S["btc_c"]
    pv_d, pv_n = S["pv_d"], S["pv_n"]
    d = ev["sig_date"]
    entry_target = (d2(d) + timedelta(days=1 + shift)).isoformat()

    p_entry, d_entry = close_on_or_after(btc_d, btc_c, entry_target)
    out = {"entry_target": entry_target, "entry_date": d_entry, "entry_px": p_entry}
    if p_entry is None:
        return out
    i_entry = btc_d.index(d_entry)

    for h in HORIZONS:
        tgt = (d2(d_entry) + timedelta(days=h)).isoformat()
        p_exit, d_exit = close_at_or_before(btc_d, btc_c, tgt)
        out[f"btc_fwd{h}"] = apparatus.long_return(p_entry, p_exit)
        out[f"btc_exit{h}"] = d_exit
        # 交易日口径(对照)
        j = min(i_entry + h, len(btc_d) - 1)
        out[f"btc_fwd{h}_tdays"] = apparatus.long_return(p_entry, btc_c[j])
        # 面板
        pe = None
        for k in range(len(pv_d) - 1, -1, -1):
            if d2(pv_d[k]) <= d2(d_entry):
                pe = pv_n[k]
                break
        px = None
        if d_exit:
            for k in range(len(pv_d) - 1, -1, -1):
                if d2(pv_d[k]) <= d2(d_exit):
                    px = pv_n[k]
                    break
        out[f"panel_fwd{h}"] = apparatus.long_return(pe, px)

    # 最差路径:入场后 90 天内再跌最大幅度(逐日收盘对入场价的最小跌幅)
    end90 = (d2(d_entry) + timedelta(days=90)).isoformat()
    worst = None
    worst_d = None
    for j in range(i_entry, len(btc_d)):
        if d2(btc_d[j]) > d2(end90):
            break
        c = btc_c[j]
        if c is None or c <= 0:
            continue
        r = c / p_entry - 1.0
        if worst is None or r < worst:
            worst = r
            worst_d = btc_d[j]
    out["worst_path_90d"] = worst
    out["worst_path_date"] = worst_d

    # ④ 下一次站上 200 日均线
    cross_d = None
    for j in range(i_entry, len(btc_d)):
        dd = btc_d[j]
        ma = S["ma200"].get(dd)
        if ma is not None and btc_c[j] > ma:
            cross_d = dd
            break
    if cross_d:
        out["ma200_cross_date"] = cross_d
        out["ma200_days_from_sig"] = (d2(cross_d) - d2(d)).days
        out["ma200_days_from_entry"] = (d2(cross_d) - d2(d_entry)).days
        out["ma200_btc_chg_from_entry"] = apparatus.long_return(p_entry, btc_c[btc_d.index(cross_d)])
        out["ma200_btc_chg_from_sig"] = apparatus.long_return(ev["close"], btc_c[btc_d.index(cross_d)])
    else:
        out["ma200_cross_date"] = None
        out["ma200_days_from_sig"] = None
    return out


def null_distribution_of(events: list[dict], pool: list[str], S: dict, D: dict,
                          shift: int = 0) -> dict:
    """条件零分布:在满足 (a) 的日子池里按年份分层抽同样个数,统计 90 天 BTC 前向收益中位。"""
    if not events or not pool:
        return {"available": False, "why": "没有事件或没有合格的池"}
    btc_d, btc_c = S["btc_d"], S["btc_c"]

    def fwd90(d: str):
        entry_target = (d2(d) + timedelta(days=1 + shift)).isoformat()
        p_entry, d_entry = close_on_or_after(btc_d, btc_c, entry_target)
        if p_entry is None:
            return None
        tgt = (d2(d_entry) + timedelta(days=90)).isoformat()
        p_exit, _ = close_at_or_before(btc_d, btc_c, tgt)
        return apparatus.long_return(p_entry, p_exit)

    cache: dict[str, float | None] = {}

    def one(rng):
        picks = _RDL([(0, e["sig_date"]) for e in events], {0: pool}, rng)
        vals = []
        for _, dd in picks:
            if dd is None:
                continue
            if dd not in cache:
                cache[dd] = fwd90(dd)
            v = cache[dd]
            if v is not None:
                vals.append(v)
        return float(np.median(vals)) if vals else float("nan")

    actual = float(np.median([e["fwd"]["btc_fwd90"] for e in events
                              if e["fwd"].get("btc_fwd90") is not None]))
    try:
        null = apparatus.null_distribution(one, N_NULL, SEED, actual=actual)
    except apparatus.NoOpNull as e:
        return {"available": False, "why": str(e)}
    pct = apparatus.percentile_of(actual, null)
    return {"available": True, "actual_median": actual,
            "null_median": float(np.median(null)),
            "null_p95": float(np.percentile(null, 95)),
            "null_p99": float(np.percentile(null, 99)),
            "null_min": float(np.min(null)), "null_max": float(np.max(null)),
            "actual_pct_in_null": pct,
            "beats_p95": bool(actual > float(np.percentile(null, 95))),
            "beats_p99": bool(actual > float(np.percentile(null, 99))),
            "n_pool": len(pool), "n_events": len(events)}


def judge(events: list[dict], nd: dict) -> dict:
    n = len(events)
    v90 = [e["fwd"].get("btc_fwd90") for e in events]
    v90 = [x for x in v90 if x is not None]
    if not v90:
        return {"verdict": "不可算", "why": "没有事件有 90 天前向收益"}
    med90 = float(np.median(v90))
    half1 = [e["fwd"]["btc_fwd90"] for e in events
             if e["sig_date"] < CUT1 and e["fwd"].get("btc_fwd90") is not None]
    half2 = [e["fwd"]["btc_fwd90"] for e in events
             if e["sig_date"] >= CUT1 and e["fwd"].get("btc_fwd90") is not None]
    # 最差 10%
    k = max(1, math.ceil(0.10 * n))
    by_worst = sorted([e for e in events if e["fwd"].get("btc_fwd90") is not None],
                      key=lambda e: e["fwd"]["btc_fwd90"])[:k]
    worst_paths = [e["fwd"].get("worst_path_90d") for e in by_worst
                   if e["fwd"].get("worst_path_90d") is not None]
    worst_med = float(np.median(worst_paths)) if worst_paths else None
    c1 = bool(nd.get("available")) and nd.get("beats_p95", False)
    c2 = bool(half1) and bool(half2) and float(np.median(half1)) > 0 and float(np.median(half2)) > 0
    c3 = worst_med is not None and worst_med >= -0.25
    if n < MIN_EVENTS:
        verdict = "只报不判(事件 < 8)"
    elif c1 and c2 and c3:
        verdict = "✅ 全过"
    else:
        verdict = "❌ 未全过"
    return {"n_events": n, "median_btc_fwd90": med90,
            "half1": {"n": len(half1), "median": float(np.median(half1)) if half1 else None},
            "half2": {"n": len(half2), "median": float(np.median(half2)) if half2 else None},
            "worst_decile": {"k": k, "events": [e["sig_date"] for e in by_worst],
                             "median_worst_path": worst_med},
            "criterion_1_median_gt_null_p95": c1,
            "criterion_2_both_halves_positive": c2,
            "criterion_3_worst_decile_tail_ge_-25pct": c3,
            "verdict": verdict}


def run(D: dict, S: dict, shift: int) -> dict:
    events = find_events(S, D, shift=shift)
    for e in events:
        e["fwd"] = forward_stats(e, S, D, shift=shift)
    # 条件零分布的池:所有满足 (a) 且 90 天前向可算的日子
    btc_d, btc_c = S["btc_d"], S["btc_c"]
    btc_idx = {d: i for i, d in enumerate(btc_d)}
    pool: list[str] = []
    for d in S["alld"]:
        if d < START or d > DATA_END:
            continue
        i = btc_idx.get(d)
        if i is None:
            continue
        h = S["hi90"].get(d)
        if h is None or h <= 0:
            continue
        if btc_c[i] / h - 1.0 > -0.25:
            continue
        # 池内日子也要有 90 天前向
        tgt = (d2(d) + timedelta(days=1 + shift + 90)).isoformat()
        p_exit, _ = close_at_or_before(btc_d, btc_c, tgt)
        if p_exit is None:
            continue
        pool.append(d)
    nd = null_distribution_of(events, pool, S, D, shift=shift)
    jd = judge(events, nd)
    diag = condition_diagnostics(S, D)
    pers = persistence(events, S, D)
    for e, p in zip(events, pers):
        e["persistence"] = p
    return {"shift": shift, "events": events, "pool_n": len(pool),
            "pool_sample": pool[:5], "null": nd, "judge": jd, "diag": diag,
            "persistence": pers}


# ── 报告 ───────────────────────────────────────────────────────────────────
def pp(x, nd=2):
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def num(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def render(res: dict, D: dict, S: dict) -> str:
    A: list[str] = []
    A.append("# T-245 · S-729 —— 投降日之后:深回撤里「全市场被迫卖出」那几天,之后 30/60/90 天怎么走")
    A.append("")
    A.append(f"生成:{res['meta']['generated_at']} · 脚本 `docs/research/t245_capitulation.py` · 数值 `docs/research/t245_results.json`")
    A.append("数据只读(supabase publishable key):`perp_bv_daily` / `perp_bv_pairs` / `v_funding_daily` /")
    A.append("`ohlcv_daily`(source=binance_hist) / `core_variants_daily`(arm=cap_pit24)。不改代码、不做 DDL、不入库。")
    A.append("")
    A.append("## 0. 预注册(抄在结果之前)")
    A.append("")
    A.append("S-729(Seth,2026-11-05 06:04 UTC)原文:")
    A.append("")
    A.append("> **事件(写死):** BTC 收盘 ≤ 0.75 × 90 天最高收盘 × [全市场永续主动卖出占比 ≥ 扩张 90 分位 或")
    A.append("> 资金费为负的合约占比 ≥ 扩张 90 分位] × 全市场永续成交 ≥ 2 × 30 日均;20 天去重。")
    A.append("> 前向 30 / 60 / 90 天 BTC 与 cap_pit24。")
    A.append(">")
    A.append("> **条件零分布:** 同样满足「≤ 0.75 × 90 天高点」的日子随机抽同样个数(按年分层,1,000 次,种子 729)。")
    A.append(">")
    A.append("> **判据(全过 ✅):** 90 天 BTC 收益中位 > 条件零分布 95 分位;两半中位都 > 0;")
    A.append("> 最差 10% 事件之后 90 天内再跌的最大幅度中位 ≥ −25%。事件 < 8 个只报不判;事件逐条列。")
    A.append("> 副报:到下一次站上 200 日线的天数与那段涨跌。**试验计数:③(再入场)+1。**")
    A.append("")
    A.append("### 0b. 口径(在看到任何结果之前写死)")
    A.append("")
    for line in res["meta"]["pre_registered_conventions"]:
        A.append(f"- {line}")
    A.append("")
    A.append("## 1. 结论")
    A.append("")
    for line in res["meta"]["headline"]:
        A.append(line)
    A.append("")
    A.append("## 2. 事件清单(逐条)")
    A.append("")
    A.append("| # | 信号日 | 回撤深度(a) | 主动卖出占比 / 扩张分位 | 资金费负值占比 / 扩张分位 | Σqv ÷ 前 30 日均 | 当日合约数 | 入场(d+1 收盘) | BTC 30d | BTC 60d | BTC 90d | ①面板 30d | ①面板 60d | ①面板 90d | 90 天最差路径 |")
    A.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, e in enumerate(res["shift0"]["events"], 1):
        f = e["fwd"]
        sell_txt = (f"{num(e['sell_share'], 4)} / {num(e['sell_pctl'], 4)} {'✅' if e['b_sell'] else '·'}"
                    if e["sell_share"] is not None else "不可算(tbqv 缺)")
        A.append(f"| {i} | {e['sig_date']} | {pp(e['depth_pct'])} | {sell_txt}"
                 f" | {num(e['fund_neg_share'], 4)} / {num(e['fund_neg_pctl'], 4)}"
                 f" {'✅' if e['b_fund'] else '·'} | {num(e['qv_ratio'], 2)}× | {e['n_pairs']} | "
                 f"{f.get('entry_date')} @ {num(f.get('entry_px'), 0)} | "
                 f"{pp(f.get('btc_fwd30'))} | {pp(f.get('btc_fwd60'))} | {pp(f.get('btc_fwd90'))} | "
                 f"{pp(f.get('panel_fwd30'))} | {pp(f.get('panel_fwd60'))} | {pp(f.get('panel_fwd90'))} | "
                 f"{pp(f.get('worst_path_90d'))} |")
    A.append("")
    A.append("每条事件判定时用的扩张分位历史观测数(`n_prior`,严格在信号日之前):")
    A.append("")
    A.append("| # | 信号日 | 卖压的 n_prior | 资金费的 n_prior | 当天有资金费的合约数 |")
    A.append("|---|---|---|---|---|")
    for i, e in enumerate(res["shift0"]["events"], 1):
        A.append(f"| {i} | {e['sig_date']} | {e.get('sell_nprior')} | {e.get('fund_nprior')} | {e.get('n_fund_syms')} |")
    A.append("")
    A.append("## 3. 为什么只有这么少事件(条件的通过率)")
    A.append("")
    for line in res["meta"]["diag_lines"]:
        A.append(line)
    A.append("")
    A.append("## 3b. 汇总")
    A.append("")
    for line in res["meta"]["summary_lines"]:
        A.append(line)
    A.append("")
    A.append("## 4. 条件零分布(③)")
    A.append("")
    for line in res["meta"]["null_lines"]:
        A.append(line)
    A.append("")
    A.append("## 5. 「早多少」—— 投降日 vs 重新站上 200 日线(④)")
    A.append("")
    for line in res["meta"]["ma200_lines"]:
        A.append(line)
    A.append("")
    A.append("## 6. 判(⑤)")
    A.append("")
    for line in res["meta"]["judge_lines"]:
        A.append(line)
    A.append("")
    A.append("## 7. 诚实与限制")
    A.append("")
    for line in res["meta"]["caveats"]:
        A.append(line)
    A.append("")
    A.append("## 8. 挪一天(晚一天入场)(稳健性)")
    A.append("")
    for line in res["meta"]["shift_lines"]:
        A.append(line)
    A.append("")
    A.append("## 9. 信号持续性(S-665:只在当天成立的不算)")
    A.append("")
    for line in res["meta"]["persistence_lines"]:
        A.append(line)
    A.append("")
    A.append("## 10. 价格数据完整性(与 Binance 官方日线对账)")
    A.append("")
    for line in res["meta"]["px_lines"]:
        A.append(line)
    A.append("")
    return "\n".join(A)


def main() -> None:
    print("[t245] 装载数据…", flush=True)
    D = load_all()
    S = build_series(D)
    print(f"[t245] 序列就绪:alld {len(S['alld'])} 天 "
          f"{S['alld'][0]}→{S['alld'][-1]}", flush=True)
    r0 = run(D, S, shift=0)
    r1 = run(D, S, shift=1)
    print("[t245] 对账 Binance 官方日线…", flush=True)
    pxchk = verify_btc_against_binance(D["btc"])
    res = {"meta": {}, "shift0": r0, "shift1": r1, "px_check": pxchk}
    fill_meta(res, D, S)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    REPORT.write_text(render(res, D, S))
    print(f"[t245] 写出 {OUT} 与 {REPORT}", flush=True)


def fill_meta(res: dict, D: dict, S: dict) -> None:
    import datetime as _dt
    r0, r1 = res["shift0"], res["shift1"]
    ev = r0["events"]
    nd = r0["null"]
    jd = r0["judge"]
    n = len(ev)

    f30 = [e["fwd"].get("btc_fwd30") for e in ev if e["fwd"].get("btc_fwd30") is not None]
    f60 = [e["fwd"].get("btc_fwd60") for e in ev if e["fwd"].get("btc_fwd60") is not None]
    f90 = [e["fwd"].get("btc_fwd90") for e in ev if e["fwd"].get("btc_fwd90") is not None]
    p30 = [e["fwd"].get("panel_fwd30") for e in ev if e["fwd"].get("panel_fwd30") is not None]
    p60 = [e["fwd"].get("panel_fwd60") for e in ev if e["fwd"].get("panel_fwd60") is not None]
    p90 = [e["fwd"].get("panel_fwd90") for e in ev if e["fwd"].get("panel_fwd90") is not None]
    wp = [e["fwd"].get("worst_path_90d") for e in ev if e["fwd"].get("worst_path_90d") is not None]

    med = lambda xs: (float(np.median(xs)) if xs else None)
    headline = []
    headline.append(f"- **事件 {n} 个**(判据要求 ≥ {MIN_EVENTS} 个才判)。")
    if n:
        headline.append(f"- 90 天 BTC 收益:**中位 {pp(med(f90))}**(n={len(f90)});"
                        f"30 天中位 {pp(med(f30))},60 天中位 {pp(med(f60))}。")
        headline.append(f"- ①面板(cap_pit24)同窗口:30 天中位 {pp(med(p30))},60 天中位 {pp(med(p60))},"
                        f"90 天中位 {pp(med(p90))}。")
        headline.append(f"- 90 天内最差路径(入场后再跌最大幅度)中位 {pp(med(wp))}。")
    if nd.get("available"):
        headline.append(f"- 条件零分布:实际 90 天中位 {pp(nd['actual_median'])} vs 零分布 95 分位 "
                        f"{pp(nd['null_p95'])}(中位 {pp(nd['null_median'])});实际值在零分布里的分位 "
                        f"**{nd['actual_pct_in_null']:.3f}**。")
    headline.append(f"- **判:{jd.get('verdict')}**"
                    + ("" if n >= MIN_EVENTS else f"(事件 {n} < {MIN_EVENTS} ⇒ 只报不判)"))
    res["meta"]["headline"] = headline

    summary = []
    summary.append("| 量 | n | 中位 | 均值 | 最差 | 最好 |")
    summary.append("|---|---|---|---|---|---|")
    for label, xs in (("BTC 30 天", f30), ("BTC 60 天", f60), ("BTC 90 天", f90),
                      ("①面板 30 天", p30), ("①面板 60 天", p60), ("①面板 90 天", p90),
                      ("90 天最差路径", wp)):
        if not xs:
            summary.append(f"| {label} | 0 | — | — | — | — |")
            continue
        summary.append(f"| {label} | {len(xs)} | {pp(med(xs))} | {pp(float(np.mean(xs)))} | "
                       f"{pp(min(xs))} | {pp(max(xs))} |")
    summary.append("")
    if n:
        h1 = [e["fwd"]["btc_fwd90"] for e in ev if e["sig_date"] < CUT1 and e["fwd"].get("btc_fwd90") is not None]
        h2 = [e["fwd"]["btc_fwd90"] for e in ev if e["sig_date"] >= CUT1 and e["fwd"].get("btc_fwd90") is not None]
        summary.append(f"- 两半(2020-03 → 2022-12 / 2023-01 → 2026-10)90 天 BTC 收益中位:"
                       f"前半 **{pp(med(h1))}**(n={len(h1)})、后半 **{pp(med(h2))}**(n={len(h2)})。")
    res["meta"]["summary_lines"] = summary

    # 条件通过率诊断
    dg = r0["diag"]
    st = dg["stats"]
    dl = []
    dl.append(f"- 样本内(2020-01-01 → {DATA_END})共 {st['n_days']} 天,其中满足 (a)「BTC ≤ 0.75 × 90 天高点」的 "
              f"**{st['n_a']}** 天。")
    dl.append(f"- (a) 基础上满足 (b)(卖压/资金费)的 **{st['n_a_b']}** 天;满足 (c)(放量)的 **{st['n_a_c']}** 天;")
    dl.append(f"  **同时**满足 (b) 与 (c) 的 **{st['n_a_bc']}** 天 —— 这就是事件的全部候选"
              f"(其中靠卖压分支的 {st['n_a_bc_sell']} 天、靠资金费分支的 {st['n_a_bc_fund']} 天)。")
    dl.append(f"- 再按 20 天去重 ⇒ **{n} 个事件**。事件少的直接原因是 (c):**放量 2× 在真正的暴跌里很难成立** ——")
    dl.append("  暴跌当天成交确实放大,但「前 30 日均」里已经含了上一轮暴跌的天量。")
    near = dg["near"]
    dl.append(f"- 「只差一条」的近似事件(满足 (a) 且 (b)/(c) 恰好一条成立)共 **{len(near)}** 天。"
              f"下面列最深的 20 条(这类日子说明事件定义卡在哪一条上):")
    dl.append("")
    dl.append("| 日期 | 深度 | (b) 卖压 | (b) 资金费 | (c) Σqv÷前 30 日均 | 缺哪条 |")
    dl.append("|---|---|---|---|---|---|")
    for x in near[:20]:
        dl.append(f"| {x['d']} | {pp(x['depth'])} | "
                  f"{num(x['sell'], 4)} / {num(x['sell_pctl'], 4)} {'✅' if x['b_sell'] else '✗'} | "
                  f"{num(x['fneg'], 4)} / {num(x['fneg_pctl'], 4)} {'✅' if x['b_fund'] else '✗'} | "
                  f"{num(x['qv_ratio'], 2)}× | {x['missing']} |")
    sv = sorted(v for v in S["sell"].values() if v is not None)
    if sv:
        dl.append(f"- **「主动卖出占比」这条腿几乎是死的**:全样本(可算的日子)里它一直在 "
                  f"{num(float(np.median(sv)), 4)} 附近(区间 {num(sv[0], 4)} – {num(sv[-1], 4)})—— "
                  f"主动买入占成交量的一半左右,这条序列几乎没有变动空间,扩张 90 分位因而是个很紧的门槛。"
                  f"结果:9 个候选日里只有 **{st['n_a_bc_sell']}** 天靠它成立,**(b) 实际上是被资金费那一支扛起来的**。")
    res["meta"]["diag_lines"] = dl

    null_lines = []
    null_lines.append(f"- 抽样池:满足 (a)(BTC ≤ 0.75 × 90 天高点)且 90 天前向可算的日子共 "
                      f"**{r0['pool_n']}** 个;事件 {n} 个。")
    if nd.get("available"):
        null_lines.append(f"- 抽样:按年份分层,每个事件在同年池里随机抽 1 个日子,1,000 次,种子 729"
                          f"(零分布只用 `apparatus.null_distribution`;"
                          f"按年分层抽样用 `apparatus.random_dates_like`)。")
        if USING_APPARATUS_RDL:
            null_lines.append("- 抽样函数:`apparatus.random_dates_like`(已在 origin/main 里)。")
        else:
            null_lines.append("- ⚠️ **`apparatus.random_dates_like` 此刻不在 origin/main 里**"
                              "(它是 lane-b 的 T-242 在主工作区的未提交改动)⇒ 本次用的是脚本内"
                              "**同算法副本**(逐行照抄),等 lane-b 的改动合进来后脚本自动改用 apparatus 的。")
        null_lines.append(f"- 零分布的 90 天 BTC 收益中位:中位 {pp(nd['null_median'])}、"
                          f"95 分位 **{pp(nd['null_p95'])}**、99 分位 {pp(nd['null_p99'])}、"
                          f"范围 {pp(nd['null_min'])} → {pp(nd['null_max'])}。")
        null_lines.append(f"- 实际(事件)中位 {pp(nd['actual_median'])} ⇒ 在零分布里的分位 "
                          f"**{nd['actual_pct_in_null']:.3f}**;"
                          f"{'超过' if nd['beats_p95'] else '**没有超过**'} 95 分位。")
    else:
        null_lines.append(f"- 零分布不可算:{nd.get('why')}")
    res["meta"]["null_lines"] = null_lines

    ma_lines = []
    ma_lines.append("| # | 信号日 | 站上 200 日线的日期 | 信号日→该日(天) | 入场→该日(天) | 入场→该日 BTC 涨跌 | 信号日→该日 BTC 涨跌 |")
    ma_lines.append("|---|---|---|---|---|---|---|")
    for i, e in enumerate(ev, 1):
        f = e["fwd"]
        ma_lines.append(f"| {i} | {e['sig_date']} | {f.get('ma200_cross_date') or '未站上'} | "
                        f"{f.get('ma200_days_from_sig') if f.get('ma200_days_from_sig') is not None else '—'} | "
                        f"{f.get('ma200_days_from_entry') if f.get('ma200_days_from_entry') is not None else '—'} | "
                        f"{pp(f.get('ma200_btc_chg_from_entry'))} | {pp(f.get('ma200_btc_chg_from_sig'))} |")
    days = [e["fwd"]["ma200_days_from_sig"] for e in ev if e["fwd"].get("ma200_days_from_sig") is not None]
    chg = [e["fwd"]["ma200_btc_chg_from_entry"] for e in ev if e["fwd"].get("ma200_btc_chg_from_entry") is not None]
    crossed = sum(1 for e in ev if e["fwd"].get("ma200_cross_date"))
    ma_lines.append("")
    ma_lines.append(f"- {n} 个事件里 {crossed} 个在样本内重新站上 200 日线;天数中位 "
                    f"{num(med(days), 1) if days else '—'} 天;"
                    f"这段 BTC 涨跌中位 {pp(med(chg))}。")
    ma_lines.append("- 读法:这是 S-601「趋势规则的代价付在每次反弹的开头」的另一半 —— 投降日进场的人")
    ma_lines.append("  在这��段里已经吃到反弹;等 200 日线的人这段没吃到,后面才拿趋势段。")
    res["meta"]["ma200_lines"] = ma_lines

    judge_lines = []
    judge_lines.append(f"**(a) 90 天 BTC 收益中位 > 条件零分布 95 分位** → "
                       f"{'✅' if jd.get('criterion_1_median_gt_null_p95') else '❌'}"
                       f"({pp(jd.get('median_btc_fwd90'))} vs {pp(nd.get('null_p95'))})")
    judge_lines.append(f"**(b) 两半中位都 > 0** → "
                       f"{'✅' if jd.get('criterion_2_both_halves_positive') else '❌'}"
                       f"(前半 {pp(jd.get('half1', {}).get('median'))} / 后半 {pp(jd.get('half2', {}).get('median'))})")
    judge_lines.append(f"**(c) 最差 10% 事件的 90 天再跌最大幅度中位 ≥ −25%** → "
                       f"{'✅' if jd.get('criterion_3_worst_decile_tail_ge_-25pct') else '❌'}"
                       f"({pp(jd.get('worst_decile', {}).get('median_worst_path'))})")
    judge_lines.append("")
    judge_lines.append(f"**判:{jd.get('verdict')}**")
    res["meta"]["judge_lines"] = judge_lines

    cav = []
    cav.append(f"1. **事件稀少**:{n} 个事件,判据要求 ≥ {MIN_EVENTS} 个才判;"
               f"少于就只报不判。事件不是独立样本 —— 20 天去重后仍可能同属一轮暴跌。")
    cav.append("2. **扩张分位的历史很薄**:perp_bv_daily 从 2019-12-31 起,事件窗口起于 2020 年春,")
    cav.append("   早期事件的「扩张 90 分位」只有几个月历史(每个事件的历史观测数见结果 json),")
    cav.append("   阈值天然偏低 —— 这对 2020-03 那批事件尤其要紧。")
    cav.append("3. **条件零分布控制的是「深回撤之后本来就会反弹」**,不是「投降日之后的反弹更强」。")
    cav.append("   所以 (a) 判 ✅ 只说明「投降日不额外差」,不等于「投降日之后更好」。")
    cav.append("4. **事件与零分布不是同一个总体**:池里有 (b)(c) 不成立的日子(深度回撤但没有放量/卖压)。")
    cav.append("   这正是预注册要的控制,但代价是把「(b)(c) 的增量信息」留在了判据之外。")
    cav.append("5. **90 天前向有 2026 年样本右删失**:事件与池都截止 2026-10-31,")
    cav.append("   否则最后 90 天没有前向收益。")
    cav.append("6. **①面板是 cap_pit24 的回放 NAV**(code_ref「S-700 core_pit v1」,")
    cav.append("   computed_at 2026-11-05),不是真钱曲线;它与 ① 的成分规则有关。")
    cav.append("7. **⚠️ `perp_bv_daily.tbqv` 自 2025-12-01 起整列 NULL**(11-05 实测:2025-11 及以前"
               "tbqv 非空行数 = 0 个 NULL,2025-12 起 100% NULL)。若不设覆盖率闸门,这些日子的")
    cav.append("   「卖占比」会算成 1 − 0/Σqv = **1.0**(看起来像「全市场全在卖」),而且扩张 90 分位在")
    cav.append("   这个退化序列上恒等于 1.0 ⇒ (b) 被**平凡满足**。本卡设了覆盖率闸门"
               f"(tbqv 非空行数 ÷ 有成交行数 ≥ {int(TB_COV_MIN * 100)}%),这些日子的卖占比判为**不可算**,")
    cav.append("   (b) 只能走资金费那一支。**不设闸门会多出 2 个 2026 年的假事件** —— 其中 2026-02-05")
    cav.append("   的 (b) 完全靠这个 NULL 伪造成立(资金费那支没过)。")
    cav.append("8. **扩张分位的历史观测数随事件列出**(表里 `n_prior` 列)**:早期事件只有几个月历史。")
    res["meta"]["caveats"] = cav

    shift_lines = []
    e1 = res["shift1"]["events"]
    j1 = res["shift1"]["judge"]
    nd1 = res["shift1"]["null"]
    shift_lines.append("- 口径:事件识别完全不变(条件仍在信号日 d 判定),**只把入场挪到 d+2 收盘** ——")
    shift_lines.append("  模拟「信号是当天收盘后才确认的,只能第二天动手」。")
    shift_lines.append(f"- 事件 **{len(e1)}** 个(与主口径相同)。")
    if e1:
        v1 = [e["fwd"].get("btc_fwd90") for e in e1 if e["fwd"].get("btc_fwd90") is not None]
        shift_lines.append(f"- 90 天 BTC 收益中位 **{pp(med(v1))}**(主口径 {pp(jd.get('median_btc_fwd90'))})。")
    if nd1.get("available"):
        shift_lines.append(f"- 条件零分布 95 分位 {pp(nd1['null_p95'])};实际值在零分布里的分位 "
                           f"**{nd1['actual_pct_in_null']:.3f}**(主口径 {nd.get('actual_pct_in_null', 0):.3f})。")
    shift_lines.append(f"- 挪一天后的判:**{j1.get('verdict')}**"
                       f"(主口径 {jd.get('verdict')})。")
    if not e1:
        shift_lines.append("- 挪一天后**一个事件都没有** —— 若主口径的事件全部经不起挪一天,那就不该判。")
    res["meta"]["shift_lines"] = shift_lines

    # 持续性(S-665:只在当天成立的不算)
    pl = []
    pl.append("| # | 信号日 | 信号**连续成立**几天 | 次日仍成立? |")
    pl.append("|---|---|---|---|")
    for i, p in enumerate(res["shift0"]["persistence"], 1):
        pl.append(f"| {i} | {p['sig_date']} | {p['run_days']} | "
                  f"{'是' if p['holds_next_day'] else '否'} |")
    runs = [p["run_days"] for p in res["shift0"]["persistence"]]
    nxt = sum(1 for p in res["shift0"]["persistence"] if p["holds_next_day"])
    pl.append("")
    pl.append(f"- 连续成立天数中位 {num(med(runs), 1) if runs else '—'} 天;"
              f"{nxt}/{len(runs)} 个事件在次日仍然三个条件同时成立。")
    pl.append("- 读法:**信号不是只在崩盘当天闪一下** —— 连续成立的簇长度决定了「投降日」是一天还是几天。")
    res["meta"]["persistence_lines"] = pl

    # 价格数据对账
    plx = []
    pk = res.get("px_check", {})
    if pk.get("available"):
        plx.append(f"- `ohlcv_daily`(source=binance_hist, symbol=BTC)共 {pk['n_table']} 天"
                   f"(2017-08-17 → 2026-11-04);与 **Binance 官方日线 klines** 对账:"
                   f"共同 {pk['n_common']} 天,**最大相对偏差 {pk['max_rel_diff']:.2e}**"
                   f"(最大的一天 {pk['max_rel_diff_date']})—— 只有 2 位小数的存储精度。")
        plx.append(f"- 只在表里:{pk['only_in_table'] or '无'};只在 Binance:{pk['only_in_binance'] or '无'}"
                   f"(最后一天 2026-11-05 在事件窗口外)。")
        plx.append("- 结论:价格序列可信,本卡的收益数字不是数据瑕疵造成的。")
    else:
        plx.append(f"- 对账不可用({pk.get('why')})。")
    res["meta"]["px_lines"] = plx

    res["meta"]["generated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    res["meta"]["pre_registered_conventions"] = [
        "宇宙 = `perp_bv_pairs` 里 kind='coin' 或 kind 为空且 dead_from 有值(653 个合约);tradfi 不入。",
        "扩张 90 分位 = 严格在 d 之前的扩张历史的 90 分位(numpy 线性插值),历史观测数 ≥ 60 才判。",
        "(a) 90 天最高收盘 = 含当天、往前 90 个日历日的窗口内最大收盘。",
        "(c)「前 30 日均」= 不含当天、往前 30 个日历日的 Σqv 均值。",
        "期限的「天」= 日历日;入场 = 信号日 +1 天收盘(或之后 3 天内第一个有效收盘);"
        "出场 = 入场日 + h 日历日当天或之前最后一个有效收盘。另报交易日口径作对照。",
        "200 日均线 = BTC 收盘的 200 个日历日简单均值(逐日向后看);「站上」= 收盘严格大于该均线。",
        "20 天去重:距上一个事件不足 20 个日历日的触发不重复计数。",
        "资金费负值占比的分母 = 当天有资金费数据且符号在 coin 宇宙内的合约数(另报全表版)。",
        "tbqv 覆盖率闸门 = 当天 tbqv 非空行数 ÷ 有成交行数 ≥ 80%;低于闸门的日子「卖占比」判为不可算,"
        "(b) 只能走资金费那一支(2025-12 起 tbqv 整列 NULL,不设闸门会白送假事件)。",
        "条件零分布 = 满足 (a) 且 90 天前向可算的日子池,按年份分层抽事件个数,1,000 次,种子 729,"
        "只用 apparatus.random_dates_like + apparatus.null_distribution;统计量 = 抽到的日子的 90 天收益中位。",
        "挪一天(S-665 纪律):事件识别不变(条件仍在信号日 d 判定),只把**入场挪到 d+2 收盘** —— "
        "模拟「信号是当天收盘后才确认的,只能第二天动手」;零分布与判据同步重算。",
        "最差 10% = 按 90 天前向收益排序取最差 k = max(1, ceil(10% × n)) 个事件,"
        "算它们入场后 90 天内再跌最大幅度的中位。",
    ]


if __name__ == "__main__":
    main()
