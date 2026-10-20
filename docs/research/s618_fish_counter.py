#!/usr/bin/env python3
"""S-618「大鱼」计数器 —— 本地 Python 复现 docs/research/s618_fish_count.sql 的口径。

Seth 10-20 的 SQL(§Seth-1020i)给的是 286 条 / 13,396 命中 / 147 个名字。
本文件把同一条 SQL 逐字翻译成 pandas,用来在没有任意 SQL 执行通道的环境里
(publishable key 只读,PostgREST 不接受 window function)拿到同样的三个数。

口径(与 SQL 全文一一对应):
  宇宙  ohlcv_daily where source='binance_hist' and symbol not in ('USDC','BTCDOM','DEFI')
  rn    该名按 trade_date 排的第几根日线(1 起)
  adv30 close*volume 的 30 行滚动均值,**含当天**(rows between 29 preceding and current row)
  fmax  之后 120 行里最高的 close(rows between 1 following and 120 following),取不到就空
  命中  rn>=220 且 adv30>=5e6 且 2020-03-01<=d<=2026-06-20 且 fmax>=3*c
  并鱼  同名的命中按 rn 排序,**与上一个命中**相隔 <=30 根就并进同一条鱼(链式)

链式 vs 与起点比:一段 100 根长的连续命中,链式算 1 条,起点比会切成 4 条。
这就是 672 与 286 的差(见 __main__ 的 --anchor 反例)。

读库只用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'],不读 .env、不打印 key。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("env SUPABASE_URL / SUPABASE_KEY missing")

DEFAULT_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t151b/ohlcv_binance_hist.csv")
EXCLUDE = ("USDC", "BTCDOM", "DEFI")
COLUMNS = ["symbol", "trade_date", "close", "volume"]


def fetch_binance_hist(cache: Path = DEFAULT_CACHE, refresh: bool = False) -> pd.DataFrame:
    """拉 binance_hist 的 4 列(约 35 万行);落缓存,refresh=True 强制重取。"""
    if cache.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["trade_date"])
    import urllib.request

    cache.parent.mkdir(parents=True, exist_ok=True)
    hdr_base = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    rows: list[pd.DataFrame] = []
    step = 1000  # db 的 max-rows=1000,超过就被截;只能 1000 一页地翻
    start = 0
    total = int(fetch_binance_hist.total or 0) if hasattr(fetch_binance_hist, "total") else None
    while True:
        q = (
            "/rest/v1/ohlcv_daily?select=" + ",".join(COLUMNS) + "&source=eq.binance_hist"
            f"&order=symbol.asc,trade_date.asc&offset={start}&limit={step}"
        )
        req = urllib.request.Request(SUPABASE_URL + q, headers=hdr_base)
        batch = pd.read_json(urllib.request.urlopen(req, timeout=180))
        rows.append(batch)
        start += len(batch)
        if len(batch) < step:
            break
    df = pd.concat(rows, ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df[~df["symbol"].isin(EXCLUDE)].sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """加 rn / adv30 / fmax 三列(窗口全部是「按行」,不是按日历)。

    全部走 numpy 循环而不是 pandas.rolling —— rolling 的 min_periods 与 SQL 的
    「开头不足 30 行也给部分均值」不同,这里显式对齐 SQL:
      adv30[i] = mean(dv[max(0,i-29) : i+1])
      fmax[i]  = max(c[i+1 : i+121])   (不足 120 根 -> NaN,和 SQL 窗口一致)
    """
    n = len(df)
    rn = np.empty(n, dtype=np.int64)
    adv30 = np.full(n, np.nan)
    fmax = np.full(n, np.nan)
    c = df["close"].to_numpy(dtype=float)
    dv = c * df["volume"].to_numpy(dtype=float)
    sym = df["symbol"].to_numpy()
    bounds = np.flatnonzero(np.r_[True, sym[1:] != sym[:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:]):
        seg_c, seg_dv = c[a:b], dv[a:b]
        seg_n = b - a
        rn[a:b] = np.arange(1, seg_n + 1)
        csum = np.concatenate(([0.0], np.cumsum(seg_dv)))
        for i in range(seg_n):
            lo = max(0, i - 29)
            adv30[a + i] = (csum[i + 1] - csum[lo]) / (i - lo + 1)
            if i + 121 <= seg_n:
                fmax[a + i] = seg_c[i + 1 : i + 121].max()
    out = df.copy()
    out["rn"] = rn
    out["adv30"] = adv30
    out["fmax"] = fmax
    return out


def hits_of(df: pd.DataFrame, d0: str = "2020-03-01", d1: str = "2026-06-20",
            adv_min: float = 5e6, mult: float = 3.0, rn_min: int = 220) -> pd.DataFrame:
    m = (df["rn"] >= rn_min) & (df["adv30"] >= adv_min) & df["fmax"].notna() & (df["fmax"] >= mult * df["close"])
    m &= (df["trade_date"] >= pd.Timestamp(d0)) & (df["trade_date"] <= pd.Timestamp(d1))
    return df.loc[m, ["symbol", "rn", "trade_date"]].sort_values(["symbol", "rn"]).reset_index(drop=True)


def fish_of(hits: pd.DataFrame, gap: int = 30, anchor: bool = False) -> np.ndarray:
    """给每条鱼编号。anchor=False 链式(与上一个命中比);anchor=True 与鱼的起点比(反例)。

    返回:anchor=False -> 每行 0/1 的 newfish;anchor=True -> 从 0 起的鱼编号。
    """
    rn = hits["rn"].to_numpy()
    sym = hits["symbol"].to_numpy()
    if len(rn) == 0:
        return np.zeros(0, dtype=np.int64)
    prev_rn = np.r_[-(10**9), rn[:-1]]
    same = np.r_[False, sym[1:] == sym[:-1]]
    newfish = (rn - np.where(same, prev_rn, -(10**9)) > gap).astype(np.int64)
    if not anchor:
        return newfish
    fid = np.zeros(len(rn), dtype=np.int64)
    cur, start = -1, 0
    for i in range(len(rn)):
        if newfish[i] or rn[i] - start > gap or sym[i] != sym[i - 1 if i else i]:
            cur += 1
            start = rn[i]
        fid[i] = cur
    return fid


def count(hits: pd.DataFrame, anchor: bool = False) -> dict:
    f = fish_of(hits, anchor=anchor)
    return {"fish": int(f.sum() if not anchor else f.max() + 1), "hits": int(len(hits)),
            "symbols": int(hits["symbol"].nunique())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    a = ap.parse_args()
    df = annotate(fetch_binance_hist(Path(a.cache), refresh=a.refresh))
    hits = hits_of(df)
    chain = count(hits, anchor=False)
    anch = count(hits, anchor=True)
    print(f"bars={len(df)} symbols={df['symbol'].nunique()}")
    print(f"chain(链式,   与 SQL 同) fish={chain['fish']:>7} hits={chain['hits']:>7} symbols={chain['symbols']:>4}")
    print(f"anchor(反例:  与起点比)   fish={anch['fish']:>7} hits={anch['hits']:>7} symbols={anch['symbols']:>4}")


if __name__ == "__main__":
    main()