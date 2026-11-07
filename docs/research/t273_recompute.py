#!/usr/bin/env python3
"""T-273 · S-752 盲复算 —— S-749(④ 套息 vs 稳定币借贷)与 S-750(按过去 4 周切换)。

只看台账 REFUTATION_LEDGER.md 的 S-749 / S-750 正文(含两条补记与时间更正)与
src/data/signals/carry_hl.py(公用内核:matrix / path)。**不看** Seth 的临时脚本。

装配(照台账字面):
  资金费  2023-05-12 → 2026-07-20 = Mac 数据根 _data/hyperliquid_funding/*_funding_1h.csv
          2026-07-21 → 2026-11-05 = Supabase hl_funding_daily
  口径    UTC 日内 rate 之和(rate_sum)+ 当日行数(n_hours),与视图
          `select coin,(t at time zone 'utc')::date d, sum(rate) rate_sum, count(*) n_hours ...` 同
  宇宙    ① 面板 24 名去掉 ADA / LTC(小时档没有这两个)= 22 名
  借贷    feature_matrix_daily.stable_lend_apy_7d(%/yr),日收益 = apy/100/365
  套息    carry_hl.path(arm='carry_b_top_rc') —— 规则 B ∧ 过去 30 天排名前一半,分母 = 选中,
          真实成本 15.5bp/次,资本口径 = 名义 × 0.75

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
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.data.signals.carry_hl import COST_REAL, matrix, path          # noqa: E402
from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE  # noqa: E402

MAC_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
NAMES = tuple(n for n in DEFAULT_UNIVERSE if n not in ("ADA", "LTC"))   # 22 名
NAMES_ALPHA = tuple(sorted(NAMES))
D0 = dt.date(2023, 5, 12)          # 台账:第一个满 30 天排名的周一之前要有历史
D1 = dt.date(2026, 11, 5)          # 台账:算到 2026-11-05
CUT = dt.date(2026, 7, 20)         # 台账补记:≤07-20 用小时档,≥07-21 用 hl_funding_daily
S749_START = dt.date(2023, 6, 12)   # 台账:第一个满 30 天排名的周一
S750_START = dt.date(2023, 7, 10)   # 台账:让套息有 28 天尾部
CAP = 0.75                         # 资本口径:名义 × 0.75(现货 + 1/3 保证金)


# ---------------------------------------------------------------- Supabase 读
def sb_get(table: str, params: dict, want_count: bool = False):
    q = urllib.parse.urlencode(params)
    headers = {"apikey": os.environ["SUPABASE_KEY"],
               "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}"}
    if want_count:
        headers["Prefer"] = "count=exact"
    req = urllib.request.Request(f"{os.environ['SUPABASE_URL']}/rest/v1/{table}?{q}", headers=headers)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range")
    return (json.loads(body) if body.strip() else []), cr


def sb_paged(table: str, params: dict, page: int = 1000, max_pages: int = 200):
    out = []
    for i in range(max_pages):
        p = dict(params)
        p["limit"] = str(page)
        p["offset"] = str(i * page)
        rows, cr = sb_get(table, p)
        out += rows
        if len(rows) < page:
            break
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
                key = d.isoformat()
                b = buckets.get(key)
                if b is None:
                    buckets[key] = [float(row[1])]
                else:
                    b.append(float(row[1]))
        for d, vals in buckets.items():
            out.append({"coin": n, "d": d, "rate_sum": sum(vals), "n_hours": len(vals)})
    return out


def load_sb_daily(names: tuple[str, ...], d0: str = "2023-05-12", d1: str = "2026-11-05") -> list[dict]:
    """Supabase hl_funding_daily → [{coin, d, rate_sum, n_hours}](分页带 order,每页 ≤ 1000)。"""
    params = {"select": "coin,d,rate_sum,n_hours",
              "coin": "in.(" + ",".join(names) + ")",
              "d": f"gte.{d0}", "order": "coin.asc,d.asc"}
    rows = sb_paged("hl_funding_daily", params)
    keep = []
    for r in rows:
        d = str(r["d"])[:10]
        if d <= d1:
            keep.append({"coin": r["coin"], "d": d, "rate_sum": float(r["rate_sum"]),
                         "n_hours": int(r["n_hours"])})
    return keep


def load_lend(d0: str = "2023-05-01", d1: str = "2026-11-05") -> dict[str, float]:
    """feature_matrix_daily.f->>'stable_lend_apy_7d'(%/yr)。"""
    rows = sb_paged("feature_matrix_daily", {"select": "d,f", "d": f"gte.{d0}",
                                              "order": "d.asc"})
    rows = [r for r in rows if str(r["d"])[:10] <= d1]
    apy = {}
    for r in rows:
        v = (r.get("f") or {}).get("stable_lend_apy_7d")
        if v is not None:
            apy[str(r["d"])[:10]] = float(v)
    return apy


# ---------------------------------------------------------------- 汇总口径
INTERVALS_749 = [
    ("2023H2", dt.date(2023, 7, 1), dt.date(2023, 12, 31)),
    ("2024H1", dt.date(2024, 1, 1), dt.date(2024, 6, 30)),
    ("2024H2", dt.date(2024, 7, 1), dt.date(2024, 12, 31)),
    ("2025H1", dt.date(2025, 1, 1), dt.date(2025, 6, 30)),
    ("2025H2", dt.date(2025, 7, 1), dt.date(2025, 12, 31)),
    ("2026H1", dt.date(2026, 1, 1), dt.date(2026, 6, 30)),
    ("2026-07 → 11-05", dt.date(2026, 7, 1), dt.date(2026, 11, 5)),
    ("最近 13 周(91 天)", D1 - dt.timedelta(days=90), D1),
    ("最近 13 周(92 天)", D1 - dt.timedelta(days=91), D1),
    ("全样本(起 2023-06-12)", S749_START, D1),
    ("全样本(起 2023-07-01)", dt.date(2023, 7, 1), D1),
]

def window(rows: list[dict], d0: dt.date, d1: dt.date) -> list[dict]:
    return [r for r in rows if d0 <= dt.date.fromisoformat(r["d"]) <= d1]


def sum_ret(series: dict[str, float], d0: dt.date, d1: dt.date) -> tuple[float, int]:
    """区间内日简单收益之和 + 区间自然日数。"""
    s, n = 0.0, 0
    d = d0
    while d <= d1:
        s += series.get(d.isoformat(), 0.0)
        n += 1
        d += dt.timedelta(days=1)
    return s, n


def ann(sum_daily: float, ndays: int) -> float:
    return sum_daily * 365.0 / ndays


def lend_series(apy: dict[str, float]) -> dict[str, float]:
    return {d: v / 100.0 / 365.0 for d, v in apy.items()}


# ---------------------------------------------------------------- 主流程
def main() -> None:
    print("[1/5] 读 Mac 小时档 …", flush=True)
    hourly = load_hourly(NAMES)
    print(f"      小时档行数 {len(hourly)}", flush=True)

    print("[2/5] 读 Supabase hl_funding_daily …", flush=True)
    sb = load_sb_daily(NAMES)
    print(f"      Supabase 行数 {len(sb)}", flush=True)

    print("[3/5] 读 feature_matrix_daily 借贷 …", flush=True)
    apy = load_lend()
    print(f"      借贷日数 {len(apy)}  范围 {min(apy)} → {max(apy)}", flush=True)

    # 装配:台账口径(≤07-20 小时档,≥07-21 Supabase)
    rows = [r for r in hourly if r["d"] <= CUT.isoformat()] + \
           [r for r in sb if r["d"] > CUT.isoformat()]
    rows.sort(key=lambda r: (r["coin"], r["d"]))
    # 装配:全 Supabase(敏感性)
    rows_sb = sorted(sb, key=lambda r: (r["coin"], r["d"]))
    # 装配:全小时档到其自身末尾 + Supabase 之后(敏感性)
    hmax = max(r["d"] for r in hourly)
    rows_hy = [r for r in hourly if r["d"] <= hmax] + [r for r in sb if r["d"] > hmax]
    rows_hy.sort(key=lambda r: (r["coin"], r["d"]))

    # 重叠期一致性(小时档 vs Supabase)
    hmap = {(r["coin"], r["d"]): (r["rate_sum"], r["n_hours"]) for r in hourly}
    smap = {(r["coin"], r["d"]): (r["rate_sum"], r["n_hours"]) for r in sb}
    overlap = sorted(set(hmap) & set(smap))
    diffs = [abs(hmap[k][0] - smap[k][0]) for k in overlap]
    nh_diff = [1 for k in overlap if hmap[k][1] != smap[k][1]]

    res: dict = {
        "meta": {
            "task": "T-273", "prereg": "S-752",
            "names": list(NAMES), "n_names": len(NAMES),
            "d0": D0.isoformat(), "d1": D1.isoformat(),
            "cut_hourly_to": CUT.isoformat(),
            "hourly_rows": len(hourly), "sb_rows": len(sb),
            "hourly_max_d": hmax,
            "overlap_days": len(overlap),
            "overlap_max_abs_rate_sum_diff": max(diffs) if diffs else None,
            "overlap_n_hours_mismatch_days": len(nh_diff),
            "lend_days": len(apy), "lend_min": min(apy), "lend_max": max(apy),
            "cost_real_bp": COST_REAL * 1e4, "cap": CAP,
        }
    }

    # ---------------------------------------------------------- S-749

    lend_daily = lend_series(apy)

    def run_749(rows_in, label):
        days, F = matrix(rows_in, NAMES, D0, D1)
        pth = path(days, F, "carry_b_top_rc", S749_START, COST_REAL)
        nom = {r["d"]: r["ret"] for r in pth}
        tbl = []
        for name, a, b in INTERVALS_749:
            sn, n = sum_ret(nom, a, b)
            sl, _ = sum_ret(lend_daily, a, b)
            a_nom = ann(sn, n)
            a_cap = a_nom * CAP
            a_lend = ann(sl, n)
            tbl.append({"interval": name, "start": a.isoformat(), "end": b.isoformat(), "days": n,
                        "carry_nominal": round(a_nom * 100, 4),
                        "carry_capital": round(a_cap * 100, 4),
                        "lend": round(a_lend * 100, 4),
                        "winner": "carry" if a_cap > a_lend else "lend",
                        "gap_pp": round((a_cap - a_lend) * 100, 4)})
        return tbl, nom

    print("[4/5] 跑 S-749 …", flush=True)
    tbl_749, nom_749 = run_749(rows, "台账口径")
    tbl_749_sb, _ = run_749(rows_sb, "全 Supabase")
    tbl_749_hy, _ = run_749(rows_hy, "全小时档")
    res["s749"] = {"ledger_assembly": tbl_749, "all_supabase": tbl_749_sb, "all_hourly": tbl_749_hy}

    # 判据 (a) 2026H1、(b) 最近 13 周
    def pick(tbl, key):
        return next(r for r in tbl if r["interval"] == key)
    h1 = pick(tbl_749, "2026H1")
    w13 = pick(tbl_749, "最近 13 周(91 天)")
    res["s749"]["verdict"] = {
        "a_2026H1_carry_gt_lend": h1["carry_capital"] > h1["lend"],
        "b_last13w_carry_gt_lend": w13["carry_capital"] > w13["lend"],
        "verdict": "不提真钱" if not (h1["carry_capital"] > h1["lend"] and w13["carry_capital"] > w13["lend"]) else "支持提真钱",
    }

    # ---------------------------------------------------------- S-750
    print("[5/5] 跑 S-750 …", flush=True)
    res["s750"] = build_750(rows, apy, nom_749)
    res["s750_sb"] = build_750(rows_sb, apy, nom_749)

    res["extras"] = run_extras(rows, apy)

    out = Path(__file__).resolve().parent / "t273_results.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print("写出", out, flush=True)


def run_extras(rows_in, apy) -> dict:
    """副项与敏感性:①名字顺序(并列排序)②闲置槽位也放贷 ③原成本口径 ④逐半年胜负。"""
    out = {}

    # ① 名字顺序敏感性(台账写「并列按列序 = 代码字母序」;carry_hl.coins() 实际是面板顺序)
    def table_for(names):
        days, F = matrix(rows_in, names, D0, D1)
        pth = path(days, F, "carry_b_top_rc", S749_START, COST_REAL)
        nom = {r["d"]: r["ret"] for r in pth}
        t = []
        for name, a, b in INTERVALS_749:
            sn, n = sum_ret(nom, a, b)
            t.append(round(ann(sn, n) * CAP * 100, 4))
        return t

    base = table_for(NAMES)
    alpha = table_for(NAMES_ALPHA)
    out["name_order_sensitivity"] = {
        "panel_order_capital_pct": base,
        "alpha_order_capital_pct": alpha,
        "max_abs_diff_pp": round(max(abs(a - b) for a, b in zip(base, alpha)), 6),
    }

    # ②③ 副项
    days, F = matrix(rows_in, NAMES, D0, D1)
    pth = path(days, F, "carry_b_top_rc", S749_START, COST_REAL)
    nom = {r["d"]: r["ret"] for r in pth}
    frac = {r["d"]: (r["n_on"] / r["n_names"] if r["n_names"] else 0.0) for r in pth}
    lend_daily = lend_series(apy)

    # 原成本口径(S-733 的 4bp + 3.5bp = 7.5bp/次)
    pth_old = path(days, F, "carry_b_top", S749_START, 0.0004 + 0.00035)
    nom_old = {r["d"]: r["ret"] for r in pth_old}

    def interval_val(series, a, b):
        s, n = sum_ret(series, a, b)
        return round(ann(s, n) * 100, 4), n

    # 「闲置槽位也放贷」:持有槽位挣套息,闲置槽位挣借贷(逐日加权)
    idle = {}
    for d, r in nom.items():
        dd = dt.date.fromisoformat(d)
        idle[d] = r * CAP + (1.0 - frac.get(d, 0.0)) * lend_daily.get(d, 0.0)

    items = {}
    for name, a, b in INTERVALS_749:
        c_cap, n = interval_val({k: v * CAP for k, v in nom.items()}, a, b)
        c_idle, _ = interval_val(idle, a, b)
        c_old_cap, _ = interval_val({k: v * CAP for k, v in nom_old.items()}, a, b)
        l, _ = interval_val(lend_daily, a, b)
        items[name] = {"carry_capital": c_cap, "carry_capital_idle_lend": c_idle,
                        "carry_capital_old_cost": c_old_cap, "lend": l}
    out["s749_side_items"] = items

    # ④ 逐半年胜负
    wins = []
    for name, a, b in INTERVALS_749[:7]:
        it = items[name]
        wins.append({"interval": name, "winner": "carry" if it["carry_capital"] > it["lend"] else "lend",
                     "gap_pp": round(it["carry_capital"] - it["lend"], 4)})
    out["s749_halfyear_wins"] = wins
    out["s749_carry_wins"] = sum(1 for w in wins if w["winner"] == "carry")
    out["s749_lend_wins"] = sum(1 for w in wins if w["winner"] == "lend")
    return out


def build_750(rows_in, apy, nom_749) -> dict:
    """S-750:每周一按过去 4 周谁高换。"""
    days, F = matrix(rows_in, NAMES, D0, D1)
    pth = path(days, F, "carry_b_top_rc", S749_START, COST_REAL)
    nom = {r["d"]: r["ret"] for r in pth}
    info = {r["d"]: (r["n_names"], r["n_on"]) for r in pth}
    lend_daily = lend_series(apy)

    # 每周一
    mons = []
    d = S750_START
    while d <= D1:
        mons.append(d)
        d += dt.timedelta(days=7)

    def build(win_mode: str):
        """win_mode: 'prev28' = [m-28, m-1]; 'incl28' = [m-27, m]。"""
        modes = {}
        for m in mons:
            if win_mode == "prev28":
                win = [m - dt.timedelta(days=k) for k in range(28, 0, -1)]
            else:
                win = [m - dt.timedelta(days=k) for k in range(27, -1, -1)]
            # 套息:过去 28 天日收益之和 × 365/28 × 0.75(资本口径),换算成 %/yr 与 apy 同单位
            c = sum(nom.get(x.isoformat(), 0.0) for x in win) * 365.0 / 28.0 * CAP * 100.0
            lvals = [v for v in (apy.get(x.isoformat()) for x in win) if v is not None]
            l = sum(lvals) / len(lvals) if lvals else 0.0
            modes[m] = "carry" if c > l else "lend"
        # 逐日
        daily = {}
        for i, m in enumerate(mons):
            nxt = mons[i + 1] - dt.timedelta(days=1) if i + 1 < len(mons) else D1
            mode = modes[m]
            prev = modes[mons[i - 1]] if i > 0 else mode
            switch = (i > 0) and (mode != prev)
            for dd in range((nxt - m).days + 1):
                day = m + dt.timedelta(days=dd)
                ds = day.isoformat()
                if mode == "carry":
                    r = nom.get(ds, 0.0) * CAP
                else:
                    r = lend_daily.get(ds, 0.0)
                if switch and dd == 0:
                    nn, non = info.get(ds, (0, 0))
                    frac = (non / nn) if nn else 0.0
                    r -= COST_REAL * frac * CAP
                daily[ds] = r
        return modes, daily

    out = {}
    for win_mode in ("prev28", "incl28"):
        modes, daily = build(win_mode)
        intervals = [
            ("全样本 2023-07-10 → 2026-11-05", S750_START, D1),
            ("2025-01 → 2026-11-05", dt.date(2025, 1, 1), D1),
            ("2026H1", dt.date(2026, 1, 1), dt.date(2026, 6, 30)),
            ("2023H2", S750_START, dt.date(2023, 12, 31)),
            ("2024H1", dt.date(2024, 1, 1), dt.date(2024, 6, 30)),
            ("2024H2", dt.date(2024, 7, 1), dt.date(2024, 12, 31)),
            ("2025H1", dt.date(2025, 1, 1), dt.date(2025, 6, 30)),
            ("2025H2", dt.date(2025, 7, 1), dt.date(2025, 12, 31)),
            ("2026-07 → 11-05", dt.date(2026, 7, 1), dt.date(2026, 11, 5)),
        ]
        tbl = []
        for name, a, b in intervals:
            sw, n = sum_ret(daily, a, b)
            sn, _ = sum_ret(nom, a, b)
            sl, _ = sum_ret(lend_daily, a, b)
            tbl.append({"interval": name, "days": n,
                        "switch": round(ann(sw, n) * 100, 4),
                        "always_carry_capital": round(ann(sn, n) * CAP * 100, 4),
                        "always_lend": round(ann(sl, n) * 100, 4)})
        n_weeks = len(mons)
        n_carry = sum(1 for v in modes.values() if v == "carry")
        n_switch = sum(1 for i in range(1, len(mons)) if modes[mons[i]] != modes[mons[i - 1]])
        out[win_mode] = {"table": tbl, "weeks": n_weeks, "carry_weeks": n_carry,
                         "switches": n_switch,
                         "pattern_2026": "".join("C" if modes[m] == "carry" else "L"
                                                for m in mons if m.year == 2026)}
    return out


if __name__ == "__main__":
    main()
