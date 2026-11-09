#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-317 / S-796 —— 对手盘族的站住事件(squeeze / Binance 上币 / 上永续 / Upbit 韩元上币)接进
R-v2 开票闸:事件日之后 30 天不开新票,在 T-310 同一个回放账本上值不值钱 —— 四类各自判。

**引擎与票源(S-796 写死,与 S-788 / T-310 完全相同)**:
  引擎 `docs/research/t251_gross_cap.py` 的 `simulate` / `curve_stats` —— **一字不改**(import,不复制);
  票源 `docs/research/t197_results.json` → `tickets.A`(956 张);
  装配方式 = 本 lane 自己的 `t310_slots.py`(`load_tickets` / `load_bars` / `classify_exits` /
  `to_engine_tickets` / `load_gate` / `run_cap` —— 直接 import,保证与 T-310 逐字一致);
  f = 0.5%、起始净值 $630、L = 1、gross_cap = 0.40、**cap_n = 14**(现行生产)。

**自检(跑之前先过,不过就停下报差)**:cap_n = 14 的基准账本必须复现 T-310 发布的
  total = +63.50% / max_dd = −25.71%(t310_results.json → guardrail.cap_n_14)。

**四类事件(S-796 写死,各自独立判)**:
  S = `crowding_watch` kind = squeeze 的 `d`;
  L = `binance_event_watch` kind = listing 的 `d0`;
  P = `binance_event_watch` kind = perp_listing 的 `d0`;
  U = `binance_event_watch` kind = upbit_krw_listing 的 `d0`。
  代号匹配:精确;精确没有则去 `1000` / `1000000` 前缀(与 S-751 同)。

**规则**:票的开票日 e(= 票的 `signal_d`,T-235 已核实过的口径)满足 0 ≤ e − 事件日 ≤ 30 天
  ⇒ 这张票不开(从票源里删掉,其余票原样进引擎 —— 名额与名义上限会把空出来的位置让给别的票)。

**判(每类单独,四类做 Bonferroni ⇒ 每类用 98.75% 区间)**:
  (i)   被挡的票 ≥ 15 张;
  (ii)  被挡票的平均 R 比其余票低,差 ≤ −0.3R,且票级自助(10,000 次,种子 796)的 98.75% 区间上沿 < 0;
  (iii) 金额:加规则后账本总收益 ≥ 原账本、最大回撤不更差(差 ≤ +1pp);
  (iv)  被挡票按开票日对半,两半的平均 R 差同号。
  四条全过 ⇒ 这一类提给 Jazz 作硬规则(我不代拍);任一条不过 ⇒ 不进规则,只留在 `crowd_map`。

**同时报(不判)**:四类合并一版的账本;每类被挡票的 R 分布(均值/中位/p10/p90/胜率/最大单票 R)。

用法:
  python3 docs/research/t317_gates.py fetch    # 拉事件表缓存(只读,分页带 order=,count=exact 核行数)
  python3 docs/research/t317_gates.py run      # 回放 + 判定 → t317_hits.csv / t317_results.json

纪律:只读库、只算、不改生产代码、不入库;引擎一字不改;票源与装配一字不改。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import t251_gross_cap as T251          # noqa: E402  —— 引擎(不改一字)
import t310_slots as T310               # noqa: E402  —— 本 lane 的装配(T-310 原样)

CACHE_CROWD = HERE / "_t317_crowd.jsonl"
CACHE_BEW = HERE / "_t317_bew.jsonl"
HITS_CSV = HERE / "t317_hits.csv"
RESULTS = HERE / "t317_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

# ── S-796 写死的参数 ──────────────────────────────────────────────────────────
CAP_FRAC = 0.40            # gross_cap
CAP_N = 14                 # 名额(现行生产)
EQ0 = 630.0                # 起始净值 $630
F = 0.005                  # 每票风险占净值 0.5%
WINDOW_D = 30              # 事件日之后 30 天内不开新票
MIN_BLOCKED = 15           # (i)
MEAN_R_DIFF_MAX = -0.3     # (ii) 差 ≤ −0.3R
BOOT_N = 10000             # (ii) 票级自助次数
BOOT_SEED = 796            # (ii) 种子
CI = 0.9875                # (ii) 98.75% 区间(四类 Bonferroni ⇒ 每类 α = 0.0125)
DD_TOL_PP = 1.0            # (iii) 最大回撤容许恶化 +1pp

# 四类事件(S-796 原文)
CLASSES = [
    ("S", "squeeze", "crowding_watch", "d"),              # S = crowding_watch kind=squeeze 的 d
    ("L", "listing", "binance_event_watch", "d0"),        # L = Binance 上币的 d0
    ("P", "perp_listing", "binance_event_watch", "d0"),   # P = 上永续的 d0
    ("U", "upbit_krw_listing", "binance_event_watch", "d0"),  # U = Upbit 韩元上币的 d0
]
CLASS_LABEL = {
    "S": "squeeze(crowding_watch.d)",
    "L": "listing(binance_event_watch.d0)",
    "P": "perp_listing(binance_event_watch.d0)",
    "U": "upbit_krw_listing(binance_event_watch.d0)",
}

# T-310 已发布的 cap_n = 14 基准(自检用)
T310_REF = dict(total_return=0.6350272262487078, max_dd=-0.25709663592753196,
                calmar=0.3248861730440124, n_days=None)


# ── 取数(只读) ────────────────────────────────────────────────────────────────
def _hdr(extra=None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if extra:
        h.update(extra)
    return h


def _get(url, headers, tries=5, timeout=180):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return f.read().decode(), dict(f.headers)
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode()[:200])
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(2 * (i + 1))
    raise SystemExit("取数失败 %s :: %s" % (url[:200], last))


def _fetch_all(table, select, order, path, where=None, workers=8):
    """整表拉取:Range 分页 + order= 固定排序 + count=exact 核总行数(每页 ≤ 1000 行)。"""
    base = URL.rstrip("/") + "/rest/v1/"
    q = "%s?select=%s&order=%s" % (table, select, order)
    if where:
        q += "&" + where
    _b, hd = _get(base + q, _hdr({"Prefer": "count=exact", "Range": "0-0"}))
    cr = hd.get("Content-Range", "")
    total = int(cr.split("/")[-1]) if "/" in cr else 0
    print("  %s %s 总行数 %d" % (table, where or "(全部)", total), flush=True)
    page = 1000
    ranges = [(o, min(o + page - 1, total - 1)) for o in range(0, total, page)]

    def one(rng):
        b, _h = _get(base + q, _hdr({"Range": "%d-%d" % rng}))
        return json.loads(b)

    out = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, rows in enumerate(ex.map(one, ranges)):
            out.extend(rows)
            if (i + 1) % 40 == 0:
                print("    %s %d/%d  %.0fs" % (table, (i + 1) * page, total, time.time() - t0), flush=True)
    with open(path, "w") as f:
        for r in out:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print("  %s 拉取 %d 行 → %s  %.0fs" % (table, len(out), path.name, time.time() - t0), flush=True)
    if len(out) != total:
        raise SystemExit("!! %s 行数不符: 拉到 %d / 期望 %d" % (table, len(out), total))
    return out


def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    _fetch_all("crowding_watch", "symbol,d,kind", "d.asc,symbol.asc", CACHE_CROWD,
               where="kind=eq.squeeze")
    _fetch_all("binance_event_watch", "symbol,kind,d0", "d0.asc,symbol.asc", CACHE_BEW,
               where="kind=in.(listing,perp_listing,upbit_krw_listing)")
    # 各 kind 的总行数(核对覆盖面,不落盘)
    for tbl, kinds in (("crowding_watch", ["squeeze"]),
                       ("binance_event_watch", ["listing", "perp_listing", "upbit_krw_listing"])):
        for k in kinds:
            _b, hd = _get("%s/rest/v1/%s?select=kind&kind=eq.%s" % (URL.rstrip("/"), tbl, k),
                          _hdr({"Prefer": "count=exact", "Range": "0-0"}))
            print("  [核] %s %s = %s 行" % (tbl, k, hd.get("Content-Range")), flush=True)
    print("缓存齐了:", flush=True)


# ── 事件装载与匹配 ────────────────────────────────────────────────────────────
def _d(s):
    return str(s)[:10]


def base_name(s, prefixes=("1000000", "1000")):
    """1000 / 1000000 前缀去掉算同名(1000SHIB ↔ SHIB)—— 与 S-751 / t197 同一口径。"""
    for p in prefixes:
        if s.startswith(p) and s[len(p):].isalpha():
            return s[len(p):]
    return s


def load_events():
    """→ {class: {"exact": {sym: [d, ...]}, "base": {base: [d, ...]}}}"""
    ev = {}
    for code, kind, tbl, dcol in CLASSES:
        exact, base = {}, {}
        if tbl == "crowding_watch":
            path, dkey = CACHE_CROWD, "d"
        else:
            path, dkey = CACHE_BEW, "d0"
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if r.get("kind") != kind:
                    continue
                sym = str(r.get("symbol") or "")
                day = _d(r.get(dkey))
                if not sym or not day:
                    continue
                exact.setdefault(sym, []).append(day)
                base.setdefault(base_name(sym), []).append(day)
        for v in exact.values():
            v.sort()
        for v in base.values():
            v.sort()
        ev[code] = dict(exact=exact, base=base, n_events=sum(len(v) for v in exact.values()))
    return ev


def event_days_for(ev_class, sym):
    """代号匹配:精确优先;精确没有则去 1000 / 1000000 前缀。返回该代号在事件表里的所有日期。"""
    ex = ev_class["exact"]
    if sym in ex:
        return ex[sym]
    return ev_class["base"].get(base_name(sym), [])


def blocked_map(tickets, ev_class):
    """→ {tid: (事件日, 该窗口内全部事件日)}  规则:0 ≤ 开票日(e = signal_d) − 事件日 ≤ 30 天。"""
    out = {}
    for t in tickets:
        sym = t["symbol"]
        e = t["signal_d"]
        days = event_days_for(ev_class, sym)
        if not days:
            continue
        eo = dt.date.fromisoformat(e)
        lo = (eo - dt.timedelta(days=WINDOW_D)).isoformat()
        hit = [d for d in days if lo <= d <= e]
        if hit:
            out[t["tid"]] = (hit[-1], hit)     # 最新的一条当「事件日」
    return out


def coverage(tickets, ev_class):
    """为什么挡了 0 张也要说清楚:事件表覆盖到多少票源代号、这些代号的票开票日与事件日差多少天。"""
    sym_in_tab, n_t_with_event, n_before, gaps = set(), 0, 0, []
    n_at_30, n_at_minus1 = 0, 0
    for t in tickets:
        sym = t["symbol"]
        days = event_days_for(ev_class, sym)
        if not days:
            continue
        sym_in_tab.add(sym)
        n_t_with_event += 1
        e = dt.date.fromisoformat(t["signal_d"])
        prior = [d for d in days if d <= t["signal_d"]]
        if prior:
            n_before += 1
            gaps.append((e - dt.date.fromisoformat(prior[-1])).days)
        # 边界敏感票:若 开票日 改按 entry_d = signal_d + 1 读,只有「间隔恰好 30」与「事件在进场当天」的会进出
        if any((e - dt.date.fromisoformat(d)).days == WINDOW_D for d in days):
            n_at_30 += 1
        if any((e - dt.date.fromisoformat(d)).days == -1 for d in days):
            n_at_minus1 += 1
    gaps.sort()
    return dict(
        n_ticket_symbols_matched=len(sym_in_tab),
        n_tickets_with_symbol_in_table=n_t_with_event,
        n_tickets_with_event_on_or_before_open=n_before,
        min_gap_days=gaps[0] if gaps else None,
        median_gap_days=T251.q(gaps, 0.5) if gaps else None,
        n_gap_gt_window=sum(1 for g in gaps if g > WINDOW_D) if gaps else 0,
        n_tickets_at_gap_30=n_at_30, n_tickets_event_on_entry_day=n_at_minus1,
        boundary_note=("改按 entry_d 读时,只有「事件间隔恰好 30 天」与「事件在进场当天」两类票会进出;"
                       "两者都是 0 ⇒ 被挡票集合与 开票日 口径无关"),
    )


# ── 统计 ──────────────────────────────────────────────────────────────────────
def rstats(rs):
    """R 分布:均值/中位/p10/p90/胜率/最大单票 R(S-796 要求报的那几个)。"""
    if not rs:
        return dict(n=0)
    arr = np.asarray(rs, dtype=float)
    s = sorted(arr.tolist())
    return dict(
        n=len(s),
        mean=float(arr.mean()),
        median=float(T251.q(s, 0.50)),
        p10=float(T251.q(s, 0.10)),
        p90=float(T251.q(s, 0.90)),
        win_pct=float(100.0 * sum(1 for x in s if x > 0) / len(s)),
        max_r=float(s[-1]),
        min_r=float(s[0]),
        sum_r=float(arr.sum()),
    )


def boot_diff(blocked_rs, rest_rs, n=BOOT_N, seed=BOOT_SEED, ci=CI):
    """票级自助:重抽被挡票与其余票,算平均 R 差(blocked − rest)的分位区间。"""
    nb, nr = len(blocked_rs), len(rest_rs)
    if nb == 0 or nr == 0:
        return dict(error="样本不足", n_blocked=nb, n_rest=nr)
    b = np.asarray(blocked_rs, dtype=float)
    r = np.asarray(rest_rs, dtype=float)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n, dtype=float)
    for i in range(0, n, 500):
        m = min(500, n - i)
        ib = rng.integers(0, nb, size=(m, nb))
        ir = rng.integers(0, nr, size=(m, nr))
        diffs[i:i + m] = b[ib].mean(axis=1) - r[ir].mean(axis=1)
    diffs.sort()
    alpha = 1.0 - ci
    lo_q, hi_q = alpha / 2.0, 1.0 - alpha / 2.0
    lo = float(np.quantile(diffs, lo_q))
    hi = float(np.quantile(diffs, hi_q))
    return dict(n_boot=n, seed=seed, ci=ci, lo_q=lo_q, hi_q=hi_q,
                mean_diff=float(diffs.mean()), lo=lo, hi=hi)


def half_split(tickets):
    """按开票日对半:前一半 = 开票日 ≤ 中位数,后一半 = > 中位数。"""
    ds = sorted(t["signal_d"] for t in tickets)
    mid = ds[len(ds) // 2]
    a = [t for t in tickets if t["signal_d"] <= mid]
    b = [t for t in tickets if t["signal_d"] > mid]
    return a, b, mid


# ── 主流程 ────────────────────────────────────────────────────────────────────
def run_ledger(tickets, bars, gate, cap_n=CAP_N):
    """跑一遍回放账本(引擎与装配都不改)。"""
    T310.by_tid_global = {x["tid"]: x for x in tickets}
    res, out = T310.run_cap(CAP_FRAC, tickets, bars, gate, cap_n=cap_n)
    return res, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    args = ap.parse_args()
    if args.cmd == "fetch":
        return cmd_fetch()

    # ── 票源与装配(与 T-310 逐字一致) ──
    raw, t197 = T310.load_tickets()
    need = {t["symbol"] for t in raw}
    bars = T310.load_bars(need)
    print("[load] tickets %d  symbols %d  bars %d" % (len(raw), len(need), len(bars)), flush=True)
    exits, bad = T310.classify_exits(raw, bars)
    print("[exit-reason] 重算 %d 张,与 t197 不一致 %d 张" % (len(exits), len(bad)), flush=True)
    for b in bad[:5]:
        print("   ", b, flush=True)
    tk = T310.to_engine_tickets(raw, exits)
    gate, lvl_by_d, gdiag = T310.load_gate()
    print("[gate]", gdiag, flush=True)

    # ── 自检:复现 T-310 的 cap_n = 14 基准 ──
    res0, sum0 = run_ledger(tk, bars, gate)
    s0 = sum0["stats"]
    selfcheck = dict(
        ref=dict(total_return=T310_REF["total_return"], max_dd=T310_REF["max_dd"], calmar=T310_REF["calmar"]),
        got=dict(total_return=s0["total_return"], max_dd=s0["max_dd"], calmar=s0["calmar"],
                 n_days=s0["n_days"], taken=sum0["taken"], max_positions=sum0["max_positions"]),
        match=bool(abs(s0["total_return"] - T310_REF["total_return"]) < 1e-9
                   and abs(s0["max_dd"] - T310_REF["max_dd"]) < 1e-9),
    )
    print("[selfcheck] total %+.6f%% (ref %+.6f%%)  mdd %+.6f%% (ref %+.6f%%)  match %s"
          % (s0["total_return"] * 100, T310_REF["total_return"] * 100,
             s0["max_dd"] * 100, T310_REF["max_dd"] * 100, selfcheck["match"]), flush=True)
    if not selfcheck["match"]:
        raise SystemExit("!! 自检不符:基准账本没复现 T-310 的 cap_n=14,停下报差")

    # ── 事件表 ──
    EV = load_events()
    for code, _k, _t, _c in CLASSES:
        print("[event] %s %s 事件 %d 条,代号 %d 个"
              % (code, CLASS_LABEL[code], EV[code]["n_events"], len(EV[code]["exact"])), flush=True)

    results = dict(
        meta=dict(
            card="T-317", lane="lane-c", rule="S-796",
            prereg="REFUTATION_LEDGER.md S-796 (Seth, 2026-11-09 15:33 UTC)",
            engine="docs/research/t251_gross_cap.py(simulate / curve_stats,未改一字)",
            assembly="docs/research/t310_slots.py(load_tickets / load_bars / classify_exits / "
                     "to_engine_tickets / load_gate / run_cap,未改一字)",
            ticket_source="docs/research/t197_results.json → tickets.A",
            n_tickets=len(raw), n_symbols=len(need),
            params=dict(risk_frac=F, equity0=EQ0, gross_cap=CAP_FRAC, cap_n=CAP_N,
                        leverage=1.0, window_days=WINDOW_D,
                        min_blocked=MIN_BLOCKED, mean_r_diff_max=MEAN_R_DIFF_MAX,
                        boot_n=BOOT_N, boot_seed=BOOT_SEED, ci=CI, dd_tol_pp=DD_TOL_PP),
            open_day_definition="开票日 e = 票的 signal_d(依 T-235 已核实的口径:entry_px == signal_d 收盘,"
                                "进场在 d+1 开盘 ⇒ d 是开票日)",
            symbol_match="精确优先;精确没有则去 1000 / 1000000 前缀(S-751 口径)",
            event_sources={code: "%s kind=%s" % (tbl, kind) for code, kind, tbl, _c in CLASSES},
        ),
        selfcheck=selfcheck,
        baseline=dict(cap_n=CAP_N, cap_frac=CAP_FRAC, stats=s0, taken=sum0["taken"],
                      max_positions=sum0["max_positions"],
                      blocked_gross=sum0["blocked"]["gross"], blocked_slots=sum0["blocked"]["slots_blocked"],
                      gross=sum0["gross"]),
        classes={}, combined={}, hits=[],
    )

    # ── 逐类判 ──
    all_hits = []
    for code, kind, tbl, dcol in CLASSES:
        evc = EV[code]
        bmap = blocked_map(tk, evc)
        by_tid = {x["tid"]: x for x in tk}
        blocked_tids = set(bmap)
        kept = [t for t in tk if t["tid"] not in blocked_tids]

        # R 比较:只用有 R 的票(closed)
        brs = [by_tid[tid]["r"] for tid in sorted(blocked_tids) if by_tid[tid].get("r") is not None]
        rrs = [t["r"] for t in kept if t.get("r") is not None]
        mean_b = float(np.mean(brs)) if brs else None
        mean_r = float(np.mean(rrs)) if rrs else None
        diff = (mean_b - mean_r) if (mean_b is not None and mean_r is not None) else None
        bd = boot_diff(brs, rrs)

        # 加规则后的账本
        res_c, sum_c = run_ledger(kept, bars, gate)
        sc = sum_c["stats"]
        d_total_pp = (sc["total_return"] - s0["total_return"]) * 100.0
        d_dd_pp = (sc["max_dd"] - s0["max_dd"]) * 100.0

        # 置换效应:空出来的名额让给了谁?(S-796:「名额与名义上限会把空出来的位置让给别的票」)
        base_taken = set(res0["taken"])
        gate_taken = set(res_c["taken"])
        dropped = base_taken - gate_taken      # 基准里进了、加规则后没了
        added = gate_taken - base_taken        # 加规则后才挤进来的
        dropped_r = [by_tid[t]["r"] for t in dropped if by_tid[t].get("r") is not None]
        added_r = [by_tid[t]["r"] for t in added if by_tid[t].get("r") is not None]
        displ = dict(
            n_taken_base=len(base_taken), n_taken_gated=len(gate_taken),
            n_dropped=len(dropped), n_added=len(added),
            dropped_r_stats=rstats(dropped_r), added_r_stats=rstats(added_r),
            dropped_is_blocked=len(dropped & blocked_tids),
            dropped_sample=[dict(tid=t, symbol=by_tid[t]["symbol"], open_day=by_tid[t]["signal_d"],
                                 r=by_tid[t].get("r"), was_blocked=bool(t in blocked_tids))
                            for t in sorted(dropped, key=lambda x: -(abs(by_tid[x].get("r") or 0.0)))[:30]],
            added_sample=[dict(tid=t, symbol=by_tid[t]["symbol"], open_day=by_tid[t]["signal_d"],
                               r=by_tid[t].get("r")) for t in sorted(added)[:30]],
        )

        # 稳健性:金额判定是否被**单张**票翻掉?(R-v2 是凸性策略,右尾一张就能决定账本)
        flip = base_taken ^ gate_taken
        loo = None
        if flip:
            X = max(flip, key=lambda tid: abs(by_tid[tid].get("r") or 0.0))
            base_no = [t for t in tk if t["tid"] != X]
            gated_no = [t for t in tk if t["tid"] != X and t["tid"] not in blocked_tids]
            _rb, sbn = run_ledger(base_no, bars, gate)
            _rg, sgn = run_ledger(gated_no, bars, gate)
            d_loo = (sgn["stats"]["total_return"] - sbn["stats"]["total_return"]) * 100.0
            loo = dict(tid=X, symbol=by_tid[X]["symbol"], open_day=by_tid[X]["signal_d"],
                       r=by_tid[X].get("r"), was_blocked=bool(X in blocked_tids),
                       base_total_without_X=sbn["stats"]["total_return"],
                       gated_total_without_X=sgn["stats"]["total_return"],
                       delta_pp_without_X=d_loo, delta_pp_main=d_total_pp,
                       sign_flip=bool((d_loo > 0) != (d_total_pp > 0)))
            T310.by_tid_global = {x["tid"]: x for x in tk}   # 恢复全局表(后续 run_cap 依赖)

        # (iv) 按开票日对半,两半的平均 R 差同号
        ha, hb, cut = half_split(tk)
        halves = []
        for name, hh in (("early", ha), ("late", hb)):
            bl = [t["r"] for t in hh if t["tid"] in blocked_tids and t.get("r") is not None]
            re_ = [t["r"] for t in hh if t["tid"] not in blocked_tids and t.get("r") is not None]
            mb = float(np.mean(bl)) if bl else None
            mr = float(np.mean(re_)) if re_ else None
            halves.append(dict(half=name, n_total=len(hh), cut=cut,
                               n_blocked=len(bl), n_rest=len(re_),
                               mean_blocked_r=mb, mean_rest_r=mr,
                               diff=(mb - mr) if (mb is not None and mr is not None) else None))
        d1 = halves[0]["diff"]
        d2 = halves[1]["diff"]
        same_sign = bool(d1 is not None and d2 is not None and ((d1 > 0 and d2 > 0) or (d1 < 0 and d2 < 0)))

        # 四条判
        j1 = len(blocked_tids) >= MIN_BLOCKED
        j2 = bool(diff is not None and diff <= MEAN_R_DIFF_MAX and bd.get("hi") is not None and bd["hi"] < 0)
        # (iii) 金额:总收益 ≥ 原账本,且最大回撤不更差(容许恶化 ≤ +1pp ⇒ d_dd_pp ≥ −1pp)
        j3 = bool(sc["total_return"] >= s0["total_return"] and d_dd_pp >= -DD_TOL_PP)
        j4 = same_sign
        verdict = "✅ 四条全过 ⇒ 提给 Jazz 作硬规则(我不代拍)" if (j1 and j2 and j3 and j4) else \
                 "❌ 不过 ⇒ 不进规则,只留在 crowd_map"

        # hits 行
        for tid in sorted(blocked_tids):
            t = by_tid[tid]
            day, all_days = bmap[tid]
            all_hits.append(dict(tid=tid, symbol=t["symbol"], open_day=t["signal_d"],
                                 entry_day=t["entry_d"], event_class=code, event_day=day,
                                 r=t.get("r"), n_events_in_window=len(all_days),
                                 event_days="|".join(all_days)))

        results["classes"][code] = dict(
            label=CLASS_LABEL[code], kind=kind, table=tbl, date_col=dcol,
            n_events_in_table=evc["n_events"], n_symbols_in_table=len(evc["exact"]),
            n_blocked=len(blocked_tids), n_blocked_with_r=len(brs),
            coverage=coverage(tk, evc),
            displacement=displ, leave_one_out=loo,
            blocked_r_dist=rstats(brs), rest_r_dist=rstats(rrs),
            mean_blocked_r=mean_b, mean_rest_r=mean_r, mean_r_diff=diff,
            bootstrap=bd,
            ledger=dict(stats=sc, taken=sum_c["taken"], max_positions=sum_c["max_positions"],
                        d_total_return_pp=d_total_pp, d_max_dd_pp=d_dd_pp,
                        total_ge_base=bool(sc["total_return"] >= s0["total_return"]),
                        dd_not_worse=bool(d_dd_pp >= -DD_TOL_PP)),
            halves=halves, half_cut=cut,
            judgments=dict(i_n_blocked_ge_15=bool(j1), ii_mean_r_diff_and_boot=bool(j2),
                           iii_money=bool(j3), iv_halves_same_sign=bool(j4)),
            all_pass=bool(j1 and j2 and j3 and j4), verdict=verdict,
        )
        print("[%s] 挡 %d 张  均值R 挡 %.4f / 其余 %.4f  差 %+.4f  boot hi %s  "
              "总收益 %+.4f%% (%+.2fpp)  mdd %+.4f%% (%+.2fpp)  判 %s"
              % (code, len(blocked_tids), mean_b or 0, mean_r or 0, diff or 0,
                 ("%+.4f" % bd["hi"]) if bd.get("hi") is not None else "n/a",
                 sc["total_return"] * 100, d_total_pp, sc["max_dd"] * 100, d_dd_pp,
                 "全过" if (j1 and j2 and j3 and j4) else "不过"), flush=True)

    # ── 四类合并一版 ──
    union = {}
    for code, _k, _t, _c in CLASSES:
        for tid, v in blocked_map(tk, EV[code]).items():
            union.setdefault(tid, []).append((code, v[0]))
    kept_u = [t for t in tk if t["tid"] not in union]
    res_u, sum_u = run_ledger(kept_u, bars, gate)
    su = sum_u["stats"]
    by_tid = {x["tid"]: x for x in tk}
    brs_u = [by_tid[t]["r"] for t in union if by_tid[t].get("r") is not None]
    rrs_u = [t["r"] for t in kept_u if t.get("r") is not None]
    results["combined"] = dict(
        n_blocked=len(union), n_blocked_with_r=len(brs_u),
        blocked_r_dist=rstats(brs_u), rest_r_dist=rstats(rrs_u),
        mean_blocked_r=float(np.mean(brs_u)) if brs_u else None,
        mean_rest_r=float(np.mean(rrs_u)) if rrs_u else None,
        mean_r_diff=(float(np.mean(brs_u)) - float(np.mean(rrs_u))) if (brs_u and rrs_u) else None,
        bootstrap=boot_diff(brs_u, rrs_u),
        ledger=dict(stats=su, taken=sum_u["taken"], max_positions=sum_u["max_positions"],
                    d_total_return_pp=(su["total_return"] - s0["total_return"]) * 100.0,
                    d_max_dd_pp=(su["max_dd"] - s0["max_dd"]) * 100.0),
        by_class={code: sum(1 for v in union.values() if any(c == code for c, _d in v))
                  for code, _k, _t, _c in CLASSES},
        n_multi_class=sum(1 for v in union.values() if len(v) > 1),
        displacement=dict(
            n_dropped=len(set(res0["taken"]) - set(res_u["taken"])),
            n_added=len(set(res_u["taken"]) - set(res0["taken"])),
            dropped_r_stats=rstats([by_tid[t]["r"] for t in (set(res0["taken"]) - set(res_u["taken"]))
                                    if by_tid[t].get("r") is not None]),
            added_r_stats=rstats([by_tid[t]["r"] for t in (set(res_u["taken"]) - set(res0["taken"]))
                                  if by_tid[t].get("r") is not None]),
        ),
    )
    print("[COMBINED] 挡 %d 张  总收益 %+.4f%% (%+.2fpp)  mdd %+.4f%% (%+.2fpp)"
          % (len(union), su["total_return"] * 100,
             (su["total_return"] - s0["total_return"]) * 100,
             su["max_dd"] * 100, (su["max_dd"] - s0["max_dd"]) * 100), flush=True)

    # ── 落盘 ──
    with open(HITS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "symbol", "open_day", "event_class", "event_day", "r"])
        for h in all_hits:
            w.writerow([h["tid"], h["symbol"], h["open_day"], h["event_class"], h["event_day"],
                        "" if h["r"] is None else round(h["r"], 6)])
    print("[hits] %d 行 → %s" % (len(all_hits), HITS_CSV.name), flush=True)

    results["hits_n_rows"] = len(all_hits)
    results["hits_n_tickets_union"] = len(union)
    results["hits"] = all_hits
    with open(RESULTS, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=float)
    print("[results] → %s" % RESULTS.name, flush=True)


if __name__ == "__main__":
    main()
