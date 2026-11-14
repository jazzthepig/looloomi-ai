#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-383(lane-c,2026-11-14):T-348-19 / T-348-21 补述。

要回答的问题(卡上 acceptance):
  ① S-681 H2 / H4 两族在 2026-10-01 → 11-09(库里最新 11-13)有没有新入场信号?
  ② 两条已入账条目的概率来源(样本内 62 日滚动频率)、重叠窗口数、10-01 后状态、C0 单一口径
  ③ 零信号对照:族累计 vs 随机组合,报 H4 +11.28% / H2 −32.03% 的分位

只读来源:
  docs/research/t348_r3_families.csv            族曲线缓存(末日 11-09)
  docs/research/t348_r5_results.json           第五轮汇总(C0 长账本口径)
  docs/research/s681_h2_pump_fade_results.json  H2 原始票(止 09-30)
  docs/research/s681_h4_bear_rally_fail_results.json  H4 原始票(止 09-30)
  <DATA>/research/s681/_um_daily.jsonl          perp 日线(止 2026-09-30)
  <DATA>/research/s681/_um_funding.jsonl        资金费
  Supabase 只读:perp_bv_daily(日线,到 2026-11-13)/ v_funding_daily(资金费,到 2026-11-14)

规则一行不改:扫描用仓库里 s681_h2_pump_fade.py / s681_h4_bear_rally_fail.py 自己的函数;
资金曲线用 t159_bear_short.nav(照 short_lab_common.money 的尺:f=0.5%/票、cap=10、逐日盯市);
零分布 / 分位用 src/data/evaluation/apparatus.py。

产物:
  <DATA>/research/t383/_t383_results.json   原始数
  docs/research/_t383_supplement.md         原始数表
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO_ROOT)

DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
S681 = os.path.join(DATA_ROOT, "research", "s681")
WORK = os.path.join(DATA_ROOT, "research", "t383")
os.makedirs(WORK, exist_ok=True)

H = 62                      # 62 自然日滚动窗口(与 T-377 的先验口径一致)
HORIZON_D = "2026-12-31"
CUT = "2026-10-01"          # 族曲线断点之后的第一天
F_FAM, CAP_FAM = 0.005, 10  # 族尺:t159.nav(f=0.5%/票、cap=10)


def log(msg: str) -> None:
    print(msg, flush=True)


# ── Supabase 只读 ────────────────────────────────────────────────────────────────
def _get(path: str, params: dict) -> tuple[list[dict], str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    q = dict(params)
    full = f"{url}/rest/v1/{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(full, headers={"apikey": key, "Authorization": f"Bearer {key}",
                                               "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()), r.headers.get("Content-Range", "")


def pull_table(table: str, select: str, d_from: str) -> list[dict]:
    """按 (symbol,d) 主键序翻页;每页 1000 行;核总行数。"""
    rows: list[dict] = []
    off = 0
    total = None
    while True:
        page, cr = _get(table, {"select": select, "d": f"gte.{d_from}",
                                "order": "symbol.asc,d.asc", "limit": "1000", "offset": str(off)})
        if total is None and "/" in cr:
            total = int(cr.rsplit("/", 1)[1])
        rows.extend(page)
        off += len(page)
        if len(page) < 1000:
            break
        if off % 20000 == 0:
            log(f"    {table}: {off} 行…")
    log(f"  {table}: 取到 {len(rows)} 行(表内筛选后 {total} 行)")
    if total is not None and len(rows) != total:
        raise SystemExit(f"{table} 翻页数不符:取到 {len(rows)} ≠ 表内 {total}")
    return rows


# ── 宇宙:um 文件(止 09-30)+ 库里的延续(10-01 起)────────────────────────────────
def build_universe(db_rows: list[dict]):
    import short_lab_common as sl
    um = sl.load_um()
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for r in db_rows:
        by_sym[r["symbol"]].append(r)
    # 重叠校验:库里 vs um 文件(同一段日线是否同源)
    diffs_c, diffs_q, n_ov = [], [], 0
    for sym, a in um.items():
        if sym not in by_sym:
            continue
        idx = {d: i for i, d in enumerate(a["d"])}
        for r in by_sym[sym]:
            i = idx.get(r["d"])
            if i is None:
                continue
            n_ov += 1
            if a["c"][i] > 0:
                diffs_c.append(abs(float(r["c"]) - float(a["c"][i])) / float(a["c"][i]))
            if a["qv"][i] > 0:
                diffs_q.append(abs(float(r["qv"]) - float(a["qv"][i])) / float(a["qv"][i]))
    ov = {"n_overlap_rows": n_ov,
          "close_rel_abs_max": float(np.max(diffs_c)) if diffs_c else None,
          "close_rel_abs_p99": float(np.quantile(diffs_c, 0.99)) if diffs_c else None,
          "close_rel_abs_mean": float(np.mean(diffs_c)) if diffs_c else None,
          "qv_rel_abs_max": float(np.max(diffs_q)) if diffs_q else None,
          "qv_rel_abs_p99": float(np.quantile(diffs_q, 0.99)) if diffs_q else None,
          "qv_rel_abs_mean": float(np.mean(diffs_q)) if diffs_q else None}
    added, newsyms = 0, []
    for sym, rows in by_sym.items():
        rows.sort(key=lambda r: r["d"])
        if sym in um:
            a = um[sym]
            last = a["d"][-1]
            extra = [r for r in rows if r["d"] > last]
            if extra:
                a["d"] = list(a["d"]) + [r["d"] for r in extra]
                for k in ("o", "h", "l", "c", "qv"):
                    a[k] = np.concatenate([a[k], np.array([float(r[k]) for r in extra])])
                added += len(extra)
        else:
            rows2 = [r for r in rows]
            arr = np.array([[float(r[k]) for k in ("o", "h", "l", "c", "qv")] for r in rows2], float)
            um[sym] = {"d": [r["d"] for r in rows2], "o": arr[:, 0], "h": arr[:, 1], "l": arr[:, 2],
                       "c": arr[:, 3], "qv": arr[:, 4]}
            newsyms.append({"symbol": sym, "first_d": rows2[0]["d"], "n": len(rows2)})
    last_d = max((d for a in um.values() for d in a["d"]), default="")
    log(f"  宇宙:{len(um)} 标的 · um 末日 {max(a['d'][-1] for a in um.values())} · 合并后末日 {last_d}")
    log(f"  新增 bar {added} 行 · 只在库里出现的标的 {len(newsyms)} 个")
    return um, ov, newsyms, last_d


def build_funds(db_fund_rows: list[dict]):
    import short_lab_common as sl
    funds = sl.daily_funding(sl.load_funding())
    n_new = 0
    for r in db_fund_rows:
        d = str(r["d"])[:10]
        s = funds.setdefault(r["symbol"], {})
        s[d] = s.get(d, 0.0) + float(r["funding_rate"] or 0.0)
        n_new += 1
    last = max((d for s in funds.values() for d in s), default="")
    log(f"  资金费:{len(funds)} 标的 · 库内新增 {n_new} 行 · 末日 {last}")
    return funds


# ── 族资金曲线(照 t348_s681.money_curve 的尺)─────────────────────────────────────
CLOSES: dict[str, list] = {}
IDX: dict[str, dict] = {}


def build_closes(um: dict) -> None:
    """t159.nav 用的 bars(symbol → [d,o,h,l,c,qv])与 日期→下标 索引(只建一次,零分布里反复用)。"""
    global CLOSES, IDX
    CLOSES = {}
    IDX = {}
    for s, a in um.items():
        CLOSES[s] = [[d, float(a["o"][i]), float(a["h"][i]), float(a["l"][i]), float(a["c"][i]), float(a["qv"][i])]
                     for i, d in enumerate(a["d"])]
        IDX[s] = {d: i for i, d in enumerate(a["d"])}


def money_curve(tickets: list[dict], um: dict):
    import t159_bear_short as T159
    if not CLOSES:
        build_closes(um)
    closes = CLOSES
    tk = [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
           "exit_d": None if t.get("still") else t["exit_d"], "entry_px": t["entry_px"],
           "stop_px": t["stop_px"], "exit_px": None if t.get("still") else t["exit_px"]}
          for t in tickets if t.get("entry_d") and t.get("entry_px") and t.get("stop_px")
          and t["entry_px"] != t["stop_px"]]
    if not tk:
        return pd.Series(dtype=float), 0
    d_to = max([t["exit_d"] for t in tk if t["exit_d"]] + [max(t["entry_d"] for t in tk)])
    curve = list(T159.nav(tk, closes, F_FAM, cap=CAP_FAM, d_to=d_to))
    nav = pd.Series({pd.Timestamp(r["d"]): float(r["equity"]) for r in curve}).sort_index()
    return nav, len(tk)


# ── 滚动 62 日先验(照 t348_r6_scenario_fix.roll_stats)─────────────────────────────
def roll_stats(nav: pd.Series, thr: float) -> dict:
    v = nav.to_numpy()
    n = len(v)
    if n <= H:
        return {"n_days": n, "note": "样本太短"}
    r = v[H:] / v[:-H] - 1.0
    span_days = int((nav.index[-1] - nav.index[0]).days)
    return {"n_days": n, "d0": str(nav.index[0].date()), "d1": str(nav.index[-1].date()),
            "nav_start": float(v[0]), "nav_end": float(v[-1]), "total_return": float(v[-1] / v[0] - 1.0),
            "H": H, "n_windows": int(len(r)), "thr": float(thr),
            "freq_le_thr": float(np.mean(r <= thr)), "freq_ge_thr": float(np.mean(r >= thr)),
            "roll_mean": float(np.mean(r)), "roll_std": float(np.std(r, ddof=1)),
            "roll_min": float(np.min(r)), "roll_max": float(np.max(r)),
            "roll_p05": float(np.quantile(r, 0.05)), "roll_p95": float(np.quantile(r, 0.95)),
            "span_days": span_days,
            "n_nonoverlap_equiv": round(span_days / H, 1),
            "indep_frac": round(len(r) / max(1.0, span_days / H), 1)}


def main() -> None:
    t0 = time.time()
    res: dict = {"generated": "lane-c 2026-11-14", "card": "T-383"}
    cache = os.path.join(WORK, "_t383_results.json")

    # ── ① 取库里的延续数据 ─────────────────────────────────────────────────────
    log("=== ① 取库里的延续数据 ===")
    pull_cache = os.path.join(WORK, "_db_pull.json")
    if os.path.exists(pull_cache):
        db = json.load(open(pull_cache))
        log("  用缓存的库数据")
    else:
        perp = pull_table("perp_bv_daily", "symbol,d,o,h,l,c,qv", "2026-08-01")
        fund = pull_table("v_funding_daily", "symbol,d,funding_rate,n", "2026-08-01")
        db = {"perp": perp, "fund": fund}
        json.dump(db, open(pull_cache, "w"))
    um, ov, newsyms, last_d = build_universe(db["perp"])
    funds = build_funds(db["fund"])
    res["universe"] = {"n_symbols": len(um), "last_d": last_d, "overlap_check": ov,
                       "db_only_symbols": newsyms}

    # ── ② 扫描两族(规则一字不改,用仓库脚本自己的函数)──────────────────────────
    log("=== ② 扫描 H2 / H4(um + 库里的延续) ===")
    import s681_h2_pump_fade as H2
    import s681_h4_bear_rally_fail as H4
    import short_lab_common as sl

    log("  H2 …")
    H2.prep(um)
    excl = H2.top_exclusions(um)
    sigs2 = H2.signals(um, excl)
    tk2 = H2.build_tickets(um, funds, sigs2)
    pool2 = H2.eligible_pool(um, excl, H2.PUMP)
    log(f"  H2: 信号 {len(sigs2)} · 票 {len(tk2)}")

    log("  H4 …")
    r4 = H4.scan_um(um, funds)
    tk4 = sl.chain(r4["tickets"])          # 照 s681_h4 main():同币持仓期间不叠票
    log(f"  H4: 原始候选 {len(r4['tickets'])} · 叠票后 {len(tk4)} · 状态日 {r4['n_state_days']}")

    # ── ③ 与已落盘的原始票对照(复现校验)───────────────────────────────────────
    log("=== ③ 复现校验 ===")
    st2 = json.load(open(os.path.join(HERE, "s681_h2_pump_fade_results.json")))
    st4 = json.load(open(os.path.join(HERE, "s681_h4_bear_rally_fail_results.json")))

    def key(t):
        return (t["symbol"], t["signal_d"])

    def cmp(old, new, cut):
        o = {key(t) for t in old}
        n = {key(t) for t in new if t["signal_d"] < cut}
        only_old = sorted(o - n)
        only_new = sorted(n - o)
        return {"old_n": len(o), "new_hist_n": len(n), "same": len(o & n),
                "only_in_old": [list(x) for x in only_old[:20]], "only_in_old_n": len(only_old),
                "only_in_new": [list(x) for x in only_new[:20]], "only_in_new_n": len(only_new)}

    cmp2 = cmp(st2["tickets"], tk2, CUT)
    cmp4 = cmp(st4["tickets"], tk4, CUT)
    res["reproduce"] = {"H2": cmp2, "H4": cmp4}
    log(f"  H2 历史票:原 {cmp2['old_n']} · 现 {cmp2['new_hist_n']} · 只差 {cmp2['only_in_old_n'] + cmp2['only_in_new_n']}")
    log(f"  H4 历史票:原 {cmp4['old_n']} · 现 {cmp4['new_hist_n']} · 只差 {cmp4['only_in_old_n'] + cmp4['only_in_new_n']}")

    # ── ④ 10-01 之后的新入场信号 ──────────────────────────────────────────────
    log("=== ④ 10-01 之后的新入场信号 ===")
    new2 = [t for t in tk2 if t["signal_d"] >= CUT]
    new4 = [t for t in tk4 if t["signal_d"] >= CUT]
    res["new_tickets"] = {
        "H2": {"n": len(new2), "signals": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                                            "exit_d": t["exit_d"], "r": t["r"], "why": t["why"], "still": t["still"]}
                                           for t in new2]},
        "H4": {"n": len(new4), "signals": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                                            "exit_d": t["exit_d"], "r": t["r"], "why": t["why"], "still": t["still"]}
                                           for t in new4]},
    }
    log(f"  H2 新票 {len(new2)} 张 · H4 新票 {len(new4)} 张")
    for nm, lst in (("H2", new2), ("H4", new4)):
        for t in lst[:20]:
            log(f"    {nm}: {t['symbol']} 信号 {t['signal_d']} 进 {t['entry_d']} 出 {t['exit_d']} r={t['r']:.3f} {t['why']}")

    # ── ⑤ 族曲线:缓存复现 + 延长到最新 ────────────────────────────────────────
    log("=== ⑤ 族曲线 ===")
    fam_csv = pd.read_csv(os.path.join(HERE, "t348_r3_families.csv"), parse_dates=["d"])
    out_fam = {}
    for nm, tk, fam in (("H2", tk2, "S681_H2"), ("H4", tk4, "S681_H4")):
        cached = fam_csv[fam_csv["family"] == fam].set_index("d")["nav"].astype(float).sort_index()
        # (a) 用旧票 + um 收盘复现缓存曲线
        old_tk = st2["tickets"] if nm == "H2" else st4["tickets"]
        nav_old, n_old = money_curve(old_tk, um)
        cmp_idx = cached.index.intersection(nav_old.index)
        diff = float(np.max(np.abs(nav_old.loc[cmp_idx].to_numpy() - cached.loc[cmp_idx].to_numpy()))) if len(cmp_idx) else None
        # (b) 延长:新票 + 库里收盘
        nav_new, n_new = money_curve(tk, um)
        # (c) 只用历史票 + 库里收盘(看仍然持仓的票怎么收的)
        hist_tk = [t for t in tk if t["signal_d"] < CUT]
        nav_hist, _ = money_curve(hist_tk, um)
        still = [t for t in old_tk if t.get("still")]
        out_fam[nm] = {
            "cached_nav_d0": str(cached.index[0].date()), "cached_nav_d1": str(cached.index[-1].date()),
            "cached_nav_end": float(cached.iloc[-1]),
            "reproduce_max_abs_diff": diff, "n_days_cached": int(len(cached)),
            "extended_d0": str(nav_new.index[0].date()), "extended_d1": str(nav_new.index[-1].date()),
            "extended_nav_end": float(nav_new.iloc[-1]),
            "extended_total_return": float(nav_new.iloc[-1] / nav_new.iloc[0] - 1.0),
            "hist_only_d1": str(nav_hist.index[-1].date()), "hist_only_nav_end": float(nav_hist.iloc[-1]),
            "hist_only_total_return": float(nav_hist.iloc[-1] / nav_hist.iloc[0] - 1.0),
            "n_tickets_used": n_new,
            "n_still_open_at_old_end": len(still),
            "still_detail": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
                               "old_exit_d": t["exit_d"], "old_why": t["why"]} for t in still][:20],
        }
        log(f"  {nm}: 缓存末日 {out_fam[nm]['cached_nav_d1']} nav {out_fam[nm]['cached_nav_end']:.6f}"
            f" · 复现最大差 {diff} · 延长后末日 {out_fam[nm]['extended_d1']} nav {out_fam[nm]['extended_nav_end']:.6f}")
    res["families"] = out_fam

    # ── ⑥ 概率来源:62 日滚动 + 重叠窗口数 ─────────────────────────────────────
    log("=== ⑥ 概率来源(62 日滚动) ===")
    stat = {}
    for nm, tk, fam in (("H2", tk2, "S681_H2"), ("H4", tk4, "S681_H4")):
        nav_new, _ = money_curve(tk, um)
        cached = fam_csv[fam_csv["family"] == fam].set_index("d")["nav"].astype(float).sort_index()
        thr_new = 1.0 / float(nav_new.iloc[-1]) - 1.0
        thr_old = 1.0 / float(cached.iloc[-1]) - 1.0
        stat[nm] = {"extended": roll_stats(nav_new, thr_new), "cached_only": roll_stats(cached, thr_old)}
        log(f"  {nm} 延长:窗口 {stat[nm]['extended']['n_windows']} · 非重叠当量 {stat[nm]['extended']['n_nonoverlap_equiv']}"
            f" · P(≤thr) {stat[nm]['extended']['freq_le_thr']:.4f} · P(≥thr) {stat[nm]['extended']['freq_ge_thr']:.4f}")
        log(f"  {nm} 缓存:窗口 {stat[nm]['cached_only']['n_windows']} · 非重叠当量 {stat[nm]['cached_only']['n_nonoverlap_equiv']}")
    res["prob_source"] = stat

    # ── ⑦ 零信号对照 ──────────────────────────────────────────────────────────
    log("=== ⑦ 零信号对照 ===")
    from src.data.evaluation import apparatus as ap

    pools2: dict[str, list[str]] = defaultdict(list)
    for d, lst in pool2.items():
        for sym, _i in lst:
            pools2[sym].append(d)
    pools4 = {sym: [um[sym]["d"][i] for i in idxs] for sym, idxs in r4["pools"].items()}

    def rebuild_H2(pairs):
        tk = []
        for sym, d in pairs:
            a = um.get(sym)
            i = IDX.get(sym, {}).get(d) if a is not None else None
            if i is None:
                continue
            t = sl_short_ticket(a, i, H2.S_STOP, H2.N_HOLD, fund=funds.get(sym), symbol=sym)
            if t:
                t["signal_d"] = d
                tk.append(t)
        return sl_chain(tk)

    def rebuild_H4(pairs):
        tk = []
        for sym, d in pairs:
            a = um.get(sym)
            i = IDX.get(sym, {}).get(d) if a is not None else None
            if i is None or sym not in r4["stops"]:
                continue
            t = H4.open_ticket(a, i, r4["stops"][sym], r4["sma20s"][sym], funds.get(sym), sym)
            if t:
                t["signal_d"] = d
                tk.append(t)
        return tk

    def run_null(fam, tickets, pool, rebuild, n_draw, seed):
        events = [(t["symbol"], t["signal_d"]) for t in tickets]
        actual = out_fam[fam]["extended_total_return"]

        def draw(rng):
            newp = ap.random_dates_like(events, pool, rng, stratum=lambda d: d[:4])
            tk2 = rebuild([(k, d) for k, d in newp if d is not None])
            nav, _ = money_curve(tk2, um)
            if len(nav) == 0:
                return np.nan
            return float(nav.iloc[-1] / nav.iloc[0] - 1.0)

        null = ap.null_distribution(draw, n_draw, seed)
        pct = ap.percentile_of(actual, null)
        return {"n_draw": n_draw, "actual_total_return": actual,
                "null_mean": float(np.mean(null)), "null_median": float(np.median(null)),
                "null_q05": float(np.quantile(null, 0.05)), "null_q95": float(np.quantile(null, 0.95)),
                "null_min": float(np.min(null)), "null_max": float(np.max(null)),
                "percentile_of_actual": pct,
                "p_upper": ap.p_upper(actual, null), "p_lower": ap.p_lower(actual, null)}

    # 字面读法:随机 14 票组合
    def null14(fam, pool, rebuild, n_draw, seed):
        keys = sorted(pool.keys())
        allp = [(s, d) for s in keys for d in pool[s]]
        actual_mean_r = None
        nulls, means = [], []
        rng = np.random.default_rng(seed)
        for _ in range(n_draw):
            pick = [allp[int(rng.integers(0, len(allp)))] for _ in range(14)]
            tk = rebuild(pick)
            if not tk:
                continue
            nav, _ = money_curve(tk, um)
            if len(nav) == 0:
                continue
            nulls.append(float(nav.iloc[-1] / nav.iloc[0] - 1.0))
            means.append(float(np.mean([t["r"] for t in tk])))
        return {"n_draw": len(nulls), "null_total_return_median": float(np.median(nulls)) if nulls else None,
                "null_total_return_q05": float(np.quantile(nulls, 0.05)) if nulls else None,
                "null_total_return_q95": float(np.quantile(nulls, 0.95)) if nulls else None,
                "null_mean_r_median": float(np.median(means)) if means else None,
                "null_mean_r_q05": float(np.quantile(means, 0.05)) if means else None,
                "null_mean_r_q95": float(np.quantile(means, 0.95)) if means else None}

    import short_lab_common as sl
    sl_short_ticket = sl.short_ticket
    sl_chain = sl.chain
    build_closes(um)

    out_null = {}
    out_null["H4_timing"] = run_null("H4", tk4, pools4, rebuild_H4, 40, 38304)
    out_null["H2_timing"] = run_null("H2", tk2, pools2, rebuild_H2, 40, 38302)
    log(f"  H4 时点零分布:实际 {out_null['H4_timing']['actual_total_return']:+.4%}"
        f" · 零分布中位 {out_null['H4_timing']['null_median']:+.4%}"
        f" · 分位 {out_null['H4_timing']['percentile_of_actual']:.3f}")
    log(f"  H2 时点零分布:实际 {out_null['H2_timing']['actual_total_return']:+.4%}"
        f" · 零分布中位 {out_null['H2_timing']['null_median']:+.4%}"
        f" · 分位 {out_null['H2_timing']['percentile_of_actual']:.3f}")
    out_null["H4_random14"] = null14("H4", pools4, rebuild_H4, 400, 38301)
    out_null["H2_random14"] = null14("H2", pools2, rebuild_H2, 400, 38300)
    res["null_control"] = out_null

    # ── ⑧ C0 口径(A = 长账本 2020-08-16 起)───────────────────────────────────
    r5 = json.load(open(os.path.join(HERE, "t348_r5_results.json"), encoding="utf-8"))
    bl = r5["base_long"]
    cur = 1.0 + float(bl["C0_total_return"])
    peak = float(bl["C0_uw_G"]["peak_value"])
    fam4 = r5["families"]["S681_H4"]
    winB = (fam4.get("windows", {}) or {}).get("B", {})
    res["c0"] = {"kou_jing": "A(长账本 2020-08-16 起)", "d0": bl["d0"], "d1": bl["d1"],
                 "n_days": bl["n_days"], "C0_cagr": float(bl["C0_cagr"]),
                 "C0_total_return": float(bl["C0_total_return"]), "cur_level": cur,
                 "peak_level": peak, "ratio": cur / peak,
                 "uw_G": bl["C0_uw_G"], "uw_S829": bl["C0_uw_S829"],
                 "B_kou_jing": {"start": winB.get("start"),
                                "C0_cagr": ((winB.get("stats", {}).get("C0", {}) or {}).get("metrics", {}) or {}).get("cagr"),
                                "C0_total_return": ((winB.get("stats", {}).get("C0", {}) or {}).get("metrics", {}) or {}).get("total_return")}}
    log(f"  C0(A 口径):{bl['d0']} → {bl['d1']} 年化 {float(bl['C0_cagr']):+.4%}"
        f" · 水位 {cur:.6f} · 峰值 {peak:.6f} · 比 {cur / peak:.4f}")

    json.dump(res, open(cache, "w"), ensure_ascii=False, indent=1, default=str)
    log(f"→ {cache}  ({time.time() - t0:.0f} 秒)")


if __name__ == "__main__":
    main()
