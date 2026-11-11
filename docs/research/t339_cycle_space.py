#!/usr/bin/env python3
"""T-339 / S-814 周期位置空间:走步检验 add / trim / hold(A 道)。

只读,一字不改生产代码:
- 内核 `src/data/state/cycle_space.py` —— import 并直接调用 features / pit_vectors / read / stance / target_weight
  (外加 analogs / episodes / _fwd 这几个同模块的纯函数,不改一行)。
- 数据 `macro_daily` 五条序列 —— 走生产分页读 `_read_all`(order=d.asc,series.asc;1000 行/页),缓存在
  /Volumes/CometCloudAI/cometcloud-local/research/t339/。
- 零分布 / Brier / 分位 / 指纹 —— 全用 `src/data/evaluation/apparatus.py`(circular_shift / p_upper /
  stationary_bootstrap_index / ab_test / brier / content_fingerprint)。本脚本不另写零分布。

产物(仓库 docs/research/):t339_weekly.csv、t339_results.json。
用法:python3 docs/research/t339_cycle_space.py
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import cycle_space as cs  # noqa: E402
from src.data.evaluation import apparatus as ap  # noqa: E402

CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/research/t339")
CACHE_ROWS = CACHE_DIR / "macro_daily_rows.json"
CACHE_PRICE = CACHE_DIR / "coinmetrics_price_usd.json"
OUT_CSV = HERE / "t339_weekly.csv"
OUT_JSON = HERE / "t339_results.json"

# macro_daily 里现成的序列(只读):内核要的五条 + 两条派生序列的原料
DB_SERIES = ("btc_mvrv", "btc_issuance_usd", "btc_hashrate", "fng")
FETCH_SERIES = tuple(dict.fromkeys(tuple(cs.SERIES) + DB_SERIES))

COST = 0.001                      # 10bp × 换手
EPOCHS = ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20")
BOOT_SEED = 814
NULL_N = 1000
BOOT_N = 2000
BLOCK_W = 26                      # 周


# ── 小工具(非零分布:Spearman / 排名 / 分段只是统计量,零分布一律 apparatus)─────────
def rankdata(a) -> np.ndarray:
    arr = np.asarray(a, dtype=float)
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty(arr.size, dtype=float)
    i = 0
    while i < arr.size:
        j = i
        while j + 1 < arr.size and arr[order[j + 1]] == arr[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 3:
        return None
    rx, ry = rankdata(x), rankdata(y)
    rx -= rx.mean()
    ry -= ry.mean()
    den = math.sqrt(float(rx @ rx) * float(ry @ ry))
    return float(rx @ ry / den) if den > 0 else None


def mondays_between(first: str, last: str):
    d0 = dt.date.fromisoformat(first)
    d0 += dt.timedelta(days=(0 - d0.weekday()) % 7)      # 第一个周一
    out = []
    while d0 <= dt.date.fromisoformat(last):
        out.append(d0.isoformat())
        d0 += dt.timedelta(days=7)
    return out


# ── 数据 ───────────────────────────────────────────────────────────────────────
async def _fetch_rows():
    from src.data.style.header import _read_all
    return await _read_all("macro_daily", {"select": "series,d,value",
                                           "series": "in.(" + ",".join(FETCH_SERIES) + ")",
                                           "order": "d.asc,series.asc"})


async def _fetch_price():
    """Coin Metrics PriceUSD —— 生产抓取器(免密钥)。macro_daily 现在没有 btc_price_usd,
    生产内核 load() 会直接抛 'btc_price_usd 只有 0 天' ⇒ 这里只读抓一次、缓存到研究目录,不入库。"""
    from src.data.market.data_layer import get_coinmetrics_btc
    return await get_coinmetrics_btc(["PriceUSD"], "2011-01-01")


def load_rows():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_ROWS.exists():
        rows = json.loads(CACHE_ROWS.read_text())
        print(f"[cache] macro_daily {len(rows)} 行", flush=True)
    else:
        rows = asyncio.run(_fetch_rows())
        if not rows:
            raise SystemExit("macro_daily 读不到 —— 不是 0 行,别当没有数据")
        CACHE_ROWS.write_text(json.dumps(rows, ensure_ascii=False))
        print(f"[fetch] macro_daily {len(rows)} 行", flush=True)
    if CACHE_PRICE.exists():
        praw = json.loads(CACHE_PRICE.read_text())
        print(f"[cache] PriceUSD {len(praw)} 行", flush=True)
    else:
        praw = asyncio.run(_fetch_price())
        if not praw:
            raise SystemExit("Coin Metrics PriceUSD 读不到")
        CACHE_PRICE.write_text(json.dumps(praw, ensure_ascii=False))
        print(f"[fetch] PriceUSD {len(praw)} 行", flush=True)
    return rows, praw


def split_series(rows):
    by = {}
    for r in rows:
        s, d, v = r.get("series"), r.get("d"), r.get("value")
        if s and v is not None and d is not None:
            by.setdefault(s, {})[str(d)[:10]] = float(v)
    return by


def assemble(rows, praw):
    """五条序列 —— 内核 features() 需要的形状。两条派生序列用生产函数
    `src/data/market/btc_cycle.derived_rows`(Puell = 当日发行美元 ÷ 自身 365 日均值;
    算力 30 天变化 = ln(近 7 日均值 ÷ 30 天前 7 日均值)),与生产入库脚本同一条路。"""
    from src.data.market import btc_cycle
    all_by = split_series(rows)
    by = {s: dict(all_by.get(s, {})) for s in cs.SERIES}
    base_rows = [{"series": s, "d": d, "value": v} for s in ("btc_issuance_usd", "btc_hashrate")
                 for d, v in all_by.get(s, {}).items()]
    derived = btc_cycle.derived_rows(base_rows, "2011-01-01")
    for r in derived:
        s, d, v = r.get("series"), r.get("d"), r.get("value")
        if s in by and v is not None:
            by[s][d] = float(v)
    price = {}
    for r in praw:
        d = str(r.get("time") or "")[:10]
        v = r.get("PriceUSD")
        if len(d) == 10 and v is not None:
            price[d] = float(v)
    by["btc_price_usd"] = price
    return by, {"db_series": list(DB_SERIES), "derived": list(btc_cycle.DERIVED),
                "price_source": "coinmetrics_community PriceUSD(研究缓存,未入库)",
                "macro_daily_missing": [s for s in cs.SERIES if s not in DB_SERIES]}


# ── 周度走步 ───────────────────────────────────────────────────────────────────
def weekly_rows(vectors, price, k: int):
    """每个周一:内核 read + 实现 fwd180。k 可变(K 敏感性用)。"""
    days = sorted(price)
    out = []
    for m in mondays_between(days[0], days[-1]):
        if m not in price:
            continue
        r = cs.read(vectors, price, m, k=k)
        if not r.get("ok"):
            continue
        fwd = cs._fwd(price, m, cs.HORIZON_D)
        vec = vectors.get(m) or []
        out.append({
            "d": m,
            "z": list(vec),
            "n": r.get("n"),
            "episodes": r.get("episodes"),
            "tilt_excess": r.get("tilt_excess"),
            "stance": cs.stance(r),
            "weight": cs.target_weight(cs.stance(r)),
            "fwd180": fwd,
            "p_up": r["probs"]["up"],
            "p_down": r["probs"]["down"],
            "p_flat": r["probs"]["flat"],
            "base_up": r["base"]["up"],
            "base_down": r["base"]["down"],
            "base_flat": max(0.0, 1.0 - r["base"]["up"] - r["base"]["down"]),
        })
    return out


def pit_selfcheck(vectors, price, by, rows, n_check: int = 20, seed: int = 339):
    """随机 20 个周一:删掉其后的数据重算,读数逐位相同。"""
    cand = [r["d"] for r in rows]
    rng = np.random.default_rng(seed)
    pick = list(rng.choice(cand, size=min(n_check, len(cand)), replace=False))
    pick.sort()
    same, detail = 0, []
    for m in pick:
        trunc = {s: {d: v for d, v in sv.items() if d <= m} for s, sv in by.items()}
        v2 = cs.pit_vectors(cs.features(trunc["btc_price_usd"], trunc["btc_mvrv"], trunc["btc_puell"],
                                        trunc["btc_hash_30d"], trunc["fng"]))
        r2 = cs.read(v2, trunc["btc_price_usd"], m)
        r1 = next(r for r in rows if r["d"] == m)
        z1, z2 = vectors.get(m), v2.get(m)
        bits = {
            "z": (z1 == z2),
            "n": (r1["n"] == r2.get("n")),
            "episodes": (r1["episodes"] == r2.get("episodes")),
            "tilt_excess": (r1["tilt_excess"] == r2.get("tilt_excess")),
            "stance": (r1["stance"] == cs.stance(r2)),
            "probs": (r1["p_up"] == r2.get("probs", {}).get("up")
                      and r1["p_down"] == r2.get("probs", {}).get("down")
                      and r1["p_flat"] == r2.get("probs", {}).get("flat")),
        }
        ok = all(bits.values())
        same += int(ok)
        detail.append({"d": m, "identical": ok, "fields": bits,
                       "tilt_full": r1["tilt_excess"], "tilt_trunc": r2.get("tilt_excess")})
    return {"n_checked": len(pick), "n_identical": same, "all_identical": same == len(pick),
            "dates": pick, "detail": detail}


# ── 配置级模拟(周一收盘定权重、次日收盘生效、10bp × 换仓、现金 0)──────────────────
def sim_weights(daily, mondays, wmap, base_w: float = 0.70):
    """daily: [(d, ret)];权重 = 最近一个 ≤ d−2 的周一的权重;换仓成本记在「周一 + 1 天」那天。"""
    order = sorted(mondays)
    idx = {m: i for i, m in enumerate(order)}
    j = -1
    eq, peak, costs = 1.0, 1.0, 0.0
    curve = []
    for d, r in daily:
        lim = (dt.date.fromisoformat(d) - dt.timedelta(days=2)).isoformat()
        while j + 1 < len(order) and order[j + 1] <= lim:
            j += 1
        w = wmap[order[j]] if j >= 0 else base_w
        cost = 0.0
        prev_day = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        if prev_day in idx:                       # 昨天是决策周一 ⇒ 今天收盘换仓
            k = idx[prev_day]
            w_new = wmap[prev_day]
            w_old = wmap[order[k - 1]] if k > 0 else base_w
            cost = COST * abs(w_new - w_old)
        rp = w * r - cost
        costs += cost
        eq *= (1.0 + rp)
        peak = max(peak, eq)
        curve.append((d, eq, rp, peak))
    maxdd = min((e / p - 1.0) for _, e, _, p in curve) if curve else 0.0
    total = eq - 1.0
    span_d = (dt.date.fromisoformat(curve[-1][0]) - dt.date.fromisoformat(curve[0][0])).days if curve else 0
    years = max(span_d / 365.0, 1e-9)
    ann = (1.0 + total) ** (1.0 / years) - 1.0 if total > -1 else -1.0
    return {
        "total_return": total,
        "annualized": ann,
        "max_drawdown": maxdd,
        "calmar": (total / abs(maxdd)) if maxdd < 0 else None,
        "calmar_ann": (ann / abs(maxdd)) if maxdd < 0 else None,
        "cost_paid": costs,
        "n_days": len(curve),
        "span_years": years,
        "final_equity": eq,
    }


def run_allocation(rows, price):
    """配置级检验 (c)。"""
    days = sorted(price)
    daily = [(days[i], price[days[i]] / price[days[i - 1]] - 1.0) for i in range(1, len(days))]
    mondays = [r["d"] for r in rows]
    wmap = {r["d"]: r["weight"] for r in rows}
    first_m = mondays[0]
    win = [(d, r) for d, r in daily if d > first_m]
    strat = sim_weights(win, mondays, wmap)
    hold = sim_weights(win, mondays, {m: 0.70 for m in mondays})
    # 零分布:权重日程整体循环平移(26 周块、1000 次、种子 814)
    arr = [wmap[m] for m in mondays]
    rng = np.random.default_rng(BOOT_SEED)
    null = []
    for _ in range(NULL_N):
        sh = ap.circular_shift(arr, rng, block=BLOCK_W)
        null.append(sim_weights(win, mondays, {m: float(sh[i]) for i, m in enumerate(mondays)})["calmar"])
    null = [x for x in null if x is not None and math.isfinite(x)]
    p = ap.p_upper(strat["calmar"], null)
    return {"strategy": strat, "hold70": hold,
            "null_calmar": {"n": len(null), "p_upper": p,
                            "q50": float(np.quantile(null, 0.5)) if null else None,
                            "q95": float(np.quantile(null, 0.95)) if null else None,
                            "max": float(np.max(null)) if null else None},
            "judge": {
                "total_return_ge_hold70": strat["total_return"] >= hold["total_return"],
                "maxdd_shallower_by_5pp": (hold["max_drawdown"] - strat["max_drawdown"]) >= 0.05,
                "calmar_p_upper_le_010": (p is not None and p <= 0.10),
            }}


# ── (d) 四轮周期的极端 ──────────────────────────────────────────────────────────
def cycle_table(rows, price):
    days = sorted(price)
    stance_by_d = {r["d"]: r for r in rows}
    mons = sorted(stance_by_d)
    bounds = list(EPOCHS) + [days[-1]]

    def around(center, days_n=30):
        c = dt.date.fromisoformat(center)
        lo = (c - dt.timedelta(days=days_n)).isoformat()
        hi = (c + dt.timedelta(days=days_n)).isoformat()
        return [m for m in mons if lo <= m <= hi]

    out = []
    tops, bottoms = [], []
    for i, start in enumerate(EPOCHS):
        rng_end = bounds[i + 1]
        seg = [d for d in days if start <= d < rng_end]
        if not seg:
            continue
        top = max(seg, key=lambda d: price[d])
        tops.append((start, top, price[top]))
        nxt = None
        if i + 1 < len(EPOCHS):
            seg2 = [d for d in days if top < d < bounds[i + 1]]
        else:
            seg2 = [d for d in days if d > top]
        if seg2:
            bot = min(seg2, key=lambda d: price[d])
            bottoms.append((start, bot, price[bot]))
        else:
            bot = None
        top_weeks = around(top)
        bot_weeks = around(bot) if bot else []
        out.append({
            "epoch_start": start,
            "epoch_end": rng_end,
            "top_d": top, "top_close": price[top],
            "top_weeks": [{"d": m, "stance": stance_by_d[m]["stance"], "tilt": stance_by_d[m]["tilt_excess"],
                           "episodes": stance_by_d[m]["episodes"]} for m in top_weeks],
            "bottom_d": bot, "bottom_close": price[bot] if bot else None,
            "bottom_weeks": [{"d": m, "stance": stance_by_d[m]["stance"], "tilt": stance_by_d[m]["tilt_excess"],
                              "episodes": stance_by_d[m]["episodes"]} for m in bot_weeks],
            "top_stances": sorted({stance_by_d[m]["stance"] for m in top_weeks}),
            "bottom_stances": sorted({stance_by_d[m]["stance"] for m in bot_weeks}),
            "has_trim_near_top": any(stance_by_d[m]["stance"] == "trim" for m in top_weeks),
            "has_add_near_bottom": any(stance_by_d[m]["stance"] == "add" for m in bot_weeks),
            "has_add_near_top": any(stance_by_d[m]["stance"] == "add" for m in top_weeks),
            "has_trim_near_bottom": any(stance_by_d[m]["stance"] == "trim" for m in bot_weeks),
            "n_top_weeks": len(top_weeks), "n_bottom_weeks": len(bot_weeks),
        })
    return {
        "cycles": out,
        "judge": {
            "no_add_near_top": all(not c["has_add_near_top"] for c in out),
            "no_trim_near_bottom": all(not c["has_trim_near_bottom"] for c in out),
            "n_tops_with_trim": sum(1 for c in out if c["has_trim_near_top"]),
            "n_bottoms_with_add": sum(1 for c in out if c["has_add_near_bottom"]),
            "n_tops": len(out),
        }}


# ── 单维基线(另报,不判)──────────────────────────────────────────────────────────
def single_dim_tilt(vectors, price, d, dim, k=cs.K, horizon=cs.HORIZON_D):
    """只有一维的同款空间(同样的 K / 收缩 / 阈值):距离 = |z_t − z_s|。研究脚本内的复刻,不改内核。"""
    tv = vectors.get(d)
    if not tv or tv[dim] is None:
        return None
    cutoff = (dt.date.fromisoformat(d) - dt.timedelta(days=horizon + 1)).isoformat()
    cand = []
    for s, v in vectors.items():
        if s > cutoff or v[dim] is None:
            continue
        cand.append((abs(tv[dim] - v[dim]), s))
    near = sorted(cand)[:k]
    fw = [(s, cs._fwd(price, s, horizon)) for _, s in near]
    fw = [(s, f) for s, f in fw if f is not None]
    if not fw:
        return None
    allf = [f for s in vectors if s <= cutoff and (f := cs._fwd(price, s, horizon)) is not None]
    if not allf:
        return None
    base = {"down": sum(f <= cs.DOWN for f in allf) / len(allf), "up": sum(f >= cs.UP for f in allf) / len(allf)}
    vals = [f for _, f in fw]
    raw = {"down": sum(f <= cs.DOWN for f in vals) / len(vals), "up": sum(f >= cs.UP for f in vals) / len(vals)}
    ep = cs.episodes([s for s, _ in fw])
    w = ep / (ep + cs.SHRINK_M)
    p = {k: w * raw[k] + (1 - w) * base[k] for k in ("down", "up")}
    return (p["up"] - p["down"]) - (base["up"] - base["down"])


def main():
    t0 = time.time()
    rows_raw, praw = load_rows()
    by, prov = assemble(rows_raw, praw)
    price = by["btc_price_usd"]
    input_rows = [{"series": s, "d": d, "value": v} for s in cs.SERIES for d, v in sorted(by[s].items())]
    fingerprint = ap.content_fingerprint(input_rows, ["series", "d", "value"])
    fp_macro = ap.content_fingerprint(rows_raw, ["series", "d", "value"])
    print(f"[data] price {len(price)} 天 {min(price)}→{max(price)}; 各序列 "
          f"{ {s: len(by[s]) for s in cs.SERIES} }", flush=True)

    feats = cs.features(price, by["btc_mvrv"], by["btc_puell"], by["btc_hash_30d"], by["fng"])
    vectors = cs.pit_vectors(feats)
    print(f"[kernel] features {len(feats)} 天 / vectors {len(vectors)} 天", flush=True)

    rows = weekly_rows(vectors, price, k=cs.K)
    print(f"[weekly] {len(rows)} 个周一有读数", flush=True)

    # CSV
    cols = (["d"] + [f"z_{d}" for d in cs.DIMS] +
            ["n_near", "episodes", "tilt_excess", "stance", "fwd180", "p_up", "p_down", "base_up", "base_down"])
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(cols)
        for r in rows:
            wtr.writerow([r["d"]] + ["" if v is None else v for v in r["z"]] +
                         [r["n"], r["episodes"], repr(r["tilt_excess"]), r["stance"],
                          "" if r["fwd180"] is None else repr(r["fwd180"]),
                          repr(r["p_up"]), repr(r["p_down"]), repr(r["base_up"]), repr(r["base_down"])])
    print(f"[csv] {OUT_CSV} ({len(rows)} 行)", flush=True)

    known = [r for r in rows if r["fwd180"] is not None]
    tilts = np.array([r["tilt_excess"] for r in known], dtype=float)
    fwds = np.array([r["fwd180"] for r in known], dtype=float)
    print(f"[sample] 有实现 fwd180 的周一 {len(known)} 个: {known[0]['d']} → {known[-1]['d']}", flush=True)

    # (a) Spearman + 循环平移零分布
    rho = spearman(tilts, fwds)
    rng = np.random.default_rng(BOOT_SEED)
    null_a = []
    for _ in range(NULL_N):
        null_a.append(spearman(tilts, ap.circular_shift(fwds, rng, block=BLOCK_W)))
    null_a = [x for x in null_a if x is not None]
    p_a = ap.p_upper(rho, null_a)
    a_res = {"n_weeks": len(known), "spearman": rho, "p_upper": p_a,
             "null_n": len(null_a), "null_q50": float(np.quantile(null_a, 0.5)),
             "null_q95": float(np.quantile(null_a, 0.95)),
             "judge": {"spearman_ge_020": (rho is not None and rho >= 0.20),
                       "p_upper_le_005": (p_a is not None and p_a <= 0.05)}}
    print(f"(a) spearman={rho:.4f} p_upper={p_a}", flush=True)

    # (b) 三档 Brier
    cats = []
    for r in known:
        f = r["fwd180"]
        y = [1.0 if f <= cs.DOWN else 0.0, 0.0, 1.0 if f >= cs.UP else 0.0]
        cats.append((r, y))
    ps = np.array([[r["p_down"], r["p_flat"], r["p_up"]] for r, _ in cats])
    pb = np.array([[r["base_down"], r["base_flat"], r["base_up"]] for r, _ in cats])
    ys = np.array([y for _, y in cats])
    brier_shrunk = sum(ap.brier(ps[:, c].tolist(), ys[:, c].tolist()) for c in range(3))
    brier_base = sum(ap.brier(pb[:, c].tolist(), ys[:, c].tolist()) for c in range(3))
    week_shrunk = ((ps - ys) ** 2).sum(axis=1)
    week_base = ((pb - ys) ** 2).sum(axis=1)
    diff = week_shrunk - week_base                  # 负 = 收缩后的 p 更好
    idx = ap.stationary_bootstrap_index(len(diff), float(BLOCK_W), BOOT_N, np.random.default_rng(BOOT_SEED))
    boot = diff[idx].mean(axis=1)
    q05, q95 = float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95))
    ab = ap.ab_test(week_shrunk.tolist(), week_base.tolist(), mean_block=float(BLOCK_W),
                    n_boot=BOOT_N, seed=BOOT_SEED)
    b_res = {"brier3_shrunk": brier_shrunk, "brier3_unconditional": brier_base,
             "mean_week_diff_shrunk_minus_base": float(diff.mean()),
             "paired_block_boot_q05": q05, "paired_block_boot_q95": q95,
             "paired_block_boot_n": BOOT_N, "paired_block_boot_block_w": BLOCK_W, "paired_block_boot_seed": BOOT_SEED,
             "ab_test": {k: ab[k] for k in ("n_days", "ci95_log_diff", "p_b_le_a", "p_b_ge_a", "verdict", "underpowered")},
             "judge": {"brier_shrunk_lt_base": brier_shrunk < brier_base,
                       "boot_q95_lt_0": q95 < 0}}
    print(f"(b) Brier shrunk={brier_shrunk:.4f} base={brier_base:.4f} q95(diff)={q95:.5f}", flush=True)

    # (c) 配置
    alloc = run_allocation(rows, price)
    print(f"(c) 策略总收益 {alloc['strategy']['total_return']:.3f} vs HOLD70 {alloc['hold70']['total_return']:.3f}; "
          f"maxDD {alloc['strategy']['max_drawdown']:.3f} vs {alloc['hold70']['max_drawdown']:.3f}; "
          f"calmar p={alloc['null_calmar']['p_upper']}", flush=True)

    # (d) 四轮周期
    cyc = cycle_table(rows, price)
    print(f"(d) {cyc['judge']}", flush=True)

    # (e) 两半
    h = len(known) // 2
    rho1 = spearman(tilts[:h], fwds[:h])
    rho2 = spearman(tilts[h:], fwds[h:])
    e_res = {"split_date": known[h]["d"], "n_first": h, "n_second": len(known) - h,
             "spearman_first": rho1, "spearman_second": rho2,
             "judge": {"same_sign": (rho1 is not None and rho2 is not None
                                    and (rho1 > 0) == (rho2 > 0)
                                    and rho1 != 0 and rho2 != 0)}}
    print(f"(e) ρ1={rho1:.4f} ρ2={rho2:.4f}", flush=True)

    # 另报:单维基线 / 占比 / 换仓 / 独立区间 / K 敏感性
    dim_mvrv = cs.DIMS.index("mvrv")
    dim_dist = cs.DIMS.index("dist_200")
    base_mvrv, base_dist = [], []
    for r in known:
        t1 = single_dim_tilt(vectors, price, r["d"], dim_mvrv)
        t2 = single_dim_tilt(vectors, price, r["d"], dim_dist)
        base_mvrv.append(t1 if t1 is not None else np.nan)
        base_dist.append(t2 if t2 is not None else np.nan)
    # 原始单指标:MVRV 的扩张分位(在 t 之前的历史里的分位)与 dist_200 的 z
    feat = cs.features(price, by["btc_mvrv"], by["btc_puell"], by["btc_hash_30d"], by["fng"])
    mvrv_hist, pct_mvrv, z_dist = [], [], []
    for r in known:
        d = r["d"]
        prior = [feat[x][0] for x in sorted(feat) if x < d and feat[x][0] is not None]
        cur = feat[d][0]
        pct_mvrv.append((sum(1 for v in prior if v < cur) / len(prior)) if (prior and cur is not None) else np.nan)
        mvrv_hist.append(cur)
        z_dist.append(r["z"][dim_dist])
    extra = {
        "single_dim_space": {
            "mvrv_only_rho": spearman(base_mvrv, fwds),
            "dist200_only_rho": spearman(base_dist, fwds),
        },
        "single_predictor": {
            "mvrv_expansion_pct_rho": spearman(pct_mvrv, fwds),
            "dist200_z_rho": spearman(z_dist, fwds),
        },
        "stance_share": {s: sum(1 for r in rows if r["stance"] == s) / len(rows) for s in ("add", "trim", "hold")},
        "stance_counts": {s: sum(1 for r in rows if r["stance"] == s) for s in ("add", "trim", "hold")},
        "n_weeks_total": len(rows),
        "turnover": None,
        "independent_180d_intervals": None,
        "K_sensitivity": {},
    }
    # 换仓次数:权重变化
    ws = [r["weight"] for r in rows]
    changes = sum(1 for i in range(1, len(ws)) if ws[i] != ws[i - 1])
    span_years = (dt.date.fromisoformat(rows[-1]["d"]) - dt.date.fromisoformat(rows[0]["d"])).days / 365.0
    yearly = []
    for i, r in enumerate(rows):
        y = r["d"][:4]
        if not yearly or yearly[-1][0] != y:
            yearly.append([y, 0])
        if i > 0 and r["weight"] != rows[i - 1]["weight"]:
            yearly[-1][1] += 1
    extra["turnover"] = {"n_changes": changes, "years": span_years, "per_year": changes / span_years,
                         "max_in_any_year": max((c for _, c in yearly), default=0),
                         "by_year": {y: c for y, c in yearly}}
    first_known, last_known = dt.date.fromisoformat(known[0]["d"]), dt.date.fromisoformat(known[-1]["d"])
    extra["independent_180d_intervals"] = (last_known - first_known).days // cs.HORIZON_D
    extra["sample_span"] = {"first_monday": known[0]["d"], "last_monday": known[-1]["d"],
                            "span_days": (last_known - first_known).days}
    for k in (30, 120):
        t0k = time.time()
        rk = weekly_rows(vectors, price, k=k)
        kk = [r for r in rk if r["fwd180"] is not None]
        tk = np.array([r["tilt_excess"] for r in kk], dtype=float)
        fk = np.array([r["fwd180"] for r in kk], dtype=float)
        rho_k = spearman(tk, fk)
        rngk = np.random.default_rng(BOOT_SEED)
        nullk = [spearman(tk, ap.circular_shift(fk, rngk, block=BLOCK_W)) for _ in range(NULL_N)]
        nullk = [x for x in nullk if x is not None]
        extra["K_sensitivity"][f"K={k}"] = {
            "spearman": rho_k, "p_upper": ap.p_upper(rho_k, nullk),
            "stance_share": {s: sum(1 for r in rk if r["stance"] == s) / len(rk) for s in ("add", "trim", "hold")},
            "n_weeks": len(kk), "secs": round(time.time() - t0k, 1)}
        print(f"[K={k}] rho={rho_k:.4f} p={extra['K_sensitivity'][f'K={k}']['p_upper']}", flush=True)

    results = {
        "task": "T-339",
        "ledger": "S-814",
        "lane": "lane-a",
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kernel": {"file": "src/data/state/cycle_space.py", "code_ref": cs.CODE_REF,
                   "dims": list(cs.DIMS), "K": cs.K, "min_hist": cs.MIN_HIST, "min_shared": cs.MIN_SHARED,
                   "horizon_d": cs.HORIZON_D, "shrink_m": cs.SHRINK_M, "tilt_on": cs.TILT_ON,
                   "min_episodes": cs.MIN_EPISODES, "weights": {"add": cs.W_ADD, "trim": cs.W_TRIM, "hold": cs.W_BASE},
                   "down": cs.DOWN, "up": cs.UP},
        "data": {"source": "macro_daily + Coin Metrics PriceUSD(缓存)", "series": list(cs.SERIES),
                 "n_rows": len(rows_raw),
                 "days_per_series": {s: len(by[s]) for s in cs.SERIES},
                 "price_first": min(price), "price_last": max(price),
                 "fingerprint": fingerprint,
                 "fingerprint_macro_daily_raw": fp_macro,
                 "provenance": prov,
                 "cache": [str(CACHE_ROWS), str(CACHE_PRICE)]},
        "sample": {"n_mondays_with_read": len(rows), "n_with_known_fwd180": len(known),
                   "first": known[0]["d"], "last": known[-1]["d"]},
        "pit_selfcheck": pit_selfcheck(vectors, price, by, rows),
        "criteria": {"a": a_res, "b": b_res, "c": alloc, "d": cyc, "e": e_res},
        "extra": extra,
        "artifacts": {"weekly_csv": str(OUT_CSV), "results_json": str(OUT_JSON)},
    }
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[done] {OUT_JSON} ({time.time() - t0:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
