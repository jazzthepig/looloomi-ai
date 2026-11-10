#!/usr/bin/env python3
"""T-331 — S-807 盲复算(lane-b):真钱 T25 的依据 S-799(W1)与 S-801(W2)的**第二份独立实现**。

口径来源:**只读** `REFUTATION_LEDGER.md` 的 `## S-799` / `## S-801` 原文(预注册的「写死」段)
与两者的**结果段**(C 道发表数 —— 本文件的对照目标)。**禁读** lane-c 的 `t321_*` / `t322_*` /
`t323_*` / `t329_*` —— 腿的装配只用 lane-b 自己的 `t320_blind.py`(S-797 盲复算,逐位一致那份)。

装配(全部沿用 `t320_blind.py`,一字不改的部分照抄):
  腿(日收盘) crypto = `forward_books.TOM_ARMS['CORE_X1V']` 同一规则作用于 **① 的 NAV**(`signals/tom` 核)
               equity = `ohlcv_daily` eodhd `ACWI`;gold = eodhd `XAUUSD`
  区间(W1,S-799 原文) ① = `core_variants_daily.cap_pit24`(2021-07-13 起);共同日期从 2021-07-13 起,
               前 **63** 个共同日只作历史,之后到 **2022-12-30** 记 NAV
  区间(W2,S-797/S-801 原文) ① = `multiplier_daily.core_u_replay`;共同日期第一天起,
               前 **252** 个共同日作历史,之后到 **2026-10-31** 记 NAV
  三条臂      全部 `flex_alloc.dynamic_mix_nav(legs, fn, reb=21, cost=20bp)`:
               T25_K(fn 恒返回 `BASE_T25`,对照)· RB(fn=`rb_weights(hist)`,**原 BOUNDS** 加密 0.0–0.90)
               · RBv2(同核,只把 `BOUNDS["crypto"]` 改成 (0.20,0.40) —— 研究脚本里覆盖常量,不改 `src/`)
  报          总收益 / 最大回撤 / 最差月 / Calmar / 两半(按天数对半,多一天给前半)+ 调仓权重

只读库、不入库、不改 `src/`。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.signals import tom as TOM                  # noqa: E402  交易层核
from src.data.universe import forward_books as FB         # noqa: E402  mix_nav / TOM_ARMS

# 组合层核:**S-801 之前**的版本(BOUNDS crypto 0.0–0.90),逐字节副本(S-797/S-799/S-801 用的那一份)。
# `src/data/universe/flex_alloc.py` 已被 Seth 按 S-801 后果条款改成 crypto (0.20,0.40) —— 直接 import src
# 会让「RB(原 BOUNDS)」这一臂悄悄变成 RBv2。故用 lane-b 自己 T-320 留下的副本,并核对 sha256。
CORE_COPY = Path(__file__).resolve().parent / "t320_flex_alloc_core.py"
CORE_SRC = ROOT / "src" / "data" / "universe" / "flex_alloc.py"
_spec = importlib.util.spec_from_file_location("t320_flex_alloc_core", CORE_COPY)
FA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FA)

OUT = Path(__file__).resolve().parent
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出")
URL = URL.rstrip("/")

REB, COST = 21, 20 / 1e4
BOUNDS_ORIG = (0.0, 0.90)      # S-797/S-799 的原偏离预算(加密)
BOUNDS_V2 = (0.20, 0.40)       # S-801 的加密偏离预算
YEAR_BASIS = 365.0

# ── 窗口口径(S-799 / S-801 原文写死)─────────────────────────────────────────
WINDOWS = {
    "W1": {"core": "cap_pit24", "core_table": "core_variants_daily",
           "leg_from": "2021-07-13", "warm": 63, "end": "2022-12-30",
           "ledger": "S-799(W1)/S-801(W1)"},
    "W2": {"core": "core_u_replay", "core_table": "multiplier_daily",
           "leg_from": None, "warm": 252, "end": "2026-10-31",
           "ledger": "S-797/S-801(W2)"},
}

# C 道发表数(台账 S-799 / S-801 结果段;百分比两位小数 ⇒ 舍入粒度 0.01pp)
PUBLISHED = {
    "W1": {
        "T25_K": {"total_return": -0.1570, "max_drawdown": -0.2591, "worst_month": -0.0902,
                  "vol_ann": 0.1776, "weights_mean": {"crypto": 0.30, "equity": 0.30, "gold": 0.20}},
        "RB": {"total_return": -0.0990, "max_drawdown": -0.1947, "worst_month": -0.0651,
               "vol_ann": 0.1562,
               "weights_mean": {"crypto": 0.262, "equity": 0.312, "gold": 0.294}},
        "RBv2": {"total_return": -0.1207, "max_drawdown": -0.2213, "worst_month": -0.0721,
                 "weights_mean": {"crypto": 0.254},
                 "cap_bite": {"n": 2, "of": 15}, "gold_at_cap": {"n": 15, "of": 15}},
    },
    "W2": {
        "T25_K": {"total_return": 0.5378, "max_drawdown": -0.0886,
                  "half_calmar": {"h1": 3.349, "h2": 0.530}},
        "RB": {"total_return": 0.6503, "max_drawdown": -0.0949},
        "RBv2": {"total_return": 0.6218, "max_drawdown": -0.0923,
                 "half_calmar": {"h1": 3.947, "h2": 1.089},
                 "weights_mean": {"crypto": 0.261},
                 "cap_bite": {"n": 8, "of": 34}, "floor_bite": {"n": 17, "of": 34}},
    },
}
TOL_PP = 0.1     # 差 > 0.1pp 逐条找原因


# ── 只读取库(分页,每页 ≤1000,带 order=)───────────────────────────────────────
def fetch(table: str, query: str, order: str) -> list[dict]:
    """读 PostgREST。Range 分页(每页 1000),order 必带;核总行数。"""
    rows, start = [], 0
    total = None
    while True:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{table}?{query}&order={order}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": f"{start}-{start + 999}"},
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            cr = r.headers.get("Content-Range", "")
            body = r.read().decode()
        page = json.loads(body)
        if total is None and "/" in cr:
            total = int(cr.split("/")[-1])
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
        if total is not None and start >= total:
            break
    if total is not None and len(rows) != total:
        raise SystemExit(f"{table}: 抓到 {len(rows)} 行 ≠ server total {total}")
    return rows


# ── 指标(照抄 t320_blind.py)─────────────────────────────────────────────────
def metrics(nav: pd.Series, year_basis: float = YEAR_BASIS) -> dict:
    nav = nav.dropna()
    if len(nav) < 3:
        return {"n_days": int(len(nav))}
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / year_basis
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / yrs) - 1.0) if yrs > 0 else None
    vol = float(r.std(ddof=1) * math.sqrt(year_basis)) if len(r) > 1 else None
    dd = nav / nav.cummax() - 1.0
    maxdd = float(dd.min())
    calmar = float(cagr / abs(maxdd)) if (cagr is not None and maxdd < 0) else None
    m = r.groupby([r.index.year, r.index.month]).apply(lambda x: float((1 + x).prod() - 1.0))
    worst_m = float(m.min()) if len(m) else None
    worst_mk = f"{int(m.idxmin()[0])}-{int(m.idxmin()[1]):02d}" if len(m) else None
    return {"n_days": int(len(nav)), "first": nav.index[0].date().isoformat(),
            "last": nav.index[-1].date().isoformat(), "years": round(yrs, 3),
            "total_return": round(total, 6), "cagr": round(cagr, 6) if cagr is not None else None,
            "vol_ann": round(vol, 6) if vol is not None else None,
            "max_drawdown": round(maxdd, 6), "calmar": round(calmar, 4) if calmar is not None else None,
            "worst_month": round(worst_m, 6) if worst_m is not None else None,
            "worst_month_key": worst_mk}


def halves(nav: pd.Series, extra_to: str = "first") -> tuple[pd.Series, pd.Series]:
    n = len(nav)
    cut = (n + 1) // 2 if extra_to == "first" else n // 2
    return nav.iloc[:cut], nav.iloc[cut:]


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _src_bounds_crypto() -> list | None:
    """只读 `src/data/universe/flex_alloc.py` 的 `BOUNDS["crypto"]`(S-801 之后 src 已改成 0.20–0.40)。"""
    if not CORE_SRC.exists():
        return None
    m = re.search(r"^BOUNDS\s*=\s*(\{.*\})", CORE_SRC.read_text(), re.M)
    if not m:
        return None
    return list(ast.literal_eval(m.group(1))["crypto"])


# ── BOUNDS 覆盖的机制核对(口径陷阱,必须实测)───────────────────────────────
def bounds_probe() -> dict:
    """`clip_to_budget(w, bounds=BOUNDS)` 的默认参数在**函数定义时**绑定 dict 对象:
    原地改 `FA.BOUNDS["crypto"]` ⇒ 生效;重新绑定 `FA.BOUNDS = {...}` ⇒ **不生效**。实测两种。"""
    orig_obj = FA.BOUNDS
    orig_clip = {"crypto": 0.9, "equity": 0.3, "gold": 0.2}
    out = {"default_is_same_object": FA.clip_to_budget.__defaults__[0] is orig_obj,
           "orig_bounds_crypto": list(orig_obj["crypto"])}
    # 1) 原地改 ⇒ 生效
    FA.BOUNDS["crypto"] = BOUNDS_V2
    out["inplace_mutation"] = FA.clip_to_budget(dict(orig_clip))
    out["inplace_effective"] = abs(out["inplace_mutation"]["crypto"] - BOUNDS_V2[1]) < 1e-12
    # 2) 先把原对象复原,再**重新绑定** FA.BOUNDS ⇒ 默认参数仍指向旧对象 ⇒ 不生效
    FA.BOUNDS["crypto"] = BOUNDS_ORIG
    out["restored_inplace"] = FA.clip_to_budget(dict(orig_clip))
    FA.BOUNDS = {"crypto": BOUNDS_V2, "equity": (0.20, 0.40), "gold": (0.10, 0.30)}
    out["rebinding"] = FA.clip_to_budget(dict(orig_clip))
    out["rebinding_effective"] = abs(out["rebinding"]["crypto"] - BOUNDS_V2[1]) < 1e-12
    # 复原(同一对象)
    FA.BOUNDS = orig_obj
    FA.BOUNDS["crypto"] = BOUNDS_ORIG
    out["restored"] = FA.clip_to_budget(dict(orig_clip))
    out["orig_bounds_crypto_after_restore"] = list(FA.BOUNDS["crypto"])
    return out


# ── 取数 ─────────────────────────────────────────────────────────────────────
def load_data() -> dict:
    out = {}

    # ①(cap_pit24):`core_variants_daily` 日 ret → NAV = (1+ret).cumprod()
    cv = fetch("core_variants_daily", "select=d,ret&arm=eq.cap_pit24", "d.asc")
    rets = {pd.Timestamp(str(r["d"])[:10]): float(r["ret"]) for r in cv if r.get("ret") is not None}
    s = pd.Series(rets).sort_index()
    out["cap_pit24_ret"] = s
    out["cap_pit24_nav"] = (1.0 + s).cumprod()

    # ①(core_u_replay):`multiplier_daily` 的 nav(③ 的底仓 = ①)
    md = fetch("multiplier_daily", "select=d,arm,nav&arm=eq.core_u_replay", "d.asc")
    out["core_u_replay_nav"] = pd.Series(
        {pd.Timestamp(str(r["d"])[:10]): float(r["nav"]) for r in md if r.get("nav") is not None}
    ).sort_index()

    # equity / gold
    tf = fetch("ohlcv_daily", "select=trade_date,symbol,close&source=eq.eodhd"
                             "&symbol=in.(ACWI,XAUUSD)", "symbol.asc,trade_date.asc")
    eq, gd = {}, {}
    for r in tf:
        c = r.get("close")
        if c is None:
            continue
        (eq if r["symbol"] == "ACWI" else gd)[pd.Timestamp(r["trade_date"])] = float(c)
    out["equity"] = pd.Series(eq).sort_index()
    out["gold"] = pd.Series(gd).sort_index()

    # 资金费(BTC 永续,年化)
    fh = fetch("funding_history", "select=funding_time,funding_rate&venue=eq.binance_perp"
                                  "&symbol=eq.BTC", "funding_time.asc")
    fdf = pd.DataFrame(fh)
    fdf["d"] = pd.to_datetime(fdf["funding_time"].str[:10])
    out["funding"] = fdf.groupby("d")["funding_rate"].sum().astype(float) * 365.0
    return out


def core_nav_for(spec: dict, data: dict) -> pd.Series:
    if spec["core_table"] == "core_variants_daily":
        nav = data["cap_pit24_nav"]
    else:
        nav = data["core_u_replay_nav"]
    if spec["leg_from"]:
        nav = nav[nav.index >= pd.Timestamp(spec["leg_from"])]
    return nav


def crypto_leg(cnav: pd.Series, fund: pd.Series) -> tuple[pd.Series, pd.Series]:
    """CORE_X1V 规则作用于 ① 的 NAV ⇒ 加密腿。核与 t320_blind.py 一字不改。"""
    key, bear, size, exit_mode, vol = FB.TOM_ARMS["CORE_X1V"]
    assert key == "CORE" and bear == "rally" and exit_mode == "l20" and vol is True
    g = TOM.trade_path(cnav, bear, size, exit_mode, vol)
    cr = TOM.trade_returns(cnav, g, fund)
    leg = pd.Series((1.0 + cr).cumprod(), index=cr.index)
    leg = pd.concat([pd.Series({cnav.index[0]: 1.0}), leg]).sort_index()
    return leg, g


def _leg_stats(g: pd.Series | None, common, nav_start, end) -> dict | None:
    """加密腿(X1V 作用于 ①)的敞口统计:空仓天数(结构陷阱的来源)、加仓天数。"""
    if g is None:
        return None
    gg = g[(g.index >= nav_start) & (g.index <= end)]
    if len(gg) == 0:
        return None
    return {"n_days": int(len(gg)),
            "flat_days": int((gg <= 0.0).sum()),
            "flat_frac": round(float((gg <= 0.0).mean()), 4),
            "over1_days": int((gg > 1.0).sum()),
            "max_g": round(float(gg.max()), 4)}


def run_window(spec: dict, data: dict, warm: int | None = None,
               crypto_leg_mode: str = "x1v") -> dict:
    """一个窗口:装配三条腿 → 三条臂(T25_K / RB 原 BOUNDS / RBv2)→ 指标。"""
    cnav = core_nav_for(spec, data)
    if crypto_leg_mode == "x1v":
        cleg, g = crypto_leg(cnav, data["funding"])
    else:
        cleg, g = cnav, None
    end = pd.Timestamp(spec["end"])
    legs = {"crypto": cleg, "equity": data["equity"], "gold": data["gold"]}
    legs = {k: v[v.index <= end] for k, v in legs.items()}
    df = pd.concat(legs, axis=1).dropna().sort_index()
    common = df.index
    warm = spec["warm"] if warm is None else warm
    if spec.get("nav_start_override"):
        nav_start = pd.Timestamp(spec["nav_start_override"])
        if nav_start not in common:
            raise SystemExit(f"nav_start_override {nav_start.date()} 不在共同日里")
    else:
        nav_start = common[warm] if warm < len(common) else None
    if nav_start is None:
        raise SystemExit(f"共同日不足 {warm} 天")

    def fn_t25(hist, d):
        return dict(FA.BASE_T25)

    def fn_rb(hist, d):
        return FA.rb_weights(hist)

    out = {"spec": {**spec, "warm_used": warm, "crypto_leg": crypto_leg_mode},
           "n_common": int(len(common)), "common_first": common[0].date().isoformat(),
           "common_last": common[-1].date().isoformat(),
           "nav_start": nav_start.date().isoformat(),
           "core_first": cnav.index[0].date().isoformat(),
           "core_last": cnav.index[-1].date().isoformat(),
           "leg_stats": _leg_stats(g, common, nav_start, end),
           "arms": {}}

    for arm, bounds in (("T25_K", None), ("RB", BOUNDS_ORIG), ("RBv2", BOUNDS_V2)):
        if bounds is not None:
            FA.BOUNDS["crypto"] = bounds
        nav, log = FA.dynamic_mix_nav(legs, fn_t25 if arm == "T25_K" else fn_rb,
                                      reb=REB, cost=spec.get("cost", COST), start=nav_start)
        FA.BOUNDS["crypto"] = BOUNDS_ORIG
        w = pd.DataFrame([{c: r[c] for c in ("crypto", "equity", "gold")} for r in log])
        m = metrics(nav)
        h1, h2 = halves(nav, "first")
        h1b, h2b = halves(nav, "last")
        m["weights_mean"] = {c: round(float(w[c].mean()), 4) for c in w.columns}
        m["weights_min"] = {c: round(float(w[c].min()), 4) for c in w.columns}
        m["weights_max"] = {c: round(float(w[c].max()), 4) for c in w.columns}
        m["n_rebalances"] = int(len(log))
        m["first_target"] = {c: log[0][c] for c in ("crypto", "equity", "gold")} if log else None
        m["first_target_date"] = log[0]["d"] if log else None
        cm = max(log, key=lambda r: r["crypto"]) if log else None
        m["crypto_max"] = cm["crypto"] if cm else None
        m["crypto_max_date"] = cm["d"] if cm else None
        m["cap_bite"] = int(sum(1 for r in log if abs(r["crypto"] - bounds[1]) < 1e-9)) if bounds else 0
        m["floor_bite"] = int(sum(1 for r in log if abs(r["crypto"] - bounds[0]) < 1e-9)) if bounds else 0
        m["gold_at_cap"] = int(sum(1 for r in log if abs(r["gold"] - 0.30) < 1e-9))
        m["equity_at_cap"] = int(sum(1 for r in log if abs(r["equity"] - 0.40) < 1e-9))
        m["h1"] = metrics(h1)
        m["h2"] = metrics(h2)
        m["half_calmar"] = {"h1": m["h1"].get("calmar"), "h2": m["h2"].get("calmar")}
        m["half_calmar_last"] = {"h1": metrics(h1b).get("calmar"), "h2": metrics(h2b).get("calmar")}
        out["arms"][arm] = {"metrics": m, "rebalance_log": log}
    return out


# ── 与 C 道发表数逐项对照 ───────────────────────────────────────────────────
def compare(win: str, res: dict) -> dict:
    """与 C 道发表数逐项对照。差 > 0.1pp 的逐条找原因。

    两半 Calmar 的对照用「多一天给**后半**」的切法(C 道口径;实测见报告 §口径歧义 4);
    「多一天给前半」的切法一并报出。
    """
    rows = []
    pub = PUBLISHED[win]
    for arm in ("T25_K", "RB", "RBv2"):
        mine = res["arms"][arm]["metrics"]
        p = pub.get(arm, {})
        for key, label in (("total_return", "总收益"), ("max_drawdown", "最大回撤"),
                           ("worst_month", "最差月"), ("vol_ann", "年化波动")):
            if key in p and mine.get(key) is not None:
                d = (mine[key] - p[key]) * 100.0
                rows.append({"arm": arm, "metric": key, "label": label,
                             "mine": round(mine[key], 6), "published": p[key],
                             "delta_pp": round(d, 4), "over_tol": bool(abs(d) > TOL_PP)})
        if "half_calmar" in p:
            for h in ("h1", "h2"):
                mv = mine["half_calmar_last"][h]
                pv = p["half_calmar"][h]
                if mv is None:
                    continue
                rows.append({"arm": arm, "metric": f"half_calmar_{h}", "label": f"{h} Calmar",
                             "mine": mv, "mine_first_conv": mine["half_calmar"][h],
                             "published": pv, "delta_pp": round(mv - pv, 4),
                             "over_tol": bool(abs(mv - pv) > TOL_PP)})
        if "weights_mean" in p:
            for leg, pv in p["weights_mean"].items():
                mv = mine["weights_mean"].get(leg)
                if mv is None:
                    continue
                d = (mv - pv) * 100.0
                rows.append({"arm": arm, "metric": f"weights_mean_{leg}", "label": f"平均权重 {leg}",
                             "mine": mv, "published": pv, "delta_pp": round(d, 4),
                             "over_tol": bool(abs(d) > TOL_PP)})
        for key, label in (("cap_bite", "加密上限咬合"), ("floor_bite", "加密下限咬合")):
            if key in p and isinstance(p[key], dict):
                mv = mine.get(key)
                rows.append({"arm": arm, "metric": key, "label": label, "mine": mv,
                             "published": p[key]["n"], "published_denominator": p[key]["of"],
                             "my_denominator": mine.get("n_rebalances"),
                             "delta_pp": round(mv - p[key]["n"], 4),
                             "over_tol": bool(abs(mv - p[key]["n"]) > 0)})
        for key, label in (("gold_at_cap", "金腿顶 0.30"), ("equity_at_cap", "股腿顶 0.40")):
            if key in p and isinstance(p[key], dict):
                mv = mine.get(key)
                rows.append({"arm": arm, "metric": key, "label": label, "mine": mv,
                             "published": p[key]["n"], "published_denominator": p[key]["of"],
                             "my_denominator": mine.get("n_rebalances"),
                             "delta_pp": round(mv - p[key]["n"], 4),
                             "over_tol": bool(abs(mv - p[key]["n"]) > 0)})
    return {"rows": rows, "n_over_tol": int(sum(1 for r in rows if r["over_tol"]))}


def main() -> int:
    probe = bounds_probe()
    data = load_data()
    res: dict = {"meta": {
        "card": "T-331", "ledger": "REFUTATION_LEDGER S-799 / S-801(原文与结果段);S-807 派工",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reb": REB, "cost_bp": 20, "year_basis": YEAR_BASIS,
        "base_t25": FA.BASE_T25,
        "core_copy_sha256": _sha(CORE_COPY), "core_src_sha256": _sha(CORE_SRC),
        "core_copy_bounds_crypto": list(FA.BOUNDS["crypto"]),
        "core_src_bounds_crypto": _src_bounds_crypto(),
        "bounds_probe": probe,
        "vol_window": FA.VOL_WINDOW, "min_obs": FA.MIN_OBS, "sig_floor": FA.SIGMA_FLOOR,
    }}
    windows = {}
    for wname, spec in WINDOWS.items():
        r = run_window(spec, data)
        windows[wname] = r
        res.setdefault("windows", {})[wname] = {
            "spec": r["spec"], "n_common": r["n_common"],
            "common_first": r["common_first"], "common_last": r["common_last"],
            "nav_start": r["nav_start"], "core_first": r["core_first"], "core_last": r["core_last"],
            "leg_stats": r["leg_stats"],
            "arms": {a: {"metrics": r["arms"][a]["metrics"]} for a in r["arms"]},
        }
        res.setdefault("compare", {})[wname] = compare(wname, r)

    # ── 口径变体(结论会不会变)───────────────────────────────────────────────
    variants = {}
    # VA: W1 若按 S-797 的 252 天空跑(而非 S-799 的 63 天)
    va = run_window(WINDOWS["W1"], data, warm=252)
    variants["VA_W1_warm252"] = {
        "note": "W1 空跑 252 个共同日(S-797 口径)而非 S-799 的 63 天 ⇒ 窗口整体后移",
        "nav_start": va["nav_start"], "n_common": va["n_common"],
        "arms": {a: {k: va["arms"][a]["metrics"][k]
                     for k in ("n_days", "first", "last", "total_return", "max_drawdown",
                               "worst_month", "calmar")} for a in va["arms"]},
    }
    # VB: W2 的 ① 换成 cap_pit24(两段不是同一条 ①)—— 窗口保持与 W2 完全一样
    spec_alt = {**WINDOWS["W2"], "core": "cap_pit24", "core_table": "core_variants_daily",
                "nav_start_override": res["windows"]["W2"]["nav_start"]}
    vb = run_window(spec_alt, data)
    variants["VB_W2_core_cap_pit24"] = {
        "note": "W2 的 ① 换成 `cap_pit24`(与 W1 同一条),窗口保持 2024-01-04 → 2026-10-30 —— 测「两段不是同一条 ①」",
        "nav_start": vb["nav_start"], "n_common": vb["n_common"],
        "common_first": vb["common_first"], "common_last": vb["common_last"],
        "arms": {a: {k: vb["arms"][a]["metrics"][k]
                     for k in ("n_days", "first", "last", "total_return", "max_drawdown",
                               "worst_month", "calmar", "half_calmar", "weights_mean",
                               "n_rebalances")} for a in vb["arms"]},
    }
    # VC: 两半切分 —— 多一天给后半(T-320 的 V5 变体)
    variants["VC_half_extra_to_last"] = {
        "note": "两半切分:多一天给后半(默认多一天给前半)",
        "W1": {a: res["windows"]["W1"]["arms"][a]["metrics"]["half_calmar_last"] for a in ("T25_K", "RB", "RBv2")},
        "W2": {a: res["windows"]["W2"]["arms"][a]["metrics"]["half_calmar_last"] for a in ("T25_K", "RB", "RBv2")},
    }
    # VD: W1 的 ① 用 cap_pit24 的**全部**历史(不切 2021-07-13)—— 只改 X1V 状态机的起点,窗口不变
    spec_vd = {**WINDOWS["W1"], "leg_from": None,
               "nav_start_override": res["windows"]["W1"]["nav_start"]}
    vd = run_window(spec_vd, data)
    variants["VD_W1_core_full_history"] = {
        "note": "W1 的 ① 不切 2021-07-13(cap_pit24 实有 2019-01-02 起的历史)—— X1V 状态机的起点变了,窗口不变",
        "nav_start": vd["nav_start"], "n_common": vd["n_common"],
        "common_first": vd["common_first"], "common_last": vd["common_last"],
        "leg_stats": vd["leg_stats"],
        "arms": {a: {k: vd["arms"][a]["metrics"][k]
                     for k in ("n_days", "first", "last", "total_return", "max_drawdown",
                               "worst_month", "calmar", "weights_mean")} for a in vd["arms"]},
    }
    # VE: 成本 0(探索性)—— 20bp 换手成本吃掉多少
    ve = {}
    for wname, spec in WINDOWS.items():
        r = run_window({**spec, "cost": 0.0}, data)
        ve[wname] = {a: {k: r["arms"][a]["metrics"][k]
                         for k in ("total_return", "max_drawdown")} for a in r["arms"]}
    variants["VE_cost_zero"] = {"note": "成本 0(探索性:换手 20bp 的归因,未预注册)",
                                 "by_window": ve}
    res["variants"] = variants

    (OUT / "t331_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    print(json.dumps({
        "meta": {k: res["meta"][k] for k in ("core_copy_sha256", "core_src_sha256",
                                              "core_copy_bounds_crypto", "core_src_bounds_crypto",
                                              "bounds_probe")},
        "windows": {w: {"nav_start": res["windows"][w]["nav_start"],
                        "n_common": res["windows"][w]["n_common"],
                        "common": [res["windows"][w]["common_first"], res["windows"][w]["common_last"]],
                        "arms": {a: {k: res["windows"][w]["arms"][a]["metrics"].get(k)
                                     for k in ("n_days", "first", "last", "total_return", "max_drawdown",
                                               "worst_month", "worst_month_key", "calmar",
                                               "half_calmar", "weights_mean", "n_rebalances",
                                               "cap_bite", "floor_bite", "gold_at_cap",
                                               "equity_at_cap")}
                                 for a in res["windows"][w]["arms"]}} for w in res["windows"]},
        "compare_over_tol": {w: [r for r in res["compare"][w]["rows"] if r["over_tol"]]
                             for w in res["compare"]},
        "compare_all": {w: res["compare"][w]["rows"] for w in res["compare"]},
        "variants": res["variants"],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
