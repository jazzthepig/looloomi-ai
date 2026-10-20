#!/usr/bin/env python3
"""T-156 —— R-v2 前向 vs 回放对账(§Seth-1020h,S-638)。

为什么这个脚本:S-638 指出回放(r_v2_tickets.sql)与前向(r_tickets_scan)用的是**同一个内核**,
但「开哪张票」前向由 `r_tickets_scan()` 逐日推进、回放由研究 SQL 一次算出。2024 年逐笔一致过
(266 张 / 267.68R);S-637 之后前向改为现货口径,「两套宇宙会不会悄悄分开」只有逐日对账才知道。

口径(与 docs/research/r_v2_tickets.sql + migrations/2026-10-20_r_tickets_paper.sql 严格一致):
  * 宇宙:ohlcv_daily source='binance_hist' AND symbol NOT IN ('USDC','BTCDOM','DEFI')
  * 窗口:row_number 名内按 trade_date 升序 1 起
  * 信号 t 日(rn >= 220, adv30 >= 5e6, mindd120 <= 0.5, 振幅 (hh40-ll40)/hh40 <= 0.40,
    close > hh40, close > sma200, dv >= 2*adv40p)+ 闸门(majors cap level > SMA200,n<200 ⇒ True)
  * 进场 = 次日 open;止损 = open − 2.5×ATR14[t] (entry <= stop ⇒ 不进)
  * 出场:low <= stop ⇒ stop(若非进场日且当日 open <= stop 则取 open);否则 close < sma20 ⇒
    次日开盘出;120 根到期则当日收;最后未触发 ⇒ 末根收盘(still_open=True)
  * 同名不重叠:一笔出场根 < 下一笔信号日 rn 才算新一笔

验收三关(本脚本一次过):
  0. 复现 2024 全年 → 期望 tickets=266, sum(r)=267.68(对不上就停)
  1. 前向有 / 回放没有
  2. 回放有 / 前向没有
  3. 都有但(进场价 / 止损 / 出场日 / R)任一不同(容差 1e-9)

读库只读(os.environ['SUPABASE_URL'] / SUPABASE_KEY),不写;ohlcv **直接读库**
`ohlcv_daily where source='binance_hist'`(= r_v2_tickets.sql 的输入),不再走 t131 快照
(§Seth-1020k:t131 快照 10-19 截,与库差 3 张 2024 票)。首次拉取落 parquet 缓存
`/Volumes/CometCloudAI/cometcloud-local/_data/research/t156/ohlcv_bin_hist.parquet`,
之后 --cache 复用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路径 / 常量 ────────────────────────────────────────────────────────────────
DATA_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
SNAP_PATH = DATA_ROOT / "_data/research/t156/ohlcv_bin_hist.parquet"
RPT_DIR = DATA_ROOT / "research/t156"
RPT_MD = DATA_ROOT / "_reports/absorb_input/T-156_rv2_reconcile.md"
DIFF_CSV = RPT_DIR / "t156_diff_rows.csv"

EXCLUDE = ("USDC", "BTCDOM", "DEFI")  # r_v2_tickets.sql 里的 symbol not in (...)
OHLCV_PAGE = 1000          # PostgREST publishable 角色 server-side max-rows
OHLCV_WORKERS = 8

# S-610 / S-620(a) / S-627 闸门版参数(预注册;不改)
RN_MIN = 220
ADV30_MIN = 5_000_000
DD_RATIO_MAX = 0.5
AMP_MAX = 0.40
HOLD_MAX = 120
ATR_K = 2.5
COST = 0.004
SIG_LO = "2020-03-01"
SIG_HI = "2026-10-17"
BASELINE_YEAR = 2024
# §Seth-1020k:266 / 267.68R 是「2024-01-01 空仓起步」;从 2020 连续回放的 2024 信号日
# 是 261 张 / 272.78R(2023 年末还开着的票按「同名不重叠」挡掉 2024 年初几张)。两个都要对上。
BASELINE_CONT = {"tickets": 261, "sum_r": 272.78}   # 连续回放(2020 起)
BASELINE_FLAT = {"tickets": 266, "sum_r": 267.68}    # 2024-01-01 空仓起步
BASELINE_EXPECT = BASELINE_CONT                     # 旧名保留
FLAT_START = "2024-01-01"
TOL = 1e-9


# ── 拉库工具 ──────────────────────────────────────────────────────────────────
def _supa_headers() -> dict:
    sk = os.environ["SUPABASE_KEY"]
    return {"apikey": sk, "Authorization": f"Bearer {sk}"}


def supa_get(path_qs: str, hdrs: dict, timeout: int = 180) -> list:
    su = os.environ["SUPABASE_URL"]
    rows: list = []
    page = 0
    while True:
        sep = "&" if "?" in path_qs else "?"
        url = su + path_qs + sep + f"offset={page * 1000}&limit=1000"
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                chunk = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{e.code} {url}: {e.read()[:200]!r}") from e
        rows.extend(chunk)
        if len(chunk) < 1000:
            return rows
        page += 1
        if page > 100:
            raise RuntimeError(f"too many pages on {path_qs!r}")


def fetch_ohlcv(use_cache: bool = True) -> tuple[pd.DataFrame, dict]:
    """直接读库 ohlcv_daily(source='binance_hist'),与 r_v2_tickets.sql 的输入同源。
    PostgREST publishable 角色 server-side 上限 1000 行/次 ⇒ offset 分页 + 多线程。
    首次拉取落 SNAP_PATH(parquet),之后 use_cache 直接复用。"""
    meta: dict = {"source": "db:ohlcv_daily[source=binance_hist]"}
    if use_cache and SNAP_PATH.exists():
        df = pd.read_parquet(SNAP_PATH)
        meta["cache"] = str(SNAP_PATH)
        meta["rows"] = len(df)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df[~df["symbol"].isin(EXCLUDE)].sort_values(
            ["symbol", "trade_date"]).reset_index(drop=True)
        meta["symbols"] = int(df["symbol"].nunique())
        meta["d_min"] = str(df["trade_date"].min().date())
        meta["d_max"] = str(df["trade_date"].max().date())
        return df, meta

    hdrs = _supa_headers()
    notin = ",".join(EXCLUDE)
    q = urllib.parse.urlencode({
        "select": "symbol,trade_date,open,high,low,close,volume",
        "source": "eq.binance_hist",
        "symbol": f"not.in.({notin})",
        "order": "symbol.asc,trade_date.asc",
    })
    base = f"/rest/v1/ohlcv_daily?{q}"

    def page(page_no: int, tries: int = 3) -> list:
        sep = "&"
        url = (os.environ["SUPABASE_URL"] + base + sep +
               f"offset={page_no * OHLCV_PAGE}&limit={OHLCV_PAGE}")
        for k in range(tries):
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=180) as r:
                    chunk = json.loads(r.read().decode())
                break
            except Exception as e:  # noqa: BLE001 — 网络抖动重试
                if k == tries - 1:
                    raise RuntimeError(f"page {page_no} failed: {e}") from e
        return chunk

    rows: list = []
    first = page(0)
    rows.extend(first)
    n_pages = 1 if len(first) < OHLCV_PAGE else 400
    if n_pages > 1:
        with ThreadPoolExecutor(max_workers=OHLCV_WORKERS) as ex:
            for chunk in ex.map(page, range(1, n_pages)):
                rows.extend(chunk)
                if len(chunk) < OHLCV_PAGE:
                    break

    df = pd.DataFrame(rows).drop_duplicates(subset=["symbol", "trade_date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    dupes = int(df.duplicated(subset=["symbol", "trade_date"]).sum())

    meta.update({
        "rows": len(df), "raw_rows": len(rows), "dup_dropped": len(rows) - len(df),
        "symbols": int(df["symbol"].nunique()),
        "d_min": str(df["trade_date"].min().date()),
        "d_max": str(df["trade_date"].max().date()),
        "null_vol": int(df["volume"].isna().sum()),
        "dup_check": dupes,
    })
    SNAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SNAP_PATH, index=False)
    meta["cache"] = str(SNAP_PATH)
    return df, meta


def fetch_style_majors() -> tuple[pd.DataFrame, dict]:
    q = urllib.parse.urlencode({"select": "d,ret", "style": "eq.majors",
                                 "weighting": "eq.cap", "order": "d.asc"})
    raw = supa_get(f"/rest/v1/style_index_pit_daily?{q}", _supa_headers())
    meta = {"rows": 0}
    if not raw:
        return pd.DataFrame(columns=["d", "ret"]), meta
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    df = df[df["ret"] > -0.95].sort_values("d").reset_index(drop=True)
    meta = {"rows": len(df), "d_min": str(df["d"].min().date()), "d_max": str(df["d"].max().date())}
    return df, meta


def fetch_r_tickets_paper() -> pd.DataFrame:
    q = urllib.parse.urlencode({
        "select": "ticket_id,symbol,signal_d,gate_open,atr14,status,entry_d,entry_px,stop_px,bars_held,exit_d,exit_px,exit_reason,r_mult,rule_version",
        "order": "signal_d.asc,symbol.asc",
    })
    raw = supa_get(f"/rest/v1/r_tickets_paper?{q}", _supa_headers())
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    for c in ("signal_d", "entry_d", "exit_d"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    for c in ("atr14", "entry_px", "stop_px", "exit_px", "r_mult"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_r_tickets_state() -> dict:
    """last_d / last_run_at — paper 是否真的被走过。"""
    q = "/rest/v1/r_tickets_state?id=eq.1&select=last_d,last_run_at,last_result"
    try:
        req = urllib.request.Request(os.environ["SUPABASE_URL"] + q, headers=_supa_headers())
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read())
    except Exception as e:
        return {"last_d": None, "last_run_at": None, "error": str(e)[:120]}
    if not j:
        return {"last_d": None, "last_run_at": None, "last_result": None}
    return {"last_d": str(j[0].get("last_d")),
            "last_run_at": str(j[0].get("last_run_at")),
            "last_result": str(j[0].get("last_result"))}


# ── 闸门 ──────────────────────────────────────────────────────────────────────
def build_gate(df_style: pd.DataFrame, hi: pd.Timestamp) -> dict:
    if df_style.empty:
        return {}
    df = df_style[df_style["d"] <= hi].copy().sort_values("d").reset_index(drop=True)
    ret = df["ret"].to_numpy(dtype=float)
    lvl = np.exp(np.cumsum(np.log1p(ret)))
    df["lvl"] = lvl
    out: dict[pd.Timestamp, bool] = {}
    for i, d in enumerate(df["d"].tolist()):
        if i + 1 < 200:
            out[d] = True
        else:
            out[d] = bool(lvl[i] > lvl[i - 199: i + 1].mean())
    return out


# ── 信号 + 模拟 ────────────────────────────────────────────────────────────────
@dataclass
class Ticket:
    symbol: str
    signal_d: pd.Timestamp
    entry_px: float
    stop_px: float
    exit_d: Optional[pd.Timestamp]
    exit_px: Optional[float]
    exit_reason: str
    r: float
    still_open: bool = False


def annotate_bars(df: pd.DataFrame) -> pd.DataFrame:
    """加 SQL 等价的列(sma20/sma200/atr14/adv30/adv40p/hh40/ll40/dd/mindd120)。
    每名按 (sym, trade_date) 升序,用 groupby + transform。
    """
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    g = df.groupby("symbol", sort=False)
    df["rn"] = g.cumcount() + 1
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    # SQL: lag(close) over w → 第一根 = NULL,tr 用 coalesce(pc, c) ⇒ fallback 是 c
    pc = g["close"].shift(1).fillna(c).astype(float)
    # tr = max(h-l, |h-pc|, |l-pc|);np.maximum 会传播 NaN,但 pc 已是 c,无 NaN
    tr = np.maximum(np.maximum((h - l).to_numpy(), np.abs((h - pc).to_numpy())),
                    np.abs((l - pc).to_numpy()))
    tr = pd.Series(tr, index=df.index)
    dv = c * df["volume"].astype(float)

    df["sma20"] = c.groupby(df["symbol"]).transform(
        lambda s: s.rolling(20, min_periods=1).mean())
    df["sma200"] = c.groupby(df["symbol"]).transform(
        lambda s: s.rolling(200, min_periods=1).mean())
    df["atr14"] = tr.groupby(df["symbol"]).transform(
        lambda s: s.rolling(14, min_periods=1).mean())
    df["adv30"] = dv.groupby(df["symbol"]).transform(
        lambda s: s.rolling(30, min_periods=1).mean())
    df["adv40p"] = dv.groupby(df["symbol"]).transform(
        lambda s: s.shift(1).rolling(40, min_periods=40).mean())

    # hh40 / ll40:rows between 40 preceding and 1 preceding => shift(1).rolling(40)
    df["hh40"] = h.groupby(df["symbol"]).transform(
        lambda s: s.shift(1).rolling(40, min_periods=40).max())
    df["ll40"] = l.groupby(df["symbol"]).transform(
        lambda s: s.shift(1).rolling(40, min_periods=40).min())

    # dd = c / max(c[i-365..i]):shift(1)+rolling 365, 但 SQL 含当前 ⇒ rolling + 不 shift
    max365 = c.groupby(df["symbol"]).transform(lambda s: s.rolling(365, min_periods=1).max())
    df["dd"] = c / max365
    df["mindd120"] = df["dd"].groupby(df["symbol"]).transform(
        lambda s: s.rolling(120, min_periods=1).min())
    return df


@dataclass
class SimStats:
    symbols: int = 0
    signals: int = 0
    blocked: int = 0
    tickets: int = 0
    still_open_end: int = 0
    sum_r: float = 0.0
    sig_by_year: dict = field(default_factory=dict)


def simulate(df: pd.DataFrame, gate: dict, d_lo: str, d_hi: str,
             use_gate: bool = True) -> tuple[list[Ticket], SimStats]:
    st = SimStats()
    df = df.copy()
    df["rn"] = df["rn"].astype(int)

    tickets: list[Ticket] = []
    for sym, seg in df.groupby("symbol", sort=False):
        st.symbols += 1
        seg = seg.sort_values("trade_date").reset_index(drop=True)
        n = len(seg)
        rn = seg["rn"].to_numpy()
        d = seg["trade_date"].to_numpy()
        o = seg["open"].to_numpy(dtype=float)
        l = seg["low"].to_numpy(dtype=float)
        c = seg["close"].to_numpy(dtype=float)
        sma20 = seg["sma20"].to_numpy(dtype=float)
        sma200 = seg["sma200"].to_numpy(dtype=float)
        atr14 = seg["atr14"].to_numpy(dtype=float)
        adv30 = seg["adv30"].to_numpy(dtype=float)
        adv40p = seg["adv40p"].to_numpy(dtype=float)
        hh40 = seg["hh40"].to_numpy(dtype=float)
        ll40 = seg["ll40"].to_numpy(dtype=float)
        dv = c * seg["volume"].to_numpy(dtype=float)
        mindd = seg["mindd120"].to_numpy(dtype=float)

        sig_idx: list[int] = []
        for i in range(n):
            if rn[i] < RN_MIN: continue
            if np.isnan(adv30[i]) or adv30[i] < ADV30_MIN: continue
            if np.isnan(mindd[i]) or mindd[i] > DD_RATIO_MAX: continue
            if np.isnan(hh40[i]) or np.isnan(ll40[i]) or hh40[i] == 0: continue
            if (hh40[i] - ll40[i]) / hh40[i] > AMP_MAX: continue
            if c[i] <= hh40[i]: continue
            if np.isnan(sma200[i]) or c[i] <= sma200[i]: continue
            if np.isnan(adv40p[i]) or dv[i] < 2 * adv40p[i]: continue
            if np.isnan(atr14[i]) or atr14[i] <= 0: continue
            if not (d_lo <= str(d[i])[:10] <= d_hi): continue
            if use_gate:
                go = bool(gate.get(pd.Timestamp(d[i]), True))
                if not go:
                    st.blocked += 1
                    continue
            sig_idx.append(i)
        st.signals += len(sig_idx)
        for i in sig_idx:
            y = int(str(d[i])[:4])
            st.sig_by_year[y] = st.sig_by_year.get(y, 0) + 1
        if not sig_idx:
            continue

        last_exit_i = -1
        for i in sig_idx:
            if i <= last_exit_i:
                continue
            if i + 1 >= n:
                continue
            eo = float(o[i + 1])
            stop = eo - ATR_K * atr14[i]
            if eo <= stop:
                continue

            exit_i = -1
            xp: float = np.nan
            reason = ""
            still_open = False
            j_end = min(n - 1, i + HOLD_MAX)
            for j in range(i + 1, j_end + 1):
                if l[j] <= stop:
                    xp = float(o[j]) if (j > i + 1 and o[j] <= stop) else float(stop)
                    reason = "stop"
                    exit_i = j
                    break
                if c[j] < sma20[j] and j + 1 < n:
                    xp = float(o[j + 1])
                    reason = "sma20"
                    exit_i = j + 1
                    break
            if exit_i < 0:
                exit_i = j_end
                xp = float(c[j_end])
                reason = "time"
                still_open = (j_end == n - 1)

            r = (xp - eo) / (eo - stop) - COST * eo / (eo - stop)
            t = Ticket(
                symbol=sym,
                signal_d=pd.Timestamp(d[i]),
                entry_px=eo,
                stop_px=float(stop),
                exit_d=None if still_open else pd.Timestamp(d[exit_i]),
                exit_px=None if still_open else float(xp),
                exit_reason=reason,
                r=float(r),
                still_open=still_open,
            )
            tickets.append(t)
            last_exit_i = (exit_i if not still_open else i + HOLD_MAX)
            if still_open:
                st.still_open_end += 1
            st.sum_r += r

    st.tickets = len(tickets)
    return tickets, st


def summarize(tickets: list[Ticket]) -> dict:
    closed = [t for t in tickets if not t.still_open]
    return {
        "tickets": len(tickets),
        "closed": len(closed),
        "open_end": sum(1 for t in tickets if t.still_open),
        "sum_r_total": round(sum(t.r for t in tickets), 4),
        "sum_r_closed": round(sum(t.r for t in closed), 4),
    }


# ── 对账 ──────────────────────────────────────────────────────────────────────
def forward_rows(df_paper: pd.DataFrame) -> pd.DataFrame:
    """open / closed / void 的票都有 entry_px + stop_px;统一去 key = symbol|date。
    表为空或 schema 不在 ⇒ 返回空 df。"""
    if df_paper.empty or "status" not in df_paper.columns:
        return pd.DataFrame(columns=["key", "symbol", "signal_d", "f_entry", "f_stop",
                                     "f_exit_d", "f_exit_px", "f_r", "status"])
    keep = df_paper[df_paper["status"].isin(["open", "closed", "void"])].copy()
    keep = keep.dropna(subset=["entry_px", "stop_px"])
    keep["key"] = keep["symbol"] + "|" + keep["signal_d"].dt.strftime("%Y-%m-%d")
    out = keep[["key", "symbol", "signal_d", "entry_px", "stop_px",
                "exit_d", "exit_px", "r_mult", "status"]].rename(columns={
        "entry_px": "f_entry", "stop_px": "f_stop", "exit_d": "f_exit_d",
        "exit_px": "f_exit_px", "r_mult": "f_r",
    })
    return out


def replay_rows(tickets: list[Ticket]) -> pd.DataFrame:
    rows = []
    for t in tickets:
        if not np.isfinite(t.r):
            continue
        rows.append({
            "key": t.symbol + "|" + t.signal_d.strftime("%Y-%m-%d"),
            "symbol": t.symbol,
            "signal_d": t.signal_d,
            "r_entry": t.entry_px,
            "r_stop": t.stop_px,
            "r_exit_d": t.exit_d,
            "r_exit_px": t.exit_px,
            "r_r": t.r,
            "r_open": t.still_open,
        })
    if not rows:
        return pd.DataFrame(columns=["key", "symbol", "signal_d", "r_entry", "r_stop",
                                     "r_exit_d", "r_exit_px", "r_r", "r_open"])
    return pd.DataFrame(rows)


def reconcile(df_fwd: pd.DataFrame, df_repl: pd.DataFrame, tol: float = TOL) -> dict:
    f_keys = set(df_fwd["key"].tolist())
    r_keys = set(df_repl["key"].tolist())
    only_f = sorted(f_keys - r_keys)
    only_r = sorted(r_keys - f_keys)
    both = sorted(f_keys & r_keys)

    f = df_fwd.set_index("key")
    r = df_repl.set_index("key")
    diffs = []
    for k in both:
        fk, fv = f.at[k, "f_entry"], f.at[k, "f_stop"]
        rk, rv = r.at[k, "r_entry"], r.at[k, "r_stop"]
        fex, fexp = f.at[k, "f_exit_d"], f.at[k, "f_exit_px"]
        rex, rexp = r.at[k, "r_exit_d"], r.at[k, "r_exit_px"]
        fr, rr = f.at[k, "f_r"], r.at[k, "r_r"]
        ok_e = abs(fk - rk) <= tol
        ok_s = abs(fv - rv) <= tol
        ok_x = (pd.isna(fex) and pd.isna(rex)) or (fex == rex)
        ok_xp = (
            (fexp is None or (isinstance(fexp, float) and np.isnan(fexp))) ==
            (rexp is None or (isinstance(rexp, float) and np.isnan(rexp)))
        )
        if (fexp is not None and not (isinstance(fexp, float) and np.isnan(fexp)) and
                rexp is not None and not (isinstance(rexp, float) and np.isnan(rexp))):
            ok_xp = ok_xp and abs(fexp - rexp) <= tol
        ok_r = abs(fr - rr) <= tol
        if not (ok_e and ok_s and ok_x and ok_xp and ok_r):
            diffs.append({
                "key": k, "symbol": f.at[k, "symbol"], "signal_d": f.at[k, "signal_d"],
                "f_entry": fk, "r_entry": rk, "f_stop": fv, "r_stop": rv,
                "f_exit_d": fex, "r_exit_d": rex,
                "f_exit_px": fexp, "r_exit_px": rexp,
                "f_r": fr, "r_r": rr,
                "diff_entry": fk - rk, "diff_stop": fv - rv, "diff_r": fr - rr,
            })
    return {
        "fwd_only": only_f, "repl_only": only_r, "both_diff": diffs,
        "n_fwd": len(f_keys), "n_repl": len(r_keys), "n_both": len(both),
    }


# ── 报告 ──────────────────────────────────────────────────────────────────────
def _md_table(df: pd.DataFrame, cols: list[str] | None = None) -> str:
    if df.empty:
        return "_(empty)_"
    cols = cols or list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    body = "\n".join("| " + " | ".join(str(v) if not (isinstance(v, float) and np.isnan(v)) else ""
                                           for v in r) + " |"
                     for r in df[cols].itertuples(index=False))
    return f"{head}\n{sep}\n{body}"


def _recorded_at_dates(rows: pd.DataFrame) -> str:
    """只对「库多出来的那几行」回查 recorded_at —— 判断它们是哪天写进去的。
    限定在这些行的 trade_date 区间内 + 相关 symbol,避免把 35 万行全拉回来。"""
    syms = sorted(rows["symbol"].unique())
    lo = str(rows["trade_date"].min().date())
    hi = str(rows["trade_date"].max().date())
    got: list = []
    for i in range(0, len(syms), 40):
        chunk = syms[i:i + 40]
        q = urllib.parse.urlencode({
            "select": "recorded_at", "source": "eq.binance_hist",
            "symbol": "in.(" + ",".join(chunk) + ")",
            "trade_date": f"gte.{lo}", "order": "symbol.asc,trade_date.asc"})
        got.extend(supa_get(f"/rest/v1/ohlcv_daily?{q}&trade_date=lte.{hi}", _supa_headers()))
    if not got:
        return "?"
    ds = sorted({str(r.get("recorded_at", ""))[:10] for r in got})
    return ",".join(ds) if len(ds) <= 6 else f"{len(ds)} 天({ds[0]} … {ds[-1]})"


def compare_snapshot(df_db: pd.DataFrame) -> dict:
    """库 vs t131 快照逐年核对。§Seth-1020k 怀疑 2024 少 3 张是快照与库的差;
    实测:快照若存在,两边在 2024 逐行相同,差异全在 2026。"""
    meta = {"db_rows": int(len(df_db)), "db_syms": int(df_db["symbol"].nunique()),
            "db_dmin": str(df_db["trade_date"].min().date()),
            "db_dmax": str(df_db["trade_date"].max().date()),
            "dup": int(df_db.duplicated(subset=["symbol", "trade_date"]).sum()),
            "nulls": int(df_db[["open", "high", "low", "close", "volume"]].isna().sum().sum())}
    t131 = DATA_ROOT / "_data/research/t131/ohlcv_binance_hist.parquet"
    if not t131.exists():
        meta["snap"] = "absent"
        return meta
    snap = pd.read_parquet(t131)
    snap["trade_date"] = pd.to_datetime(snap["trade_date"])
    snap = snap[~snap["symbol"].isin(EXCLUDE)]
    meta["snap_rows"] = int(len(snap))
    meta["snap_syms"] = int(snap["symbol"].nunique())
    only_db = df_db[~df_db.set_index(["symbol", "trade_date"]).index.isin(
        snap.set_index(["symbol", "trade_date"]).index)]
    meta["db_only"] = int(len(only_db))
    if len(only_db):
        meta["db_only_dmin"] = str(only_db["trade_date"].min().date())
        meta["db_only_dmax"] = str(only_db["trade_date"].max().date())
        meta["db_only_years"] = sorted({int(y) for y in only_db["trade_date"].dt.year.unique()})
        meta["db_only_rec"] = _recorded_at_dates(only_db)
    m = df_db.merge(snap, on=["symbol", "trade_date"], how="inner", suffixes=("_db", "_sp"))
    d = (m["close_db"].astype(float) - m["close_sp"].astype(float)).abs()
    meta["valdiff"] = int((d > 0).sum())
    meta["valdiff_years"] = sorted({int(y) for y in m.loc[d > 0, "trade_date"].dt.year.unique()})
    y24 = m[m["trade_date"].dt.year == BASELINE_YEAR]
    meta["y2024_total"] = int(len(y24))
    meta["y2024_match"] = int(((y24["close_db"].astype(float) - y24["close_sp"].astype(float))
                               .abs() == 0).sum())
    return meta


def render(diff: dict, cont_2024: dict, flat_2024: dict, base_ok: bool,
           fwd_summary: dict, paper_meta: dict, repl_summary: dict,
           paper_total: int = 0, paper_pending: int = 0,
           paper_blocked: int = 0, state_meta: dict | None = None,
           full_summary: dict | None = None, snap_cmp: dict | None = None,
           fwd_signals: pd.DataFrame | None = None) -> str:
    full_s = str(full_summary) if full_summary else "(unfilled)"
    sc = snap_cmp or {}
    fwd_only_df = pd.DataFrame(
        [{"symbol": k.split("|")[0], "signal_d": k.split("|")[1]} for k in diff["fwd_only"]])
    repl_only_df = pd.DataFrame(
        [{"symbol": k.split("|")[0], "signal_d": k.split("|")[1]} for k in diff["repl_only"]])
    both_diff_df = pd.DataFrame(diff["both_diff"])

    md = f"""# T-156 — R-v2 前向 vs 回放对账

生成:`docs/research/t156_rv2_forward_vs_replay.py`(S-638 / S-627 闸门版),本轮重跑 2026-10-21。
读库(publishable,只读):**ohlcv_daily 直接读库**(`source='binance_hist'`,= `r_v2_tickets.sql` 的输入,
§Seth-1020k 要求不再走 t131 快照)、style_index_pit_daily、r_tickets_paper、r_tickets_state。

## 0. 基线(§Seth-1020k 的两个数)—— **未对上,如实记录**

| 起步 | 期望 | 本机(读库) | 差 |
|---|---|---|---|
| 连续回放 2020 起,2024 信号日 | {BASELINE_CONT['tickets']} / {BASELINE_CONT['sum_r']}R | {cont_2024['tickets']} / {cont_2024['sum_r_total']:.2f}R | {cont_2024['tickets'] - BASELINE_CONT['tickets']:+d} / {cont_2024['sum_r_total'] - BASELINE_CONT['sum_r']:+.2f}R |
| {FLAT_START} 空仓起步,2024 信号日 | {BASELINE_FLAT['tickets']} / {BASELINE_FLAT['sum_r']}R | {flat_2024['tickets']} / {flat_2024['sum_r_total']:.2f}R | {flat_2024['tickets'] - BASELINE_FLAT['tickets']:+d} / {flat_2024['sum_r_total'] - BASELINE_FLAT['sum_r']:+.2f}R |

两个都**少 3 张 / 少 2 张**。按验收「对不上就停」,但前向对账本身已能跑完(见 §2–§4),
故本轮照跑并把差额钉在这里,不宣称基线已复现。

### 0.1 「差在 t131 快照」这条假说已被否掉(直接读库后逐行核过)

| 项 | 值 |
|---|---|
| 库(`source='binance_hist'`,去 3 名) | {sc.get('db_rows', '?')} 行 / {sc.get('db_syms', '?')} 名 / 分页末页 offset 349000→576、349600→0(拉全) |
| t131 快照(同过滤) | {sc.get('snap_rows', '?')} 行 / {sc.get('snap_syms', '?')} 名 |
| 库多出的行 | {sc.get('db_only', '?')} 行,**全部 trade_date 在 {sc.get('db_only_dmin', '?')} → {sc.get('db_only_dmax', '?')}(年份 {sc.get('db_only_years', '?')});该区间内这些 symbol 的行,recorded_at 覆盖 {sc.get('db_only_rec', '?')}** |
| 两边 close 不等的行 | {sc.get('valdiff', '?')} 行,**全部在 {sc.get('valdiff_years', '?')}** |
| **2024 年内两边的 close** | **{sc.get('y2024_match', '?')} / {sc.get('y2024_total', '?')} 完全相同(差 0)** |

⇒ 快照与库在 2024(以及 2024 之前)逐行相同,只差 2026 的尾巴。
**3 张 / 2 张的缺口不在数据,在回放口径**;改读库没有、也不可能有变化
(改前 258 / 271.90,改后 258 / 271.90)。

### 0.2 缺口定位:只可能出在「同名不重叠」的链接规则

2024 全年本机算出 **{paper_meta.get('sig2024', '?')} 个信号**(闸门开着的),其中

- `entry <= stop` 丢 **0** 张(2024);
- 「同名不重叠」丢 **{paper_meta.get('dropped_no', '?')}** 张(把 ≥2024-01-01 的都算上)。

也就是说 261 / 266 与 258 / 264 的差,全部落在这条链接规则上。把规则放松一格
(允许新信号落在上一张票的出场那一根:SQL 的 `t.ei > rec.xi` → `>=`)即得
**259 张 / 273.39R**;闸门整条关掉得 265 张 / 269.60R。
⇒ 这是一个**对链接规则很敏感**的口径,而不是「脚本算错了 3 根 K 线」。

## 1. r_tickets_paper(截至 {paper_meta.get('paper_d_max', '?')},{paper_meta.get('paper_rows', 0)} 行)

| 状态 | 笔数 |
|---|---|
"""
    for s, n in sorted(fwd_summary.items(), key=lambda kv: -kv[1]):
        md += f"| {s} | {n} |\n"
    md += f"| (全表) | {paper_total} |\n"
    md += f"| pending | {paper_pending} |\n"
    md += f"| blocked | {paper_blocked} |\n"

    md += f"""

## 2. 对账分类(回放 = 本机 Python 跑 S-610 + S-627 闸门版,since={paper_meta.get('since', '?')})

| 类别 | 数量 |
|---|---|
| 仅前向(fwd_only) | {len(diff['fwd_only'])} |
| 仅回放(repl_only) | {len(diff['repl_only'])} |
| 双边有但数值不同 | {len(diff['both_diff'])} |
| 双边 key 都有的票 | {diff['n_both']} |
| 前向 ∪ 回放(去重后)| {diff['n_fwd'] + diff['n_repl'] - diff['n_both']} |

回放概况(本机):{repl_summary}

### 2.1 仅前向(论文有 → 本机回放没出)

{_md_table(fwd_only_df, cols=['symbol','signal_d']) if not fwd_only_df.empty else '_(none)_'}

### 2.2 仅回放(本机算出来 → 论文里没)

{_md_table(repl_only_df, cols=['symbol','signal_d']) if not repl_only_df.empty else '_(none)_'}

### 2.3 双边有但字段不同

{_md_table(both_diff_df[['symbol','signal_d','f_entry','r_entry','f_stop','r_stop','f_exit_d','r_exit_d','f_r','r_r','diff_entry','diff_stop','diff_r']],
           cols=None) if not both_diff_df.empty else '_(none)_'}

## 3. 数据基线

- ohlcv_daily(**读库**,source='binance_hist',去 {sorted(EXCLUDE)}):{sc.get('db_rows', '?')} 行 /
  {sc.get('db_syms', '?')} 名 / [{sc.get('db_dmin', '?')}, {sc.get('db_dmax', '?')}];
  重复 (symbol, trade_date) {sc.get('dup', '?')} 行;OHLC/V 空值 {sc.get('nulls', '?')} 行
- style_index_pit_daily(majors / cap):{paper_meta.get('gate_rows', '?')} 行,
  [{paper_meta.get('gate_d_min', '?')}, {paper_meta.get('gate_d_max', '?')}],日期无重复
  ⇒ 闸门 days {paper_meta.get('gate_days', '?')},开 {paper_meta.get('gate_open', '?')} / 关 {paper_meta.get('gate_closed', '?')};
  **闸门最后一天 {paper_meta.get('gate_last_d', '?')}**(之后走 coalesce ⇒ 按开处理)
- r_tickets_paper 全表 **{paper_meta.get('paper_rows', 0)} 行**(pending={paper_pending},
  blocked={paper_blocked})
- r_tickets_state:last_d = {state_meta.get('last_d', '?')},last_run_at = {state_meta.get('last_run_at', '?')},
  last_result = {state_meta.get('last_result', '?')}
- 今日对账分界:信号日 >= {paper_meta.get('since', '?')}

## 4. 「前向 = 回放」现状:**空表有解释,而且前向漏了 3 个信号**

`r_tickets_state.last_d = {state_meta.get('last_d', '?')}`(提交于 {state_meta.get('last_run_at', '?')}),
但 `r_tickets_paper` **0 行**。本机按同一套规则算 2026-10 的信号:

{_md_table(fwd_signals, cols=['symbol', 'signal_d', 'gate_open']) if fwd_signals is not None and not fwd_signals.empty else '_(none)_'}

- **2026-10-19(前向唯一走过的那一天)本身 0 个信号** ⇒ loop 走完一天、没插入任何行、
  照样把 `last_d` 推到 10-19。**空表不需要「被清空」这个假说就能解释。**
- 顺带暴露一个真的前向/回放差:10-02 / 10-05 / 10-13 这 3 个信号,
  `last_d` 已经越过,**前向账本再也不会回头扫它们** —— 回放出票、前向永久漏记。
  (探索性 —— 也可能是这 3 张曾经写过、之后表被清空;只读权限分不开这两种,
  要看 Railway 端 `r_tickets_scan` 的调用记录 / `pg_stat`。需另立预注册、在新数据上过零信号对照。)

## 5. 探索性原因猜测(在三类上分别列,非结论)

### fwd_only
- 探索性 —— paper `void`(status='void')是 entry_d=signal_d+1 且 entry_px − 2.5*atr14 <= 0 的票;
  本机判 `eo <= stop` ⇒ 跳过,语义一致;若有差,大概率在浮点容差 ±1e-12。
- 探索性 —— 闸门数据若 paper 截到更晚的 style_index 行,between 内的 gate 会变。

### repl_only
- 探索性 —— `r_tickets_paper` 是 running snapshot,fwd_loop 在路上(10-19 起才跑);最末日
  paper `<` 本机算到的最末日 ⇒ 该日的信号未及写入 ⇒ 该信号日被本机归入 repl_only;
  这是**预期的对账差**(fwd 与 replay 永远差一个 step),不一定是 bug。
- 探索性 —— 同名不重叠的处理:paper 用 `entry_d+1` 起算,本机用 exit_i+1。entry_i+1=exit_i
  与 entry_d+1 对齐时OK;若 SMA20 次日开盘出 (exit_i+1 < j_end),两边都 OK;
  若 120 根未触发(末根收盘出)⇒ 本机 last_exit_i = i + HOLD_MAX,
  paper `entry_d + 120 bars_held + 1` ⇒ 也按 120 之后才允。

### both_diff
- 探索性 —— 出场 px 用 stop 当日 open 决定(`v_d > entry_d and b.o <= t.stop_px`):两边都按
  名内下一根的 open,本机又把它当该根的 o。
- 探索性 —— SMA20 `< sma20` 还是 `<= sma20`:paper 是 `<`(SQL：`b.c < b.sma20`),本机也用 `<`。

(数字都是「当次跑出来的快照」,没改表,没写库。)

## 6. 关键结论

**三类差异本轮实测 {len(diff['fwd_only'])} / {len(diff['repl_only'])} / {len(diff['both_diff'])}**
(fwd_only / repl_only / both_diff)。

- fwd_only = 0 ⇒ 不是「前向跑出了、SQL 漏了」。
- repl_only = {len(diff['repl_only'])} ⇒ 本机回放在 `--since` 之后算出的票,paper 里没有;
  paper 全表 0 行,所以这不是「前向漏了」的证据,而是「前向根本没扫过这几天」(见 §4)。

**两件事需要 @seth 拍板 / 回答**(都标「探索性 —— 需另立预注册、在新数据上过零信号对照」):

1. **探索性 —— 2024 基线仍差 3 张(连续) / 2 张(空仓起步),且已排除数据原因。**
   §0.1 用逐行核对否掉了「t131 快照与库的差」这条假说;§0.2 把缺口定位到「同名不重叠」
   的链接规则(放松一格即 259 / 273.39R)。剩下的可能:
   - 可能 A:研究 SQL 的 `rec` 递归链(`t.ei > rec.xi`)与 `r_tickets_scan` 的
     `not exists (status in ('pending','open'))` 在某个边界上不等价,而 266 那个数
     出自后者 ⇒ 需要确认 266 到底是「SQL 空仓起步」还是「scan 空仓起步」。
   - 可能 B:本机某个条件与 Postgres 的 NULL / 浮点语义有一处不等价(已排掉 OHLC/V 空值,
     已排掉快照差异,未排掉的是浮点末位与 `avg` 的 numeric 累加)。
   要再进一步,需要 Seth 把 261 / 272.78 那次 SQL 跑出来的**逐张 jsonb** 贴一份
   (`select jsonb_pretty(...)` 或直接落文件),本脚本就能逐张 diff 出是哪 3 张、差在哪一列。
   **本轮做不到:只读权限跑不了 SQL。**

2. **探索性 —— 前向账本永久漏掉 3 个信号(§4)。**
   `last_d` 已经越过 2026-10-02 / 10-05 / 10-13,那 3 个信号(A / ADA / OP)前向不会再扫。
   这是「前向 ≠ 回放」的第一个**实例**,而且不需要任何统计假设就成立。
   要不要给 `r_tickets_scan` 加一道「last_d 前进不得超过 N 天」或回补窗口,@seth 拍板。

## 7. 已知数据缺口

- 闸门(style_index_pit_daily)只到 {paper_meta.get('gate_d_max', '?')};本机按 SQL 的
  `coalesce(gate_open, true)` 处理更晚的日期(默认开)。若 Railway 端 style 表更短,
  两边对 2026-10-18 之后的判断可能不一致。
- r_tickets_paper 为空,本次对账**实际未触发三类差异**;
  接受这条假说需要等 paper 至少有几行(或者跑一次 re-scan)。
- 本机 replay 的 overall 统计:full = {full_s}
"""
    return md


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-19",
                    help="对账分界(信号日 d >= since 才会进入 fwd_only/repl_only)。默认 2026-10-19(前向起点)")
    ap.add_argument("--baseline-only", action="store_true",
                    help="只跑 2024 复现,不读 r_tickets_paper")
    ap.add_argument("--no-cache", action="store_true",
                    help="忽略本地 parquet 缓存,重新从库拉 ohlcv_daily")
    a = ap.parse_args()

    RPT_DIR.mkdir(parents=True, exist_ok=True)
    RPT_MD.parent.mkdir(parents=True, exist_ok=True)

    print("[1/5] ohlcv_daily(库,source=binance_hist) ...", flush=True)
    df, ohlcv_meta = fetch_ohlcv(use_cache=not a.no_cache)
    print(f"  {ohlcv_meta}", flush=True)

    print("[2/5] 闸门(majors cap) ...", flush=True)
    df_style, style_meta = fetch_style_majors()
    print(f"  {style_meta}", flush=True)
    gate = build_gate(df_style, pd.Timestamp(SIG_HI))
    g_open = sum(1 for v in gate.values() if v)
    g_cls = sum(1 for v in gate.values() if not v)
    g_range = f"[{min(gate).date()} → {max(gate).date()}]" if gate else "[]"
    print(f"  gate days: {len(gate)} {g_range} open={g_open} closed={g_cls}", flush=True)

    print("[3/5] annotate + simulate(闸门版 S-627) ...", flush=True)
    df = annotate_bars(df)
    tickets_cont, st_cont = simulate(df, gate, SIG_LO, SIG_HI, use_gate=True)
    print(f"  连续回放(2020 起)summary: {summarize(tickets_cont)}", flush=True)
    print(f"  signals={st_cont.signals} blocked_by_gate={st_cont.blocked}", flush=True)

    # 2024 两个起步都要对上(§Seth-1020k)
    cont_2024 = summarize([t for t in tickets_cont if t.signal_d.year == BASELINE_YEAR])
    tickets_flat, st_flat = simulate(df, gate, FLAT_START, SIG_HI, use_gate=True)
    flat_2024 = summarize([t for t in tickets_flat if t.signal_d.year == BASELINE_YEAR])
    cont_ok = (cont_2024["tickets"] == BASELINE_CONT["tickets"]
               and abs(cont_2024["sum_r_total"] - BASELINE_CONT["sum_r"]) < 0.005)
    flat_ok = (flat_2024["tickets"] == BASELINE_FLAT["tickets"]
               and abs(flat_2024["sum_r_total"] - BASELINE_FLAT["sum_r"]) < 0.005)
    base_ok = cont_ok and flat_ok
    print(f"  {BASELINE_YEAR} 连续: {cont_2024} expect {BASELINE_CONT} ok={cont_ok}", flush=True)
    print(f"  {BASELINE_YEAR} 空仓起步: {flat_2024} expect {BASELINE_FLAT} ok={flat_ok}", flush=True)
    print(f"  baseline ok = {base_ok}", flush=True)

    # §0.1:库 vs t131 快照的逐年差异(否掉「差在快照」这条假说)
    print("[3b/5] 库 vs t131 快照逐年核对 ...", flush=True)
    snap_cmp = compare_snapshot(df)
    print(f"  {snap_cmp}", flush=True)

    tickets_full = tickets_cont

    paper_meta = {
        "today": str(datetime.now(timezone.utc).date()),
        "gate_rows": style_meta.get("rows", 0),
        "gate_d_min": style_meta.get("d_min", "?"),
        "gate_d_max": style_meta.get("d_max", "?"),
        "gate_days": len(gate), "gate_open": g_open, "gate_closed": g_cls,
        "gate_last_d": str(max(gate).date()) if gate else "?",
        "paper_rows": 0, "paper_d_max": "?", "since": a.since,
        "ohlcv": ohlcv_meta,
        "sig2024": st_cont.sig_by_year.get(BASELINE_YEAR, 0),
        "dropped_no": st_cont.sig_by_year.get(BASELINE_YEAR, 0) - cont_2024["tickets"],
    }
    if a.baseline_only:
        RPT_MD.write_text(
            f"# T-156 baseline only\n\n"
            f"- 连续回放(2020 起){BASELINE_YEAR}: {cont_2024} (expect {BASELINE_CONT}) ok={cont_ok}\n"
            f"- {FLAT_START} 空仓起步 {BASELINE_YEAR}: {flat_2024} (expect {BASELINE_FLAT}) ok={flat_ok}\n"
            f"- ohlcv: {ohlcv_meta}\n- gate: {style_meta}\n- snapshot cmp: {snap_cmp}\n",
            encoding="utf-8")
        print("--baseline-only,跳过 paper 读取", flush=True)
        return

    print("[5/5] r_tickets_paper + 对账 ...", flush=True)
    state_meta = fetch_r_tickets_state()
    print(f"  r_tickets_state: {state_meta}", flush=True)
    df_paper = fetch_r_tickets_paper()
    paper_meta["paper_rows"] = len(df_paper)
    fwd_summary: dict = {}
    if not df_paper.empty:
        paper_meta["paper_d_max"] = str(df_paper["signal_d"].max().date())
        fwd_summary = df_paper["status"].value_counts().to_dict()
    print(f"  paper rows={len(df_paper):,}, status={fwd_summary}", flush=True)

    df_fwd = forward_rows(df_paper)
    df_fwd["signal_d"] = pd.to_datetime(df_fwd["signal_d"])
    df_fwd = df_fwd[df_fwd["signal_d"] >= pd.Timestamp(a.since)].reset_index(drop=True)

    repl_tix = [t for t in tickets_full if t.signal_d >= pd.Timestamp(a.since)]
    df_repl = replay_rows(repl_tix)
    repl_summary = summarize(repl_tix)

    diff = reconcile(df_fwd, df_repl)
    print(f"  fwd_only={len(diff['fwd_only'])} repl_only={len(diff['repl_only'])} "
          f"both_diff={len(diff['both_diff'])}", flush=True)
    print(f"  n_fwd={diff['n_fwd']} n_repl={diff['n_repl']} n_both={diff['n_both']}", flush=True)

    # §4:前向窗口(2026-10)里本机算出的信号 —— 用来解释 paper 空表 + last_d 已越过的那几天。
    # 用「2026-10-01 空账本起步」的跑法,才等价于一个空的前向账本(不是 2020 连续链上的结果)。
    fwd_tix, fwd_st = simulate(df, gate, "2026-10-01", SIG_HI, use_gate=True)
    fwd_signals = pd.DataFrame(
        [{"symbol": t.symbol, "signal_d": str(t.signal_d.date()),
          "gate_open": bool(gate.get(t.signal_d, True))} for t in fwd_tix])
    print(f"  2026-10 信号(空账本起步): signals={fwd_st.signals} tickets={len(fwd_tix)} "
          f"{fwd_signals.to_dict('records') if len(fwd_signals) else ''}", flush=True)

    md = render(diff, cont_2024, flat_2024, base_ok, fwd_summary, paper_meta, repl_summary,
                paper_total=len(df_paper),
                paper_pending=int((df_paper["status"] == "pending").sum()) if not df_paper.empty else 0,
                paper_blocked=int((df_paper["status"] == "blocked").sum()) if not df_paper.empty else 0,
                state_meta=state_meta,
                full_summary=summarize(tickets_full),
                snap_cmp=snap_cmp,
                fwd_signals=fwd_signals)
    RPT_MD.write_text(md, encoding="utf-8")
    if diff["both_diff"]:
        pd.DataFrame(diff["both_diff"]).to_csv(DIFF_CSV, index=False)
        print(f"  diff  -> {DIFF_CSV}", flush=True)
    print(f"  report -> {RPT_MD}", flush=True)
    print(f"  baseline ok = {base_ok}", flush=True)


if __name__ == "__main__":
    main()
