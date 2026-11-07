#!/usr/bin/env python3
"""T-276 · S-755 跨所套息 —— 空单每周放在资金费更高的那一所(Binance 永续 / HL 永续)。

照台账 REFUTATION_LEDGER.md S-755 写死:名字 = S-748 的 22 名;现货腿 = Binance 现货;
空腿场所每周一按过去 7 天日费率均值在两所间取高者;开关规则与选名 = carry_b_top
(规则 B 用所选场所的 7 日均值 > 0;前一半排名用两所较高者的 30 日均值);成本照写死;
资本口径 = 名义 × 0.75;判据 (a)–(d) 一字不改。

三臂:
  A0  = S-749 的 HL 单所 carry_b_top_rc(公用内核 carry_hl.path)—— 先复现 10.86% / 2.09%
  A1  = 同一选择与规则、但用 S-755 的成本结构(现货改 Binance 10bp + 永续 4.5bp + 每腿滑点 2bp)
  A2  = 跨所(S-755 写死的那条)
A1 是「同口径对照」,只报;判据按台账字面比 A0。

只算、不改代码、不入库。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.data.signals.carry_hl import COST_REAL, matrix, path  # noqa: E402
from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE  # noqa: E402

MAC_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
NAMES = tuple(n for n in DEFAULT_UNIVERSE if n not in ("ADA", "LTC"))   # 22 名
NAMES_ALPHA = tuple(sorted(NAMES))
D0 = dt.date(2023, 5, 12)
D1 = dt.date(2026, 11, 5)
CUT = dt.date(2026, 7, 20)          # 台账补记:≤07-20 用 Mac 小时档,≥07-21 用 hl_funding_daily
START = dt.date(2023, 6, 12)        # 第一个满 30 天排名的周一
CAP = 0.75                          # 资本口径:名义 × 0.75

# 成本(S-755 写死):Binance 现货 taker 10bp、Binance 永续 taker 5bp、HL 永续 taker 4.5bp、每腿滑点 2bp
SPOT_COST = 0.0010 + 0.0002         # 现货腿 12bp(开 / 关各一次)
PERP_COST = {0: 0.0005 + 0.0002,    # Binance 永续 7bp
             1: 0.00045 + 0.0002}   # HL 永续 6.5bp
VEN_BN, VEN_HL = 0, 1

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------- Supabase 读
def sb_get(table: str, params: dict, timeout: int = 240, count: bool = False):
    q = urllib.parse.urlencode(params)
    headers = {"apikey": os.environ["SUPABASE_KEY"],
               "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}"}
    if count:
        headers["Prefer"] = "count=exact"
    req = urllib.request.Request(os.environ["SUPABASE_URL"] + "/rest/v1/" + table + "?" + q,
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range")
    return (json.loads(body) if body.strip() else []), cr


def sb_paged(table: str, params: dict, label: str = "") -> list[dict]:
    """分页读全:每页 1000 行,带 order(主键序),offset 递增。"""
    out: list[dict] = []
    off = 0
    while True:
        p = dict(params)
        p["limit"] = "1000"
        p["offset"] = str(off)
        rows, _ = sb_get(table, p)
        out += rows
        off += len(rows)
        if len(rows) < 1000:
            break
    if label:
        print(f"      {label} {len(out)} 行", flush=True)
    return out


# ---------------------------------------------------------------- 数据装配
def load_hourly(names: tuple[str, ...]) -> list[dict]:
    """Mac 小时档 → [{coin, d, rate_sum, n_hours}](coin 大写, UTC 日)。"""
    out = []
    for n in names:
        p = MAC_ROOT / f"{n.lower()}_funding_1h.csv"
        if not p.exists():
            raise SystemExit(f"缺小时档文件: {p}")
        buckets: dict[str, list[float]] = {}
        with open(p, newline="") as f:
            rd = csv.reader(f)
            next(rd)
            for row in rd:
                ts = int(row[0])
                d = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
                buckets.setdefault(d.isoformat(), []).append(float(row[1]))
        for d, vals in buckets.items():
            out.append({"coin": n, "d": d, "rate_sum": sum(vals), "n_hours": len(vals)})
    return out


def load_hl_sb(names: tuple[str, ...], d0: str = "2026-07-20", d1: str = "2026-11-05") -> list[dict]:
    rows = sb_paged("hl_funding_daily",
                    {"select": "coin,d,rate_sum,n_hours",
                     "coin": "in.(" + ",".join(names) + ")",
                     "d": f"gte.{d0}", "order": "coin.asc,d.asc"}, "hl_funding_daily")
    return [{"coin": r["coin"], "d": str(r["d"])[:10], "rate_sum": float(r["rate_sum"]),
             "n_hours": int(r["n_hours"])} for r in rows if str(r["d"])[:10] <= d1]


def load_binance_funding(names: tuple[str, ...], d0: str, d1: str) -> list[dict]:
    """funding_history venue=binance_perp(8 小时档)→ UTC 日求和 + 当日档数。"""
    out = []
    for n in names:
        rows = sb_paged("funding_history",
                        {"select": "funding_time,funding_rate", "venue": "eq.binance_perp",
                         "symbol": "eq." + n, "funding_time": f"gte.{d0}",
                         "funding_time": "lte.2026-11-06", "order": "funding_time.asc"},
                        f"funding_history {n}")
        buckets: dict[str, list[float]] = {}
        for r in rows:
            ts = str(r["funding_time"])
            day = ts[:10]
            if day > d1:
                continue
            buckets.setdefault(day, []).append(float(r["funding_rate"]))
        for day, vals in buckets.items():
            out.append({"coin": n, "d": day, "rate_sum": sum(vals), "n_buckets": len(vals)})
    return out


def load_perp_bv(names: tuple[str, ...], d0: str, d1: str) -> dict[str, dict[str, float]]:
    """perp_bv_daily 的同日收盘(Binance 永续)。"""
    out: dict[str, dict[str, float]] = {n: {} for n in names}
    rows = sb_paged("perp_bv_daily",
                    {"select": "symbol,d,c", "symbol": "in.(" + ",".join(names) + ")",
                     "d": f"gte.{d0}", "d": f"lte.{d1}", "order": "symbol.asc,d.asc"},
                    "perp_bv_daily")
    for r in rows:
        c = r.get("c")
        if c is not None:
            out.setdefault(r["symbol"], {})[str(r["d"])[:10]] = float(c)
    return out


def load_spot(names: tuple[str, ...], d0: str, d1: str) -> dict[str, dict[str, float]]:
    """ohlcv_daily source=binance_hist 的收盘(Binance 现货)。"""
    out: dict[str, dict[str, float]] = {n: {} for n in names}
    rows = sb_paged("ohlcv_daily",
                    {"select": "symbol,trade_date,close", "source": "eq.binance_hist",
                     "symbol": "in.(" + ",".join(NAMES) + ")",
                     "trade_date": f"gte.{d0}", "trade_date": f"lte.{d1}",
                     "order": "symbol.asc,trade_date.asc"}, "ohlcv_daily")
    for r in rows:
        c = r.get("close")
        if c is not None:
            out.setdefault(r["symbol"], {})[str(r["trade_date"])[:10]] = float(c)
    return out


def load_lend(d0: str = "2023-05-01", d1: str = "2026-11-05") -> dict[str, float]:
    rows = sb_paged("feature_matrix_daily",
                    {"select": "d,f", "d": f"gte.{d0}", "order": "d.asc"}, "feature_matrix_daily")
    apy = {}
    for r in rows:
        v = (r.get("f") or {}).get("stable_lend_apy_7d")
        if v is not None and str(r["d"])[:10] <= d1:
            apy[str(r["d"])[:10]] = float(v)
    return apy


# ---------------------------------------------------------------- 矩阵与窗口
def matrix_generic(rows: list[dict], names: tuple[str, ...], d0: dt.date, d1: dt.date,
                   key: str = "rate_sum", min_n: int = 1) -> tuple[list[dt.date], np.ndarray]:
    """carry_hl.matrix 的通用版:日 × 名字 的费率矩阵,当日记录数 < min_n 的格子是 NaN。"""
    days = [d0 + dt.timedelta(i) for i in range((d1 - d0).days + 1)]
    di = {d: i for i, d in enumerate(days)}
    ni = {n: j for j, n in enumerate(names)}
    F = np.full((len(days), len(names)), np.nan)
    for r in rows:
        d = dt.date.fromisoformat(str(r["d"])[:10])
        if d in di and r.get("coin") in ni and r.get(key) is not None and int(r.get("n_buckets") or 0) >= min_n:
            F[di[d], ni[r["coin"]]] = float(r[key])
    return days, F


def win_mean(F: np.ndarray, i: int, look: int) -> tuple[np.ndarray, np.ndarray]:
    """窗口 [i-look, i) 的均值与有数天数(NaN 语义照 carry_hl.rule_b / top_half)。"""
    w = F[max(0, i - look):i]
    if len(w) == 0:
        return np.full(F.shape[1], np.nan), np.zeros(F.shape[1], int)
    cnt = (~np.isnan(w)).sum(0)
    with np.errstate(all="ignore"):
        mu = np.nanmean(w, 0)
    return mu, cnt


def decide(i: int, FB: np.ndarray, FHL: np.ndarray, sel_mode: str, venue_mode: str,
           rule_b_mode: str = "venue"):
    """每周一(索引 i)的决策:所选场所、所选场所上的规则 B、选中的前一半。"""
    muB7, cntB7 = win_mean(FB, i, 7)
    muH7, cntH7 = win_mean(FHL, i, 7)
    if venue_mode == "fixed_hl":
        use_b = np.zeros(FB.shape[1], bool)
    elif venue_mode == "fixed_bn":
        use_b = np.ones(FB.shape[1], bool)
    else:
        use_b = np.where(np.isnan(muB7), False,
                         np.where(np.isnan(muH7), True, muB7 > muH7))
    onB = (cntB7 >= 5) & (np.nan_to_num(muB7) > 0)
    onH = (cntH7 >= 5) & (np.nan_to_num(muH7) > 0)
    on = onH if rule_b_mode == "hl" else np.where(use_b, onB, onH)
    muB30, _ = win_mean(FB, i, 30)
    muH30, _ = win_mean(FHL, i, 30)
    if sel_mode == "max2":
        mu30 = np.where(np.isnan(muB30), muH30,
                        np.where(np.isnan(muH30), muB30, np.maximum(muB30, muH30)))
    else:
        mu30 = muH30
    ok = ~np.isnan(mu30)
    sel = np.zeros(FB.shape[1], bool)
    n = int(ok.sum()) // 2
    if n:
        order = sorted((j for j in range(FB.shape[1]) if ok[j]), key=lambda j: (-mu30[j], j))
        sel[order[:n]] = True
    venue = np.where(use_b, VEN_BN, VEN_HL)
    return venue, on, sel, muB7, muH7, mu30


def path_x(days: list[dt.date], FB: np.ndarray, FHL: np.ndarray, start: dt.date,
           sel_mode: str, venue_mode: str, spot_cost: float, perp_cost: dict,
           use_basis: bool, perp_c: dict, spot_c: dict, rule_b_mode: str = "venue"):
    """跨所 / 单所路径。结构照 carry_hl.path:起点那天 NAV=1、第一天前向收益是次日;
    决策在周一(窗口 [i-7,i) / [i-30,i))、当日生效。返回逐日 ret 与事件计数。"""
    N = FB.shape[1]
    T = len(days)
    F = {VEN_BN: FB, VEN_HL: FHL}
    k0 = days.index(start)
    last_mon = max(i for i in range(k0 + 1) if days[i].weekday() == 0)
    dec = decide(last_mon, FB, FHL, sel_mode, venue_mode, rule_b_mode)
    pending = dec
    cur_venue = dec[0].copy()
    members = dec[2].copy()
    held = np.full(N, -1, int)          # 当前持有该名的空腿场所(-1 = 无仓位)
    out: dict[str, float] = {}
    ev = {"venue_switch": 0, "open": 0, "close": 0, "spot_touch": 0,
          "basis_binance": 0, "basis_hl_zero": 0, "basis_missing_zero": 0,
          "weeks_binance": 0, "weeks_total": 0, "name_weeks_binance": 0, "name_weeks_total": 0}
    for i in range(k0 + 1, T):
        cost_total = 0.0
        basis_total = 0.0
        if pending is not None:
            venue, on, sel, muB7, muH7, mu30 = pending
            target = np.where(on & sel, venue, -1)
            for j in range(N):
                prev, cur = int(held[j]), int(target[j])
                if cur == prev:
                    continue
                if prev >= 0:
                    cost_total += perp_cost[prev]
                    ev["close"] += 1
                    if use_basis:
                        if prev == VEN_BN:
                            b, ok = basis_of(NAMES[j], days[i], perp_c, spot_c)
                            ev["basis_binance"] += 1
                            if not ok:
                                ev["basis_missing_zero"] += 1
                            basis_total += b
                        else:
                            ev["basis_hl_zero"] += 1
                    if cur < 0:
                        cost_total += spot_cost
                        ev["spot_touch"] += 1
                if cur >= 0:
                    if prev < 0:
                        cost_total += spot_cost
                        ev["spot_touch"] += 1
                    cost_total += perp_cost[cur]
                    ev["open"] += 1
                    if use_basis:
                        if cur == VEN_BN:
                            b, ok = basis_of(NAMES[j], days[i], perp_c, spot_c)
                            ev["basis_binance"] += 1
                            if not ok:
                                ev["basis_missing_zero"] += 1
                            basis_total -= b
                        else:
                            ev["basis_hl_zero"] += 1
                if prev >= 0 and cur >= 0 and prev != cur:
                    ev["venue_switch"] += 1
                held[j] = cur
            cur_venue = venue.copy()
            members = sel.copy()
            pending = None
        # 日度
        avail = np.zeros(N, bool)
        for j in range(N):
            v = cur_venue[j]
            avail[j] = not np.isnan(F[v][i, j])
        m = avail & members
        n = int(m.sum())
        funding = 0.0
        for j in range(N):
            if held[j] >= 0 and m[j]:
                funding += float(np.nan_to_num(F[held[j]][i, j]))
        r = (funding - cost_total + basis_total) / n if n else 0.0
        out[days[i].isoformat()] = r
        if days[i].weekday() == 6:      # 周日收盘 ⇒ 周一的决策(窗口到周日为止)
            pending = decide(i + 1, FB, FHL, sel_mode, venue_mode, rule_b_mode)
    # 场所占比(名字 × 周)
    for i in range(k0, T):
        if days[i].weekday() == 0:
            v, on, sel, muB7, muH7, mu30 = decide(i, FB, FHL, sel_mode, venue_mode, rule_b_mode)
            ev["weeks_total"] += 1
            nb = int((v == VEN_BN).sum())
            ev["weeks_binance"] += nb
            ev["name_weeks_total"] += int(sel.sum())
            ev["name_weeks_binance"] += int(((v == VEN_BN) & sel).sum())
    return out, ev


def basis_of(name: str, day: dt.date, perp_c: dict, spot_c: dict) -> tuple[float, bool]:
    """基差 =(Binance 永续收盘 − Binance 现货收盘)/现货收盘;缺任一 ⇒ 0 并计数。"""
    d = day.isoformat()
    p = perp_c.get(name, {}).get(d)
    s = spot_c.get(name, {}).get(d)
    if p is None or s is None or s == 0:
        return 0.0, False
    return (p - s) / s, True


# ---------------------------------------------------------------- 汇总口径
def sum_ret(series: dict[str, float], d0: dt.date, d1: dt.date) -> tuple[float, int]:
    s, n = 0.0, 0
    d = d0
    while d <= d1:
        s += series.get(d.isoformat(), 0.0)
        n += 1
        d += dt.timedelta(days=1)
    return s, n


def ann(sum_daily: float, ndays: int) -> float:
    return sum_daily * 365.0 / ndays


INTERVALS = [
    ("全样本 2023-06-12 → 2026-11-05", START, D1),
    ("2023-06 → 2024-12", START, dt.date(2024, 12, 31)),
    ("2025-01 → 2026-11-05", dt.date(2025, 1, 1), D1),
    ("2026H1", dt.date(2026, 1, 1), dt.date(2026, 6, 30)),
    ("2023H2", dt.date(2023, 7, 1), dt.date(2023, 12, 31)),
    ("2024H1", dt.date(2024, 1, 1), dt.date(2024, 6, 30)),
    ("2024H2", dt.date(2024, 7, 1), dt.date(2024, 12, 31)),
    ("2025H1", dt.date(2025, 1, 1), dt.date(2025, 6, 30)),
    ("2025H2", dt.date(2025, 7, 1), dt.date(2025, 12, 31)),
    ("2026-07 → 11-05", dt.date(2026, 7, 1), D1),
]


def table(series: dict[str, float], lend: dict[str, float]) -> list[dict]:
    out = []
    for name, a, b in INTERVALS:
        sn, n = sum_ret(series, a, b)
        sl, _ = sum_ret(lend, a, b)
        out.append({"interval": name, "start": a.isoformat(), "end": b.isoformat(), "days": n,
                    "nominal": round(ann(sn, n) * 100, 4),
                    "capital": round(ann(sn, n) * CAP * 100, 4),
                    "lend": round(ann(sl, n) * 100, 4)})
    return out


def main() -> None:
    print("[1/7] 读 Mac 小时档 …", flush=True)
    hourly = load_hourly(NAMES)
    print(f"      小时档 {len(hourly)} 行", flush=True)

    print("[2/7] 读 hl_funding_daily …", flush=True)
    hl_sb = load_hl_sb(NAMES)
    print(f"      Supabase {len(hl_sb)} 行", flush=True)

    print("[3/7] 读 funding_history(binance_perp) …", flush=True)
    bn = load_binance_funding(NAMES, "2023-05-12", "2026-11-05")
    part = [r for r in bn if r["n_buckets"] < 3]
    print(f"      Binance {len(bn)} 天-名;档数 < 3 的 {len(part)} 个", flush=True)

    print("[4/7] 读 perp_bv_daily / ohlcv_daily / 借贷 …", flush=True)
    perp_c = load_perp_bv(NAMES, "2023-05-12", "2026-11-05")
    spot_c = load_spot(NAMES, "2023-05-12", "2026-11-05")
    apy = load_lend()
    print(f"      借贷日数 {len(apy)}", flush=True)

    # HL 装配:≤07-20 小时档,≥07-21 Supabase(台账 S-749 补记)
    hl_rows = [r for r in hourly if r["d"] <= CUT.isoformat()] + \
              [r for r in hl_sb if r["d"] > CUT.isoformat()]
    hl_rows.sort(key=lambda r: (r["coin"], r["d"]))

    days, FHL = matrix(hl_rows, NAMES, D0, D1)                 # 公用内核(HL,MIN_HOURS=20)
    days2, FB = matrix_generic(bn, NAMES, D0, D1, min_n=1)     # Binance 永续日费率
    assert days == days2

    res: dict = {"meta": {
        "task": "T-276", "prereg": "S-755", "names": list(NAMES), "n_names": len(NAMES),
        "d0": D0.isoformat(), "d1": D1.isoformat(), "start": START.isoformat(),
        "cut_hourly_to": CUT.isoformat(), "hourly_rows": len(hourly), "hl_sb_rows": len(hl_sb),
        "binance_days": len(bn), "binance_partial_days": len(part),
        "cap": CAP, "cost_s749_bp": COST_REAL * 1e4,
        "cost_s755_spot_bp": SPOT_COST * 1e4,
        "cost_s755_perp_bp": {("binance_perp" if k == VEN_BN else "hyperliquid"): v * 1e4
                              for k, v in PERP_COST.items()},
        "lend_days": len(apy)}}

    # 借贷基准
    lend_daily = {d: v / 100.0 / 365.0 for d, v in apy.items()}

    print("[5/7] A0:复现 S-749(HL 单所 carry_b_top_rc) …", flush=True)
    pth0 = path(days, FHL, "carry_b_top_rc", START, COST_REAL)
    A0 = {r["d"]: r["ret"] for r in pth0}
    A0_gross = {r["d"]: r["ret"] for r in path(days, FHL, "carry_b_top_rc", START, 0.0)}
    tbl0 = table(A0, lend_daily)
    res["a0_s749_reproduce"] = {"table": tbl0, "gross_table": table(A0_gross, lend_daily)}
    fs = next(r for r in tbl0 if r["interval"].startswith("全样本"))
    h1 = next(r for r in tbl0 if r["interval"] == "2026H1")
    res["a0_s749_reproduce"]["check"] = {
        "full_sample_capital_pct": fs["capital"], "target": 10.86, "diff_pp": round(fs["capital"] - 10.86, 4),
        "h1_2026_capital_pct": h1["capital"], "target_h1": 2.09, "diff_pp_h1": round(h1["capital"] - 2.09, 4),
        "within_0p15pp": abs(fs["capital"] - 10.86) <= 0.15 and abs(h1["capital"] - 2.09) <= 0.15}

    print("[6/7] A1 / A2:同口径单所(HL) 与 跨所 …", flush=True)
    # 自检:同一选择 + 同一 15.5bp/次成本(现货 9bp + HL 永续 6.5bp)+ 无基差 ⇒ 必须逐日等于 A0
    #      (carry_hl.path 的输出自己 round 到 8 位小数,故容差 1e-8)
    chk, ev_chk = path_x(days, FB, FHL, START, "hl", "fixed_hl", 0.0009,
                          {VEN_BN: 0.0007, VEN_HL: 0.00065}, False, perp_c, spot_c,
                          rule_b_mode="hl")
    diffs = [abs(chk.get(k, 0.0) - v) for k, v in A0.items()]
    res["selfcheck_path_vs_carry_hl"] = {
        "n_days": len(diffs), "max_abs_daily_diff": float(max(diffs)) if diffs else None,
        "tolerance": 1e-8, "note": "carry_hl.path 的 ret 输出 round(…, 8),差 ≤ 5e-9 即逐日相同",
        "pass": bool(diffs and max(diffs) <= 1e-8),
        "a0_equivalent_events": ev_chk}
    print(f"      自检(我的路径 vs carry_hl.path):max|Δ| = {max(diffs) if diffs else None}", flush=True)

    A1, ev1 = path_x(days, FB, FHL, START, "hl", "fixed_hl", SPOT_COST, PERP_COST, True, perp_c, spot_c,
                      rule_b_mode="hl")
    A1_gross, _ = path_x(days, FB, FHL, START, "hl", "fixed_hl", 0.0, PERP_COST, False, perp_c, spot_c,
                          rule_b_mode="hl")
    A2, ev2 = path_x(days, FB, FHL, START, "max2", "dynamic", SPOT_COST, PERP_COST, True, perp_c, spot_c)
    A2_gross, _ = path_x(days, FB, FHL, START, "max2", "dynamic", 0.0, PERP_COST, False, perp_c, spot_c)
    # 解耦臂:A3 = 只换场所(选择与规则 B 照 A1);A4 = 只换选择与规则 B 口径(场所锁 HL)
    A3, ev3 = path_x(days, FB, FHL, START, "hl", "dynamic", SPOT_COST, PERP_COST, True, perp_c, spot_c,
                     rule_b_mode="hl")
    A3_gross, _ = path_x(days, FB, FHL, START, "hl", "dynamic", 0.0, PERP_COST, False, perp_c, spot_c,
                          rule_b_mode="hl")
    A4, ev4 = path_x(days, FB, FHL, START, "max2", "fixed_hl", SPOT_COST, PERP_COST, True, perp_c, spot_c)
    A4_gross, _ = path_x(days, FB, FHL, START, "max2", "fixed_hl", 0.0, PERP_COST, False, perp_c, spot_c)
    res["a1_hl_only_s755_cost"] = {"table": table(A1, lend_daily), "gross_table": table(A1_gross, lend_daily),
                                   "events": ev1}
    res["a2_cross_venue"] = {"table": table(A2, lend_daily), "gross_table": table(A2_gross, lend_daily),
                             "events": ev2}
    res["a3_venue_only"] = {"table": table(A3, lend_daily), "gross_table": table(A3_gross, lend_daily),
                            "events": ev3}
    res["a4_selection_only"] = {"table": table(A4, lend_daily), "gross_table": table(A4_gross, lend_daily),
                                 "events": ev4}

    print("[7/7] 判据 (a)–(d) …", flush=True)
    def pick(tbl, key):
        return next(r for r in tbl if r["interval"] == key)

    t0, t1, t2 = res["a0_s749_reproduce"]["table"], res["a1_hl_only_s755_cost"]["table"], res["a2_cross_venue"]["table"]
    g2 = res["a2_cross_venue"]["gross_table"]
    g0 = res["a0_s749_reproduce"]["gross_table"]

    full2 = pick(t2, "全样本 2023-06-12 → 2026-11-05")
    h1_2 = pick(t2, "2026H1")
    seg1_2 = pick(t2, "2023-06 → 2024-12")
    seg2_2 = pick(t2, "2025-01 → 2026-11-05")
    full0 = pick(t0, "全样本 2023-06-12 → 2026-11-05")
    h1_0 = pick(t0, "2026H1")
    seg1_0 = pick(t0, "2023-06 → 2024-12")
    seg2_0 = pick(t0, "2025-01 → 2026-11-05")
    full1 = pick(t1, "全样本 2023-06-12 → 2026-11-05")
    h1_1 = pick(t1, "2026H1")
    seg1_1 = pick(t1, "2023-06 → 2024-12")
    seg2_1 = pick(t1, "2025-01 → 2026-11-05")

    # 成本拖累分解(年化,pp)
    gf0, gf1, gf2 = pick(g0, "全样本 2023-06-12 → 2026-11-05"), pick(res["a1_hl_only_s755_cost"]["gross_table"], "全样本 2023-06-12 → 2026-11-05"), pick(g2, "全样本 2023-06-12 → 2026-11-05")
    drag0 = gf0["capital"] - full0["capital"]
    drag1 = gf1["capital"] - full1["capital"]
    drag2 = gf2["capital"] - full2["capital"]
    gross_inc_vs_a0 = gf2["capital"] - gf0["capital"]
    gross_inc_vs_a1 = gf2["capital"] - gf1["capital"]
    extra_drag_vs_a0 = drag2 - drag0
    extra_drag_vs_a1 = drag2 - drag1
    years = (D1 - START).days / 365.0
    switches_per_year = ev2["venue_switch"] / years

    res["verdict"] = {
        "a_full_sample_vs_a0": {
            "a2_capital_pct": full2["capital"], "a0_capital_pct": full0["capital"],
            "threshold_pct": round(full0["capital"] + 2.0, 4), "target_from_ledger_pct": 12.86,
            "pass": full2["capital"] >= full0["capital"] + 2.0},
        "b_2026h1_vs_lend": {
            "a2_capital_pct": h1_2["capital"], "lend_pct": h1_2["lend"], "ledger_lend_pct": 2.98,
            "pass": h1_2["capital"] > h1_2["lend"]},
        "c_two_segments_vs_a0": {
            "seg1_2023_06_to_2024_12": {"a2": seg1_2["capital"], "a0": seg1_0["capital"],
                                        "pass": seg1_2["capital"] > seg1_0["capital"]},
            "seg2_2025_01_to_2026_11": {"a2": seg2_2["capital"], "a0": seg2_0["capital"],
                                        "pass": seg2_2["capital"] > seg2_0["capital"]},
            "pass": (seg1_2["capital"] > seg1_0["capital"]) and (seg2_2["capital"] > seg2_0["capital"])},
        "d_cost_drag": {
            "venue_switches": ev2["venue_switch"], "years": round(years, 3),
            "switches_per_year": round(switches_per_year, 2),
            "gross_a0": gf0["capital"], "gross_a2": gf2["capital"],
            "net_a0": full0["capital"], "net_a2": full2["capital"],
            "drag_a0_pp": round(drag0, 4), "drag_a2_pp": round(drag2, 4),
            "gross_increment_vs_a0_pp": round(gross_inc_vs_a0, 4),
            "extra_drag_vs_a0_pp": round(extra_drag_vs_a0, 4),
            "gross_increment_vs_a1_pp": round(gross_inc_vs_a1, 4),
            "extra_drag_vs_a1_pp": round(extra_drag_vs_a1, 4),
            "pass_relative_vs_a0": bool(extra_drag_vs_a0 <= 0.5 * gross_inc_vs_a0) if gross_inc_vs_a0 > 0 else False,
            "pass_total_vs_a0": bool(drag2 <= 0.5 * gross_inc_vs_a0) if gross_inc_vs_a0 > 0 else False},
        "same_cost_comparison_vs_a1": {
            "full_sample": {"a2": full2["capital"], "a1": full1["capital"],
                            "a2_wins": full2["capital"] > full1["capital"]},
            "2026H1": {"a2": h1_2["capital"], "a1": h1_1["capital"],
                       "a2_wins": h1_2["capital"] > h1_1["capital"]},
            "seg1": {"a2": seg1_2["capital"], "a1": seg1_1["capital"],
                     "a2_wins": seg1_2["capital"] > seg1_1["capital"]},
            "seg2": {"a2": seg2_2["capital"], "a1": seg2_1["capital"],
                     "a2_wins": seg2_2["capital"] > seg2_1["capital"]}},
    }
    v = res["verdict"]
    v["all_pass"] = bool(v["a_full_sample_vs_a0"]["pass"] and v["b_2026h1_vs_lend"]["pass"]
                         and v["c_two_segments_vs_a0"]["pass"] and v["d_cost_drag"]["pass_relative_vs_a0"])

    # 解耦(全样本 / 2026H1;净与毛):A1 = 基准(选择=HL、场所=HL、规则 B=HL)
    #   A3 = 只换场所;A4 = 只换选择与规则 B 口径(场所锁 HL);A2 = 两个都换(S-755 写死的那条)
    def _arm(tbl, key):
        return pick(tbl, key)

    def _decomp(key):
        arms = {"A1_hl_only": res["a1_hl_only_s755_cost"], "A2_cross_venue": res["a2_cross_venue"],
                "A3_venue_only": res["a3_venue_only"], "A4_selection_only": res["a4_selection_only"]}
        net = {k: _arm(a["table"], key)["capital"] for k, a in arms.items()}
        gross = {k: _arm(a["gross_table"], key)["capital"] for k, a in arms.items()}
        return {"interval": key, "net_capital_pct": net, "gross_capital_pct": gross,
                "venue_effect_pp": round(net["A3_venue_only"] - net["A1_hl_only"], 4),
                "venue_effect_gross_pp": round(gross["A3_venue_only"] - gross["A1_hl_only"], 4),
                "selection_effect_pp": round(net["A4_selection_only"] - net["A1_hl_only"], 4),
                "selection_effect_gross_pp": round(gross["A4_selection_only"] - gross["A1_hl_only"], 4),
                "total_pp": round(net["A2_cross_venue"] - net["A1_hl_only"], 4),
                "total_gross_pp": round(gross["A2_cross_venue"] - gross["A1_hl_only"], 4)}

    res["decomposition"] = {
        "full_sample": _decomp("全样本 2023-06-12 → 2026-11-05"),
        "2026H1": _decomp("2026H1"),
        "seg_2025_2026": _decomp("2025-01 → 2026-11-05"),
    }

    # 副项(只报不判)
    bn_only, ev_bn = path_x(days, FB, FHL, START, "max2", "fixed_bn", SPOT_COST, PERP_COST, True, perp_c, spot_c)
    res["side_items"] = {
        "binance_only_arm": {"table": table(bn_only, lend_daily), "events": ev_bn},
        "venue_share": {
            "weeks_all_names_on_binance": ev2["weeks_binance"], "weeks_total": ev2["weeks_total"],
            "share_names_on_binance": round(ev2["weeks_binance"] / max(1, ev2["weeks_total"]), 4),
            "selected_name_weeks_on_binance": ev2["name_weeks_binance"],
            "selected_name_weeks_total": ev2["name_weeks_total"],
            "share_selected_on_binance": round(ev2["name_weeks_binance"] / max(1, ev2["name_weeks_total"]), 4)},
        "events_a2": ev2,
    }
    # 两所费率差分布(Binance − HL,逐日逐名,只在两所都有数的格子上)
    both = ~np.isnan(FB) & ~np.isnan(FHL)
    diff = FB[both] - FHL[both]
    res["side_items"]["rate_diff_distribution"] = {
        "n_cells": int(both.sum()),
        "mean_bp_per_day": round(float(diff.mean()) * 1e4, 4),
        "median_bp_per_day": round(float(np.median(diff)) * 1e4, 4),
        "p10_bp": round(float(np.percentile(diff, 10)) * 1e4, 4),
        "p90_bp": round(float(np.percentile(diff, 90)) * 1e4, 4),
        "share_binance_higher": round(float((diff > 0).mean()), 4),
        "share_hl_higher": round(float((diff < 0).mean()), 4)}

    out = REPO / "docs" / "research" / "t276_results.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print("写出", out, flush=True)

    print("\n=== A0(S-749 复现) ===", flush=True)
    for r in tbl0:
        print(f"  {r['interval']:<28} 名义 {r['nominal']:>8.4f}  资本 {r['capital']:>8.4f}  借贷 {r['lend']:>8.4f}", flush=True)
    print("=== A1(单所, S-755 成本) ===", flush=True)
    for r in res["a1_hl_only_s755_cost"]["table"]:
        print(f"  {r['interval']:<28} 名义 {r['nominal']:>8.4f}  资本 {r['capital']:>8.4f}", flush=True)
    print("=== A2(跨所) ===", flush=True)
    for r in res["a2_cross_venue"]["table"]:
        print(f"  {r['interval']:<28} 名义 {r['nominal']:>8.4f}  资本 {r['capital']:>8.4f}  借贷 {r['lend']:>8.4f}", flush=True)
    print("=== 判据 ===", flush=True)
    print(json.dumps(v, ensure_ascii=False, indent=2), flush=True)
    print("=== 解耦 ===", flush=True)
    print(json.dumps(res["decomposition"], ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
