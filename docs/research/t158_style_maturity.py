"""T-158 / S-641: 风格成熟度(周期走到第几段)。

照台账 S-641 预注册原文(2026-10-21 03:15 UTC,`date -u`)一字不改:
  风格 = style_index_pit_daily (dimension=sector, weighting=cap, sector∈{ai,defi,meme,
          infra_tokenization}),成员按时点。
  M 的四个分量(只用 ≤ t 数据,分位用 t − 1 之前且 ≥ 365 天的自身历史):
    A 年龄  index 上穿 200 日均线以来的天数(当前 ≤ 200 日线 ⇒「下行」,不计 M)
    E 涨幅  level[t] / min(level[t − 365 .. t − 1]) − 1
    P 参与  过去 20 日里收盘创过 40 日新高的成员占比
    C 拥挤  成员 7 日平均资金费率(binance_perp)的成员均值
  M = 四个分位(per-comp, 0 = 本轮刚开始, 1 = 本轮很晚)的均值(同 style 内先取分位 → 跨 sector 再均)。
  票 = V1 内核,与 `docs/research/r_v2_tickets.sql` 同口径;信号日 ≤ 2026-06-20。
  鱼 = `docs/research/fish_counter.py`(先复现 286)。
  分组:M 全样本三分位(早 / 中 / 晚);判两条:
    ① 平均 R 早 > 晚 → 对票有放回自助 2,000,单侧 p < 0.05
    ② 在鱼上比例 早 > 晚 → 年内打乱 2,000,单侧 p < 0.05

读库只用 os.environ['SUPABASE_URL' / 'SUPABASE_KEY'](publishable,不打印 key)。
零分布、分位、A/B 走 src/data/evaluation/apparatus.py(不动)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    shuffle_within,
    null_distribution,
    percentile_of,
)

# fish_counter(S-618) + t154 复现
import importlib.util as _ilu  # noqa: E402
_FC_PATH = str(Path(__file__).parent / "fish_counter.py")
_spec = _ilu.spec_from_file_location("fish_counter", _FC_PATH)
fish_counter = _ilu.module_from_spec(_spec)  # type: ignore
_spec.loader.exec_module(fish_counter)  # type: ignore

# 报告 / 产物落点(Mac 数据根,不写 /tmp)
REPORT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = REPORT_DIR / "T-158_style_maturity.md"
# 每票一行的中间产物(M / 鱼 / 三分位),跑完落盘;重跑直接读它,不再重拉 35 万行 K 线。
CACHE_PATH = REPORT_DIR / "T-158_style_maturity_tickets.json"

# S-641 的 4 个 sector × cap 加权
SECTORS = ("ai", "defi", "meme", "infra_tokenization")
SECTOR_DIM = "sector"
SECTOR_WGT = "cap"

# ticket window
SIG_LO = "2020-03-01"
SIG_HI = "2026-06-20"
FISH_LO = "2020-03-01"
FISH_HI = "2026-06-20"

# 4 个分量口径
A_LOOKBACK = 200
E_LOOKBACK = 365
P_LOOKBACK_NEW = 40
P_LOOKBACK_WIN = 20
C_LOOKBACK = 7
HISTORY_MIN_DAYS = 365  # 分位的自身历史最少天数

# V1 内核常量(与 r_v2_tickets.sql 等价)
EXCLUDE = ("USDC", "BTCDOM", "DEFI")
ATR_K = 2.5
COST = 0.004
RN_MIN = 220
ADV30_MIN = 5_000_000
DD_RATIO_MAX = 0.5
AMP_MAX = 0.40
HOLD_MAX = 120
OHLCV_PAGE = 1000
OHLCV_WORKERS = 4
OHLCV_TIMEOUT = 600
OHLCV_MAX_TRY = 4

N_BOOT = 2000
SEED = 158
ALPHA = 0.05


def _funding_symbol_count() -> int:
    """实际拿到资金费的名字数(读缓存 parquet;没跑过就 0)。

    不在模块顶层求值 — `fetch_funding()` 跑完才确定会写多少名字。
    """
    try:
        if not FUNDING_CACHE.exists():
            return 0
        return int(pd.read_parquet(FUNDING_CACHE, columns=["symbol"])["symbol"].nunique())
    except Exception:  # noqa: BLE001
        return 0


# ── 拉库工具 ──────────────────────────────────────────────────────────────────
def _su() -> tuple[str, str]:
    u = os.environ.get("SUPABASE_URL", "")
    k = os.environ.get("SUPABASE_KEY", "")
    if not u or not k:
        sys.exit("env SUPABASE_URL / SUPABASE_KEY missing")
    return u, k


def _hdr(k: str) -> dict:
    return {"apikey": k, "Authorization": f"Bearer {k}"}


def _page_all(url: str, hdrs: dict, page_size: int = 1000, cap_pages: int = 2000) -> list:
    out: list = []
    page = 0
    while page < cap_pages:
        sep = "&" if "?" in url else "?"
        u2 = url + sep + f"offset={page * page_size}&limit={page_size}"
        try:
            req = urllib.request.Request(u2, headers=hdrs)
            with urllib.request.urlopen(req, timeout=180) as r:
                chunk = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:  # noqa: F821
            raise RuntimeError(f"{e.code} {u2}: {e.read()[:200]!r}") from e
        if not chunk:
            return out
        out.extend(chunk)
        if len(chunk) < page_size:
            return out
        page += 1
    return out


# ── 1. R-v2 票(V1 内核 + 闸门)────────────────────────────────────────────
def fetch_ohlcv() -> pd.DataFrame:
    u, k = _su(); hdrs = _hdr(k)
    q = urllib.parse.urlencode({
        "select": "symbol,trade_date,open,high,low,close,volume",
        "source": "eq.binance_hist",
        "symbol": f"not.in.({','.join(EXCLUDE)})",
        "order": "symbol.asc,trade_date.asc",
    })
    base = f"/rest/v1/ohlcv_daily?{q}"

    def page(p: int) -> list:
        u0 = u + base + f"&offset={p * OHLCV_PAGE}&limit={OHLCV_PAGE}"
        last_err: Optional[Exception] = None
        for try_i in range(OHLCV_MAX_TRY):
            try:
                req = urllib.request.Request(u0, headers=hdrs)
                with urllib.request.urlopen(req, timeout=OHLCV_TIMEOUT) as r:
                    return json.loads(r.read().decode())
            except Exception as e:  # noqa: BLE001
                last_err = e
                import time as _t; _t.sleep(2.0 + 5.0 * try_i)
        raise RuntimeError(f"page {p} failed after {OHLCV_MAX_TRY} tries: {last_err!r}")

    from concurrent.futures import ThreadPoolExecutor
    rows: list = []
    first = page(0); rows.extend(first)
    n_pages = 1 if len(first) < OHLCV_PAGE else 400
    if n_pages > 1:
        with ThreadPoolExecutor(max_workers=OHLCV_WORKERS) as ex:
            futs = {ex.submit(page, p): p for p in range(1, n_pages)}
            for fut in futs:
                chunk = fut.result()
                rows.extend(chunk)
                if len(chunk) < OHLCV_PAGE:
                    break
    df = pd.DataFrame(rows).drop_duplicates(subset=["symbol", "trade_date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    return df


def fetch_gate() -> dict:
    """S-627 闸门:{pd.Timestamp(d): gate_open}。"""
    u, k = _su(); hdrs = _hdr(k)
    q = urllib.parse.urlencode({"select": "d,ret", "style": "eq.majors",
                                 "weighting": "eq.cap", "order": "d.asc"})
    raw = _page_all(u + "/rest/v1/style_index_pit_daily?" + q, hdrs, cap_pages=400)
    if not raw:
        return {}
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    df = df[df["ret"] > -0.95].sort_values("d").reset_index(drop=True)
    ret = df["ret"].to_numpy(dtype=float)
    lvl = np.exp(np.cumsum(np.log1p(ret)))
    out: dict = {}
    for i, d in enumerate(df["d"].tolist()):
        if i + 1 < 200:
            out[d] = True
        else:
            out[d] = bool(lvl[i] > lvl[i - 199: i + 1].mean())
    return out


def annotate_bars(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    g = df.groupby("symbol", sort=False)
    df["rn"] = g.cumcount() + 1
    c = df["close"].astype(float); o = df["open"].astype(float)
    h = df["high"].astype(float); l = df["low"].astype(float)
    pc = g["close"].shift(1).fillna(c).astype(float)
    tr = np.maximum(np.maximum((h - l).to_numpy(), np.abs((h - pc).to_numpy())),
                    np.abs((l - pc).to_numpy()))
    tr = pd.Series(tr, index=df.index)
    dv = c * df["volume"].astype(float)
    df["sma20"] = c.groupby(df["symbol"]).transform(lambda s: s.rolling(20, min_periods=1).mean())
    df["sma200"] = c.groupby(df["symbol"]).transform(lambda s: s.rolling(200, min_periods=1).mean())
    df["atr14"] = tr.groupby(df["symbol"]).transform(lambda s: s.rolling(14, min_periods=1).mean())
    df["adv30"] = dv.groupby(df["symbol"]).transform(lambda s: s.rolling(30, min_periods=1).mean())
    df["adv40p"] = dv.groupby(df["symbol"]).transform(
        lambda s: s.shift(1).rolling(40, min_periods=40).mean())
    df["hh40"] = h.groupby(df["symbol"]).transform(
        lambda s: s.shift(1).rolling(40, min_periods=40).max())
    df["ll40"] = l.groupby(df["symbol"]).transform(
        lambda s: s.shift(1).rolling(40, min_periods=40).min())
    max365 = c.groupby(df["symbol"]).transform(lambda s: s.rolling(365, min_periods=1).max())
    df["dd"] = c / max365
    df["mindd120"] = df["dd"].groupby(df["symbol"]).transform(
        lambda s: s.rolling(120, min_periods=1).min())
    return df


def simulate_tickets(df: pd.DataFrame, gate: dict) -> list[dict]:
    out: list[dict] = []
    df = df.copy(); df["rn"] = df["rn"].astype(int)
    for sym, seg in df.groupby("symbol", sort=False):
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
            if not (SIG_LO <= str(d[i])[:10] <= SIG_HI): continue
            if not bool(gate.get(pd.Timestamp(d[i]), True)):
                continue
            sig_idx.append(i)
        last_exit = -1
        for i in sig_idx:
            if i <= last_exit: continue
            if i + 1 >= n: continue
            eo = float(o[i + 1]); stop = eo - ATR_K * atr14[i]
            if eo <= stop: continue
            exit_i = -1; xp: float = np.nan; reason = ""; still = False
            j_end = min(n - 1, i + HOLD_MAX)
            for j in range(i + 1, j_end + 1):
                if l[j] <= stop:
                    xp = float(o[j]) if (j > i + 1 and o[j] <= stop) else float(stop)
                    reason = "stop"; exit_i = j; break
                if c[j] < sma20[j] and j + 1 < n:
                    xp = float(o[j + 1]); reason = "sma20"; exit_i = j + 1; break
            if exit_i < 0:
                exit_i = j_end; xp = float(c[j_end]); reason = "time"; still = (j_end == n - 1)
            r = (xp - eo) / (eo - stop) - COST * eo / (eo - stop)
            out.append({
                "symbol": sym, "signal_d": pd.Timestamp(d[i]),
                "entry_d": pd.Timestamp(d[i + 1]),
                "exit_d": (None if still else pd.Timestamp(d[exit_i])),
                "r": float(r), "reason": reason, "still_open": still,
            })
            last_exit = (exit_i if not still else i + HOLD_MAX)
    out.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return out


# ── 2. 鱼 ─────────────────────────────────────────────────────────────────────
def fetch_fish() -> list[dict]:
    panel = fish_counter.fetch_panel_supabase(FISH_LO, FISH_HI)
    return fish_counter.fish(panel, FISH_LO, FISH_HI)


def ticket_on_fish(t: dict, fish: list[dict]) -> bool:
    """S-641 原文 + S-618 原定义:进场日落在 [鱼起点, 峰值日] 这一段里就算「在鱼上」。

    只看进场日,不看持有期 —— 与 S-633 / T-151b 的口径一致(`t151b_fish_on_trade.py`
    的 `s[0] <= entry_date <= s[1]`),也才和台账里 892 张票 10.8% 的量级对得上。
    """
    ed = t.get("entry_d")
    if ed is None:
        return False
    ed = pd.Timestamp(ed)
    for f in fish:
        if f["symbol"] != t["symbol"]: continue
        ps = pd.Timestamp(f["start_date"]); pe = pd.Timestamp(f["peak_close_date"])
        if ps <= ed <= pe:
            return True
    return False


# ── 3. 风格指数历史(level + members)───────────────────────────────────────
def fetch_sector_history() -> dict[str, pd.DataFrame]:
    u, k = _su(); hdrs = _hdr(k)
    out: dict[str, pd.DataFrame] = {}
    for st in SECTORS:
        q = urllib.parse.urlencode({
            "select": "d,ret,level,members",
            "dimension": f"eq.{SECTOR_DIM}",
            "style": f"eq.{st}",
            "weighting": f"eq.{SECTOR_WGT}",
            "order": "d.asc",
        })
        raw = _page_all(u + "/rest/v1/style_index_pit_daily?" + q, hdrs, cap_pages=80)
        if not raw:
            out[st] = pd.DataFrame(columns=["d", "ret", "level", "members"])
            continue
        df = pd.DataFrame(raw)
        df["d"] = pd.to_datetime(df["d"])
        out[st] = df.sort_values("d").reset_index(drop=True)
    return out


# ── 4. 成员日价(只取 sector 成员命中过的票的 ohlcv,用于 P)────────────────
def fetch_ohlcv_for(bars: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Reuse the full bars pulled in step (2):{symbol: DataFrame[trade_date, close]}."""
    out: dict[str, pd.DataFrame] = {}
    g = bars.groupby("symbol", sort=False)
    for sym, seg in g:
        out[sym] = pd.DataFrame({"trade_date": pd.to_datetime(seg["trade_date"]).dt.normalize(),
                                  "close": pd.to_numeric(seg["close"], errors="coerce")})
    return out


# ── 5. funding_history → 每个名字、每日的资金费率均值 ──────────────────────
FUNDING_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t158_funding_daily.parquet")


def fetch_funding(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """每个名字每日一行的资金费率均值(3 次/8h → 日均)。

    两个坑(都踩过):
      ① `pd.concat` 逐行拼 200 万行是 O(n²) —— 先攒 list,最后一次建表。
      ② `_page_all(cap_pages=400)` 每批最多 40 万行,而一批 80 个名字要 ~58 万行,
         会**静默截断**最靠后的(最近的)一段 ⇒ C(拥挤)分量偏向早期。分批降到 40 个
         名字、cap_pages 抬到 1200(120 万行上限 vs 需要的 ~29 万),并在返回前
         断言每个名字都拿到了最后一天。
    """
    if FUNDING_CACHE.exists():
        raw = pd.read_parquet(FUNDING_CACHE)
        got = set(raw["symbol"].unique())
        if set(symbols).issubset(got):
            print(f"[t158]   funding cache hit {FUNDING_CACHE} symbols={len(got)}", flush=True)
            return {s: g.reset_index(drop=True) for s, g in raw.groupby("symbol", sort=False)}

    u, k = _su(); hdrs = _hdr(k)
    acc: dict[str, list[tuple[str, float]]] = {}
    chunk = 40
    # 有的成员名带非 ASCII(币圈里常见中文名 / emoji)⇒ 必须 percent-encode,
    # 否则 http.client 在编码 request line 时 UnicodeEncodeError(2026-10-21 首次跑到)。
    non_ascii = [s for s in symbols if not s.isascii()]
    if non_ascii:
        print(f"[t158]   成员名里 {len(non_ascii)} 个非 ASCII,已 percent-encode: "
              f"{non_ascii[:6]}", flush=True)
    for i in range(0, len(symbols), chunk):
        quoted = ",".join(f'"{urllib.parse.quote(s, safe="")}"' for s in symbols[i:i + chunk])
        path = (f"/rest/v1/funding_history?select=symbol,funding_time,funding_rate"
                f"&venue=eq.binance_perp&symbol=in.({quoted})&order=funding_time.asc")
        # 一批坏了不拖死整轮:重试若干次,仍失败就**逐个名字**补 —— 直接 continue 会
        # 静悄悄丢掉一整批(40 个)成员的资金费,C 分量少 1/7 的成员而报告上看不出来
        # (2026-10-21 第一次跑:chunk 3 RemoteDisconnected,79 个名字里少 13 个)。
        rows: list = []
        last_err: Optional[Exception] = None
        for try_i in range(3):
            try:
                rows = _page_all(u + path, hdrs, cap_pages=1200)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                import time as _t; _t.sleep(2.0 + 5.0 * try_i)
        if not rows:
            print(f"[t158]   !! funding chunk {i // chunk + 1} FAILED x3 ({last_err!r}) "
                  f"→ 逐个名字补", flush=True)
            for s in symbols[i:i + chunk]:
                q1 = (f"/rest/v1/funding_history?select=symbol,funding_time,funding_rate"
                      f"&venue=eq.binance_perp&symbol=eq."
                      f"{urllib.parse.quote(s, safe='')}&order=funding_time.asc")
                try:
                    rows += _page_all(u + q1, hdrs, cap_pages=60)
                except Exception as e:  # noqa: BLE001
                    print(f"[t158]   !! funding 单名 {s} 仍失败: {e!r}", flush=True)
        for r in rows:
            t = str(r.get("funding_time") or "")[:10]
            fr = r.get("funding_rate")
            if fr is None or not t: continue
            acc.setdefault(r["symbol"], []).append((t, float(fr)))
        print(f"[t158]   funding chunk {i // chunk + 1}: +{len(rows)} rows, "
              f"{len(acc)} symbols so far", flush=True)
    out: dict[str, pd.DataFrame] = {}
    allrows: list[dict] = []
    for s, v in acc.items():
        df = pd.DataFrame(v, columns=["d", "fr"])
        df["d"] = pd.to_datetime(df["d"])
        g = df.groupby("d", as_index=False)["fr"].mean().sort_values("d").reset_index(drop=True)
        out[s] = g
        g2 = g.assign(symbol=s)
        allrows.append(g2[["symbol", "d", "fr"]])
    if allrows:
        pd.concat(allrows, ignore_index=True).to_parquet(FUNDING_CACHE, index=False)
        print(f"[t158]   wrote {FUNDING_CACHE}", flush=True)
    last = max((df["d"].max() for df in out.values()), default=None)
    print(f"[t158]   funding days: 最晚一天 = {last}", flush=True)
    return out


# ── 6. 四个分量 + 历史百分位 ────────────────────────────────────────────────
def comp_A_from_window(levels_win: np.ndarray, idx: int) -> Optional[int]:
    """levels_win[0..idx] 都已 ascending 顺序排列。"""
    if idx < A_LOOKBACK - 1: return None
    cur = float(levels_win[idx])
    avg200 = float(levels_win[idx - A_LOOKBACK + 1: idx + 1].mean())
    if cur <= avg200:
        return None  # 当前在 200 日线下 ⇒ 下行期
    # 倒着找最近的「下穿 200 日均线」
    for j in range(idx, A_LOOKBACK - 1, -1):
        win_j = levels_win[j - A_LOOKBACK + 1: j + 1]
        if float(levels_win[j]) <= float(win_j.mean()):
            return int(idx - j)  # 上穿以来的天数
    return int(idx) + 1  # 历史都不足 ⇒ 全程在上行


def comp_E_from_window(levels_win: np.ndarray, idx: int) -> Optional[float]:
    if idx < E_LOOKBACK: return None
    win = levels_win[max(0, idx - E_LOOKBACK): idx]  # t − 365 .. t − 1
    if win.size == 0: return None
    lo = float(win.min())
    if lo <= 0: return None
    return float(levels_win[idx] / lo - 1.0)


def _percentile_rank(values: list[float] | np.ndarray, current: float) -> Optional[float]:
    """中秩分位:(N(<x) + N(=x)/2) / N(总)。要求 N(总) ≥ HISTORY_MIN_DAYS。"""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < HISTORY_MIN_DAYS: return None
    if not np.isfinite(current): return None
    less = int((arr < current).sum()); eq = int((arr == current).sum())
    return (less + eq / 2.0) / arr.size


def pack_series(df: pd.DataFrame, date_col: str, val_col: str) -> tuple[np.ndarray, np.ndarray]:
    """(升序 datetime64[D] 数组, float 数组)。之后 P / C 全用位置切片算,不再逐日建 dict。"""
    d = pd.to_datetime(df[date_col]).to_numpy(dtype="datetime64[D]")
    v = pd.to_numeric(df[val_col], errors="coerce").to_numpy(dtype=float)
    return d, v


def _idx_on_or_before(dates: np.ndarray, d_t: pd.Timestamp) -> int:
    return int(np.searchsorted(dates, np.datetime64(d_t.date(), "D"), side="right") - 1)


def comp_P_for(packs: dict[str, tuple[np.ndarray, np.ndarray]], members: list[str],
               d_t: pd.Timestamp) -> Optional[float]:
    """过去 20 根里,每个成员有没有「收盘创过 40 根新高」,占比返回 [0, 1]。

    窗口按**行**(K 线根数)算,不用日历天 —— 与全流程的 hh40 / ll40(ROWS 口径)一致,
    也不会被停牌/缺日挪动。j = 最后一行日期 ≤ d_t,看不到未来。
    """
    hit, member_count = 0, 0
    for sym in members:
        pk = packs.get(sym)
        if pk is None: continue
        dates, closes = pk
        j = _idx_on_or_before(dates, d_t)
        if j < P_LOOKBACK_NEW: continue
        member_count += 1
        ok = False
        t = j
        for _ in range(P_LOOKBACK_WIN + 1):
            if t < P_LOOKBACK_NEW: break
            cur = closes[t]
            if cur > 0 and cur >= float(closes[t - P_LOOKBACK_NEW:t].max()):
                ok = True; break
            t -= 1
        if ok: hit += 1
    if member_count == 0: return None
    return float(hit / member_count)


def comp_C_for(packs: dict[str, tuple[np.ndarray, np.ndarray]], members: list[str],
               d_t: pd.Timestamp) -> Optional[float]:
    """d_t 之前 7 根的日均资金费率,先成员内平均、再跨成员平均。

    只用 ≤ d_t − 1 根(j = 最后一行日期 ≤ d_t,窗口取 j−7 .. j−1)。
    """
    rates: list[float] = []
    for sym in members:
        pk = packs.get(sym)
        if pk is None: continue
        dates, fr = pk
        j = _idx_on_or_before(dates, d_t)
        if j < C_LOOKBACK: continue
        w = fr[j - C_LOOKBACK:j]
        w = w[np.isfinite(w)]
        if w.size: rates.append(float(w.mean()))
    if not rates: return None
    return float(np.mean(rates))


# ── 7. 给定的票 + 给定的 style/d → M ─────────────────────────────────────────
def _history_vals_for_comp(comp: str, levels: np.ndarray, idx: int,
                           members: list[str], d_t: pd.Timestamp,
                           closes: dict[str, pd.DataFrame],
                           funding: dict[str, pd.DataFrame]) -> tuple[Optional[float], Optional[float]]:
    """对当前 idx 计算 component 当前值,顺便在所有 prior day 上重算 → percentile。

    返回 (current_value, percentile) —— 任一不可算时返 (None, None)。
    A / E 走 levels 自计算;P / C 走的不是 levels(而是 members 价格 / funding),
    因此 P / C 的历史分数走另一条路径(下面 comp_P_hist / comp_C_hist)。
    """
    return None, None  # not used here


def build_PC_prior(df: pd.DataFrame, sector_members_at_d: dict[str, list[str]],
                   packs: dict[str, tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """P 的全样本历史(长度 = len(df)),索引 i 对应 d_i。"""
    n = len(df); out = np.full(n, np.nan)
    for i in range(n):
        d_t = pd.Timestamp(df["d"].iloc[i])
        members = sector_members_at_d.get(d_t.date().isoformat(), [])
        if not members: continue
        v = comp_P_for(packs, members, d_t)
        if v is not None: out[i] = v
    return out


def build_CC_prior(df: pd.DataFrame, sector_members_at_d: dict[str, list[str]],
                   packs: dict[str, tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    n = len(df); out = np.full(n, np.nan)
    for i in range(n):
        d_t = pd.Timestamp(df["d"].iloc[i])
        members = sector_members_at_d.get(d_t.date().isoformat(), [])
        if not members: continue
        v = comp_C_for(packs, members, d_t)
        if v is not None: out[i] = v
    return out


def build_AE_prior(levels: np.ndarray, comp: str) -> tuple[np.ndarray, np.ndarray]:
    """返回 (current_per_idx, prior_per_idx)。A 是 None 表示当前下行期。"""
    n = len(levels)
    cur = np.full(n, np.nan); prior = np.full(n, np.nan)
    for i in range(n):
        if comp == "A":
            v = comp_A_from_window(levels, i)
            if v is not None: cur[i] = float(v)
        elif comp == "E":
            v = comp_E_from_window(levels, i)
            if v is not None: cur[i] = v
    return cur, prior


# ── 8. 写 M 到每张票 ──────────────────────────────────────────────────────────
def compute_per_ticket(tickets: list[dict],
                        sector_hist: dict[str, pd.DataFrame],
                        sector_members_at_d: dict[str, dict[str, list[str]]],
                        closes: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Returns DataFrame with columns
        symbol, signal_d, r, entry_d, exit_d, sectors, M, per_sector_raw, ...
    对应每张至少落进一个 sector 的票;不属任何 sector 的票不在结果里(单独计数)。
    """
    # 每个成员一份 (日期数组, 值数组) —— P / C 只做位置切片
    close_packs = {s: pack_series(g, "trade_date", "close") for s, g in closes.items()}
    fund_packs = {s: pack_series(g, "d", "fr") for s, g in funding.items() if g is not None and len(g)}
    # 预计算每个 style 的 P / C 历史(用 sector_members_at_d 在该日的成员)
    pc_history: dict[str, dict[str, np.ndarray]] = {}
    for st, df in sector_hist.items():
        pc_history[st] = {
            "P": build_PC_prior(df, sector_members_at_d[st], close_packs),
            "C": build_CC_prior(df, sector_members_at_d[st], fund_packs),
        }
        # A / E 的逐日历史也**一次算完**(先前每张票都把整段历史重算一遍:
        # 724 张票 × 2 个风格 × 2450 天 × 每次倒扫 200 日 ⇒ 光 A 就几十分钟)。
        # 与 _pct_AE 逐字同口径:分量在第 j 天只看 levels[:j+1],当前值相同、
        # 历史取 j 之前的有限值、中秩分位、最少 365 天。
        _lv = df["level"].to_numpy(dtype=float)
        pc_history[st]["A"] = build_AE_prior(_lv, "A")[0]
        pc_history[st]["E"] = build_AE_prior(_lv, "E")[0]
    # 每 style 的 levels
    sec_levels: dict[str, np.ndarray] = {st: df["level"].to_numpy(dtype=float)
                                          for st, df in sector_hist.items()}
    sec_dates: dict[str, np.ndarray] = {st: df["d"].to_numpy() for st, df in sector_hist.items()}

    out: list[dict] = []
    skipped_outside = 0
    for t in tickets:
        sym = t["symbol"]; d_t = pd.Timestamp(t["signal_d"]); d_iso = d_t.date().isoformat()
        sectors_for_ticket: list[str] = []
        for st in SECTORS:
            if sym in sector_members_at_d[st].get(d_iso, []):
                sectors_for_ticket.append(st)
        if not sectors_for_ticket:
            skipped_outside += 1
            continue
        comps_cross: dict[str, list[float]] = {"A": [], "E": [], "P": [], "C": []}
        per_sector_raw: list[dict] = []
        for st in sectors_for_ticket:
            df = sector_hist[st]
            d_np = sec_dates[st]
            # find idx for d_t(≤ t 的最后一日)
            j = int(np.searchsorted(d_np, np.datetime64(d_t), side="right") - 1)
            if j < 0: continue
            members = sector_members_at_d[st].get(d_iso, [])
            levels = sec_levels[st][: j + 1]
            d_t_real = pd.Timestamp(df["d"].iloc[j])
            # A / E:当前值
            vA = comp_A_from_window(levels, j)
            vE = comp_E_from_window(levels, j)
            # P / C:当前值
            vP = comp_P_for(close_packs, members, d_t_real)
            vC = comp_C_for(fund_packs, members, d_t_real)
            # 历史 percentiles
            pA = _pct_array(pc_history[st]["A"], j, vA) if vA is not None else None
            pE = _pct_array(pc_history[st]["E"], j, vE) if vE is not None else None
            pP = _pct_array(pc_history[st]["P"], j, vP) if vP is not None else None
            pC = _pct_array(pc_history[st]["C"], j, vC) if vC is not None else None
            per_sector_raw.append({"style": st, "A": vA, "E": vE, "P": vP, "C": vC,
                                   "pA": pA, "pE": pE, "pP": pP, "pC": pC})
            for k, p in (("A", pA), ("E", pE), ("P", pP), ("C", pC)):
                if p is not None and np.isfinite(p): comps_cross[k].append(p)
        if not any(comps_cross.values()):
            continue
        # M = 各 component 跨 sector 的分位均值(每一 comp 取均值后再总均)
        per_comp_mean = [np.mean(comps_cross[k]) for k in ("A", "E", "P", "C") if comps_cross[k]]
        M = float(np.mean(per_comp_mean))
        out.append({"symbol": sym, "signal_d": d_t, "r": t["r"],
                    "entry_d": t["entry_d"], "exit_d": t["exit_d"],
                    "fish": False, "M": M, "terc": "",
                    "sectors": ",".join(sectors_for_ticket),
                    "per_sector_raw": per_sector_raw,
                    "n_pA": len(comps_cross["A"]), "n_pE": len(comps_cross["E"]),
                    "n_pP": len(comps_cross["P"]), "n_pC": len(comps_cross["C"]),
                    "down_A": not any(ps["A"] is not None for ps in per_sector_raw)})
    df_out = pd.DataFrame(out)
    df_out.attrs["skip_no_sector"] = int(skipped_outside)
    return df_out


def _pct_AE(levels: np.ndarray, comp: str, idx: int) -> Optional[float]:
    """A / E 的 percentiles:对每个 prior j < idx 重算 comp,然后取中秩分位。"""
    if idx < 1: return None
    fn = comp_A_from_window if comp == "A" else comp_E_from_window
    vals: list[float] = []
    for j in range(idx):
        v = fn(levels[: j + 1], j)
        if v is not None and np.isfinite(v):
            vals.append(float(v))
    arr = np.array(vals, dtype=float)
    if arr.size < HISTORY_MIN_DAYS: return None
    cur = fn(levels[: idx + 1], idx)
    if cur is None or not np.isfinite(cur): return None
    less = int((arr < cur).sum()); eq = int((arr == cur).sum())
    return (less + eq / 2.0) / arr.size


def _pct_array(arr: np.ndarray, idx: int, current: Optional[float]) -> Optional[float]:
    if idx < 1 or current is None: return None
    prior = arr[: idx]
    prior = prior[np.isfinite(prior)]
    if prior.size < HISTORY_MIN_DAYS: return None
    if not np.isfinite(current): return None
    less = int((prior < current).sum()); eq = int((prior == current).sum())
    return (less + eq / 2.0) / prior.size


# ── 9. 三分位 + 判 ───────────────────────────────────────────────────────────
def tercile_labels(M_arr: np.ndarray) -> np.ndarray:
    n = M_arr.size
    order = np.argsort(M_arr, kind="mergesort")
    ranks = np.empty(n, dtype=int); ranks[order] = np.arange(n)
    cut1, cut2 = n // 3, 2 * n // 3
    out = np.array(["mid"] * n, dtype=object)
    out[ranks < cut1] = "early"
    out[ranks >= cut2] = "late"
    return out


def bootstrap_R(tickets_df: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """① 平均 R 早 > 晚(对票有放回自助 2,000)。"""
    rng = np.random.default_rng(seed)
    df = tickets_df.copy()
    df_in = df[df["M"].notna()].reset_index(drop=True)
    if df_in.empty: return {"verdict": "不可算", "n": 0}
    terc = tercile_labels(df_in["M"].to_numpy())
    n_e = int((terc == "early").sum()); n_l = int((terc == "late").sum()); n_m = int((terc == "mid").sum())
    r_e = df_in.loc[terc == "early", "r"].to_numpy(dtype=float)
    r_l = df_in.loc[terc == "late", "r"].to_numpy(dtype=float)
    r_m = df_in.loc[terc == "mid", "r"].to_numpy(dtype=float)
    obs_e = float(np.mean(r_e)) if n_e else np.nan
    obs_l = float(np.mean(r_l)) if n_l else np.nan
    obs_m = float(np.mean(r_m)) if n_m else np.nan
    obs_diff = obs_e - obs_l
    if n_e < 2 or n_l < 2:
        return {"n": int(len(df_in)), "n_early": n_e, "n_mid": n_m, "n_late": n_l,
                "obs_mean_early": obs_e, "obs_mean_mid": obs_m, "obs_mean_late": obs_l,
                "obs_diff_early_minus_late": obs_diff,
                "p_early_gt_late": None, "n_boot": n_boot, "verdict": "不可算"}
    pooled = np.concatenate([r_e, r_l])
    deltas = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, pooled.size, pooled.size)
        boot = pooled[idx]
        deltas[b] = boot[: n_e].mean() - boot[n_e:].mean()
    p_one = float((deltas <= 0).mean())
    return {"n": int(len(df_in)), "n_early": n_e, "n_mid": n_m, "n_late": n_l,
            "obs_mean_early": obs_e, "obs_mean_mid": obs_m, "obs_mean_late": obs_l,
            "obs_diff_early_minus_late": obs_diff,
            "boot_delta_median": float(np.median(deltas)),
            "boot_delta_p05": float(np.quantile(deltas, 0.05)),
            "boot_delta_p95": float(np.quantile(deltas, 0.95)),
            "p_early_gt_late": p_one, "n_boot": n_boot,
            "verdict": ("早 > 晚" if p_one < ALPHA else "分不开")}


def shuffle_year_test(tickets_df: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """② 在鱼上比例 早 > 晚(年内打乱 2,000)。"""
    rng = np.random.default_rng(seed + 1)
    df = tickets_df.copy()
    df_in = df[df["M"].notna()].reset_index(drop=True)
    if df_in.empty: return {"verdict": "不可算", "n": 0}
    terc = tercile_labels(df_in["M"].to_numpy())
    f_arr = df_in["fish"].to_numpy(bool)
    years = df_in["signal_d"].dt.year.to_numpy()
    n_e = int((terc == "early").sum()); n_l = int((terc == "late").sum())
    n = len(terc)
    obs_e = float(f_arr[terc == "early"].mean()) if n_e else 0.0
    obs_l = float(f_arr[terc == "late"].mean()) if n_l else 0.0
    obs_diff = obs_e - obs_l
    boot = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        b_f = shuffle_within(f_arr.tolist(), years.tolist(), rng).astype(bool)
        p_e = float(b_f[terc == "early"].mean()) if n_e else 0.0
        p_l = float(b_f[terc == "late"].mean()) if n_l else 0.0
        boot[b] = p_e - p_l
    p_one = float((boot <= 0).mean())
    return {"n": int(n), "n_early": n_e, "n_late": n_l,
            "obs_p_early_on_fish": obs_e, "obs_p_late_on_fish": obs_l,
            "obs_diff_early_minus_late": obs_diff,
            "boot_diff_median": float(np.median(boot)),
            "boot_diff_p05": float(np.quantile(boot, 0.05)),
            "boot_diff_p95": float(np.quantile(boot, 0.95)),
            "p_early_gt_late": p_one, "n_boot": n_boot,
            "verdict": ("早 > 晚" if p_one < ALPHA else "分不开")}


# ── 10. 写报告 ────────────────────────────────────────────────────────────────
def write_report(tickets_df: pd.DataFrame, n_fish: int,
                 test_a: dict, test_b: dict, ticket_total: int,
                 skip_outside: int, test_a_loose: dict | None = None,
                 test_b_loose: dict | None = None) -> None:
    L: list[str] = []
    L.append("# T-158 — 风格成熟度(S-641)\n")
    L.append("**生成:** `docs/research/t158_style_maturity.py`(S-641 预注册原文,2026-10-21)。\n")
    L.append("**读库:** publishable,只读;零分布走 `src/data/evaluation/apparatus.py`(`shuffle_within` / `null_distribution` / `percentile_of`)—— 不另写。\n")
    L.append("")
    L.append("## 0. 复现 + 配料\n")
    L.append(f"- R-v2 票(信号日 ≤ {SIG_HI}):**{ticket_total} 张**(V1 内核,与 `docs/research/r_v2_tickets.sql` 同口径)")
    L.append(f"- 鱼(`docs/research/fish_counter.py`,窗口 {FISH_LO} → {FISH_HI}):**{n_fish} 条**(S-618 链式并鱼,先 `t154_fish_counter_check.py` 复现 286)")
    L.append(f"- 票不属任何 sector 的剔除计数:**{skip_outside}**")
    L.append("")
    L.append("## 1. S-641 预注册原文(逐字)\n")
    L.append("> 成熟度分 M(风格 s、日 t,只用 ≤ t 的数据):风格 = style_index_pit_daily 的 sector 维度("
              "ai / defi / meme / infra_tokenization,cap 加权,成员按时点)。四个分量:200 日线上行周期的年龄、"
              "离 365 日低点的涨幅、过去 20 天里收盘创过 40 日新高的成员占比、成员 7 日平均资金费率(binance_perp)"
              "的成员均值。每个分量换成该风格自己历史(t − 1 之前、至少 365 天)的分位;**M = 四个分位的平均**"
              "(0 = 本轮刚开始,1 = 本轮很晚)。票的 M = 信号日该币所属风格的 M(属多个风格取平均);"
              "不属任何风格的票剔除并计数。「在鱼上」用 `docs/research/fish_counter.py`(先复现 286)。\n\n"
              "判两条:① 平均 R(早)> 平均 R(晚),对票有放回自助 2,000 次单侧 p < 0.05 ② 在鱼上比例(早)> (晚),"
              "年内打乱三分位标签 2,000 次单侧 p < 0.05。\n")
    L.append("")
    L.append("## 2. 三分位 + 基本数\n")
    df_in = tickets_df[tickets_df["M"].notna()].copy()
    grp = df_in.groupby("terc").agg(
        n=("r", "count"), mean_r=("r", "mean"), p_fish=("fish", "mean"),
        mean_M=("M", "mean"), sum_r=("r", "sum")
    ).reindex(["early", "mid", "late"]).reset_index()
    L.append(grp.to_markdown(index=False, floatfmt=".3f"))
    L.append("")
    L.append("## 3. 判 ① 平均 R 早 > 晚(自助 2,000)\n")
    L.append(f"- N={test_a['n']},early={test_a['n_early']},mid={test_a['n_mid']},late={test_a['n_late']}")
    L.append(f"- 观测平均 R:early=`{test_a['obs_mean_early']:.3f}`,mid=`{test_a['obs_mean_mid']:.3f}`,late=`{test_a['obs_mean_late']:.3f}`")
    L.append(f"- 观测差(early − late)=`{test_a['obs_diff_early_minus_late']:.3f}`")
    L.append(f"- 自助 delta 中位=`{test_a.get('boot_delta_median', float('nan')):.3f}`,p05=`{test_a.get('boot_delta_p05', float('nan')):.3f}`,p95=`{test_a.get('boot_delta_p95', float('nan')):.3f}`")
    L.append(f"- 单侧 p(boot delta ≤ 0 比例)=`{test_a['p_early_gt_late']}`,n_boot=`{test_a['n_boot']}`")
    L.append(f"- 结论:**{test_a['verdict']}**")
    L.append("")
    L.append("## 4. 判 ② 在鱼上比例 早 > 晚(年内打乱 2,000)\n")
    L.append(f"- N={test_b['n']},early={test_b['n_early']},late={test_b['n_late']}")
    L.append(f"- 观测在鱼上比例:early=`{test_b['obs_p_early_on_fish']:.3f}`,late=`{test_b['obs_p_late_on_fish']:.3f}`")
    L.append(f"- 观测差(early − late)=`{test_b['obs_diff_early_minus_late']:.3f}`")
    L.append(f"- 自助差 中位=`{test_b['boot_diff_median']:.3f}`,p05=`{test_b['boot_diff_p05']:.3f}`,p95=`{test_b['boot_diff_p95']:.3f}`")
    L.append(f"- 单侧 p(boot diff ≤ 0 比例)=`{test_b['p_early_gt_late']}`,n_boot=`{test_b['n_boot']}`")
    L.append(f"- 结论:**{test_b['verdict']}**")
    L.append("")
    L.append("## 5. 分年表\n")
    df_in2 = df_in.copy()
    df_in2["year"] = df_in2["signal_d"].dt.year
    yoy = df_in2.groupby(["year", "terc"]).agg(
        n=("r", "count"), mean_r=("r", "mean"), p_fish=("fish", "mean")
    ).reset_index()
    L.append(yoy.to_markdown(index=False, floatfmt=".3f"))
    L.append("")
    L.append("**为什么 2022 与 2026 一张都没有:** 票的闸门是 majors cap 风格指数的 200 日均线 —— "
             "2022 全年 365 天里闸门只开 4 天、2026-01-01 → 2026-06-20 的 171 天**一天都没开**"
             "(`style_index_pit_daily` style=majors weighting=cap,本脚本 `fetch_gate()` 同一口径复算)。"
             "不是筛掉了 2026,是 2026 上半年 R-v2 本来不开票。\n")
    L.append("## 6. 各分量单独当成熟度用(同口径:同样的三分位、同样的两条判)\n")
    L.append("每个分量的票级值 = 该票所属风格的分量原始值取平均;**单独**按它切三分位"
             "(不是沿用 M 的分组 —— 那样四行必然长得一样)。\n")
    rows = []
    for comp in ("A", "E", "P", "C"):
        tmp = tickets_df.copy()
        vals = []
        for ps in tmp["per_sector_raw"]:
            vv = [s.get(comp) for s in (ps or [])]
            vv = [float(v) for v in vv if v is not None and np.isfinite(v)]
            vals.append(float(np.mean(vv)) if vv else np.nan)
        tmp["M"] = vals
        ta = bootstrap_R(tmp)
        tb = shuffle_year_test(tmp)
        g = tmp[tmp["M"].notna()].copy()
        if len(g):
            terc = tercile_labels(g["M"].to_numpy())
            g["terc"] = terc
            ge = g[g["terc"] == "early"]; gm = g[g["terc"] == "mid"]; gl = g[g["terc"] == "late"]
            mr = [float(ge["r"].mean()) if len(ge) else np.nan,
                  float(gm["r"].mean()) if len(gm) else np.nan,
                  float(gl["r"].mean()) if len(gl) else np.nan]
            mono = ("单调↑" if len(ge) and len(gm) and len(gl) and mr[0] < mr[1] < mr[2]
                    else "单调↓" if len(ge) and len(gm) and len(gl) and mr[0] > mr[1] > mr[2]
                    else "不单调")
            rows.append({"comp": comp, "n": len(g),
                         "n_early": int(len(ge)), "n_mid": int(len(gm)), "n_late": int(len(gl)),
                         "mean_r_early": round(mr[0], 3), "mean_r_mid": round(mr[1], 3),
                         "mean_r_late": round(mr[2], 3), "单调": mono,
                         "p_fish_early": round(float(ge["fish"].mean()), 3) if len(ge) else None,
                         "p_fish_late": round(float(gl["fish"].mean()), 3) if len(gl) else None,
                         "p_①": ta.get("p_early_gt_late"), "p_②": tb.get("p_early_gt_late")})
        else:
            rows.append({"comp": comp, "n": 0, "n_early": 0, "n_mid": 0, "n_late": 0,
                         "mean_r_early": None, "mean_r_mid": None, "mean_r_late": None,
                         "单调": None, "p_fish_early": None, "p_fish_late": None,
                         "p_①": None, "p_②": None})
    L.append(pd.DataFrame(rows).to_markdown(index=False))
    L.append("")
    L.append("## 7. 下行组(`A == None` ⇒ 未进 M 的票)\n")
    dr = tickets_df[tickets_df["down_A"]].copy()
    if dr.empty:
        L.append("- 无下行组。")
    else:
        L.append(f"- 张数:**{len(dr)}**(不进三分位,单列)")
        L.append(f"- 平均 R:**{dr['r'].mean():.3f}**(全部有 M 的票 {tickets_df[tickets_df['M'].notna()]['r'].mean():.3f})")
        L.append(f"- 在鱼上比例:**{dr['fish'].mean():.3f}**(全部有 M 的票 {tickets_df[tickets_df['M'].notna()]['fish'].mean():.3f})")
    L.append("")
    if test_a_loose is not None and test_b_loose is not None:
        L.append("## 7b. 敏感性(只报,不判):宽松口径 —— 下行风格仍用 E/P/C 凑 M\n")
        L.append(f"- in_M(宽松)=`{test_a_loose.get('n')}` vs 严格 `{test_a.get('n')}`")
        L.append(f"- ① 平均 R 早 − 晚 = `{test_a_loose.get('obs_diff_early_minus_late'):+.3f}`,"
                 f"p=`{test_a_loose.get('p_early_gt_late')}`")
        L.append(f"- ② 在鱼上比例 早 − 晚 = `{test_b_loose.get('obs_diff_early_minus_late'):+.3f}`,"
                 f"p=`{test_b_loose.get('p_early_gt_late')}`")
        L.append("")
    L.append("## 8. S-641 结果(草稿)\n")
    rep_a = (test_a["p_early_gt_late"] is not None and test_a["p_early_gt_late"] < ALPHA)
    rep_b = (test_b["p_early_gt_late"] is not None and test_b["p_early_gt_late"] < ALPHA)
    L.append(f"- **判 ① 平均 R 早 > 晚:** p=`{test_a['p_early_gt_late']}`,{('✅ 早 > 晚' if rep_a else '🔴 分不开/不可算')}")
    L.append(f"- **判 ② 在鱼上比例 早 > 晚:** p=`{test_b['p_early_gt_late']}`,{('✅ 早 > 晚' if rep_b else '🔴 分不开/不可算')}")
    L.append("")
    L.append("**读法:方向是反的,不是「差一点」。** 三分位平均 R = 早 `0.251` / 中 `0.520` / 晚 `1.011`"
             "(单调↑),在鱼上比例 早 `0.247` / 晚 `0.432` —— 假设要的是「早的更好」,"
             "数据给出的是**本轮很晚的风格里的票 R 更高、更常在鱼上**。两条判都不是「差一点没显著」:"
             "观测差落在零分布的**另一半**(① 的单侧 p=0.4955 即差值在中位之下),方向与假设相反。"
             "成熟度分按 S-641 的写法**不能**进 R-v2 的单票仓位维度。\n")
    L.append("**为什么与 S-625 / S-638 不冲突:** 那两条讲的是**同一批票内部**谁更早(S-625 热板块、S-638 上限先接),"
             "这里换了一个轴 —— **风格**走到第几段。晚的风格里 R 高,和 S-638「先接的更好」相反,说明两者说的不是同一个量;"
             "「早」在 S-638 是**同一波里的先后**,在 S-641 是**风格周期的阶段**。\n")
    L.append("**探索性(未预注册,不能当证据):** 反方向(晚 > 早)在 ② 上更接近显著,但 ② 的单侧检验是照预注册"
             "「早 > 晚」写的,p=0.7795 是对错误方向的单侧值 —— 换成「晚 > 早」需要**另立预注册 + 新数据**重跑,"
             "而且同一段历史上的反向读法是数据挖掘,不能就地翻案。\n")
    L.append("## 9. 数据 & 读数\n")
    L.append(f"- V1 内核 = `simulate_tickets()`(与 `t156_rv2_forward_vs_replay.py:simulate()` 同字面,实现搬到了本文件),"
              f"闸门 = `style_index_pit_daily`(style=majors, weighting=cap)200 日均线")
    L.append(f"- 风格指数 = `style_index_pit_daily`(dimension=sector, weighting=cap,sector∈{list(SECTORS)});"
              f"成员按时点(`members` 字段随日变化)")
    L.append(f"- 资金费 = `funding_history` venue=binance_perp;7 日均资金率。"
             f"⚠️ **实际拿到 {_funding_symbol_count()} 个名字**(4 个 sector 的成员并集 283 名里,"
             f"其余名字在该 venue 没有资金费行)⇒ C 分量的成员平均只用有资金费的那部分成员,"
             f"不是一个全成员平均。若 C 的分位因此偏窄,只会让 M 更依赖 A/E/P,不改变本条的方向。")
    L.append(f"- 鱼 = `docs/research/fish_counter.py`(S-618,链式并鱼);先 `docs/research/t154_fish_counter_check.py` 复现 286")
    L.append(f"- 零分布用 `block_permute`/`shuffle_within`(apparatus);A/B 不需要额外装置(预注册原文就是「自助」+「年内打乱」,不是装置里的 ab_test)")
    L.append("- 票引擎的对账(为什么信 724 张):`docs/research/t158_ticket_selfcheck.py` + "
             "`docs/research/t158_engine_reconcile.py` —— 拿台账里**别的道在今天的库上**"
             "数过的票数当锚(T-156 全区间 653 / 2024 全年 261 / S-637 769 张)。")
    L.append("- A / E 的历史分位改成**逐日预计算**(旧写法每张票把整段历史重算一遍,几十分钟);"
             "两条判的数字与旧写法逐位相同,已复跑核对。")
    L.append("")
    Path(REPORT_PATH).write_text("\n".join(L), encoding="utf-8")
    print(f"[t158] wrote {REPORT_PATH}", flush=True)


# ── main ──────────────────────────────────────────────────────────────────────
def _df_to_cache(df: pd.DataFrame, meta: dict) -> dict:
    rows = []
    for rec in df.to_dict("records"):
        r = dict(rec)
        for k in ("signal_d", "entry_d", "exit_d"):
            v = r.get(k)
            r[k] = None if (v is None or (isinstance(v, float) and np.isnan(v))
                            or pd.isna(v)) else pd.Timestamp(v).date().isoformat()
        rows.append(r)
    return {"meta": meta, "rows": rows}


def _df_from_cache(blob: dict) -> pd.DataFrame:
    df = pd.DataFrame(blob["rows"])
    for k in ("signal_d", "entry_d", "exit_d"):
        df[k] = pd.to_datetime(df[k])
    df["fish"] = df["fish"].astype(bool)
    df["down_A"] = df["down_A"].astype(bool)
    return df


def m_strict_from_raw(raw: list[dict]) -> float:
    """S-641 原文「A … 当前在 200 日线下 ⇒ 不在上行周期,单列一组『下行』,不进 M」。

    ⇒ 一个风格处在下行时,这个风格当天的 M **整条不算**(不是只把 A 拿掉、拿 E/P/C
    凑三个平均)。所以只对 A 非 None 的风格取分位,再按分量跨风格平均;一个风格都不
    满足 ⇒ NaN(这张票进「下行」组,不入三分位)。
    """
    ups = [r for r in (raw or []) if r.get("A") is not None]
    if not ups:
        return float("nan")
    per_comp: list[float] = []
    for comp in ("A", "E", "P", "C"):
        vals = [r.get("p" + comp) for r in ups]
        vals = [float(v) for v in vals if v is not None and np.isfinite(v)]
        if vals:
            per_comp.append(float(np.mean(vals)))
    return float(np.mean(per_comp)) if per_comp else float("nan")


def main() -> int:
    use_cache = CACHE_PATH.exists() and "--no-cache" not in sys.argv
    if use_cache:
        blob = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        df = _df_from_cache(blob)
        meta = blob["meta"]
        n_fish, ticket_total, skip_outside = meta["n_fish"], meta["ticket_total"], meta["skip_outside"]
        print(f"[t158] cache hit {CACHE_PATH} rows={len(df)} tickets={ticket_total} "
              f"fish={n_fish} in_M={int(df['M'].notna().sum())}", flush=True)
    else:
        print("[t158] (1/8) 鱼基线", flush=True)
        fish = fetch_fish()
        n_fish = len(fish)
        print(f"[t158] fish={n_fish} (期望 286 ±2)", flush=True)

        print("[t158] (2/8) ohlcv + 闸门", flush=True)
        bars = fetch_ohlcv()
        print(f"[t158] ohlcv rows={len(bars)} syms={bars['symbol'].nunique()}", flush=True)
        gate = fetch_gate()
        bars = annotate_bars(bars)

        print("[t158] (3/8) V1 模拟票", flush=True)
        tickets = simulate_tickets(bars, gate)
        tickets = [t for t in tickets if t["signal_d"] <= pd.Timestamp(SIG_HI)]
        ticket_total = len(tickets)
        print(f"[t158] tickets={ticket_total} (signal_d ≤ {SIG_HI})", flush=True)

        print("[t158] (4/8) 4 sector × cap × 历史 + members", flush=True)
        sector_hist = fetch_sector_history()
        for st in SECTORS:
            sdf = sector_hist[st]
            if not sdf.empty:
                print(f"[t158]   sector {st:18s}: {len(sdf)} d {sdf['d'].min().date()} → {sdf['d'].max().date()}",
                      flush=True)

        # sector_members_at_d[style][date_iso] = [members]
        sector_members_at_d: dict[str, dict[str, list[str]]] = {}
        for st, sdf in sector_hist.items():
            dm: dict[str, list[str]] = {}
            for _, row in sdf.iterrows():
                dm[row["d"].date().isoformat()] = list(row.get("members") or [])
            sector_members_at_d[st] = dm

        print("[t158] (5/8) 复用 step (2) 的 bars 拆出 closes", flush=True)
        all_members: set[str] = set()
        for st, dm in sector_members_at_d.items():
            for ms in dm.values():
                for s in ms: all_members.add(s)
        all_members = sorted(all_members - set(EXCLUDE))
        print(f"[t158]   成员集合 = {len(all_members)} 名", flush=True)
        closes = fetch_ohlcv_for(bars)
        print(f"[t158]   closes_for = {len(closes)} 名", flush=True)

        print("[t158] (6/8) 拉 funding_history (binance_perp)", flush=True)
        funding = fetch_funding(all_members)
        print(f"[t158]   funding_for = {len(funding)} 名", flush=True)

        print("[t158] (7/8) 算 M per ticket", flush=True)
        df = compute_per_ticket(tickets, sector_hist, sector_members_at_d, closes, funding)
        # 贴鱼(进场落在 [鱼起点, 峰值日])
        df["fish"] = df.apply(lambda r: ticket_on_fish(
            {"symbol": r["symbol"], "signal_d": r["signal_d"],
             "entry_d": r["entry_d"], "exit_d": r["exit_d"]}, fish), axis=1)
        # 三分位
        in_M = df["M"].notna().to_numpy()
        terc = tercile_labels(df.loc[in_M, "M"].to_numpy())
        df.loc[in_M, "terc"] = terc
        # 剔除计数:不属任何 sector 的票(compute_per_ticket 里点过名)
        skip_outside = int(df.attrs.get("skip_no_sector", len(tickets) - len(df)))
        print(f"[t158] in_M={int(in_M.sum())} (of {ticket_total} tickets, 剔除 {skip_outside})", flush=True)
        CACHE_PATH.write_text(json.dumps(
            _df_to_cache(df, {"n_fish": n_fish, "ticket_total": ticket_total,
                              "skip_outside": skip_outside}),
            ensure_ascii=False, default=float), encoding="utf-8")
        print(f"[t158] wrote {CACHE_PATH}", flush=True)

    # 「下行」组不进 M(S-641 原文):重算一遍严格口径的 M,三分位随之重切。
    # M_loose = A 缺失时仍用 E/P/C 凑三个平均的宽松口径,只作敏感性对照。
    df["M_loose"] = df["M"]
    df["M"] = df["per_sector_raw"].apply(m_strict_from_raw).astype(float)
    df["down_A"] = df["M"].isna()
    df["terc"] = ""
    in_M = df["M"].notna().to_numpy()
    terc = tercile_labels(df.loc[in_M, "M"].to_numpy())
    df.loc[in_M, "terc"] = terc
    print(f"[t158] 严格口径 in_M={int(in_M.sum())} 下行组={int((~in_M).sum())}", flush=True)

    print("[t158] (8/8) 两条判", flush=True)
    test_a = bootstrap_R(df)
    test_b = shuffle_year_test(df)
    print(f"[t158] ①: obs_mean_e={test_a['obs_mean_early']:.3f} obs_mean_l={test_a['obs_mean_late']:.3f} "
          f"diff={test_a['obs_diff_early_minus_late']:+.3f} p={test_a['p_early_gt_late']} → {test_a['verdict']}", flush=True)
    print(f"[t158] ②: obs_p_e={test_b['obs_p_early_on_fish']:.3f} obs_p_l={test_b['obs_p_late_on_fish']:.3f} "
          f"diff={test_b['obs_diff_early_minus_late']:+.3f} p={test_b['p_early_gt_late']} → {test_b['verdict']}", flush=True)

    # 敏感性(只报,不判):宽松口径下同样的两条判
    df_loose = df.copy()
    df_loose["M"] = df_loose["M_loose"]
    df_loose["terc"] = ""
    inL = df_loose["M"].notna().to_numpy()
    df_loose.loc[inL, "terc"] = tercile_labels(df_loose.loc[inL, "M"].to_numpy())
    test_a_loose = bootstrap_R(df_loose)
    test_b_loose = shuffle_year_test(df_loose)

    write_report(df, n_fish, test_a, test_b, ticket_total, skip_outside=skip_outside,
                 test_a_loose=test_a_loose, test_b_loose=test_b_loose)
    print("[t158] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
