#!/usr/bin/env python3
"""T-290 — S-769 散户注意力尖峰(CoinGecko 热搜新上榜 / Santiment 社交量 z≥3)之后 7 / 30 天相对篮子。

预注册:REFUTATION_LEDGER S-769(Seth,2026-11-07 12:48 UTC)。只读该条。

口径(照抄预注册):
  A = trending_log:一个代号**连续 7 天不在榜后第一次上榜**的 UTC 日 = 事件日 d
  B = social_daily(santiment / social_volume_total):当日值相对自身前 90 天(≥60 个观测)的 z ≥ 3,
      同代号 30 天去重
  C(只报)= social_daily(santiment / sentiment_weighted_total)同口径 z ≤ −3
  价 = asset_mcap_daily(d 是当日收盘);进场 d+1 收盘 → +7 / +30 天收盘
  超额 = 代币 − 同期时点等权篮(当天有价、市值 ≥ 2,000 万的全部)
  随机日对照 = 同代号、同季度,1,000 次,种子 769

纪律:零分布 / 盈亏只用 src/data/evaluation/apparatus.py;翻页带 order=;每页 ≤ 1000 行;
      事件清单先落文件再取价;只算、不改代码、不做 DDL、不入库。

用法:
  python3 t290_attention.py fetch   # 拉表 → 事件清单落文件 → 再取价
  python3 t290_attention.py run     # 全流程(有缓存则跳过拉取)→ t290_results.json
"""
from __future__ import annotations

import json
import os
import sys
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
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    long_return,
    null_distribution,
    percentile_of,
    random_dates_like,
)

U = os.environ["SUPABASE_URL"].rstrip("/")
K = os.environ["SUPABASE_KEY"]
HDR = {"apikey": K, "Authorization": "Bearer " + K}
CACHE = REPO / ".t290_cache"  # 落在 lane 根上(可列、可断点续拉),不落 /tmp
MCAP_MIN = 20_000_000
SEED = 769
N_NULL = 1000
PRICE_FLOOR = "2025-09-01"  # 价格表只需覆盖 B 臂最早事件(2025-10-20)及其 +31 天


def log(msg: str) -> None:
    print("[t290] " + msg, flush=True)


def q(v) -> str:
    return urllib.parse.quote(str(v), safe="")


def _get(table: str, params: str, tries: int = 4):
    url = U + "/rest/v1/" + table + "?" + params
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (a + 1))
    raise RuntimeError("GET failed: " + table + " :: " + repr(last)[:300])


def _keyset_or(cols, cursor) -> str:
    parts = []
    for i in range(len(cols)):
        conds = [q(cols[j]) + ".eq." + q(cursor[j]) for j in range(i)]
        conds.append(q(cols[i]) + ".gt." + q(cursor[i]))
        parts.append(conds[0] if len(conds) == 1 else "and(" + ",".join(conds) + ")")
    return "or=(" + ",".join(parts) + ")"


def pull(table: str, where: str, cols, order_cols, fname: str):
    """带 order= 的分页拉取(每页 ≤ 1000);keyset 优先,失败退回 offset。

    断点续拉:每页追加写 `<fname>.part`(JSONL)+ `<fname>.cursor`。
    墙钟 60 分钟被打断时,下一轮从游标继续,不用重拉。
    """
    path = CACHE / fname
    part = CACHE / (fname + ".part")
    cpath = CACHE / (fname + ".cursor")
    CACHE.mkdir(parents=True, exist_ok=True)
    if path.exists():
        rows = json.loads(path.read_text())
        log("cache hit " + fname + " rows=" + str(len(rows)))
        return rows
    rows = []
    cursor = None
    if part.exists() and cpath.exists():
        try:
            rows = [json.loads(x) for x in part.read_text().splitlines() if x.strip()]
            cursor = json.loads(cpath.read_text())
            log("resume " + fname + " rows=" + str(len(rows)))
        except Exception as e:  # noqa: BLE001
            log("resume failed " + fname + ": " + repr(e)[:120])
            rows, cursor = [], None
    fh = part.open("a")
    t0 = time.time()
    npage = 0
    try:
        while True:
            params = "select=" + ",".join(cols)
            if where:
                params += "&" + where
            params += "&order=" + ",".join(c + ".asc" for c in order_cols)
            if cursor is not None:
                params += "&" + _keyset_or(order_cols, cursor)
            params += "&limit=1000"
            batch = _get(table, params)
            if not batch:
                break
            fh.write(json.dumps(batch) + "\n")
            fh.flush()
            rows.extend(batch)
            cursor = [batch[-1][c] for c in order_cols]
            cpath.write_text(json.dumps(cursor))
            npage += 1
            if len(batch) < 1000:
                break
            if npage % 20 == 0:
                log("  " + table + " p" + str(npage) + " rows=" + str(len(rows)) +
                    " " + str(int(time.time() - t0)) + "s")
    except Exception as e:  # noqa: BLE001
        log("keyset failed (" + table + "): " + repr(e)[:200] + " -> offset fallback")
        rows = []
        fh.close()
        part.unlink(missing_ok=True)
        cpath.unlink(missing_ok=True)
        fh = part.open("a")
        off = 0
        while True:
            params = "select=" + ",".join(cols)
            if where:
                params += "&" + where
            params += "&order=" + ",".join(c + ".asc" for c in order_cols)
            params += "&limit=1000&offset=" + str(off)
            batch = _get(table, params)
            fh.write(json.dumps(batch) + "\n")
            fh.flush()
            rows.extend(batch)
            if len(batch) < 1000:
                break
            off += 1000
            if off % 20000 == 0:
                log("  " + table + " (offset) " + str(len(rows)) + " " + str(int(time.time() - t0)) + "s")
    fh.close()
    path.write_text(json.dumps(rows))
    part.unlink(missing_ok=True)
    cpath.unlink(missing_ok=True)
    log("fetched " + table + " rows=" + str(len(rows)) + " in " + str(int(time.time() - t0)) + "s")
    return rows


# ── 事件 ────────────────────────────────────────────────────────────────────

def build_events(trend_rows, social_rows, z_thr_b: float = 3.0):
    days = defaultdict(set)
    cg_id = {}
    for r in trend_rows:
        days[r["symbol"]].add(str(r["recorded_at"])[:10])
        if r.get("coingecko_id"):
            cg_id[r["symbol"]] = r["coingecko_id"]
    all_days = set()
    for ds in days.values():
        all_days |= ds
    data_start = min(all_days)
    data_end = max(all_days)

    events_a, first_appear = [], []
    for sym, ds in days.items():
        for d in sorted(ds):
            do = date.fromisoformat(d)
            absent = all((do - timedelta(days=k)).isoformat() not in ds for k in range(1, 8))
            if not absent:
                continue
            first_appear.append((sym, d))
            if (do - date.fromisoformat(data_start)).days >= 7:
                events_a.append((sym, d))

    sv = defaultdict(dict)
    sw = defaultdict(dict)
    slug = {}
    for r in social_rows:
        if r["source"] != "santiment":
            continue
        if r["metric"] == "social_volume_total":
            sv[r["symbol"]][r["d"]] = r["value"]
        elif r["metric"] == "sentiment_weighted_total":
            sw[r["symbol"]][r["d"]] = r["value"]
        if r.get("slug"):
            slug[r["symbol"]] = r["slug"]

    def z_events(series_map, thr, sign, ddof=1):
        cands = []
        for sym, ser in series_map.items():
            ds = sorted(ser)
            for i, d in enumerate(ds):
                lo = (date.fromisoformat(d) - timedelta(days=90)).isoformat()
                prior = [ser[x] for x in ds[:i] if x >= lo]
                if len(prior) < 60:
                    continue
                m = sum(prior) / len(prior)
                var = sum((p - m) ** 2 for p in prior) / max(1, len(prior) - ddof)
                sd = var ** 0.5
                if sd <= 0:
                    continue
                z = (ser[d] - m) / sd
                if (sign > 0 and z >= thr) or (sign < 0 and z <= thr):
                    cands.append((sym, d, z))
        out, last = [], {}
        for sym, d, z in sorted(cands, key=lambda x: (x[0], x[1])):
            do = date.fromisoformat(d)
            if sym in last and (do - last[sym]).days < 30:
                continue
            last[sym] = do
            out.append((sym, d, z))
        return out

    events_b = z_events(sv, z_thr_b, +1)
    events_c = z_events(sw, -3.0, -1)
    events_b_pop = z_events(sv, 3.0, +1, ddof=0)

    return {
        "data_start": data_start,
        "data_end": data_end,
        "trend_symbols": len(days),
        "trend_days": len(all_days),
        "trend_rows": len(trend_rows),
        "A": events_a,
        "A_all_first_appear": first_appear,
        "B": events_b,
        "B_popvar": events_b_pop,
        "C": events_c,
        "slug": slug,
        "cg_id": cg_id,
        "soc_symbols": len(sv),
    }


# ── 价格 / 篮子 ──────────────────────────────────────────────────────────────

def load_prices(price_rows):
    px = defaultdict(dict)
    by_date = defaultdict(dict)
    for r in price_rows:
        sym, d = r["symbol"], r["d"]
        rec = (r.get("price"), r.get("mcap"))
        if sym in px and d in px[sym]:
            continue  # 同一 (symbol,d) 多来源 → 取第一次(按 order= 稳定)
        px[sym][d] = rec
        by_date[d][sym] = rec
    return px, by_date


def make_basket_fn(by_date, px):
    """返回 (d, exit_date, off) → 等权篮收益;成员 = d 当天有价且市值 ≥ 2000 万,入场 d+1+off 收盘、exit_date 收盘。"""
    cache = {}

    def fn(d: str, exit_d: str, off: int = 0):
        key = (d, exit_d, off)
        if key in cache:
            return cache[key]
        entry_d = (date.fromisoformat(d) + timedelta(days=1 + off)).isoformat()
        uni = by_date.get(d)
        out = None
        n_drop = 0
        if uni:
            rets = []
            for sym, (p, m) in uni.items():
                if p is None or m is None or m < MCAP_MIN:
                    continue
                e = px[sym].get(entry_d)
                x = px[sym].get(exit_d)
                if e is None or e[0] is None or x is None or x[0] is None:
                    n_drop += 1
                    continue
                r = long_return(e[0], x[0])
                if r is not None:
                    rets.append(r)
            if rets:
                out = (sum(rets) / len(rets), len(rets), n_drop)
        cache[key] = out
        return out

    return fn


def arm_stats(events, px, by_date, basket, label, off: int = 0):
    """对一组事件算 7 / 30 天超额。事件 = [(sym, d)]。off = 进场日偏移(0 = d+1 收盘,1 = 挪一天)。"""
    rows = []
    n_unmatured = 0
    for sym, d in events:
        do = date.fromisoformat(d)
        d1 = (do + timedelta(days=1 + off)).isoformat()
        d8 = (do + timedelta(days=8 + off)).isoformat()
        d31 = (do + timedelta(days=31 + off)).isoformat()
        ser = px.get(sym, {})
        e = ser.get(d1)
        x7 = ser.get(d8)
        x30 = ser.get(d31)
        b7 = basket(d, d8, off)
        b30 = basket(d, d31, off)
        rec = {"symbol": sym, "d": d, "has_d": (d in ser)}
        if e is None or e[0] is None or x7 is None or x7[0] is None or x30 is None or x30[0] is None:
            rec["status"] = "no_price"
            if x30 is None and do + timedelta(days=31) > date.fromisoformat(max_price_date):
                rec["status"] = "not_matured"
                n_unmatured += 1
            rows.append(rec)
            continue
        if b7 is None or b30 is None:
            rec["status"] = "no_basket"
            rows.append(rec)
            continue
        r7 = long_return(e[0], x7[0])
        r30 = long_return(e[0], x30[0])
        mcap_d = ser[d][1] if d in ser else None
        rec.update({
            "status": "ok",
            "ret7": r7,
            "ret30": r30,
            "basket7": b7[0],
            "basket30": b30[0],
            "excess7": r7 - b7[0],
            "excess30": r30 - b30[0],
            "basket_n30": b30[1],
            "basket_drop30": b30[2],
            "mcap_d": mcap_d,
            "in_basket": bool(mcap_d is not None and mcap_d >= MCAP_MIN),
        })
        rows.append(rec)
    ok = [r for r in rows if r["status"] == "ok"]
    return {"label": label, "n_events": len(events), "rows": rows, "ok": ok,
            "n_no_price": sum(1 for r in rows if r["status"] == "no_price"),
            "n_not_matured": n_unmatured,
            "n_no_basket": sum(1 for r in rows if r["status"] == "no_basket")}


def median(v):
    v = [x for x in v if x is not None and np.isfinite(x)]
    return float(np.median(v)) if v else None


def summarize(arm, null_pct30=None, null_pct7=None):
    ok = arm["ok"]
    ex30 = [r["excess30"] for r in ok]
    ex7 = [r["excess7"] for r in ok]
    dates = sorted(r["d"] for r in ok)
    mid = dates[len(dates) // 2] if dates else None
    lo = [r["excess30"] for r in ok if r["d"] < mid]
    hi = [r["excess30"] for r in ok if r["d"] >= mid]
    srt = sorted(ex30)
    k = max(1, int(round(len(srt) * 0.1)))
    out = {
        "n": len(ok),
        "n_events": arm["n_events"],
        "n_no_price": arm["n_no_price"],
        "n_not_matured": arm["n_not_matured"],
        "n_no_basket": arm["n_no_basket"],
        "median_excess30": median(ex30),
        "median_excess7": median(ex7),
        "frac_neg30": (sum(1 for x in ex30 if x < 0) / len(ex30)) if ex30 else None,
        "frac_neg7": (sum(1 for x in ex7 if x < 0) / len(ex7)) if ex7 else None,
        "split_date": mid,
        "median_excess30_first_half": median(lo),
        "median_excess30_second_half": median(hi),
        "n_first_half": len(lo),
        "n_second_half": len(hi),
        "worst10_mean": float(np.mean(srt[:k])) if srt else None,
        "worst10_median": median(srt[:k]),
        "best10_mean": float(np.mean(srt[-k:])) if srt else None,
        "best10_median": median(srt[-k:]),
        "null_pct30": null_pct30,
        "null_pct7": null_pct7,
        "frac_in_basket": (sum(1 for r in ok if r.get("in_basket")) / len(ok)) if ok else None,
        "median_basket30": median([r["basket30"] for r in ok]),
        "median_ret30": median([r["ret30"] for r in ok]),
    }
    if out["median_excess30_first_half"] is not None and out["median_excess30_second_half"] is not None:
        out["halves_same_sign"] = bool(
            np.sign(out["median_excess30_first_half"]) == np.sign(out["median_excess30_second_half"])
        )
    else:
        out["halves_same_sign"] = None
    return out


def quarter(d: str) -> str:
    return str(d)[:4] + "Q" + str((int(str(d)[5:7]) - 1) // 3 + 1)


def null_for(arm, px, basket, event_dates_by_sym, n_null=N_NULL, seed=SEED, off: int = 0):
    """随机日对照:同代号、同季度;统计量 = 30 天超额中位。"""
    events = [(r["symbol"], r["d"]) for r in arm["rows"] if r["status"] in ("ok", "no_price")]
    events = [(s, d) for s, d in events if d in px.get(s, {})]
    eligible = {}
    excess_cache = {}
    for sym in {s for s, _ in events}:
        own = event_dates_by_sym.get(sym, set())
        cand = []
        for d, (p, m) in px.get(sym, {}).items():
            if d in own:
                continue
            do = date.fromisoformat(d)
            d1 = (do + timedelta(days=1 + off)).isoformat()
            d31 = (do + timedelta(days=31 + off)).isoformat()
            ser = px[sym]
            e = ser.get(d1)
            x30 = ser.get(d31)
            if e is None or e[0] is None or x30 is None or x30[0] is None:
                continue
            b30 = basket(d, d31, off)
            if b30 is None:
                continue
            r30 = long_return(e[0], x30[0])
            if r30 is None:
                continue
            cand.append(d)
            excess_cache[(sym, d)] = r30 - b30[0]
        eligible[sym] = cand

    def one(rng):
        picks = random_dates_like(events, eligible, rng, stratum=quarter)
        vals = []
        for (s0, d0), (s1, d1) in zip(events, picks):
            if d1 is None:
                continue
            v = excess_cache.get((s1, d1))
            if v is not None:
                vals.append(v)
        return median(vals)

    actual = median([r["excess30"] for r in arm["ok"]])
    t0 = time.time()
    log("null " + arm.get("label", "?") + ": events=" + str(len(events)) + " n_null=" + str(n_null))
    null = null_distribution(one, n_null, seed, actual=actual)
    log("null " + arm.get("label", "?") + " done in " + str(int(time.time() - t0)) + "s")
    pct = percentile_of(actual, null)
    null_med = float(np.median(null))
    return {"actual_median30": actual, "null_median30": null_med, "null_pct30": pct,
            "n_null": len(null), "seed": seed,
            "null_q05": float(np.quantile(null, 0.05)),
            "null_q95": float(np.quantile(null, 0.95)),
            "n_events_used": len(events),
            "mean_eligible": float(np.mean([len(v) for v in eligible.values()])) if eligible else 0}


# ── 稳健性 / 证伪诊断(不改预注册判定,只作诚实性检查)────────────────────────

def run_robust(ev, px, by_date, basket, trend_rows, social_rows):
    """返回诊断字典。全部为探索性;预注册的判定已在主结果里算完,不因这里重算。"""
    rob = {}

    # 事件日期(供零分布排除自身事件日)
    ev_dates = defaultdict(set)
    for sym, d in ev["A"]:
        ev_dates[sym].add(d)
    for sym, d, _ in ev["B"]:
        ev_dates[sym].add(d)
    c_dates = defaultdict(set)
    for sym, d, _ in ev["C"]:
        c_dates[sym].add(d)

    # ① 挪一天:进场 d+2 收盘 → d+9 / d+32
    shift = {}
    for key, evs in (("A", [(s, d) for s, d in ev["A"]]),
                     ("B", [(s, d) for s, d, _ in ev["B"]])):
        arm = arm_stats(evs, px, by_date, basket, key + "_shift1", off=1)
        nl = null_for(arm, px, basket, ev_dates, off=1)
        s = summarize(arm, null_pct30=nl["null_pct30"])
        s["null"] = nl
        shift[key] = s
    rob["shift_entry_plus1"] = shift

    # ② C 臂(只报)也给零分布:检验「绝望」方向是否同样预测跑输
    armC = arm_stats([(s, d) for s, d, _ in ev["C"]], px, by_date, basket, "C")
    nlC = null_for(armC, px, basket, c_dates)
    sC = summarize(armC, null_pct30=nlC["null_pct30"])
    sC["null"] = nlC
    rob["C_with_null"] = sC

    # ③ z 阈值扫描:如果 z≥2 与 z≥3 一样差,说明「阈值没干活」
    sweep = {}
    for thr in (2.0, 2.5, 3.0, 3.5, 4.0):
        ev2 = build_events(trend_rows, social_rows, z_thr_b=thr)
        evs = [(s, d) for s, d, _ in ev2["B"]]
        arm = arm_stats(evs, px, by_date, basket, "B_z" + str(thr))
        nl = null_for(arm, px, basket, ev_dates)
        s = summarize(arm, null_pct30=nl["null_pct30"])
        s["null"] = nl
        s["n_events"] = len(evs)
        sweep["z>=" + str(thr)] = s
        log("sweep z>=" + str(thr) + " n=" + str(s["n"]) + " med30=" + str(s["median_excess30"]) +
            " pct=" + str(s["null_pct30"]) + " nullmed=" + str(nl["null_median30"]))
    rob["z_threshold_sweep"] = sweep

    # ④ z 值分桶(单调性)
    armB = arm_stats([(s, d) for s, d, _ in ev["B"]], px, by_date, basket, "B")
    zmap = {(s, d): z for s, d, z in ev["B"]}
    buckets = defaultdict(list)
    for r in armB["ok"]:
        z = zmap.get((r["symbol"], r["d"]))
        if z is None:
            continue
        buckets[min(int(z), 12)].append(r["excess30"])
    rob["z_bucket_median_excess30"] = {
        ("z" + str(k) + "-" + str(k + 1)): {"n": len(v), "median": median(v)}
        for k, v in sorted(buckets.items())
    }
    rob["B_event_z_quantiles"] = {
        "n": len(ev["B"]),
        "min": min((z for _, _, z in ev["B"]), default=None),
        "p25": float(np.quantile([z for _, _, z in ev["B"]], 0.25)) if ev["B"] else None,
        "median": float(np.median([z for _, _, z in ev["B"]])) if ev["B"] else None,
        "p75": float(np.quantile([z for _, _, z in ev["B"]], 0.75)) if ev["B"] else None,
        "max": max((z for _, _, z in ev["B"]), default=None),
        "n_symbols": len({s for s, _, _ in ev["B"]}),
    }

    # ⑤ 事件日期分布(重叠程度)与 A/B 重叠
    mon = defaultdict(lambda: defaultdict(int))
    for sym, d in ev["A"]:
        mon["A"][d[:7]] += 1
    for sym, d, _ in ev["B"]:
        mon["B"][d[:7]] += 1
    rob["events_per_month"] = {k: dict(sorted(v.items())) for k, v in mon.items()}
    setA = {(s, d) for s, d in ev["A"]}
    setB = {(s, d) for s, d, _ in ev["B"]}
    rob["A_B_overlap_same_symbol_day"] = {
        "n_A": len(setA), "n_B": len(setB), "n_both": len(setA & setB),
        "share_of_B": (len(setA & setB) / len(setB)) if setB else None,
        "same_symbol_any_day": len({s for s, _ in setA} & {s for s, _ in setB}),
    }

    # ⑥ 无条件的「同代号随机日」基准:所有有价代号在所有可算 30 天窗口上的超额中位
    all_ex = []
    for sym, ser in px.items():
        for d in ser:
            do = date.fromisoformat(d)
            e = ser.get((do + timedelta(days=1)).isoformat())
            x30 = ser.get((do + timedelta(days=31)).isoformat())
            if e is None or x30 is None or e[0] is None or x30[0] is None:
                continue
            b = basket(d, (do + timedelta(days=31)).isoformat())
            if b is None:
                continue
            r = long_return(e[0], x30[0])
            if r is not None:
                all_ex.append(r - b[0])
    rob["universe_baseline_excess30"] = {
        "n_windows": len(all_ex), "median": median(all_ex),
        "frac_neg": (sum(1 for x in all_ex if x < 0) / len(all_ex)) if all_ex else None,
    }
    log("universe baseline median excess30=" + str(rob["universe_baseline_excess30"]["median"]) +
        " n=" + str(len(all_ex)))
    return rob


# ── main ────────────────────────────────────────────────────────────────────

max_price_date = "2099-01-01"


def main():
    global max_price_date
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    CACHE.mkdir(parents=True, exist_ok=True)

    ev_path = CACHE / "events.json"
    if cmd in ("fetch", "run"):
        trend_rows = pull("trending_log", "", ["id", "recorded_at", "symbol", "coingecko_id",
                                               "trending_rank", "market_cap_rank"], ["id"], "trending.json")
        social_rows = pull("social_daily", "source=eq.santiment",
                           ["source", "symbol", "metric", "d", "value", "slug"],
                           ["symbol", "d", "metric"], "social.json")
        ev = build_events(trend_rows, social_rows)
        ev["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ev_path.write_text(json.dumps(ev))
        log("events written " + str(ev_path) + " at " + ev["built_at"])
        log("A=" + str(len(ev["A"])) + " A_all=" + str(len(ev["A_all_first_appear"])) +
            " B=" + str(len(ev["B"])) + " B_popvar=" + str(len(ev["B_popvar"])) +
            " C=" + str(len(ev["C"])))
        if cmd == "fetch":
            return

    ev = json.loads(ev_path.read_text())
    log("prices pull starts AFTER events file exists (" + ev.get("built_at", "?") + ")")
    price_rows = pull("asset_mcap_daily", "d=gte." + PRICE_FLOOR,
                       ["symbol", "coin_id", "d", "price", "mcap"], ["symbol", "d"], "prices.json")
    px, by_date = load_prices(price_rows)
    global max_price_date
    max_price_date = max(by_date)
    log("price days=" + str(len(by_date)) + " symbols=" + str(len(px)) + " max_d=" + max_price_date)
    basket = make_basket_fn(by_date, px)

    if cmd == "robust":
        trend_rows = json.loads((CACHE / "trending.json").read_text())
        social_rows = json.loads((CACHE / "social.json").read_text())
        rob = run_robust(ev, px, by_date, basket, trend_rows, social_rows)
        out = HERE / "t290_results.json"
        res = json.loads(out.read_text()) if out.exists() else {}
        res["robust"] = rob
        out.write_text(json.dumps(res, indent=2, default=str))
        log("robust written " + str(out))
        return

    event_dates = defaultdict(set)
    for sym, d in ev["A"]:
        event_dates[sym].add(d)
    for sym, d, _ in ev["B"]:
        event_dates[sym].add(d)

    results = {
        "task": "T-290",
        "prereg": "REFUTATION_LEDGER S-769 (Seth, 2026-11-07 12:48 UTC)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "trend_start": ev["data_start"], "trend_end": ev["data_end"],
            "trend_symbols": ev["trend_symbols"], "trend_days": ev["trend_days"],
            "trend_rows": ev["trend_rows"],
            "soc_symbols": ev["soc_symbols"],
            "price_rows": len(price_rows), "price_symbols": len(px),
            "price_days": len(by_date), "price_max_d": max_price_date,
            "price_min_d": min(by_date),
        },
        "event_counts": {
            "A_reentry_after_7d_off": len(ev["A"]),
            "A_incl_first_appearance": len(ev["A_all_first_appear"]),
            "B_social_z3": len(ev["B"]),
            "B_social_z3_popvar_ddof0": len(ev["B_popvar"]),
            "C_sentiment_z-3": len(ev["C"]),
        },
        "arms": {},
    }

    # A 臂(主口径:7 天回看窗口完整在数据内)
    armA = arm_stats([(s, d) for s, d in ev["A"]], px, by_date, basket, "A")
    nA = null_for(armA, px, basket, event_dates)
    results["arms"]["A"] = summarize(armA, null_pct30=nA["null_pct30"])
    results["arms"]["A"]["null"] = nA

    # A 臂敏感性:把「首次上榜」也当事件(日志开头截断的那批)
    armA_all = arm_stats([(s, d) for s, d in ev["A_all_first_appear"]], px, by_date, basket, "A_all")
    nAa = null_for(armA_all, px, basket, event_dates)
    results["arms"]["A_incl_first_appearance"] = summarize(armA_all, null_pct30=nAa["null_pct30"])
    results["arms"]["A_incl_first_appearance"]["null"] = nAa

    # B 臂
    armB = arm_stats([(s, d) for s, d, _ in ev["B"]], px, by_date, basket, "B")
    nB = null_for(armB, px, basket, event_dates)
    results["arms"]["B"] = summarize(armB, null_pct30=nB["null_pct30"])
    results["arms"]["B"]["null"] = nB

    # C 臂(只报不判)
    armC = arm_stats([(s, d) for s, d, _ in ev["C"]], px, by_date, basket, "C")
    results["arms"]["C_report_only"] = summarize(armC)
    results["arms"]["C_report_only"]["null"] = None

    # 判定(A、B 各自,BH 两条)
    verdicts = {}
    for key in ("A", "B"):
        s = results["arms"][key]
        c1 = s["median_excess30"] is not None and s["median_excess30"] < 0
        c2 = s["null_pct30"] is not None and s["null_pct30"] <= 0.05
        c3 = s["halves_same_sign"] is True
        verdicts[key] = {"c1_median30_lt0": bool(c1), "c2_null_pct_le_005": bool(c2),
                         "c3_halves_same_sign": bool(c3),
                         "pass": bool(c1 and c2 and c3)}
    results["verdicts"] = verdicts

    # 代号映射命中率
    px_syms = set(px)
    coin_ids = defaultdict(set)
    for r in price_rows:
        if r.get("coin_id"):
            coin_ids[r["symbol"]].add(r["coin_id"])
    a_syms = {s for s, _ in ev["A"]}
    b_syms = {s for s, _, _ in ev["B"]}
    cg = ev.get("cg_id", {})
    slug = ev.get("slug", {})
    coin_id_index = defaultdict(set)
    for sym, ids in coin_ids.items():
        for cid in ids:
            coin_id_index[cid].add(sym)
    slug_index = defaultdict(set)
    for sym, sg in slug.items():
        slug_index[sg].add(sym)
    mapping = {
        "A_symbol_in_price_table": (len(a_syms & px_syms), len(a_syms)),
        "A_cgid_exact_to_coin_id": (sum(1 for s in a_syms if cg.get(s) in coin_id_index), len(a_syms)),
        "B_symbol_in_price_table": (len(b_syms & px_syms), len(b_syms)),
        "B_slug_exact_to_coin_id": (sum(1 for s in b_syms if slug.get(s) in coin_id_index), len(b_syms)),
        "B_slug_in_trending_symbols": (sum(1 for s in b_syms if slug.get(s) in set(cg)), len(b_syms)),
        "B_symbol_in_trending_symbols": (len(b_syms & set(cg)), len(b_syms)),
    }
    results["mapping"] = {k: {"hit": v[0], "n": v[1], "rate": (v[0] / v[1] if v[1] else None)}
                          for k, v in mapping.items()}

    out = HERE / "t290_results.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    log("results written " + str(out))
    for key in ("A", "B"):
        s = results["arms"][key]
        log(key + ": n=" + str(s["n"]) + " med30=" + str(s["median_excess30"]) +
            " pct=" + str(s["null_pct30"]) + " halves=" + str(s["halves_same_sign"]) +
            " verdict=" + str(results["verdicts"][key]["pass"]))


if __name__ == "__main__":
    main()
