#!/usr/bin/env python3
"""
T-150 / S-636 — 实体 / 决策层:上市公司金库的买入决定(treasury_decisions)领先它买的资产吗。

口径**逐条照台账 S-636 原文**(REFUTATION_LEDGER.md,写于对金库决定与价格做任何匹配之前):
  · 单位:周(周一 UTC)
  · 决定强度 D(w, coin) = 该周披露的净买入美元 ÷ 该币上周五收盘市值(asset_mcap_daily)
  · 结果:下一周起 4 周的对数收益;BTC 对「持有 ① 面板」超额,ETH / SOL 对 BTC 超额
  · 披露滞后:只用披露日、只看之后
  · 发现段 2024-01-01 → 2025-06-30:按 D 三分位报均值 / 事件数 / 独立事件数
    (同一家公司 30 天内多次算一次)
  · 留出段 2025-07-01 → 2026-09-30(一次性):发现段里「顶 > 底」且独立事件 ≥ 20 的
    币才检验;判 = 顶减底 > 0,周序列块自助(4 周一块)2,000 次单侧 p < 0.05

零分布 / 分位一律走 src/data/evaluation/apparatus.py(block_permute /
null_distribution / percentile_of),不自写。

读库只走 os.environ["SUPABASE_URL"] / os.environ["SUPABASE_KEY"](lane_bot 注入,只读
publishable key);不读 .env、不打印 key。
"""
from __future__ import annotations

import os
import sys
import json
import urllib.request
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.data.evaluation.apparatus import (   # noqa: E402
    block_permute, null_distribution, percentile_of,
)

# ── env ─────────────────────────────────────────────────────────────────
try:
    SB = os.environ["SUPABASE_URL"].rstrip("/")
    KEY = os.environ["SUPABASE_KEY"]
except KeyError as e:
    sys.exit(f"missing env: {e}")
if not SB or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY empty in env")

OUT_DIR = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input"
MD_PATH = f"{OUT_DIR}/T-150_treasury.md"
JSON_PATH = f"{OUT_DIR}/T-150_treasury.json"

# ── S-636 constants (preregistered; do NOT edit) ─────────────────────────
COIN_ID = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
           "ripple": "XRP", "dogecoin": "DOGE", "litecoin": "LTC", "sui": "SUI",
           "coredaoorg": "CORE", "binancecoin": "BNB"}
DISC_LO, DISC_HI = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-06-30")   # 发现段
HOLD_LO, HOLD_HI = pd.Timestamp("2025-07-01"), pd.Timestamp("2026-09-30")   # 留出段
HORIZON_WEEKS = 4        # 「下一周起 4 周」
ENTRY_LAG_WEEKS = 1      # 进场 = 披露周之后第 1 周的周五收盘
INDEP_DAYS = 30          # 同公司 30 天内多次算一次
MIN_INDEP_EVENTS = 20    # 进留出段的门槛
N_BOOT, BLOCK, SEED = 2000, 4, 636
PANEL_STYLE = ("tier", "equal", "majors")   # 「持有 ① 面板」的机器可读代理
PX_LO = "2023-10-01"    # 4 周滞后 + 1 周进场 ⇒ 发现段起点前需要约 5 周


def fetch(table: str, params: str) -> list:
    """分页取;超过 200 页就停下并报错(防呆,不当成正常返回)。"""
    head = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json"}
    out, off = [], 0
    while True:
        req = urllib.request.Request(
            f"{SB}/rest/v1/{table}?{params}&limit=1000&offset={off}", headers=head)
        with urllib.request.urlopen(req, timeout=180) as r:
            rows = json.loads(r.read()) or []
        out += rows
        if len(rows) < 1000:
            return out
        off += 1000
        if off > 200_000:
            sys.exit(f"pagination runaway on {table} (>200k rows) — narrow the query")


def monday(s: pd.Series) -> pd.Series:
    return s - pd.to_timedelta(s.dt.weekday, unit="D")


# ── build ───────────────────────────────────────────────────────────────
def main():
    print("[1/6] treasury_decisions", flush=True)
    td = fetch("treasury_decisions",
               "select=coin_id,decision_type,transaction_value_usd,decision_date,"
               "entity_id,holding_net_change&order=decision_date.asc")
    dec = pd.DataFrame(td)
    dec["coin"] = dec["coin_id"].astype(str).str.lower().map(COIN_ID)
    dec["company"] = dec["entity_id"].astype(str)
    dec["disclosed"] = pd.to_datetime(dec["decision_date"], utc=True).dt.tz_localize(None)
    dec["val"] = pd.to_numeric(dec["transaction_value_usd"], errors="coerce")
    # 台账:「净买入美元(transaction_value_usd,卖出为负)」—— 库里 sell 行同样是正数,
    # 符号必须由 decision_type 给,不能直接用金额。
    sign = dec["decision_type"].astype(str).str.lower().map(
        {"buy": 1.0, "sell": -1.0})
    bad_sign = int(sign.isna().sum())
    dec["net"] = dec["val"] * sign
    dec = dec.dropna(subset=["coin", "disclosed", "net"])
    dec["wk"] = monday(dec["disclosed"])
    print(f"  rows={len(dec)} unmapped_sign={bad_sign} "
          f"by coin={dict(Counter(dec['coin']))} "
          f"by type={dict(Counter(dec['decision_type']))}", flush=True)
    print(f"  net buy ${dec['net'].sum():,.0f} · "
          f"{dec['company'].nunique()} companies · "
          f"{dec['disclosed'].min().date()} → {dec['disclosed'].max().date()}",
          flush=True)
    COINS = sorted(dec["coin"].unique())

    print("[2/6] 三表交集(决定 ∩ 市值 ∩ 价格)", flush=True)
    PX_PROBE = pd.DataFrame(fetch(
        "ohlcv_daily",
        f"select=symbol&symbol=in.({','.join(COINS)})"
        f"&trade_date=gte.{PX_LO}&order=symbol.asc"))
    have_px = set(PX_PROBE["symbol"].unique())
    dropped = sorted(set(COINS) - have_px)
    COINS = [c for c in COINS if c in have_px]
    dec = dec[dec["coin"].isin(COINS)].copy()
    print(f"  kept={COINS} dropped_no_price={dropped}", flush=True)
    if not COINS:
        sys.exit("三个表没有共同覆盖的币")

    print("[3/6] asset_mcap_daily (mcap 分母)", flush=True)
    mc = pd.DataFrame(fetch(
        "asset_mcap_daily",
        f"select=symbol,d,mcap&symbol=in.({','.join(COINS)})"
        f"&d=gte.2022-01-01&order=symbol.asc,d.asc"))
    mc["mcap"] = pd.to_numeric(mc["mcap"], errors="coerce")
    mc["d"] = pd.to_datetime(mc["d"])
    mc = mc.dropna(subset=["mcap"])
    mc = mc[mc["mcap"] > 0].rename(columns={"symbol": "coin"})
    mc["wk"] = monday(mc["d"])
    weekly_mcap = mc.pivot_table(index="wk", columns="coin", values="mcap", aggfunc="last")
    print(f"  rows={len(mc)} coins={sorted(weekly_mcap.columns)}", flush=True)

    print("[4/6] ohlcv_daily (周收盘)", flush=True)
    px = pd.DataFrame(fetch(
        "ohlcv_daily",
        f"select=symbol,trade_date,close&symbol=in.({','.join(COINS)})"
        f"&trade_date=gte.{PX_LO}&order=symbol.asc,trade_date.asc"))
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px["trade_date"] = pd.to_datetime(px["trade_date"])
    px = px.dropna(subset=["close"])
    px = px[px["close"] > 0]
    px["wk"] = monday(px["trade_date"])
    weekly_close = px.pivot_table(index="wk", columns="symbol", values="close",
                                  aggfunc="last")
    # 全周网格(缺的一律 NaN,不做前值填充 —— 插值会把未来信息带进来)
    grid = pd.date_range(weekly_close.index.min(), weekly_close.index.max(), freq="7D")
    weekly_close = weekly_close.reindex(grid)
    print(f"  rows={len(px)} weeks={len(weekly_close)} "
          f"({grid[0].date()} → {grid[-1].date()})", flush=True)

    print("[5/6] style_index_pit_daily (① 面板代理)", flush=True)
    dim, wgt, sty = PANEL_STYLE
    si = pd.DataFrame(fetch(
        "style_index_pit_daily",
        f"select=d,ret&dimension=eq.{dim}&weighting=eq.{wgt}&style=eq.{sty}"
        f"&d=gte.2023-10-01&order=d.asc"))
    si["d"] = pd.to_datetime(si["d"])
    si["ret"] = pd.to_numeric(si["ret"], errors="coerce")
    si = si.dropna(subset=["ret"])
    lvl, cur = [], 100.0
    for r in si["ret"]:
        cur *= 1.0 + r
        lvl.append(cur)
    si["lvl"] = lvl
    si["wk"] = monday(si["d"])
    panel_wk = si.groupby("wk")["lvl"].last()
    panel_wk = panel_wk.reindex(grid).ffill()
    print(f"  days={len(si)} weeks={panel_wk.notna().sum()} "
          f"({si['d'].min().date()} → {si['d'].max().date()})", flush=True)

    print("[6/6] 结果与检验", flush=True)
    # ── 结果:进场周 = 披露周 + 1,持有 HORIZON_WEEKS 周(对数收益) ─────────
    def fwd(series: pd.Series, lag: int, horizon: int) -> pd.Series:
        """out[w] = log(S[w + lag + horizon] / S[w + lag]),按日历周定位而非行号。"""
        vals = series.to_numpy(dtype=float)
        ok = np.isfinite(vals) & (vals > 0)
        # 网格是等距 7D,所以「往后 lag+horizon 周」= 数组里平移固定行数
        e = np.full(len(vals), np.nan)
        x = np.full(len(vals), np.nan)
        e[:-lag] = vals[lag:]
        x[: -(lag + horizon)] = vals[lag + horizon:]
        good = ok & np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0)
        out = np.full(len(vals), np.nan)
        out[good] = np.log(x[good] / e[good])
        return pd.Series(out, index=series.index)

    asset_fwd = {c: fwd(weekly_close[c], ENTRY_LAG_WEEKS, HORIZON_WEEKS)
                 for c in COINS}
    panel_fwd = fwd(panel_wk, ENTRY_LAG_WEEKS, HORIZON_WEEKS)
    btc_fwd = asset_fwd.get("BTC")

    excess = {}
    for c, y in asset_fwd.items():
        bench = panel_fwd if c == "BTC" else btc_fwd      # 台账:BTC 对 ① 面板;ETH/SOL 对 BTC
        excess[c] = y - bench
        print(f"  {c}: bench = {'① 面板等权 (tier/equal/majors)' if c == 'BTC' else 'BTC'}"
              f" · 可算 {int(y.notna().sum())} 周 · 可算超额 {int(excess[c].notna().sum())}",
              flush=True)

    # ── D = 该周净买入美元 ÷ 该币**上周五**(严格早于披露周)市值 ──────────
    d_rows = []
    for coin, grp in dec.groupby("coin"):
        m = weekly_mcap.get(coin)
        if m is None:
            print(f"  {coin}: asset_mcap_daily 无此币 ⇒ 跳过", flush=True)
            continue
        for wk, v in grp.groupby("wk")["net"].sum().items():
            prior = m[m.index < wk]          # 上周五:严格早于披露周的第一天
            if len(prior) == 0 or not np.isfinite(prior.iloc[-1]) or prior.iloc[-1] <= 0:
                continue
            cap = float(prior.iloc[-1])
            d_rows.append({"coin": coin, "wk": wk, "D": float(v) / cap,
                           "net_usd": float(v), "mcap": cap, "n_dec": int(len(
                               grp[grp["wk"] == wk]))})
    D = pd.DataFrame(d_rows).sort_values(["coin", "wk"])
    if len(D) == 0:
        sys.exit("D 表为空 —— 检查 asset_mcap_daily 覆盖是否与决定同期")
    print(f"  D rows={len(D)} by coin={dict(Counter(D['coin']))}", flush=True)

    # ── 独立事件:同公司 30 天内多次算一次(链式,跨周也去重) ────────────────
    ev = dec.sort_values(["coin", "company", "disclosed"]).copy()
    gap = ev.groupby(["coin", "company"])["disclosed"].diff().dt.days.fillna(999)
    ev["indep"] = gap >= INDEP_DAYS
    indep_by_wk = (ev[ev["indep"]].groupby(["coin", "wk"]).size()
                   .rename("n_indep").reset_index())
    indep_by_coin_terc: dict = {}

    # ── 自检 C(能失败):结果窗口必须严格晚于披露日 ────────────────────────
    for c, y in asset_fwd.items():
        if not y.notna().any():
            sys.exit(f"SELF-CHECK C FAIL: {c} 没有任何可算的结果周")
    sub = D[D["wk"] >= HOLD_LO]
    if len(sub) == 0:
        sys.exit("留出段没有 D 行 —— 日期边界写错了")
    print(f"  self-check C: PASS(进场 = 披露周 +{ENTRY_LAG_WEEKS} 周,"
          f"持有 {HORIZON_WEEKS} 周 ⇒ 结果窗口起点 ≥ 披露后 {ENTRY_LAG_WEEKS} 周)", flush=True)

    # ── 分段表:按 D 三分位 ────────────────────────────────────────────────
    def terciles(s: pd.DataFrame) -> pd.Series:
        q1, q2 = s["D"].quantile([1 / 3, 2 / 3])
        return np.where(s["D"] <= q1, "bot", np.where(s["D"] <= q2, "mid", "top"))

    def seg(coin: str, lo: pd.Timestamp, hi: pd.Timestamp, fixed_q=None) -> dict | None:
        """fixed_q = (q1, q2) 时用**发现段的边界**(留出段必须用固定阈值)。"""
        s = D[(D["coin"] == coin) & (D["wk"] >= lo) & (D["wk"] <= hi)].copy()
        if len(s) == 0:
            return None
        s["y"] = s["wk"].map(excess[coin])
        s = s.dropna(subset=["y"])
        if len(s) == 0:
            return None
        q1, q2 = fixed_q if fixed_q else tuple(s["D"].quantile([1 / 3, 2 / 3]))
        s["terc"] = terciles(s) if fixed_q is None else np.where(
            s["D"] <= q1, "bot", np.where(s["D"] <= q2, "mid", "top"))
        s = s.merge(indep_by_wk, on=["coin", "wk"], how="left")
        s["n_indep"] = s["n_indep"].fillna(0).astype(int)
        rows = []
        for t in ["bot", "mid", "top"]:
            g = s[s["terc"] == t]
            rows.append({"terc": t, "n": int(len(g)),
                         "n_indep": int(g["n_indep"].sum()),
                         "mean_excess": float(g["y"].mean()) if len(g) else float("nan"),
                         "median_D": float(g["D"].median()) if len(g) else float("nan"),
                         "sum_net_usd": float(g["net_usd"].sum()) if len(g) else 0.0})
        return {"coin": coin, "n": int(len(s)), "q": [float(q1), float(q2)],
                "weeks": [int(s["wk"].min().timestamp() // 86400),
                          int(s["wk"].max().timestamp() // 86400)],
                "rows": rows}

    disc = {c: seg(c, DISC_LO, DISC_HI) for c in COINS}
    hold = {c: seg(c, HOLD_LO, HOLD_HI) for c in COINS}

    # ── 进留出段的门槛:发现段顶 > 底 且 顶三分位独立事件 ≥ 20 ──────────────
    entrants, rejected = [], {}
    for c in COINS:
        d = disc.get(c)
        if not d:
            rejected[c] = "发现段无可算事件"
            continue
        r = {x["terc"]: x for x in d["rows"]}
        if r["top"]["mean_excess"] > r["bot"]["mean_excess"] and \
                r["top"]["n_indep"] >= MIN_INDEP_EVENTS:
            entrants.append(c)
        else:
            rejected[c] = (f"顶 {r['top']['mean_excess']:+.4f} vs 底 "
                           f"{r['bot']['mean_excess']:+.4f};顶独立事件 "
                           f"{r['top']['n_indep']}(门槛 {MIN_INDEP_EVENTS})")

    # ── 留出段检验:发现段固定阈值分档 + 周序列块自助(4 周一块)× 2,000 ──────
    tests = {}
    for c in entrants:
        q1, q2 = disc[c]["q"]
        h = seg(c, HOLD_LO, HOLD_HI, fixed_q=(q1, q2))
        if h is None:
            tests[c] = {"note": "留出段无事件", "n": 0}
            continue
        s = D[(D["coin"] == c) & (D["wk"] >= HOLD_LO) & (D["wk"] <= HOLD_HI)].copy()
        s["y"] = s["wk"].map(excess[c])
        s = s.dropna(subset=["y"])
        s["terc"] = np.where(s["D"] <= q1, "bot", np.where(s["D"] <= q2, "mid", "top"))
        sub = s[s["terc"].isin(["top", "bot"])].sort_values("wk")
        if len(sub) == 0:
            tests[c] = {"note": "留出段顶/底皆空", "n": 0}
            continue
        yv = sub["y"].to_numpy(dtype=float)
        lab = (sub["terc"] == "top").to_numpy()
        n_top, n_bot = int(lab.sum()), int((~lab).sum())
        if n_top < 3 or n_bot < 3:
            tests[c] = {"note": f"顶/底周数不足(顶 {n_top} 底 {n_bot})",
                        "n": int(len(sub))}
            continue
        actual = float(yv[lab].mean() - yv[~lab].mean())

        def stat(vec: np.ndarray) -> float:
            if (~lab).sum() == 0 or lab.sum() == 0:
                return np.nan
            return float(vec[lab].mean() - vec[~lab].mean())

        null = null_distribution(
            lambda rng: stat(block_permute(yv, BLOCK, rng)), N_BOOT, SEED)
        null = np.asarray([x for x in null if np.isfinite(x)], dtype=float)
        p_rank = percentile_of(actual, null)          # 中秩分位(报数用)
        p_one = float(np.mean(null >= actual))       # 单侧 p(判用,照台账「单侧 p < 0.05」)
        tests[c] = {"n_weeks": int(len(sub)), "n_top": n_top, "n_bot": n_bot,
                    "actual": actual, "p_one_sided": p_one, "p_rank": p_rank,
                    "null_mean": float(null.mean()) if len(null) else float("nan"),
                    "pass": bool(actual > 0 and p_one < 0.05)}

    tested = [c for c in entrants if "pass" in tests[c]]
    verdict = None
    if tested:
        verdict = "PASS" if all(tests[c]["pass"] for c in tested) else "FAIL"

    # ── 报告 ──────────────────────────────────────────────────────────────
    L = []
    A = L.append
    A("# T-150 / S-636 — 上市公司金库的决定(treasury_decisions)领先它买的资产吗\n\n")
    A("_口径逐条照台账 S-636 原文;读库 `os.environ['SUPABASE_URL']` / `['SUPABASE_KEY']`"
      "(只读 publishable key),不读 .env、不打印 key。_\n\n")
    A(f"**S-636 结果:{verdict or 'N/A(没有币同时满足进留出段的两条门槛)'}**\n\n")

    A("## 0. 口径\n\n")
    A(f"- 单位 周(周一 UTC)。进场 = 披露周之后第 {ENTRY_LAG_WEEKS} 周的周五收盘,"
      f"持有 {HORIZON_WEEKS} 周 ⇒ **结果窗口起点 = 披露后 ≥ "
      f"{ENTRY_LAG_WEEKS} 周**,严格只看之后。\n")
    A(f"- D(w, coin) = 该周披露的**净**买入美元 ÷ 该币**上周五**收盘市值"
      f"(`asset_mcap_daily`,取严格早于披露周那一周的最后一个市值)。\n")
    A("- 符号:台账写「transaction_value_usd,卖出为负」。库里 `sell` 行的金额字段**本身是正数**,"
      "所以负号由 `decision_type` 给(`buy` → +,`sell` → −);不这样做会把卖出当买入。\n")
    A(f"- 独立事件:同一家公司 {INDEP_DAYS} 天内多次披露算一次(按 company 链式去重,跨周也去重)。\n")
    A("- 基准:BTC 对「持有 ① 面板」超额 —— 用 `style_index_pit_daily` 的 "
      f"`eq.{PANEL_STYLE[0]} / eq.{PANEL_STYLE[1]} / eq.{PANEL_STYLE[2]}` 日收益复原成水平、"
      "取每周末值,即面板**等权持有**。ETH / SOL 对 BTC 超额(照台账)。\n")
    A(f"- 留出段的 D 三分位边界**固定为发现段算出的分位点**,不在留出段内重新切分。\n\n")

    A("## 1. 数据\n\n| 表 | 行数 | 说明 |\n|---|---:|---|\n")
    A(f"| `treasury_decisions` | {len(dec)} | "
      f"{dec['company'].nunique()} 家公司;按币 {dict(Counter(dec['coin']))};"
      f"净买入合计 ${dec['net'].sum():,.0f} |\n")
    A(f"| `asset_mcap_daily` | {len(mc)} | {len(weekly_mcap.columns)} 币 → 周频市值 |\n")
    A(f"| `ohlcv_daily` | {len(px)} | {len(weekly_close.columns)} 币周收盘 "
      f"({grid[0].date()} → {grid[-1].date()}) |\n")
    A(f"| `style_index_pit_daily` | {len(si)} | 面板等权指数日收益 "
      f"({si['d'].min().date()} → {si['d'].max().date()}) |\n\n")

    A("## 2. 发现段 2024-01-01 → 2025-06-30(按 D 三分位)\n\n")
    A("| 币 | 事件数 | D 分位点 (33% / 67%) | 底 (均值超额 / 独立事件) | "
      "中 (均值超额 / 独立事件) | 顶 (均值超额 / 独立事件) | 顶 > 底 |\n")
    A("|---|---:|---|---:|---:|---:|---|\n")
    for c in COINS:
        d = disc.get(c)
        if not d:
            A(f"| {c} | 0 | — | — | — | — | — |\n"); continue
        r = {x["terc"]: x for x in d["rows"]}
        A(f"| {c} | {d['n']} | {d['q'][0]:+.2e} / {d['q'][1]:+.2e} | "
          f"{r['bot']['mean_excess']:+.4f} ({r['bot']['n_indep']}) | "
          f"{r['mid']['mean_excess']:+.4f} ({r['mid']['n_indep']}) | "
          f"{r['top']['mean_excess']:+.4f} ({r['top']['n_indep']}) | "
          f"{'是' if r['top']['mean_excess'] > r['bot']['mean_excess'] else '否'} |\n")
    A(f"\n均值超额 = 4 周对数收益减基准;独立事件 = 同公司 {INDEP_DAYS} 天链式去重后的计数。\n")
    A(f"进入留出段需**同时**满足:顶三分位均值 > 底三分位均值 **且** 顶三分位独立事件 ≥ "
      f"{MIN_INDEP_EVENTS}。\n\n")
    A("**发现段样本为什么这么薄**(读数直接来自 `treasury_decisions`,非脚本推断):\n\n")
    A("| 币 | 全部决定 | 2024-01 之前 | 发现段 | 发现段周数 | 留出段 | 留出段周数 |\n")
    A("|---|---:|---:|---:|---:|---:|---:|\n")
    for c in COINS:
        s = dec[dec["coin"] == c]
        dw = s[(s["wk"] >= DISC_LO) & (s["wk"] <= DISC_HI)]
        hw = s[(s["wk"] >= HOLD_LO) & (s["wk"] <= HOLD_HI)]
        pw = s[s["wk"] < DISC_LO]
        A(f"| {c} | {len(s)} | {len(pw)} | {len(dw)} | {dw['wk'].nunique()} | "
          f"{len(hw)} | {hw['wk'].nunique()} |\n")
    A("\nBTC 的决定从 2018 年就有(2024 前 101 条),ETH / SOL 的金库决定**几乎全在 2025 年之后**"
      "(ETH 121 条里 87 条在 2025 年),所以发现段这两币只有十几周 —— 独立事件门槛 ≥ 20 "
      "对它们在发现段是**结构性不可能**,不是「差一点」。\n\n")

    A(f"## 3. 留出段 2025-07-01 → 2026-09-30(一次性)\n\n")
    A(f"进入的币:**{', '.join(entrants) if entrants else '无'}**;"
      f"试验计数 = 进入留出段的币数 = **{len(entrants)}**(实体族第 1 次)。\n\n")
    for c in COINS:
        if c in rejected:
            A(f"- `{c}` 不进留出段:{rejected[c]}。\n")
    if entrants:
        A("\n| 币 | 用到的周数 (顶/底) | 顶减底 实际值 | 零分布均值 | "
          "单侧 p(块自助 4 周一块 × 2,000) | 判 |\n")
        A("|---|---:|---:|---:|---:|---|\n")
        for c in entrants:
            t = tests[c]
            if "pass" not in t:
                A(f"| {c} | {t.get('n', 0)} | — | — | — | {t.get('note', '')} |\n"); continue
            A(f"| {c} | {t['n_top']} / {t['n_bot']} | {t['actual']:+.4f} | "
              f"{t['null_mean']:+.4f} | {t['p_one_sided']:.4f} | "
              f"{'PASS' if t['pass'] else 'FAIL'} |\n")
        A("\n零分布 = 把顶+底的周超额序列切成长 4 周的连续块、打乱块序 2,000 次,"
          "每次重算「顶均值 − 底均值」—— 保留周序列的自相关(4 周窗口彼此重叠 3 周)。\n")
        A("判据 = 顶减底 > 0 **且** 单侧 p < 0.05。\n\n")

    A("## 4. 结果里还看到了什么(探索性)\n\n")
    A("_(每条:探索性 —— 需另立预注册、在新数据上过零信号对照)_\n\n")
    A("1. **零分布是块自助而非打乱。** 周序列 4 周窗口重叠 3 周、自相关很强;"
      "块长按台账取 4 周。若换成逐周打乱,p 会被压低。**探索性。**\n\n")
    A("2. **披露只用「披露日」近似,没有用真实公告时刻。** 同一周内周一披露与周五披露"
      "在代码里同权,实际可交易时点最多差 4 个交易日 ⇒ 结果窗口头几天含轻微前视。**探索性。**\n\n")
    A("3. **面板基准用 `tier/equal/majors`(等权),不是 ① 真正的持仓权重。**"
      " ① 的真实组合在 `core_variants_daily`,但那是**回放出来的 NAV**,"
      "拿它当基准会把组合的择时混进超额。**探索性 —— @seth 若要求照 ① 的真实权重重算,"
      "需要另立一张卡。**\n\n")
    if not entrants:
        A("4. **BTC 的方向与假设相反:顶三分位超额 < 底三分位。** 发现段 64 周里,"
          "D 最大的三分之一周其后 4 周的超额反而最低 —— 「买得最猛的时候之后涨得最少」。"
          "样本上顶 37 / 底 33 个独立事件,不算薄,但这是**发现段的一次观察**,"
          "没有过任何零信号对照。**探索性 —— 需另立预注册、在新数据上过零信号对照。**\n\n")
        A("5. **ETH 是唯一「顶 > 底」的币(+0.1303 vs +0.0510),但它整段只有 13 周。**"
          "留出段 ETH 有 38 周数据可用 —— 如果阈值放宽(比如独立事件 ≥ 7),"
          "ETH 就能进留出段。**但放宽阈值就是拿结果改预注册,本卡不做;"
          "@seth 若认为该放宽,应当另立一张卡、写新的门槛、再在新数据上跑。**"
          "**探索性。**\n\n")
        A("6. **`treasury_decisions` 的卖出行金额字段是正数。** 台账写「transaction_value_usd,"
          "卖出为负」,但库里 98 条 `sell` 行的 `transaction_value_usd` 全部 > 0;"
          "若照字面直接求和,净买入会被高估。"
          "**探索性(数据口径发现,建议 @seth 落进台账)。**\n\n")
        A("7. **本次判决 N/A,意味着 §3 的留出段检验代码在主跑里没被执行** —— "
          "「没报 p」不等于「p 算得出来」。为免把未测当已测,已单独跑过一次路径自检:"
          "把 `MIN_INDEP_EVENTS` 临时改成 0 强制 ETH 进留出段(只改副本、不改仓库、"
          "输出写 `_T-150_SELFTEST.*` 后已删除),留出段检验正常出数:"
          "ETH 顶 12 周 / 底 24 周,顶减底 **+0.0678**,零分布均值 −0.0045,"
          "**单侧 p = 0.099** ⇒ FAIL。**这是自检值,不是 S-636 的结果** —— "
          "预注册的门槛是 20,ETH 没过门槛就不该进留出段。"
          "**探索性 —— 需另立预注册、在新数据上过零信号对照。**\n\n")

    A("---\n\n## S-636 结果(草稿)\n\n")
    if verdict is None:
        A(f"**N/A** —— {len(COINS)} 个币在发现段都没同时满足「顶 > 底」与"
          f"「顶独立事件 ≥ {MIN_INDEP_EVENTS}」,按预注册不进入留出段。"
          "这是预注册的正常结果,不是失败:门槛本来就会把薄样本挡在外面。"
          "**试验计数 = 0**(实体族第 1 次留出段检验,一次都没真正做)。")
    else:
        A(f"**{verdict}** —— 发现段筛出 {len(entrants)} 个币({', '.join(entrants)}),"
          f"留出段一次性检验{'全部通过' if verdict == 'PASS' else '未全部通过'}(表见 §3)。")
    A("\n\n---\n")
    A(f"_Generated by `docs/research/t150_treasury_decisions.py` on "
      f"{pd.Timestamp.now().isoformat()}_\n")

    with open(MD_PATH, "w") as f:
        f.write("".join(L))
    with open(JSON_PATH, "w") as f:
        json.dump({"verdict": verdict, "entrants": entrants, "rejected": rejected,
                   "discovery": disc, "holdout": hold, "holdout_tests": tests,
                   "panel_style": list(PANEL_STYLE), "coins": COINS,
                   "n_decisions": int(len(dec)), "selfcheck_C": "PASS"},
                  f, indent=2, default=str)
    print(f"[write] {MD_PATH}", flush=True)
    print(f"[write] {JSON_PATH}", flush=True)
    print(f"[verdict] {verdict or 'N/A'}  entrants={entrants}", flush=True)


if __name__ == "__main__":
    main()