#!/usr/bin/env python3
"""T-338 —— t256 组合 NAV 三处 bug 的清扫(lane-b,2026-11-11)

只读、不入库、**不改** `docs/research/t256_tactical_short.py`(旧数要能复现)。

三处 bug(S-808「工程发现」段):
  B1 幽灵仓 —— 同日进出的票(entry_d == exit_d)永不平仓,一路盯到样本末;
              旧实现只有 `open_t` 一个仓位,幽灵仓不关 ⇒ 其后的票**全部没进场**。
  B2 资金费在盯市与出场各算一次 —— 旧实现把累计资金费记进 `unreal`(盯市),
              出场时又整段记进 `cash`(出场)。资金费因此在 NAV 路径上既当未实现、
              又当已实现 —— 终点不变,路径变(回撤、叠加口径变)。
  B3 随机对照被退化数据污染 —— 预注册写「只在 ③ 成立的日子里抽」,
              旧实现抽的是 `elig_px`(**只有价格条件**成立的日子,1029 天),
              ③ 全部三条成立的日子只有 69 天(见报告 §5)。

产出:`t338_results.json`(新旧对照 + 恒等式误差)与 `T-338_t256_nav_sweep.md`。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from src.data.evaluation.apparatus import percentile_of  # noqa: E402

# ── t332 的 sleeve_nav / hedge_leg_nav:**import**(不是抄写) —— 见报告 §2。
#     t332_squeeze_fade.py 的 `if __name__ == "__main__": main()` 保证 import 不跑它的主流程。
import t332_squeeze_fade as t332  # noqa: E402

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t256")
DVOL_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t229")

# ── t256 的常量(逐字) ─────────────────────────────────────────────
COST_BPS = 7.5
STOP_ATR = 1.5
TP_ATR = 2.5
TIME_STOP = 15
RISK_PCT = 0.005
MAX_NOTIONAL = 0.50
DVOL_TRIG = 0.70
DET_PCT = 20
MIN_DET_OBS = 250
MA_N = 20
ATR_N = 14
SEED = 736
N_NULL = 1000

S736_TRUTH = {
    "n_tickets": 18, "avg_r_net": -0.3744908562608685, "avg_r_price": -0.36693511344173546,
    "median_r_net": -0.9841310251407414 + (-8.44e-13), "win_rate": 0.2222222222222222,
    "total_r_net": -6.740835412695633,
    "reasons": {"止盈": 2, "保本": 2, "止损": 10, "时间": 4},
}


def pull(table: str, query: str, step: int = 1000) -> list[dict]:
    import urllib.request
    rows: list[dict] = []
    off, total = 0, -1
    while True:
        h = dict(H)
        h["Range"] = f"{off}-{off + step - 1}"
        req = urllib.request.Request(f"{U}/rest/v1/{table}?{query}", headers=h)
        with urllib.request.urlopen(req, timeout=300) as resp:
            cr = resp.headers.get("Content-Range", "")
            body = json.loads(resp.read())
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def load(name: str, table: str, query: str) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text())
    rows = pull(table, query)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    return rows


def maxdd(x: np.ndarray) -> float:
    peak = np.maximum.accumulate(x)
    return float(np.min(x / peak - 1.0))


print("[1] 读缓存…", flush=True)
perp_rows = load("perp_btc", "perp_bv_daily",
                  "select=d,o,h,l,c,symbol,pair&pair=eq.BTCUSDT&order=d.asc,recorded_at.asc")
fund_rows = load("v_funding_btc", "v_funding_daily",
                  "select=d,symbol,funding_rate,n&symbol=eq.BTC&order=d.asc,symbol.asc")
cyc = json.loads((CACHE / "cycle.json").read_text())
sty = json.loads((CACHE / "style_majors.json").read_text())
dvol = {k: float(v) for k, v in json.loads((DVOL_CACHE / "deribit_dvol_btc_daily.json").read_text()).items()}

btc = t332.build_panel(perp_rows, fund_rows)
DATES = btc["dates"]
IDX = btc["idx"]
OPEN, HIGH, LOW, CLOSE = btc["o"], btc["h"], btc["l"], btc["c"]
ATR = btc["atr"]
FUND = btc["fund"]
n = btc["n"]
print(f"  BTC 面板 {n} 根 {DATES[0]} → {DATES[-1]};DVOL {min(dvol)} → {max(dvol)}", flush=True)

# ── 触发(t256 第 264–284 行,逐字) ────────────────────────────────
phase: dict[str, str] = {}
det: dict[str, float] = {}
for r in cyc:
    dd = str(r["d"])[:10]
    if r.get("phase"):
        phase[dd] = str(r["phase"])
    if r.get("deterioration") is not None:
        det[dd] = float(r["deterioration"])
dv_days = sorted(dvol)
dv_vals = np.array([dvol[d] for d in dv_days], dtype=float)
dv_idx = {d: i for i, d in enumerate(dv_days)}
ma20 = np.full(n, np.nan)
for i in range(MA_N - 1, n):
    ma20[i] = float(np.mean(CLOSE[i - MA_N + 1:i + 1]))


def dvol_pct(d: str) -> float | None:
    i = dv_idx.get(d)
    if i is None:
        return None
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=365)).isoformat()
    j = int(np.searchsorted(dv_days, lo, side="left"))
    w = dv_vals[j:i]
    if w.size == 0:
        return None
    return float(np.sum(w <= dv_vals[i]) / w.size)


det_days = sorted(det)
det_exp_p20: dict[str, float] = {}
buf: list[float] = []
for d in det_days:
    buf.append(det[d])
    if len(buf) >= MIN_DET_OBS:
        det_exp_p20[d] = float(np.percentile(np.asarray(buf, dtype=float), DET_PCT))


def trig_liq(d: str) -> tuple[bool, str]:
    if phase.get(d) == "turning":
        return True, "turning"
    p = det_exp_p20.get(d)
    if p is not None and det.get(d) is not None and det[d] <= p:
        return True, f"det<=p20({det[d]:.4f}<={p:.4f})"
    return False, ""


def trig_px(d: str) -> bool:
    i = IDX[d]
    return bool(not math.isnan(ma20[i]) and CLOSE[i] < ma20[i])


sig_all: list[str] = []
sig_reason: dict[str, str] = {}
elig_px: list[str] = []
for d in DATES:
    if not (dv_days[0] <= d <= dv_days[-1]):
        continue
    ok_px = trig_px(d)
    if ok_px:
        elig_px.append(d)
    liq, why = trig_liq(d)
    ok_dv = dvol_pct(d)
    if liq and ok_dv is not None and ok_dv >= DVOL_TRIG and ok_px:
        sig_all.append(d)
        sig_reason[d] = why
print(f"  ③ 三条全中 {len(sig_all)} 天;价格条件 {len(elig_px)} 天(随机对照池)", flush=True)

# ── 票(t256 `simulate()` + `run_tickets()` 逐字;t332 已把这两段抄成面板版) ──
tickets, skipped = t332.run_tickets([("BTC", d) for d in sig_all], {"BTC": btc},
                                    TIME_STOP, global_single=True)
r_net = [t["r_net"] for t in tickets]
reasons = {r: sum(1 for t in tickets if t["reason"] == r) for r in ("止盈", "保本", "止损", "时间")}

# ── 自检(1):逐位复现 S-736 的 18 张票 ─────────────────────────────
old = json.loads((HERE / "t256_results.json").read_text())
old_tk = old["tickets"]
F = ("signal_d", "entry_d", "exit_d", "entry", "exit", "r_unit", "reason", "hold_days", "r_net")
diffs: list[str] = []
if len(tickets) != len(old_tk):
    diffs.append(f"票数 {len(tickets)} ≠ {len(old_tk)}")
for a, b in zip(tickets, old_tk):
    for f in F:
        va, vb = a[f], b[f]
        if isinstance(va, float):
            if abs(va - vb) > 1e-12:
                diffs.append(f"{a['signal_d']}.{f}: {va} ≠ {vb}")
        elif va != vb:
            diffs.append(f"{a['signal_d']}.{f}: {va} ≠ {vb}")
avg_r = float(np.mean(r_net))
selfcheck = {
    "n_tickets": len(tickets), "avg_r_net": avg_r,
    "median_r_net": float(np.median(r_net)),
    "win_rate": float(np.mean([x > 0 for x in r_net])),
    "total_r_net": float(np.sum(r_net)), "reasons": reasons,
    "truth_avg_r_net": S736_TRUTH["avg_r_net"],
    "avg_r_net_abs_diff": abs(avg_r - S736_TRUTH["avg_r_net"]),
    "per_ticket_field_diffs": diffs,
    "per_ticket_match": not diffs and len(tickets) == len(old_tk),
}
print(f"  自检:票 {len(tickets)} · 平均净 R {avg_r:.10f} · 逐位一致 {not diffs}", flush=True)
if len(tickets) != 18 or abs(avg_r - S736_TRUTH["avg_r_net"]) > 1e-12 or diffs:
    print("自检不过,停。", flush=True)
    raise SystemExit(1)

# ── 账务:NAV 变体 ─────────────────────────────────────────────────
#   v0 = t256 原样(逐字抄 t256 第 501–540 行):单仓位 + 幽灵仓 + 资金费记进 unreal
#   v1 = v0 + 修幽灵仓(同日进出当场结算);其余一字不动
#   v2 = v1 + 资金费只在出场兑现(盯市不计资金费)⇒ 与 t332.sleeve_nav 同口径


# t256 第 544–545 行:每票的 `_fund_day` 只覆盖 **持仓期**(进场日…出场日)。
# 幽灵仓(同日进出)之后的日子不在表里 ⇒ 旧实现的资金费盯市在出场日之后**归零**。
# 这一条是 v0 与旧数逐位一致的前提(实测差 1.63pp —— 少了它就不是旧实现了)。
for _t in tickets:
    _t["_fund_day"] = {dd: FUND.get(dd, 0.0)
                       for dd in DATES[IDX[_t["entry_d"]]:IDX[_t["exit_d"]] + 1]}


def _fund_sum(t: dict, upto_idx: int) -> float:
    """持仓期间(进场日…upto_idx)的资金费合计(t256 口径:超出持仓期的日子记 0)。"""
    return float(sum(t["_fund_day"].get(dd, 0.0)
                     for dd in DATES[IDX[t["entry_d"]]:upto_idx + 1]))


def nav_variant(tks: list[dict], days: list[str], mode: str) -> dict:
    cash = 1.0
    realized = 0.0          # Σ已实现(价格)
    fund_closed = 0.0       # Σ资金费(已平仓兑现的部分)
    cost = 0.0              # Σ成本
    closed_fund: list[float] = []
    open_t = None           # v0 的单仓位语义
    open_pos: dict = {}     # v1/v2
    nav: list[float] = []
    unreal_price_end = 0.0
    unreal_fund_end = 0.0
    open_ids: list[str] = []
    entered: list[str] = []

    def settle(t: dict, d: str) -> None:
        nonlocal cash, realized, cost
        pnl = t["notional"] * (t["entry"] - t["exit"]) / t["entry"]
        f = t["notional"] * _fund_sum(t, IDX[t["exit_d"]])
        cash += pnl + f - t["notional"] * (COST_BPS / 1e4)
        realized += pnl
        closed_fund.append(f)
        cost += t["notional"] * (COST_BPS / 1e4)

    def open_ticket(t: dict, d: str) -> None:
        nonlocal cash, cost
        notional = min(RISK_PCT * cash / (t["r_unit"] / t["entry"]), MAX_NOTIONAL * cash)
        t["notional"] = notional
        t["equity_at_entry"] = cash
        cash -= notional * (COST_BPS / 1e4)
        cost += notional * (COST_BPS / 1e4)
        entered.append(f"{t['signal_d']}→{t['exit_d']}")

    for d in days:
        i = IDX[d]
        if mode == "v0":
            # —— t256 原样(逐字)——
            if open_t is not None and IDX[open_t["exit_d"]] == i:
                settle(open_t, d)
                open_t = None
            if open_t is None:
                for t in tks:
                    if t["entry_d"] == d:
                        open_ticket(t, d)
                        open_t = t
                        break
            unreal = 0.0
            up = 0.0
            uf = 0.0
            if open_t is not None:
                t = open_t
                unreal += t["notional"] * (t["entry"] - CLOSE[i]) / t["entry"]
                uf = t["notional"] * _fund_sum(t, i)
                unreal += uf
            nav.append(cash + unreal)
            unreal_price_end = unreal - uf
            unreal_fund_end = uf
            if open_t is not None:
                open_ids = [f"{open_t['signal_d']}→{open_t['exit_d']}"]
            else:
                open_ids = []
        else:
            # —— v1 / v2:多仓位;v1 当日进出当场结算,ghost 不存在 ——
            for key, t in list(open_pos.items()):
                if t["exit_d"] == d:
                    settle(t, d)
                    open_pos.pop(key)
            for t in tks:
                if t["entry_d"] != d:
                    continue
                if t["exit_d"] <= d:      # 同日进出:当场结算(修幽灵仓)
                    open_ticket(t, d)
                    settle(t, d)
                    continue
                open_ticket(t, d)
                open_pos[t["signal_d"]] = t
            up = 0.0
            uf = 0.0
            for t in open_pos.values():
                up += t["notional"] * (t["entry"] - CLOSE[i]) / t["entry"]
                if mode == "v1":
                    uf += t["notional"] * _fund_sum(t, i)
            nav.append(cash + up + uf)
            unreal_price_end = up
            unreal_fund_end = uf
            open_ids = [f"{t['signal_d']}→{t['exit_d']}" for t in open_pos.values()]

    nav_arr = np.array(nav)
    fund_in_nav = float(sum(closed_fund)) + unreal_fund_end
    identity_rhs = 1.0 + realized + fund_in_nav - cost + unreal_price_end
    return {
        "days": days, "nav": nav_arr,
        "nav_end": float(nav_arr[-1]),
        "sleeve_total_ret": float(nav_arr[-1] - 1.0),
        "sleeve_maxdd": maxdd(nav_arr),
        "accounting": {
            "nav0": 1.0, "realized_pnl_sum": realized, "funding_in_nav": fund_in_nav,
            "cost_sum": cost, "final_unreal_price": unreal_price_end,
            "final_unreal_funding": unreal_fund_end,
            "identity_rhs": identity_rhs,
            "identity_error": float(nav_arr[-1] - identity_rhs),
        },
        "n_tickets_entered": len(entered),
        "tickets_entered": entered,
        "open_at_end": open_ids,
        "n_open_at_end": len(open_ids),
    }


# ── NAV 天数(t256 第 503–507 行,逐字) ─────────────────────────────
day_start = dv_days[0]
day_end = dv_days[-1]
if tickets:
    day_end = max(day_end, max(t["exit_d"] for t in tickets))
days = [d for d in DATES if day_start <= d <= day_end]
print(f"[2] NAV {len(days)} 天 {days[0]} → {days[-1]}", flush=True)

variants: dict[str, dict] = {}
for mode in ("v0", "v1", "v2"):
    variants[mode] = nav_variant(tickets, days, mode)
    a = variants[mode]["accounting"]
    print(f"  {mode}: 净值 {variants[mode]['nav_end']:.6f} · 自身回撤 {variants[mode]['sleeve_maxdd']:.4%}"
          f" · 恒等式误差 {a['identity_error']:.3e} · 进场票 {variants[mode]['n_tickets_entered']}"
          f" · 末日持仓 {variants[mode]['n_open_at_end']}", flush=True)

# v3 = t332 的 sleeve_nav(import,逐字)—— 交叉核对 v2
t332_days, t332_nav, t332_detail = t332.sleeve_nav(tickets, {"BTC": btc}, days)
v3 = {"nav_end": float(t332_nav[-1]), "sleeve_total_ret": float(t332_nav[-1] - 1.0),
      "sleeve_maxdd": maxdd(t332_nav), "n_days": len(t332_days)}
print(f"  v3(t332 import): 净值 {v3['nav_end']:.6f} · 自身回撤 {v3['sleeve_maxdd']:.4%}", flush=True)
variants["v3_t332_import"] = v3
v2v3_diff = float(np.max(np.abs(np.asarray(variants["v2"]["nav"]) - np.asarray(t332_nav))))
print(f"  v2 vs t332 import:逐日最大差 {v2v3_diff:.3e}", flush=True)

# 逐段增量(B1 幽灵仓 / B2 资金费盯市)
path_delta = {
    "b1_ghost_v0_to_v1_max_abs_nav_diff": float(np.max(np.abs(
        np.asarray(variants["v0"]["nav"]) - np.asarray(variants["v1"]["nav"])))),
    "b2_funding_v1_to_v2_max_abs_nav_diff": float(np.max(np.abs(
        np.asarray(variants["v1"]["nav"]) - np.asarray(variants["v2"]["nav"])))),
    "b2_funding_v1_to_v2_days_differing": int(np.sum(
        np.abs(np.asarray(variants["v1"]["nav"]) - np.asarray(variants["v2"]["nav"])) > 1e-12)),
}
print(f"  B1(幽灵仓)逐日最大差 {path_delta['b1_ghost_v0_to_v1_max_abs_nav_diff']:.6f};"
      f" B2(资金费)逐日最大差 {path_delta['b2_funding_v1_to_v2_max_abs_nav_diff']:.6e}"
      f"(受影响天数 {path_delta['b2_funding_v1_to_v2_days_differing']})", flush=True)

# ── ① 叠加口径(① majors 长持 + 战术空腿)—— t256 第 678–706 行,逐字 ──
core = {}
for r in sty:
    if r.get("level") is not None:
        core[str(r["d"])[:10]] = float(r["level"])
core_days = [d for d in DATES if d in core]
base = core[core_days[0]]
core_nav = np.array([core[d] / base for d in core_days])
core_maxdd = maxdd(core_nav)


def overlay(nav: np.ndarray) -> dict:
    sr = pd.Series(nav, index=pd.Index(days)).pct_change().fillna(0.0)
    aligned = sr.reindex(core_days).fillna(0.0).to_numpy()
    comb = core_nav * np.cumprod(1.0 + aligned)
    cm = maxdd(comb)
    return {
        "core_maxdd": core_maxdd, "core_total": float(core_nav[-1] - 1.0),
        "combined_maxdd": cm, "combined_total": float(comb[-1] - 1.0),
        "dd_reduction_pp": (core_maxdd - cm) * 100.0,
        "gap_nav_units": float((core_nav[-1] - 1.0) - (comb[-1] - 1.0)),
        "gap_pct_of_core_final": float(((core_nav[-1] - 1.0) - (comb[-1] - 1.0)) / (core_nav[-1] - 1.0) * 100.0),
        "gap_log": float(np.log(core_nav[-1]) - np.log(comb[-1])),
        "n_days": len(core_days),
    }


for mode in ("v0", "v1", "v2"):
    variants[mode]["overlay"] = overlay(variants[mode]["nav"])
variants["v3_t332_import"]["overlay"] = overlay(np.asarray(t332_nav))

# v0 必须逐位复现 t256 已发布的 §① 数字(否则 v0 就不是「旧实现」)
pub = old["side_hedge"]
v0o = variants["v0"]["overlay"]
pub_check = {
    "published": {k: pub.get(k) for k in ("core_maxdd", "core_total", "combined_maxdd",
                                          "combined_total", "dd_reduction_pp",
                                          "sleeve_total_ret", "sleeve_maxdd", "n_days")},
    "recomputed_v0": {
        "core_maxdd": v0o["core_maxdd"], "core_total": v0o["core_total"],
        "combined_maxdd": v0o["combined_maxdd"], "combined_total": v0o["combined_total"],
        "dd_reduction_pp": v0o["dd_reduction_pp"],
        "sleeve_total_ret": variants["v0"]["sleeve_total_ret"],
        "sleeve_maxdd": variants["v0"]["sleeve_maxdd"], "n_days": v0o["n_days"]},
}
for k in pub_check["published"]:
    a, b = pub_check["published"][k], pub_check["recomputed_v0"][k]
    if a is None or b is None:
        continue
    pub_check.setdefault("max_abs_diff", {})[k] = abs(float(a) - float(b))
pub_check["reproduces_published"] = bool(pub_check.get("max_abs_diff") and
                                         max(pub_check["max_abs_diff"].values()) < 1e-9)
print(f"  v0 是否逐位复现已发布的 §①: {pub_check['reproduces_published']}"
      f" {json.dumps(pub_check.get('max_abs_diff'), ensure_ascii=False)}", flush=True)

# 对冲腿(t332.hedge_leg_nav,import):每张空票配等名义多 BTC
hedge = t332.hedge_leg_nav(tickets, {"BTC": btc}, days, btc)
for mode in ("v0", "v1", "v2"):
    h = variants[mode]["overlay"]
    hedged_nav = np.asarray(variants[mode]["nav"]) + hedge
    h["hedge_leg_nav_end"] = float(hedge[-1])
    h["hedged_sleeve_total_ret"] = float(hedged_nav[-1] - 1.0)
    h["hedged_sleeve_maxdd"] = maxdd(hedged_nav)

# ── 随机对照(4) ───────────────────────────────────────────────────
print("[3] 随机对照(种子 736,1000 次)…", flush=True)
avg_r = float(np.mean(r_net))


def simulate_t256(d: str) -> dict | None:
    """t256 `simulate()` 逐字(面板版,取自 t332 的同款实现)。"""
    i = IDX.get(d)
    if i is None or i + 1 >= n:
        return None
    a = ATR[i]
    if math.isnan(a) or a <= 0:
        return None
    j = i + 1
    entry = float(OPEN[j])
    r_unit = STOP_ATR * a
    stop0 = entry + r_unit
    target = entry - TP_ATR * a
    be_trigger = entry - r_unit
    stop = stop0
    exit_i = exit_px = None
    reason = ""
    for k in range(TIME_STOP):
        b = j + k
        if b >= n:
            break
        o, h, l = float(OPEN[b]), float(HIGH[b]), float(LOW[b])
        if o >= stop:
            exit_i, exit_px, reason = b, o, ("保本" if stop == entry else "止损")
            break
        if o <= target:
            exit_i, exit_px, reason = b, o, "止盈"
            break
        if h >= stop:
            exit_i, exit_px, reason = b, stop, ("保本" if stop == entry else "止损")
            break
        if l <= target:
            exit_i, exit_px, reason = b, target, "止盈"
            break
        if l <= be_trigger:
            if h >= entry:
                exit_i, exit_px, reason = b, entry, "保本"
                break
            stop = entry
    truncated = False
    if exit_i is None:
        b = min(j + TIME_STOP - 1, n - 1)
        exit_i, exit_px, reason = b, float(CLOSE[b]), "时间"
        truncated = b < j + TIME_STOP - 1
    hold_days = exit_i - j + 1
    fd = DATES[j:exit_i + 1]
    fund = float(sum(FUND.get(x, 0.0) for x in fd))
    r_px = (entry - exit_px) / r_unit
    r_fund = fund * entry / r_unit
    r_cost = 2.0 * (COST_BPS / 1e4) * entry / r_unit
    return {"signal_d": d, "entry_d": DATES[j], "exit_d": DATES[exit_i], "entry": entry,
            "exit": exit_px, "atr14_d": a, "r_unit": r_unit, "stop": stop0, "target": target,
            "reason": reason, "hold_days": hold_days, "funding_sum": fund, "r_price": r_px,
            "r_fund": r_fund, "r_cost": r_cost, "r_net": r_px + r_fund - r_cost,
            "truncated": truncated, "_fund": FUND, "_fd": fd}


def null_draws(pool: list[str], seed: int, n_draws: int) -> dict:
    """t256 第 606–648 行,逐字;另加退化度诊断。"""
    rng = np.random.default_rng(seed)
    null_means: list[float] = []
    null_overlap_free: list[float] = []
    short_draws = 0
    degenerate = 0
    n_tk_total = 0
    for _ in range(n_draws):
        pick = rng.choice(len(pool), size=min(len(tickets), len(pool)), replace=False)
        tks = [simulate_t256(pool[int(j)]) for j in np.atleast_1d(pick)]
        tks = [t for t in tks if t]
        if tks:
            null_means.append(float(np.mean([t["r_net"] for t in tks])))
            n_tk_total += len(tks)
            for t in tks:
                if (not math.isfinite(t["r_net"])) or abs(t["r_net"]) > 10:
                    degenerate += 1
        order = rng.permutation(len(pool))
        got: list[dict] = []
        last_exit = ""
        for j in order:
            d = pool[int(j)]
            if len(got) >= len(tickets):
                break
            entry_d = DATES[IDX[d] + 1]
            if entry_d <= last_exit:
                continue
            t = simulate_t256(d)
            if t is None:
                continue
            got.append(t)
            last_exit = t["exit_d"]
        if got:
            null_overlap_free.append(float(np.mean([t["r_net"] for t in got])))
            if len(got) < len(tickets):
                short_draws += 1
            for t in got:
                if (not math.isfinite(t["r_net"])) or abs(t["r_net"]) > 10:
                    degenerate += 1
    arr = np.array(null_overlap_free)
    ind = np.array(null_means)
    return {
        "pool_days": len(pool), "n_draws": n_draws, "seed": seed,
        "mean_r_net_actual": avg_r,
        "null_overlap_free_mean": float(arr.mean()) if arr.size else None,
        "null_overlap_free_p95": float(np.percentile(arr, 95)) if arr.size else None,
        "null_overlap_free_pctl_of_actual": percentile_of(avg_r, arr) if arr.size else None,
        "null_independent_mean": float(ind.mean()) if ind.size else None,
        "null_independent_p95": float(np.percentile(ind, 95)) if ind.size else None,
        "null_independent_pctl_of_actual": percentile_of(avg_r, ind) if ind.size else None,
        "draws_with_fewer_tickets": short_draws,
        "mean_tickets_per_independent_draw": (n_tk_total / n_draws) if n_draws else None,
        "degenerate_tickets_rnet_abs_gt_10": degenerate,
    }


old_pool = list(elig_px)                    # 旧口径:只有价格条件成立的日子(1029 天)
new_pool = list(sig_all)                    # 预注册口径:③ 三条全中(69 天)
null_old = null_draws(old_pool, SEED, N_NULL)
null_new = null_draws(new_pool, SEED, N_NULL)
old_null = old["null_control"]
print(f"  旧池({len(old_pool)} 天):重叠自由版分位 {null_old['null_overlap_free_pctl_of_actual']}"
      f" / 独立版 {null_old['null_independent_pctl_of_actual']}", flush=True)
print(f"  ③ 池({len(new_pool)} 天):重叠自由版分位 {null_new['null_overlap_free_pctl_of_actual']}"
      f" / 独立版 {null_new['null_independent_pctl_of_actual']}"
      f" · 票不足的抽样 {null_new['draws_with_fewer_tickets']}/{N_NULL}", flush=True)

# ── 票级(不依赖 NAV)的对照 ────────────────────────────────────────
ticket_level = {
    "avg_r_net": avg_r, "median_r_net": float(np.median(r_net)),
    "win_rate": float(np.mean([x > 0 for x in r_net])),
    "total_r_net": float(np.sum(r_net)), "reasons": reasons,
    "funding_r_sum": float(np.sum([t["r_fund"] for t in tickets])),
    "price_r_sum": float(np.sum([t["r_price"] for t in tickets])),
    "cost_r_sum": float(np.sum([t["r_cost"] for t in tickets])),
}

# ── 前向情景的基准率(用同一份历史算) ──────────────────────────────
fund30: list[float] = []
for i in range(30, n):
    fund30.append(float(np.sum([FUND.get(dd, 0.0) for dd in DATES[i - 29:i + 1]])))
fund30_pos_rate = float(np.mean([x > 0 for x in fund30])) if fund30 else None
px = CLOSE
fwd20 = []
for i in range(n - 20):
    fwd20.append(px[i + 20] / px[i] - 1.0)
band = (float(np.percentile(fwd20, 25)), float(np.percentile(fwd20, 75)))
band_rate = float(np.mean([band[0] <= x <= band[1] for x in fwd20]))

# ── 判据 (b) 的 NAV 路径统计量:用修好的袖套 NAV 重跑 t256 的 ab_test ──
#     t256 第 583–587 行:ab_test(对照臂 = 0, 袖套逐日收益, mean_block=20, n_boot=2000, seed=736)
from src.data.evaluation.apparatus import ab_test as _ab_test  # noqa: E402

ab_by_mode: dict[str, dict] = {}
for mode in ("v0", "v1", "v2"):
    _nav = np.asarray(variants[mode]["nav"], dtype=float)
    _rets = pd.Series(_nav, index=pd.Index(days)).pct_change().fillna(0.0).to_numpy()
    _ab = _ab_test(np.zeros_like(_rets), _rets, mean_block=20.0, n_boot=2000, seed=SEED)
    ab_by_mode[mode] = {k: _ab.get(k) for k in ("n_days", "cum_a", "cum_b", "p_b_le_a", "p_b_ge_a",
                                                "ci95_log_diff", "verdict", "underpowered")}
pub_ab = old.get("ab_vs_zero") or {}
print("[5] 判据 (b) 的 ab_test(袖套 NAV 路径,参数同 t256):", flush=True)
for _m, _lab in (("v0", "旧(幽灵仓)"), ("v1", "修好")):
    print(f"  {_lab}: cum_b {ab_by_mode[_m]['cum_b']:+.6%} · p(b≤a) {ab_by_mode[_m]['p_b_le_a']:.4f}"
          f" · 判定 {ab_by_mode[_m]['verdict']}", flush=True)


# ── 同源实现的幽灵仓外溢:T-333 自己抄了一份 t256 的单仓位 sleeve_nav ──
def _same_day_tickets(csv_path: Path) -> dict:
    if not csv_path.exists():
        return {"available": False}
    rows = list(csv.DictReader(csv_path.open()))
    same = [r for r in rows if r.get("entry_d") == r.get("exit_d")]
    return {"available": True, "n_tickets": len(rows), "n_same_day_entry_exit": len(same),
            "same_day_rows": [{"symbol": r.get("symbol"), "entry_d": r.get("entry_d"),
                               "exit_d": r.get("exit_d"), "reason": r.get("reason")} for r in same][:10]}


def _single_slot_sleeve(src: Path) -> bool | None:
    """源码级判据:单仓位槽(open_t)且没有多仓位表(open_pos)⇒ 抄的是 t256 的幽灵仓版。"""
    if not src.exists():
        return None
    t = src.read_text()
    if "open_pos" in t:
        return False
    return "open_t" in t


spillover = {
    "criterion": "源码级:单仓位槽 open_t + 无多仓位表 open_pos ⇒ 与 t256 同实现(幽灵仓版)",
    "t256": {"file": "docs/research/t256_tactical_short.py",
             "single_slot_sleeve": _single_slot_sleeve(HERE / "t256_tactical_short.py")},
    "t332": {"file": "docs/research/t332_squeeze_fade.py",
             "single_slot_sleeve": _single_slot_sleeve(HERE / "t332_squeeze_fade.py")},
    "t333": {"file": "docs/research/t333_euphoria_short.py",
             "single_slot_sleeve": _single_slot_sleeve(HERE / "t333_euphoria_short.py"),
             "tickets": _same_day_tickets(HERE / "t333_tickets.csv"),
             "uses_t332_sleeve": "t332.sleeve_nav" in (HERE / "t333_euphoria_short.py").read_text()},
    "t334": {"file": "docs/research/t334_squeeze_fail.py",
             "single_slot_sleeve": _single_slot_sleeve(HERE / "t334_squeeze_fail.py"),
             "tickets": _same_day_tickets(HERE / "t334_tickets.csv"),
             "uses_t332_sleeve": "t332.sleeve_nav" in (HERE / "t334_squeeze_fail.py").read_text()},
}
for _k in ("t333", "t334"):
    _s = spillover[_k]
    if _s["single_slot_sleeve"] is True and _s["tickets"].get("n_same_day_entry_exit", 0) > 0:
        _s["verdict"] = "幽灵仓会咬:单仓位槽 + 有同日进出票 ⇒ 该臂的 NAV 路径统计量受影响"
    elif _s["single_slot_sleeve"] is True:
        _s["verdict"] = "单仓位槽,但本样本无同日进出票 ⇒ 本次无咬"
    else:
        _s["verdict"] = "用 t332 的多仓位 sleeve_nav ⇒ 不受 t256 幽灵仓影响"
print(f"  同源外溢:T-333 单仓位槽={spillover['t333']['single_slot_sleeve']}"
      f" · 同日进出票 {spillover['t333']['tickets'].get('n_same_day_entry_exit')}"
      f" · T-334 用 t332 袖套={spillover['t334']['uses_t332_sleeve']}", flush=True)

res = {
    "card": "T-338",
    "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "data": {
        "btc_bars": n, "btc_range": [DATES[0], DATES[-1]],
        "dvol_range": [dv_days[0], dv_days[-1]],
        "nav_days": len(days), "nav_range": [days[0], days[-1]],
        "signal_days": len(sig_all), "price_only_days": len(elig_px),
        "core_days": len(core_days), "core_range": [core_days[0], core_days[-1]],
    },
    "self_check": selfcheck,
    "published_reproduction_check": pub_check,
    "path_delta": path_delta,
    "ticket_level": ticket_level,
    "variants": {k: {kk: vv for kk, vv in v.items() if kk not in ("nav", "days")} for k, v in variants.items()},
    "v2_vs_t332_import_max_abs_diff": v2v3_diff,
    "null_control": {"old_pool_price_only": null_old, "prereg_pool_cond3": null_new,
                     "t256_original": old_null},
    "judge_b_ab_test_by_nav_path": {"published_t256": pub_ab, "recomputed": ab_by_mode},
    "same_source_ghost_spillover": spillover,
    "baserates": {
        "funding_30d_avg_positive_rate": fund30_pos_rate,
        "btc_fwd20_band": band, "btc_fwd20_band_coverage": band_rate,
    },
}
(HERE / "t338_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
print("[4] 写 t338_results.json 完成", flush=True)

print("\n=== 摘要 ===")
for mode, label in (("v0", "旧(t256 原样)"), ("v1", "+修幽灵仓"), ("v2", "+资金费只在出场兑现"),
                     ("v3_t332_import", "t332 import")):
    v = variants[mode]
    o = v.get("overlay", {})
    print(f"{label:22s} 袖套净值 {v['sleeve_total_ret']:+.4%} · 自身回撤 {v['sleeve_maxdd']:.4%}"
          f" · 叠加回撤 {o.get('combined_maxdd', float('nan')):.4%}"
          f" · 削回撤 {o.get('dd_reduction_pp', float('nan')):+.4f}pp"
          f" · 付总收益 {o.get('gap_nav_units', float('nan')):+.4f}(NAV 单位)")
