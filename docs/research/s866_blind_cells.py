#!/usr/bin/env python3
"""T-386 / S-866:按卡上的四条定义从零重算 R/L/W/T 格子划分(盲复算),再与 lane-a/T-384 的结果对账。

盲复算的意义:实现不看别人的(卡上明令不许读 `docs/research/s864_same_cell.py` 与
`docs/research/s851_watch_base_rate.py`),对账只在**自己这份跑完、落盘之后**才做。

用法:
    python3 docs/research/s866_blind_cells.py --stage cells
        # 只算自己这边的格子 → docs/research/s866_cells.json(不含 A 道任何信息)
    python3 docs/research/s866_blind_cells.py --stage reconcile --a-results <A道 s864_results.json>
        # 对账 + ETH/SOL 前瞻收益 + 循环平移对照 → docs/research/s866_results.json

只读:所有数据走 Supabase 只读入口(环境里的 SUPABASE_URL / SUPABASE_KEY,值不打印)。
零分布、盈亏、分位/p 值只走 src/data/evaluation/apparatus.py(不另写一遍)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from bisect import bisect_right
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = HERE

START = dt.date(2019, 1, 1)
HOLDOUT = 56          # 最后 56 个有格子的日子留出(不进统计)
SEG_GAP = 5           # 同格里相邻两天间隔 ≤ 5 天算同一段
W_WINDOW = 10         # W 轴:最近 10 个周日收盘(含本周)
W_BACK = 4            # W 轴:4 个周日之前的收盘
TARGET_CELL = "R升|L抽|W坏|T线下"
HORIZONS = (30, 56)
N_SHIFTS = 2000
SHIFT_SEED = 866
SHIFT_MIN = 180       # 平移 k 的下界
ASSETS = ("ETH", "SOL")        # 卡上要求的两个
CROSS_ASSETS = ("ETH", "SOL", "BTC")   # BTC 只是多一个对照(A 道没写它用的是哪只资产)


# ── 验证装置(T-097):唯一来源 ────────────────────────────────────────────────
def _load_apparatus():
    path = os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py")
    spec = importlib.util.spec_from_file_location("cc_apparatus", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cc_apparatus"] = mod
    spec.loader.exec_module(mod)
    return mod


AP = _load_apparatus()

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]


# ── 只读取数 ────────────────────────────────────────────────────────────────
def rest(table: str, query: str, order: str, page: int = 1000):
    """分页读。永远带 order=,每页 ≤ 1000 行(PostgREST 静默截断)。"""
    rows: list[dict] = []
    offset = 0
    while True:
        url = (URL + "/rest/v1/" + table + "?" + query + "&order=" + order
               + "&limit=" + str(page) + "&offset=" + str(offset))
        req = urllib.request.Request(
            url, headers={"apikey": KEY, "Authorization": "Bearer " + KEY})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                chunk = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise SystemExit("HTTP %s on %s: %s" % (e.code, table, e.read().decode()[:300]))
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        offset += page


def load_ust2y():
    rows = rest("macro_daily", "series=eq.ust_2y", "d.asc")
    vals: dict[str, float] = {}
    dup = nulls = 0
    for r in rows:
        v = r.get("value")
        if v is None:
            nulls += 1
            continue
        d = str(r["d"])[:10]
        if d in vals:
            dup += 1
        vals[d] = float(v)
    return vals, dup, nulls, len(rows)


def load_state(feature: str):
    rows = rest("state_daily", "entity=eq.panel&feature=eq." + feature, "d.asc")
    vals: dict[str, float] = {}
    dup = nulls = 0
    for r in rows:
        v = r.get("value")
        if v is None:
            nulls += 1
            continue
        d = str(r["d"])[:10]
        if d in vals:
            dup += 1
        vals[d] = float(v)
    return vals, dup, nulls, len(rows)


def load_closes(symbol: str):
    rows = rest("ohlcv_daily", "symbol=eq." + symbol + "&source=eq.binance_hist", "trade_date.asc")
    vals: dict[str, float] = {}
    dup = 0
    for r in rows:
        c = r.get("close")
        if c is None:
            continue
        d = str(r["trade_date"])[:10]
        if d in vals:
            dup += 1
        vals[d] = float(c)
    return vals, dup, len(rows)


# ── 四条轴 ──────────────────────────────────────────────────────────────────
def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def axis_R(dates: list[str], vals: list[float], day: dt.date):
    """≤d 的最近一个读数(不早于 d−7) 与 ≤d−91 的最近一个读数(不早于 d−98)比。读不到 ⇒ None。"""
    def latest_le(target: dt.date, min_d: dt.date):
        i = bisect_right(dates, target.isoformat())
        if i == 0:
            return None
        j = i - 1
        if _d(dates[j]) < min_d:
            return None
        return vals[j]

    r1 = latest_le(day, day - dt.timedelta(days=7))
    r0 = latest_le(day - dt.timedelta(days=91), day - dt.timedelta(days=98))
    if r1 is None or r0 is None:
        return None, None, None
    return ("升" if r1 > r0 else "降"), r1, r0


def axis_W(btc_dates: list[str], btc_close: dict[str, float]):
    """每个周日判一次,结论从下周一起生效到下一个周日(含)。不足 10 个周日 ⇒ 读不到。"""
    sundays = [d for d in btc_dates if _d(d).weekday() == 6]
    verdict: dict[str, str] = {}
    n_bad = 0
    for j, s in enumerate(sundays):
        if j < W_WINDOW - 1:
            continue
        win = [btc_close[sundays[j - k]] for k in range(W_WINDOW - 1, -1, -1)]
        cs = btc_close[s]
        bad = (cs < sum(win) / float(W_WINDOW)) and (cs < btc_close[sundays[j - W_BACK]])
        v = "坏" if bad else "好"
        if bad:
            n_bad += 1
        day = _d(s)
        for k in range(1, 8):  # 周一 .. 下周日(含)
            verdict[(day + dt.timedelta(days=k)).isoformat()] = v
    return verdict, len(sundays), n_bad


def cell_name(r: str, l: str, w: str, t: str) -> str:
    return "R%s|L%s|W%s|T%s" % (r, l, w, t)


ALL_CELLS = [cell_name(r, l, w, t)
             for r in ("升", "降") for l in ("注", "抽")
             for w in ("好", "坏") for t in ("线上", "线下")]


def build_daily(ust_vals, ss_vals, d200_vals, btc_close, w_verdict):
    ust_dates = sorted(ust_vals)
    ust_list = [ust_vals[x] for x in ust_dates]
    btc_dates = sorted(btc_close)
    daily: dict[str, dict] = {}
    stats = {"calendar_days": 0, "missing_R": 0, "missing_L": 0, "missing_W": 0, "missing_T": 0}
    for ds in btc_dates:
        day = _d(ds)
        if day < START:
            continue
        stats["calendar_days"] += 1
        r, r1, r0 = axis_R(ust_dates, ust_list, day)
        l = ss_vals.get(ds)
        t = d200_vals.get(ds)
        w = w_verdict.get(ds)
        if r is None:
            stats["missing_R"] += 1
        if l is None:
            stats["missing_L"] += 1
        if w is None:
            stats["missing_W"] += 1
        if t is None:
            stats["missing_T"] += 1
        if r is None or l is None or w is None or t is None:
            continue
        daily[ds] = {
            "R": r, "L": "抽" if l < 0 else "注", "W": w, "T": "线下" if t < 0 else "线上",
            "cell": cell_name(r, "抽" if l < 0 else "注", w, "线下" if t < 0 else "线上"),
            "ust_now": r1, "ust_91d": r0, "stable_supply_30d": l, "dist_200": t,
        }
    return daily, stats


def segments_of(days: list[str]) -> list[list[str]]:
    """同一格里相邻两天间隔 ≤ 5 天算同一段。"""
    segs: list[list[str]] = []
    cur: list[str] = []
    for d in days:
        if cur and (_d(d) - _d(cur[-1])).days <= SEG_GAP:
            cur.append(d)
        else:
            if cur:
                segs.append(cur)
            cur = [d]
    if cur:
        segs.append(cur)
    return segs


def cell_table(daily: dict[str, dict], day_list: list[str]):
    by_cell: dict[str, list[str]] = defaultdict(list)
    for d in day_list:
        by_cell[daily[d]["cell"]].append(d)
    out = {}
    for c in ALL_CELLS:
        days = by_cell.get(c, [])
        segs = segments_of(days)
        out[c] = {
            "days": len(days),
            "segments": len(segs),
            "segment_first_days": [s[0] for s in segs],
            "segment_lengths": [len(s) for s in segs],
            "days_list": days,
        }
    return out


# ── 前瞻收益(ETH / SOL)────────────────────────────────────────────────────
class Pricer:
    def __init__(self, closes: dict[str, float]):
        self.dates = sorted(closes)
        self.closes = [closes[x] for x in self.dates]
        self.first_date = self.dates[0] if self.dates else None

    def entry(self, d: str):
        """进场价 = d 当天的收盘;该名那时还没有日线 ⇒ None(没有「用最新收盘顶替」这回事)。

        11-15 修(T-390):原来是 `self.closes[bisect_right(self.dates, d) - 1]` ——
        d 早于第一根日线时下标 = −1 ⇒ 取到**最新一根**收盘当进场价。
        SOL 上市(2020-08-11)前的 32 天因此拿到「2026 年的价 → 2020 年的价」= 约 −98% 的假收益,
        把 SOL 全样本 n 从 2231 抬到 2263、并污染循环平移对照。
        现在走 apparatus.price_on_or_after(max_gap_days=0):d 当天没有收盘就没有进场价。
        (apparatus 文档串 10-14 写过同一个坑:find_idx 返回 −1 ⇒ 下游用 closes[-1]。)
        """
        i = bisect_right(self.dates, (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat())
        j = bisect_right(self.dates, d)
        return AP.price_on_or_after(self.dates[i:j], self.closes[i:j], d, 0)

    def exit(self, target: str, max_gap_days: int = 3):
        """用 apparatus 的 price_on_or_after(传窗口切片,语义不变:早于 target 的日子本来也会被跳过)。"""
        i = bisect_right(self.dates, (dt.date.fromisoformat(target) - dt.timedelta(days=1)).isoformat())
        j = bisect_right(self.dates, (dt.date.fromisoformat(target) + dt.timedelta(days=max_gap_days)).isoformat())
        return AP.price_on_or_after(self.dates[i:j], self.closes[i:j], target, max_gap_days)

    def fwd(self, d: str, horizon: int):
        p_in = self.entry(d)
        if p_in is None:
            return None
        target = (dt.date.fromisoformat(d) + dt.timedelta(days=horizon)).isoformat()
        p_out = self.exit(target)
        return AP.long_return(p_in, p_out)


def summarize(vals: list[float]) -> dict:
    arr = np.asarray([v for v in vals if v is not None and math.isfinite(v)], dtype=float)
    if arr.size == 0:
        return {"n": 0, "median": None, "mean": None, "share_lt_m10": None, "share_gt_p10": None}
    return {
        "n": int(arr.size),
        "median": float(np.median(arr)),
        "mean": float(arr.mean()),
        "share_lt_m10": float((arr < -0.10).mean()),
        "share_gt_p10": float((arr > 0.10).mean()),
    }


def self_check_fwd(pricers, fwd, days):
    """T-390 自检:① 上市前的日子**没有**前瞻收益(不是 0,也不是用最新收盘算出来的假收益);
    ② 有前瞻收益的日子,进场日不早于该资产的第一根日线。返回「上市前的格位数」。"""
    n_pre = 0
    for a, pz in pricers.items():
        for h in HORIZONS:
            for d in days:
                v = fwd[a][h].get(d)
                if d < pz.first_date:
                    assert v is None, ("上市前不得有前瞻收益", a, h, d, v)
                    n_pre += 1
                else:
                    assert v is None or d >= pz.first_date, ("进场日早于第一根日线", a, h, d)
    return n_pre


def _fwd_and_control(mine):
    """ETH / SOL 前瞻收益 + 循环平移对照(reconcile 与 fwd 两个 stage 共用同一段逻辑)。"""
    daily = mine["daily"]
    stat_days = mine["stat_days"]
    tbl_stat = mine["cells_stat"]

    print("[3] 读 ETH / SOL 价格 ……")
    eth, eth_dup, eth_n = load_closes("ETH")
    sol, sol_dup, sol_n = load_closes("SOL")
    btc2, btc2_dup, btc2_n = load_closes("BTC")
    print("    ETH %d 行(去重 %d)  SOL %d 行(去重 %d)  BTC %d 行(去重 %d)"
          % (eth_n, eth_dup, sol_n, sol_dup, btc2_n, btc2_dup))
    pricers = {"ETH": Pricer(eth), "SOL": Pricer(sol), "BTC": Pricer(btc2)}
    print("    第一根日线:ETH %s  SOL %s  BTC %s"
          % (pricers["ETH"].first_date, pricers["SOL"].first_date, pricers["BTC"].first_date))

    fwd: dict[str, dict[str, dict[int, float]]] = {}
    for a, pz in pricers.items():
        fwd[a] = {}
        for h in HORIZONS:
            fwd[a][h] = {d: pz.fwd(d, h) for d in stat_days}

    n_pre = self_check_fwd(pricers, fwd, stat_days)
    print("    自检通过:上市前的 %d 个「资产×horizon×日」格位前瞻收益全为 None;"
          "有收益的进场日均不早于该资产第一根日线" % n_pre)

    per_cell_stats = {}
    for c in ALL_CELLS:
        days_stat = tbl_stat[c]["days_list"]
        seg_first = [s[0] for s in segments_of(days_stat)]
        entry = {}
        for a in CROSS_ASSETS:
            entry[a] = {}
            for h in HORIZONS:
                entry[a]["%dd_day" % h] = summarize([fwd[a][h].get(d) for d in days_stat])
                entry[a]["%dd_segfirst" % h] = summarize([fwd[a][h].get(d) for d in seg_first])
        per_cell_stats[c] = entry

    full = {}
    for a in CROSS_ASSETS:
        full[a] = {}
        for h in HORIZONS:
            full[a]["%dd_day" % h] = summarize([fwd[a][h].get(d) for d in stat_days])
    seg_all_first = []
    for c in ALL_CELLS:
        seg_all_first.extend(s[0] for s in segments_of(tbl_stat[c]["days_list"]))
    for a in CROSS_ASSETS:
        for h in HORIZONS:
            full[a]["%dd_segfirst" % h] = summarize([fwd[a][h].get(d) for d in seg_all_first])

    # ── 今天这一格 ─────────────────────────────────────────────────────
    today = dt.date.today()
    latest_btc = max(daily.keys()) if daily else None
    today_cell = None
    today_axes = None
    today_ref = None
    for cand in (today.isoformat(), latest_btc):
        if cand and cand in daily:
            today_ref = cand
            today_axes = {k: daily[cand][k] for k in ("R", "L", "W", "T")}
            today_cell = daily[cand]["cell"]
            break
    today_stats = per_cell_stats.get(today_cell) if today_cell else None

    # ── 对照:目标格的循环平移 ──────────────────────────────────────────
    print("[4] 循环平移对照(格子 %s)……" % TARGET_CELL)
    control = {"cell": TARGET_CELL, "universe": "stat_days(有格子且去掉最后 %d 天留出)" % HOLDOUT,
               "n_days": len(stat_days), "n_shifts": N_SHIFTS, "seed": SHIFT_SEED,
               "k_range": [SHIFT_MIN, len(stat_days) - SHIFT_MIN], "stats": {}}
    label = np.asarray([1 if daily[d]["cell"] == TARGET_CELL else 0 for d in stat_days], dtype=float)
    in_cell = label.sum()
    for a in CROSS_ASSETS:
        for h in HORIZONS:
            # 宇宙 = 该资产**有 %dd 收益**的日子(生产 same_cell.py 的 u2 口径):
            # 上市前的日子根本没有收益,不该留在平移的标签数组里(否则每次抽样抽到的有效样本数在变)。
            u2 = [d for d in stat_days if fwd[a][h].get(d) is not None]
            v2 = np.asarray([fwd[a][h][d] for d in u2], dtype=float)
            lab2 = np.asarray([1 if daily[d]["cell"] == TARGET_CELL else 0 for d in u2], dtype=float)
            obs_vals = v2[lab2 == 1]
            observed = float(obs_vals.mean()) if obs_vals.size else None

            def fn(rng, v=v2, label=lab2):
                k = int(rng.integers(SHIFT_MIN, len(label) - SHIFT_MIN + 1))
                rolled = np.roll(label, k)
                return float(v[rolled == 1].mean())

            entry = {"observed": observed, "n_in_cell_days": int(lab2.sum()),
                     "n_obs_values": int(obs_vals.size), "n_universe": len(u2),
                     "universe": "stat_days 中该资产有 %dd 收益的日子" % h}
            if observed is None:
                entry["error"] = "目标格在该宇宙里没有可用收益"
            else:
                try:
                    null = AP.null_distribution(fn, N_SHIFTS, SHIFT_SEED, actual=observed)
                    pu = AP.p_upper(observed, null)
                    pl = AP.p_lower(observed, null)
                    nmean = float(np.nanmean(null))
                    entry.update({
                        "null_mean": nmean, "null_std": float(np.nanstd(null)),
                        "p_upper": pu, "p_lower": pl,
                        "p_two_sided": float(min(1.0, 2.0 * min(pu, pl))),
                        # dev 口径 = 生产的 p_shift_mean:离平移均值至少这么远的占比
                        "p_dev": float((np.abs(null - nmean) >= abs(observed - nmean)).mean()),
                        "percentile": AP.percentile_of(observed, null),
                        "n_null": int(len(null)),
                    })
                except AP.NoOpNull as e:
                    entry["error"] = "NoOpNull:%s" % e
            control["stats"]["%s_%dd" % (a, h)] = entry
    # 今天这一格是不是目标格
    control["today_is_target_cell"] = (today_cell == TARGET_CELL)

    return {"per_cell": per_cell_stats, "full_sample": full,
            "today": {"ref_date": today_ref, "cell": today_cell, "axes": today_axes,
                      "stats": today_stats},
            "control": control}


# ── A 道结果的对账(只在 stage reconcile)────────────────────────────────────
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _walk(obj, path=""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk(v, path + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, path + "/%d" % i)


A_W_NAME = {"好": "没坏", "坏": "坏"}   # A 道把 W 轴的「好」写成「没坏」


def to_a_name(cell: str) -> str:
    """我的格子名 → A 道的格子名(只有 W 轴的写法不同:我的「好」= A 道的「没坏」)。"""
    r, l, w, t = cell.split("|")
    return "%s|%s|W%s|%s" % (r, l, A_W_NAME.get(w[1:], w[1:]), t)


def to_my_name(a_cell: str) -> str:
    """A 道的格子名 → 我的格子名。"""
    r, l, w, t = a_cell.split("|")
    return "%s|%s|W%s|%s" % (r, l, {"没坏": "好"}.get(w[1:], w[1:]), t)


def extract_a_table(obj):
    """A 道的 `table`:格子 → {n_episodes, episode_starts, d30/d56(按天 / 按段首)}。"""
    tbl = obj.get("table") if isinstance(obj, dict) else None
    if not isinstance(tbl, dict):
        for _path, node in _walk(obj):
            if isinstance(node, dict) and node and all(
                    isinstance(v, dict) and "n_episodes" in v for v in node.values()):
                tbl = node
                break
    out = {}
    for k, v in (tbl or {}).items():
        if not isinstance(v, dict):
            continue
        d30 = v.get("d30") or {}
        out[str(k)] = {
            "days": d30.get("n_days"),
            "segments": v.get("n_episodes"),
            "episode_starts": list(v.get("episode_starts") or []),
            "d30": d30,
            "d30_by_episode_start": v.get("d30_by_episode_start") or {},
            "d56": v.get("d56") or {},
            "d56_by_episode_start": v.get("d56_by_episode_start") or {},
        }
    return out


def a_cell_of(val):
    """从 A 道逐日记录里取出格子名(尽量兼容几种写法)。"""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for k in ("cell", "格子", "label", "cell_name", "name", "combo", "state"):
            if k in val and isinstance(val[k], str):
                return val[k]
        axes = {}
        for src, dst in (("R", "R"), ("L", "L"), ("W", "W"), ("T", "T")):
            for k in val:
                if str(k).upper() == src and isinstance(val[k], str):
                    axes[dst] = val[k]
        if len(axes) == 4:
            return cell_name(axes["R"], axes["L"], axes["W"], axes["T"])
    return None


def a_axes_of(val):
    if isinstance(val, dict):
        out = {}
        for k, v in val.items():
            ku = str(k).upper()
            if ku in ("R", "L", "W", "T") and isinstance(v, str):
                out[ku] = v
        if len(out) == 4:
            return out
    return None


# ── 主流程 ──────────────────────────────────────────────────────────────────
def stage_cells():
    print("[1] 读数 ……")
    ust, ust_dup, ust_null, ust_n = load_ust2y()
    ss, ss_dup, ss_null, ss_n = load_state("stable_supply_30d")
    d2, d2_dup, d2_null, d2_n = load_state("dist_200")
    btc, btc_dup, btc_n = load_closes("BTC")
    print("    ust_2y %d 行(去重 %d,空 %d)  stable_supply_30d %d 行(去重 %d,空 %d)"
          % (ust_n, ust_dup, ust_null, ss_n, ss_dup, ss_null))
    print("    dist_200 %d 行(去重 %d,空 %d)  BTC binance_hist %d 行(去重 %d)"
          % (d2_n, d2_dup, d2_null, btc_n, btc_dup))

    btc_dates = sorted(btc)
    w_verdict, n_sun, n_bad = axis_W(btc_dates, btc)
    print("    W 轴: %d 个周日,坏 %d 个;首周日 %s" % (n_sun, n_bad, _first_sunday(btc_dates)))

    daily, stats = build_daily(ust, ss, d2, btc, w_verdict)
    labeled = sorted(daily)
    stat_days = labeled[:-HOLDOUT] if len(labeled) > HOLDOUT else labeled
    holdout = labeled[len(stat_days):]
    print("    日历 %d 天(2019-01-01 起 BTC 有收盘);四轴齐 %d 天;统计集 %d 天;留出 %d 天(%s → %s)"
          % (stats["calendar_days"], len(labeled), len(stat_days), len(holdout),
             holdout[0] if holdout else "-", holdout[-1] if holdout else "-"))
    print("    缺读:R %d / L %d / W %d / T %d(不可叠加)"
          % (stats["missing_R"], stats["missing_L"], stats["missing_W"], stats["missing_T"]))

    tbl_all = cell_table(daily, labeled)
    tbl_stat = cell_table(daily, stat_days)
    out = {
        "meta": {
            "task": "T-386", "ledger": "S-866",
            "generated_by": "docs/research/s866_blind_cells.py --stage cells",
            "definitions": "R=macro_daily ust_2y(≤d 近读 vs ≤d-91 近读);L=state_daily panel/stable_supply_30d;T=state_daily panel/dist_200;W=BTC binance_hist 每周日判定",
            "start": START.isoformat(), "holdout_days": HOLDOUT, "seg_gap_days": SEG_GAP,
            "counts": stats,
            "labeled_days": len(labeled), "stat_days": len(stat_days),
            "holdout_first": holdout[0] if holdout else None, "holdout_last": holdout[-1] if holdout else None,
            "ust_rows": ust_n, "state_ss_rows": ss_n, "state_d200_rows": d2_n, "btc_rows": btc_n,
        },
        "cells_all": {c: {k: v for k, v in tbl_all[c].items()} for c in ALL_CELLS},
        "cells_stat": {c: {k: v for k, v in tbl_stat[c].items()} for c in ALL_CELLS},
        "daily": daily,
        "labeled_days": labeled,
        "stat_days": stat_days,
    }
    p = os.path.join(OUT_DIR, "s866_cells.json")
    with open(p, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=False)
    print("[1] 写 %s" % p)
    print()
    print("%-22s %8s %8s %8s %8s" % ("格子", "天(全)", "段(全)", "天(统计)", "段(统计)"))
    for c in ALL_CELLS:
        print("%-22s %8d %8d %8d %8d"
              % (c, tbl_all[c]["days"], tbl_all[c]["segments"], tbl_stat[c]["days"], tbl_stat[c]["segments"]))
    return out


def _first_sunday(btc_dates):
    for d in btc_dates:
        if _d(d).weekday() == 6:
            return d
    return "-"


def stage_reconcile(a_path, a_text=None):
    mine = json.load(open(os.path.join(OUT_DIR, "s866_cells.json")))
    daily = mine["daily"]
    labeled = mine["labeled_days"]
    stat_days = mine["stat_days"]
    tbl_all = mine["cells_all"]
    tbl_stat = mine["cells_stat"]

    a_obj = json.loads(a_text) if a_text is not None else json.load(open(a_path))
    a_tbl = extract_a_table(a_obj)
    print("[2] A 道结果:%s" % a_path)
    print("    顶层键:%s" % list(a_obj.keys())[:20])
    print("    格子表:table(%d 格;A 道 W 轴写「没坏」= 我侧的「好」)" % len(a_tbl))
    print("    A 道 today_cell=%s asof=%s" % (a_obj.get("today_cell"), a_obj.get("asof")))

    # ── 对账:逐格比天数、段数、段首日期 ────────────────────────────────
    # (A 道的文件里没有逐日表 —— 最细只能对到「段首日期」)
    recon_cells = []
    for c in ALL_CELLS:
        an = to_a_name(c)
        a = a_tbl.get(an)
        rec = {
            "cell": c,
            "a_cell_name": an,
            "mine_all": {"days": tbl_all[c]["days"], "segments": tbl_all[c]["segments"]},
            "mine_stat": {"days": tbl_stat[c]["days"], "segments": tbl_stat[c]["segments"]},
            "a": a,
        }
        if a:
            rec["match_days_stat"] = (a["days"] == rec["mine_stat"]["days"])
            rec["match_seg_stat"] = (a["segments"] == rec["mine_stat"]["segments"])
            rec["match_days_all"] = (a["days"] == rec["mine_all"]["days"])
            rec["match_seg_all"] = (a["segments"] == rec["mine_all"]["segments"])
            my_starts = tbl_stat[c]["segment_first_days"]
            a_starts = a["episode_starts"]
            rec["episode_starts_match"] = (my_starts == a_starts)
            rec["episode_starts_mine"] = my_starts
            rec["episode_starts_a"] = a_starts
            div = []
            for d in sorted(set(my_starts) | set(a_starts)):
                if (d in my_starts) == (d in a_starts):
                    continue
                div.append({
                    "date": d,
                    "mine": {"cell": c, "is_segment_start": d in my_starts,
                             "axes": ({k: daily[d][k] for k in ("R", "L", "W", "T")}
                                      if d in daily else None)},
                    "a": {"is_segment_start": d in a_starts, "axes": None},
                })
            rec["divergent_episode_starts_total"] = len(div)
            rec["divergent_episode_starts_first3"] = div[:3]
        recon_cells.append(rec)

    # ── ETH / SOL 前瞻收益 + 循环平移对照(共用函数,reconcile 与 fwd 两个 stage 共用)──
    fwd_block = _fwd_and_control(mine)
    per_cell_stats = fwd_block["per_cell"]
    full = fwd_block["full_sample"]
    today_ref = fwd_block["today"]["ref_date"]
    today_cell = fwd_block["today"]["cell"]
    today_axes = fwd_block["today"]["axes"]
    today_stats = fwd_block["today"]["stats"]
    control = fwd_block["control"]

    # ── A 道的数字与我的数字对一遍(哪只资产对得上)────────────────────────
    a_today_row = a_obj.get("today_cell_row") or {}
    a_uncond = a_obj.get("unconditional") or {}

    def _cmp(mine, arow):
        if not arow or not mine:
            return None
        return {
            "n": [mine.get("n"), arow.get("n_days")],
            "median": [mine.get("median"), arow.get("median")],
            "mean": [mine.get("mean"), arow.get("mean")],
            "share_lt_m10_vs_p_down_big": [mine.get("share_lt_m10"), arow.get("p_down_big")],
            "share_gt_p10_vs_p_up_big": [mine.get("share_gt_p10"), arow.get("p_up_big")],
        }

    cross = {"a_today_cell": a_obj.get("today_cell"), "a_asof": a_obj.get("asof"),
             "my_today_cell": today_cell, "target_cell_pairs": {}, "unconditional_pairs": {},
             "a_control": a_obj.get("control_today_cell")}
    tc = a_obj.get("today_cell")
    if tc:
        tc_mine = to_my_name(tc)
        for a in CROSS_ASSETS:
            for h, key in ((30, "d30"), (56, "d56")):
                cross["target_cell_pairs"]["%s_%dd" % (a, h)] = {
                    "a": a_today_row.get(key),
                    "mine": per_cell_stats.get(tc_mine, {}).get(a, {}).get("%dd_day" % h),
                }
                cross["unconditional_pairs"]["%s_%dd" % (a, h)] = {
                    "a": a_uncond.get(key),
                    "mine": full.get(a, {}).get("%dd_day" % h),
                }

    out = {
        "meta": {
            "task": "T-386", "ledger": "S-866",
            "a_results": a_path,
            "generated_by": "docs/research/s866_blind_cells.py --stage reconcile",
            "holdout_days": HOLDOUT, "seg_gap_days": SEG_GAP,
            "labeled_days": len(labeled), "stat_days": len(stat_days),
        },
        "reconciliation": {
            "per_cell": recon_cells,
            "n_cells_matching_days_stat": sum(1 for r in recon_cells if r.get("match_days_stat")),
            "n_cells_matching_seg_stat": sum(1 for r in recon_cells if r.get("match_seg_stat")),
            "n_cells_matching_days_all": sum(1 for r in recon_cells if r.get("match_days_all")),
            "n_cells_matching_seg_all": sum(1 for r in recon_cells if r.get("match_seg_all")),
            "n_cells_episode_starts_identical": sum(1 for r in recon_cells if r.get("episode_starts_match")),
            "total_divergent_episode_starts": sum(r.get("divergent_episode_starts_total", 0) for r in recon_cells),
            "a_self_checks": a_obj.get("self_checks"),
            "a_coverage": a_obj.get("coverage"),
            "my_self_checks": {
                "days_with_cell": len(labeled), "usable_days": len(stat_days), "n_cells": 16,
                "first": labeled[0] if labeled else None,
                "last_usable": stat_days[-1] if stat_days else None,
            },
        },
        "a_vs_mine_stats": cross,
        "eth_sol": {
            "per_cell": per_cell_stats,
            "full_sample": full,
            "today": {"ref_date": today_ref, "cell": today_cell, "axes": today_axes,
                      "stats": today_stats},
        },
        "control": control,
    }
    p = os.path.join(OUT_DIR, "s866_results.json")
    with open(p, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=False)
    print("[4] 写 %s" % p)

    # ── 人读的摘要 ─────────────────────────────────────────────────────
    print()
    print("=== 格子对账(我侧统计集 vs A 道)===")
    print("%-22s %6s %6s | %6s %6s | %6s %6s %6s"
          % ("格子", "我天", "我段", "A天", "A段", "天同", "段同", "段首同"))
    for r in recon_cells:
        a = r["a"] or {}
        print("%-22s %6d %6d | %6s %6s | %6s %6s %6s"
              % (r["cell"], r["mine_stat"]["days"], r["mine_stat"]["segments"],
                 a.get("days"), a.get("segments"),
                 r.get("match_days_stat"), r.get("match_seg_stat"), r.get("episode_starts_match")))
    rc = out["reconciliation"]
    print("天一致 %d/16 · 段一致 %d/16 · 段首日期完全相同 %d/16 · 段首分歧 %d 个"
          % (rc["n_cells_matching_days_stat"], rc["n_cells_matching_seg_stat"],
             rc["n_cells_episode_starts_identical"], rc["total_divergent_episode_starts"]))
    print("我侧 self_checks:%s" % json.dumps(rc["my_self_checks"], ensure_ascii=False))
    print("A 道 self_checks:%s" % json.dumps(rc["a_self_checks"], ensure_ascii=False))
    print("A 道 coverage:%s" % json.dumps(rc["a_coverage"], ensure_ascii=False))
    for r in recon_cells:
        if r.get("divergent_episode_starts_total"):
            print("  分歧 %s:" % r["cell"])
            for d in r["divergent_episode_starts_first3"]:
                print("    %s 我侧段首=%s 四轴=%s | A 道段首=%s"
                      % (d["date"], d["mine"]["is_segment_start"],
                         json.dumps(d["mine"]["axes"], ensure_ascii=False),
                         d["a"]["is_segment_start"]))

    print()
    print("=== A 道的数字 vs 我的数字(哪只资产对得上)===")
    for k, v in cross["target_cell_pairs"].items():
        print("目标格 %-9s A: %s" % (k, json.dumps(v["a"], ensure_ascii=False)))
        print("            我: %s" % json.dumps(v["mine"], ensure_ascii=False))
    for k, v in cross["unconditional_pairs"].items():
        print("全样本 %-9s A: %s" % (k, json.dumps(v["a"], ensure_ascii=False)))
        print("            我: %s" % json.dumps(v["mine"], ensure_ascii=False))
    print("A 道 control: %s" % json.dumps(cross["a_control"], ensure_ascii=False))
    print()
    print("=== ETH / SOL(统计集 %d 天)===" % len(stat_days))
    for c in ALL_CELLS:
        e = per_cell_stats[c]
        print("%-22s ETH30d 天 n=%-4s 均=%-9s | SOL30d 天 n=%-4s 均=%-9s"
              % (c, e["ETH"]["30d_day"]["n"], _fmt(e["ETH"]["30d_day"]["mean"]),
                 e["SOL"]["30d_day"]["n"], _fmt(e["SOL"]["30d_day"]["mean"])))
    print("全样本 ETH30d:%s  SOL30d:%s"
          % (json.dumps(full["ETH"]["30d_day"]), json.dumps(full["SOL"]["30d_day"])))
    print("今天(%s)的格子:%s 轴=%s" % (today_ref, today_cell, json.dumps(today_axes, ensure_ascii=False)))
    print()
    print("=== 对照(循环平移)===")
    for k, v in control["stats"].items():
        print("%-10s 观测=%-10s 平移均值=%-10s p2=%-8s n=%s"
              % (k, _fmt(v.get("observed")), _fmt(v.get("null_mean")), _fmt(v.get("p_two_sided")),
                 v.get("n_in_cell_days")))
    return out


def stage_fwd():
    """T-390:只重跑 ETH / SOL 前瞻收益 + 循环平移对照(复用已落盘的 s866_cells.json)。

    对账段(A 道)原样继承上一轮的结果 —— 格子划分(四轴)与进场价无关,不受这次修复影响。
    """
    p_cells = os.path.join(OUT_DIR, "s866_cells.json")
    if not os.path.exists(p_cells):
        raise SystemExit("找不到 %s(先跑 --stage cells)" % p_cells)
    mine = json.load(open(p_cells))
    p_old = os.path.join(OUT_DIR, "s866_results.json")
    old = json.load(open(p_old)) if os.path.exists(p_old) else {}

    block = _fwd_and_control(mine)
    out = {
        "meta": {
            "task": "T-390", "ledger": "S-866",
            "generated_by": "docs/research/s866_blind_cells.py --stage fwd",
            "fix": "T-390: Pricer.entry 改走 apparatus.price_on_or_after(max_gap_days=0) —— "
                   "d 早于第一根日线 ⇒ 没有进场价(不再拿最新收盘顶替)",
            "holdout_days": HOLDOUT, "seg_gap_days": SEG_GAP,
            "labeled_days": len(mine["labeled_days"]), "stat_days": len(mine["stat_days"]),
            "inherited_sections": ["reconciliation", "a_vs_mine_stats"],
        },
        "reconciliation": old.get("reconciliation"),
        "a_vs_mine_stats": old.get("a_vs_mine_stats"),
        "eth_sol": {"per_cell": block["per_cell"], "full_sample": block["full_sample"],
                    "today": block["today"]},
        "control": block["control"],
    }
    p = os.path.join(OUT_DIR, "s866_results.json")
    with open(p, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=False)
    print("[5] 写 %s" % p)

    print()
    print("=== 全样本 30 天(统计集 %d 天)===" % len(mine["stat_days"]))
    for a in CROSS_ASSETS:
        s = block["full_sample"][a]["30d_day"]
        print("%-4s n=%-6s 中位=%-11s 均值=%-11s 跌超10%%=%-10s 涨超10%%=%-10s"
              % (a, s["n"], _fmt(s["median"]), _fmt(s["mean"]),
                 _fmt(s["share_lt_m10"]), _fmt(s["share_gt_p10"])))
    print()
    print("=== 对照(循环平移)===")
    for k, v in block["control"]["stats"].items():
        print("%-10s 观测=%-11s 平移均值=%-11s p上尾=%-9s p下尾=%-9s p2=%-9s dev=%-9s 格内=%s/宇宙=%s"
              % (k, _fmt(v.get("observed")), _fmt(v.get("null_mean")), _fmt(v.get("p_upper")),
                 _fmt(v.get("p_lower")), _fmt(v.get("p_two_sided")), _fmt(v.get("p_dev")),
                 v.get("n_in_cell_days"), v.get("n_universe")))
    return out


def _fmt(x):
    if x is None:
        return "-"
    if isinstance(x, float):
        return "%.6g" % x
    return str(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["cells", "reconcile", "fwd"], required=True)
    ap.add_argument("--a-results", default=None)
    a = ap.parse_args()
    if a.stage == "cells":
        stage_cells()
    elif a.stage == "fwd":
        stage_fwd()
    else:
        if not a.a_results:
            raise SystemExit("--stage reconcile 需要 --a-results <A道 s864_results.json>")
        if a.a_results == "-":
            stage_reconcile("stdin", sys.stdin.read())
        else:
            if not os.path.exists(a.a_results):
                raise SystemExit("找不到 %s" % a.a_results)
            stage_reconcile(a.a_results)


if __name__ == "__main__":
    main()
