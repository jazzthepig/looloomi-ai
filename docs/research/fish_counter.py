"""T-154 / S-618 —— 公用「大鱼」计数器,三条 lane 共用。

参照台账 S-618 原文(2026-10-20 Seth 用同字面 SQL 在同库上跑出 286 条鱼,原记 287)。
任何 lane 的鱼计数器先对上这一条再往下算。

## S-618 原文

宇宙:
    source = 'binance_hist' 且 symbol ∉ {USDC, BTCDOM, DEFI},
    按 symbol 分区、按 trade_date 排,row_number() = rn。
每个 (symbol, d) 日:
    dv         = close × volume
    adv30      = avg(dv) over (rn-29 … rn)(行内,不是日历)
    fmax       = max(close) over (rn+1 … rn+120)(行内)
    合格日    = rn ≥ 220 AND adv30 ≥ 5e6 AND d ∈ [start, end] AND fmax ≥ 3 × close
命中日     = 合格日
同名合并   = 命中按 (symbol, rn asc) 排,与上一个命中相隔 ≤ 30 根就**并进同一条鱼**(链式,不是相对鱼的起点)。
鱼的起点    = 每条鱼第一个命中日的 trade_date。
鱼的峰值    = max(close) over [起点 rn … 最后一个命中日 rn + 120] 的最高收盘。

## 接口

panel = dict[str, dict] —— 已经是 S-618 宇宙过滤(去掉 USDC/BTCDOM/DEFI、源 = binance_hist)
        后、按 (symbol, trade_date) 升序排好,而且每条至少有 fields: 'd', 'c', 'vol'。
        'd' 是 ISO 字符串 'YYYY-MM-DD';'c' 是当日收盘;'vol' 是当日成交量。
        panel 不强制按月份切片,你只负责把面板交给函数,函数负责 n>=220 的滑窗门禁。

fish(panel, start, end) -> list[dict]:
    返回 [{'symbol', 'start_date', 'last_hit_date', 'n_hits', 'rn_first', 'rn_last',
           'peak_close', 'peak_close_date', 'peak_multiple'}, ...]

零分布、分位、A/B 比较照旧走 src.data.evaluation.apparatus 不在这里重写。

读库只用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'](publishable)。
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
import json
from collections import defaultdict
from datetime import date
from typing import Any

# ── 来自 S-618 原文,改一处都要回到 s618_fish_count.sql 对一下 ─────────────
EXCLUDED = {"USDC", "BTCDOM", "DEFI"}
SOURCE = "binance_hist"
RN_MIN = 220  # 该名第几根日线起才有资格
ADV30_USD = 5_000_000.0  # 30 日均成交额门槛
FWD_BARS = 120  # 命中:t 日之后 120 根内最高收盘 ≥ 3 × t 日收盘
HIT_RATIO = 3.0  # 3 倍
MERGE_BARS = 30  # 同名命中相隔 ≤ 30 根并进同一条鱼


def fetch_panel_supabase(start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    """从 Supabase `ohlcv_daily`(source = 'binance_hist')拉宇宙,按 symbol 返回日序行。

    行字典字段:
        'd'   'YYYY-MM-DD'
        'c'   float(close)
        'vol' float(volume)
        'rn'  1-based rank within symbol by trade_date asc(算 fish 时也会重排,这里方便 debug)

    拉到空就报错退出:鱼计数器必须拿到全量才能复现 286;半量会系统性少算。
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        sys.exit("env SUPABASE_URL / SUPABASE_KEY missing")
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}

    # 先拉一份 symbol 全表(分区前要知道哪些名活着),但用 select 限定列
    sym_rows: list[dict[str, Any]] = []
    page = 0
    while True:
        q = urllib.parse.urlencode({
            "select": "symbol,trade_date,close,volume,source",
            "source": "eq." + SOURCE,
            "symbol": "not.in.(" + ",".join(sorted(EXCLUDED)) + ")",
            "order": "symbol.asc,trade_date.asc",
            "limit": "1000",
            "offset": str(page * 1000),
        })
        req = urllib.request.Request(f"{url}/rest/v1/ohlcv_daily?{q}", headers=hdr)
        with urllib.request.urlopen(req, timeout=120) as r:
            chunk = json.loads(r.read().decode())
        sym_rows.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
        if page > 4000:
            break  # 400 万行上限自保
    # 按 symbol 分组
    by = defaultdict(list)
    for r in sym_rows:
        d = str(r["trade_date"])[:10]
        by[r["symbol"]].append({"d": d, "c": float(r["close"]), "vol": float(r["volume"])})
    for s in by:
        by[s].sort(key=lambda x: x["d"])
        for i, row in enumerate(by[s]):
            row["rn"] = i + 1
    return by


def _adv30(panel: list[dict[str, Any]], idx: int) -> float:
    """rolling 30 日均成交额(close * volume,含当日)。S-618 原文:`rows between 29 preceding and current row`。"""
    lo = max(0, idx - 29)
    s = 0.0
    n = 0
    for j in range(lo, idx + 1):
        s += panel[j]["c"] * panel[j]["vol"]
        n += 1
    return s / n if n else 0.0


def _fwd_max_close(panel: list[dict[str, Any]], idx: int) -> float:
    """t 日之后 120 根内最高收盘(t+1 … t+120 按行不是日历)。S-618:`rows between 1 following and 120 following`。"""
    hi = min(len(panel), idx + 121)
    out = 0.0
    for j in range(idx + 1, hi):
        c = panel[j]["c"]
        if c > out:
            out = c
    return out


def _chain_fish(rows: list[tuple[str, int, float]]) -> list[dict[str, Any]]:
    """rows = sorted (symbol, rn, close) 命中日(已按 (symbol, rn asc) 排)。
    链式并鱼:`rn - prev_rn ≤ MERGE_BARS` ⇒ 并进同一条鱼(是相对**上一个命中**,不是相对鱼起点)。
    返回 [{rn_first, rn_last, n_hits, first_close, last_close, local_peak_close} ...]
    峰值的最后定锚(从 rn_first 到 rn_last + FWD_BARS 的最大收盘)交给 fish() 负责,
    这里只保留足够并鱼的状态。
    """
    fish: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    prev_rn: int | None = None
    for sym, rn, c in rows:
        new_fish = prev_rn is None or rn - prev_rn > MERGE_BARS
        if new_fish:
            if cur is not None:
                fish.append(cur)
            cur = {"rn_first": rn, "rn_last": rn, "n_hits": 1,
                   "first_close": c, "last_close": c, "local_peak_close": c}
        else:
            assert cur is not None
            cur["rn_last"] = rn
            cur["n_hits"] += 1
            cur["last_close"] = c
            if c > cur["local_peak_close"]:
                cur["local_peak_close"] = c
        prev_rn = rn
    if cur is not None:
        fish.append(cur)
    return fish


def fish(panel: dict[str, list[dict[str, Any]]], start: str, end: str) -> list[dict[str, Any]]:
    """S-618「大鱼」计数。

    panel: 已按 (symbol, d) 升序且 symbol 不在 EXCLUDED 的 dict[symbol] = [rows]。
           若直接 fetch_panel_supabase() 来,字段都齐;若你手工构造,字段也得齐(d/c/vol/rn 可缺;
           没有 rn 时这里会重排)。
    start/end: ISO 'YYYY-MM-DD',与 s618_fish_count.sql 同字面。
    返回 list[dict]: 每个鱼一条,字段见模块 docstring。

    实现保真:
      - 命中:rn ≥ RN_MIN AND adv30 ≥ ADV30_USD AND d ∈ [start, end] AND fmax ≥ HIT_RATIO × close
      - 并鱼:链式,`rn - prev_rn ≤ MERGE_BARS` ⇒ 同条鱼
      - 起点:每条鱼第一个命中日的 trade_date
      - 峰值:last_hit rn + FWD_BARS 闭区间内最大收盘(锚到当根真的 panel 行的 trade_date)
    """
    out: list[dict[str, Any]] = []
    for sym, rows in panel.items():
        n = len(rows)
        if n < RN_MIN:
            continue
        # 没有 rn 就补
        if not rows or "rn" not in rows[0]:
            for i, r in enumerate(rows):
                r["rn"] = i + 1
        # 命中:rng 段内,逐行算 adv30 + fwd_max;命中攒 (rn, close)。
        hits: list[tuple[str, int, float]] = []
        for idx in range(n):
            r = rows[idx]
            # 日期窗:S-618 的 BETWEEN 按 trade_date 字符串字面;
            # 但 panel 是按 d 排好的,所以字符串字面比较就是日历序(ISO YYYY-MM-DD)。
            if not (start <= r["d"] <= end):
                continue
            if r["rn"] < RN_MIN:
                continue
            if _adv30(rows, idx) < ADV30_USD:
                continue
            fm = _fwd_max_close(rows, idx)
            if fm >= HIT_RATIO * r["c"]:
                hits.append((sym, r["rn"], r["c"]))
        if not hits:
            continue
        # 链式并鱼
        # 注意:_chain_fish 是给纯 (symbol, rn, close) 输入用的通用版,
        # 在本函数多 symbol 不会同时进来,这里 pan 按 sym 切,所以无歧义。
        for f in _chain_fish(hits):
            first = rows[f["rn_first"] - 1]
            last = rows[f["rn_last"] - 1]
            hi_n = min(n, last["rn"] + FWD_BARS)
            peak_c = 0.0
            peak_d = None
            # rn 是 1-based,rows 是 0-based python list
            for j in range(f["rn_first"] - 1, hi_n):
                rr = rows[j]
                if rr["c"] > peak_c:
                    peak_c = rr["c"]
                    peak_d = rr["d"]
            out.append({
                "symbol": sym,
                "start_date": first["d"],
                "last_hit_date": last["d"],
                "rn_first": f["rn_first"],
                "rn_last": f["rn_last"],
                "n_hits": f["n_hits"],
                "first_close": first["c"],
                "last_hit_close": last["c"],
                "peak_close": peak_c,
                "peak_close_date": peak_d,
                "peak_multiple": peak_c / first["c"],
            })
    out.sort(key=lambda f: (f["start_date"], f["symbol"]))
    return out


# ── 一行 CLI 形式(给自检和 lane 直接看) ─────────────────────────────────
def count_fish(start: str, end: str) -> dict[str, Any]:
    panel = fetch_panel_supabase(start, end)
    rows = fish(panel, start, end)
    syms = {f["symbol"] for f in rows}
    return {"fish": len(rows), "symbols": len(syms), "panel_rows": sum(len(v) for v in panel.values())}


if __name__ == "__main__":
    # 用法:python3 docs/research/fish_counter.py [start] [end]
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-03-01")
    ap.add_argument("--end", default="2026-06-20")
    args = ap.parse_args()
    r = count_fish(args.start, args.end)
    print(json.dumps(r, indent=2))
