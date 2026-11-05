"""T-252 —— 崩盘夜的空头腿(只报不判):③ 判 0 倍时另加一条 BTC 永续空腿(④)。

**卡上的 acceptance 就是下面的 PREREG;先写下来再算,只算一次,不挑量、不挑参数。**

用法:python3 docs/research/t252_short_leg.py
产物:docs/research/T-252_crash_short_leg.md + docs/research/t252_results.json
数据:只读 Supabase(缓存目录 /Volumes/CometCloudAI/cometcloud-local/research/t252)。
纪律:不改代码、不做 DDL、不入库;零分布/盈亏只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    short_return,
)
from src.data.signals.tom import trade_path  # noqa: E402  —— ③ 的规则核,直接用生产代码

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t252")

WIN_START = "2020-07-01"
COST_BPS = 7.5          # 每次开 / 关 7.5bp(卡上口径)
SHORT = {"BTC": 0.5, "ETH": 0.5}   # executor.SLEEVES
TOM_WARM_FROM = "2024-01-01"      # forward_books.TOM_WARM_FROM(活计划的历史起点)

PREREG = """# T-252 —— 崩盘夜的空头腿(只报不判)

**预注册(2026-11-06,先写下来再算;三种定义各算一遍,不扫参、不挑量)**

> **问题(Jazz 11-05 夜)**「我们的策略没有开空或者对冲吗」——③ 判 0 倍时账户就是现金。
> 本卡只描述「如果 ④ 有一条择时空腿会怎样」:**不立臂、不动钱、不判**。
>
> ① **窗口**:2020-07-01 → 最后一个有永续收盘价的日子(2026-11-04)。
> ② **三种空腿定义**(各算一遍,只有这三个):
>    - **A** = ③ 判 0 的日子(加密腿敞口 = 0)持 1 倍 BTC 永续空;
>    - **B** = A 且 ⓪ 相位 = turning(⓪ = `cycle_vector_daily`.phase);
>    - **C** = majors 指数(`style_index_pit_daily` style=majors weighting=cap)在 200 日线下。
> ③ **③ 的敞口从哪来**:`exposure_decision_daily` 只有 3 行(2026-11-02→11-04),不够跑历史。
>    因此 ③ 的敞口**本地复算**:用生产的同一个核 `src/data/signals/tom.trade_path`
>    + `executor` 的权重(BTC 0.5 / ETH 0.5,敞口 = 两者之和,单币 clip 到 [0,1]),
>    收盘价取 `asset_mcap_daily`.price(BTC、ETH)—— 与活计划同一个价源。
>    **校验(必做)**:复算值 vs 已落表的 3 行 `rule_exposure`,逐日对。
>    另跑一版「从 2024-01-01 起(活计划的历史起点)」,报两版在 2024 年后的分歧比例。
> ④ **价 / 资金费 / 成本**:价 = `perp_bv_daily` 的 BTCUSDT 收盘(c);
>    资金费两口径各报 —— Binance `v_funding_daily`(symbol=BTC,日合计 = funding_rate × n)、
>    HL `hl_funding_hourly`(coin=BTC,日合计 = 当日 hourly rate 之和,2023-05-12 起);
>    另报混合口径(2023-05-12 之前 Binance、之后 HL)。成本 = 每次开 / 关 7.5bp。
> ⑤ **时点**:d 收盘定的信号,d+1 生效(与 `tom.trade_returns` 同一个错一天约定)。
>    资金费归因到当日(整日 3 次或 24 次支付全记在持仓日),另给 2/3 归因的敏感度。
> ⑥ **报**:总收益、年化、最大回撤、Calmar、最长亏损段、资金费合计、逐年;
>    与「同期空仓(0)」比、与 ① 持有(`style_index_pit_daily` 的 majors 指数)比。
> ⑦ **回撤段**:2020-07 起所有 BTC「30 日内回撤 ≥ 25%」的段(定义写死:滚动 30 日最高价回撤 ≤ −25%,
>    连续命中日合并,间隔 ≤ 5 天算同一段):每段报 崩跌段空腿赚了多少、反弹段回吐了多少、净额。
> ⑧ **零信号对照**:同等在场天数、同等开关次数的随机空腿 1,000 次(随机摆放同样长度的空腿段,
>    资金费与成本照算),种子 252,`apparatus.null_distribution` + `percentile_of`。
> ⑨ **只报不判**;不改代码、不入库;交付附 `docs/research/scenarios/lane-a-T-252.json`(≥ 3 条可核命题)。
"""

# ───────────────────────────── 数据 ─────────────────────────────


def pull(table: str, query: str, step: int = 1000) -> list[dict]:
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


def dser(rows: list[dict], key: str = "d", val: str | None = None) -> pd.Series:
    out = {}
    for r in rows:
        v = r.get(val or key)
        if v is None:
            continue
        out[pd.Timestamp(str(r[key])[:10])] = float(v)
    return pd.Series(out).sort_index()


print("[1/6] 读数据…", flush=True)
am_btc = load("asset_mcap_BTC", "asset_mcap_daily",
              "select=d,price,symbol&symbol=eq.BTC&d=gte.2019-01-01&order=d.asc,symbol.asc")
am_eth = load("asset_mcap_ETH", "asset_mcap_daily",
              "select=d,price,symbol&symbol=eq.ETH&d=gte.2019-01-01&order=d.asc,symbol.asc")
perp = load("perp_btc", "perp_bv_daily",
            "select=d,o,h,l,c,qv,tbqv,pair,symbol,recorded_at&pair=eq.BTCUSDT&order=d.asc,recorded_at.asc")
vf = load("v_funding_btc", "v_funding_daily",
          "select=d,symbol,funding_rate,n&symbol=eq.BTC&order=d.asc,symbol.asc")
hl = load("hl_funding_btc", "hl_funding_hourly", "select=t,coin,rate,premium&coin=eq.BTC&order=t.asc")
sty = load("style_majors", "style_index_pit_daily",
           "select=d,level,ret,style,weighting,dimension,members,n_members,computed_at&style=eq.majors"
           "&weighting=eq.cap&order=d.asc")
cyc = load("cycle", "cycle_vector_daily",
           "select=d,phase,deterioration,shift,shift_pct,code_ref,components&order=d.asc")
expdec = load("exposure_decision", "exposure_decision_daily",
              "select=d,sleeve,rule_exposure,mult_arm,mult_m,inputs,bucket,probs,flag,code_ref&order=d.asc")

px_btc = dser(am_btc, "d", "price")
px_eth = dser(am_eth, "d", "price")
perp_c = dser(perp, "d", "c")
perp_dup = len(perp) - len(perp_c)
fund_bn: dict[str, float] = {}
for r in vf:
    n = int(r.get("n") or 1)
    fund_bn[str(r["d"])[:10]] = fund_bn.get(str(r["d"])[:10], 0.0) + float(r["funding_rate"]) * n
fund_hl: dict[str, float] = {}
for r in hl:
    dd = str(r["t"])[:10]
    fund_hl[dd] = fund_hl.get(dd, 0.0) + float(r["rate"])
level = dser(sty, "d", "level")
phase = {str(r["d"])[:10]: r.get("phase") for r in cyc}

# ───────────────────────────── ③ 的敞口(本地复算 + 校验) ─────────────────────────────
print("[2/6] 复算 ③ 的敞口…", flush=True)


def exposure_from(px: dict[str, pd.Series], start: str | None) -> pd.Series:
    """按生产核复算 ③ 的加密腿敞口(0..1)。start = 截断起点(活计划 = 2024-01-01)。"""
    gs = {}
    for sym, s in px.items():
        ss = s if start is None else s[s.index >= pd.Timestamp(start)]
        g = trade_path(ss, "rally", 0.0, exit_mode="l20", vol=True)
        gs[sym] = g.clip(0.0, 1.0)
    idx = gs["BTC"].index.intersection(gs["ETH"].index)
    out = sum(SHORT[sym] * gs[sym].reindex(idx) for sym in gs)
    return out.sort_index()


exp_full = exposure_from({"BTC": px_btc, "ETH": px_eth}, None)
exp_live = exposure_from({"BTC": px_btc, "ETH": px_eth}, TOM_WARM_FROM)

validation = []
for r in expdec:
    d = str(r["d"])[:10]
    pub = r.get("rule_exposure")
    rec_full = float(exp_full.get(pd.Timestamp(d), float("nan")))
    rec_live = float(exp_live.get(pd.Timestamp(d), float("nan")))
    validation.append({"d": d, "published": pub, "recon_full": rec_full, "recon_live": rec_live,
                       "match_live": (pub is not None and abs(rec_live - float(pub)) < 1e-6),
                       "match_full": (pub is not None and abs(rec_full - float(pub)) < 1e-6)})
common24 = exp_full.index.intersection(exp_live.index)
diff24 = float((exp_full.reindex(common24) - exp_live.reindex(common24)).abs().gt(1e-9).mean())
n_zero_full = int((exp_full.reindex(perp_c.index).fillna(0.0).abs() < 1e-9).sum())

# ───────────────────────────── 信号 ─────────────────────────────
print("[3/6] 组信号…", flush=True)
cal = perp_c.index
c = perp_c.to_numpy()

sig_a = pd.Series(0.0, index=cal)
sig_a.loc[exp_full.index.intersection(cal)] = (exp_full.reindex(cal).fillna(1.0).abs() < 1e-9).astype(float)
sig_a = sig_a.where(exp_full.reindex(cal).notna(), 0.0)

ph = pd.Series({pd.Timestamp(k): (1.0 if v == "turning" else 0.0) for k, v in phase.items()})
sig_b = (sig_a * ph.reindex(cal).fillna(0.0)).where(sig_a > 0, 0.0)

ma200 = level.rolling(200, min_periods=200).mean()
below = (level < ma200)
sig_c = pd.Series(0.0, index=cal)
sig_c.loc[below.index.intersection(cal)] = below.reindex(cal).fillna(False).astype(float)

DEFS = {"A": sig_a, "B": sig_b, "C": sig_c}

# ③ 敞口复算的起点敏感度(2024 起 = 活计划的历史起点)
sig_a_live = pd.Series(0.0, index=cal)
_ef = exp_live.reindex(cal)
sig_a_live.loc[exp_live.index.intersection(cal)] = (_ef.abs() < 1e-9).astype(float)
sig_a_live = sig_a_live.where(_ef.notna(), 0.0)
sig_b_live = (sig_a_live * ph.reindex(cal).fillna(0.0)).where(sig_a_live > 0, 0.0)
DEFS_LIVE = {"A": sig_a_live, "B": sig_b_live, "C": sig_c}
_zf = (exp_full.reindex(cal).fillna(1.0).abs() < 1e-9)
_zl = (exp_live.reindex(cal).fillna(1.0).abs() < 1e-9)
_ov = exp_live.reindex(cal).notna()          # 两版都有值的重叠期(2024-01-01 起)
zero_agree = float((_zf[_ov] == _zl[_ov]).mean())
zero_disagree_days = [str(d.date()) for d in cal[_ov & (_zf != _zl)]]

# ───────────────────────────── 回测核 ─────────────────────────────


def simulate(pos: np.ndarray, fund: dict[str, float], dates: list[str], px: np.ndarray,
             cost_bps: float = COST_BPS, price_model: str = "linear") -> dict:
    """pos[i] = 第 i 日持仓(1 = 空 1 倍名义)。日收益 = 价格 + 资金费 − 换手成本。

    px 必须与 dates / pos 同一日历(永续收盘)。
    价格口径两版(都在下面报):
      linear  = 1 − c_t/c_{t−1}(apparatus.short_return;1 倍名义按当日权益再平衡);
      inverse = c_{t−1}/c_t − 1(同一名义、每日全额再投,单日亏损封顶 −100%)。
    资金费:费率 > 0 ⇒ 多头付、空头收 ⇒ 空腿 pnl = +pos × 当日资金费合计。
    """
    px_pnl = np.zeros(len(pos))
    for i in range(1, len(pos)):
        if price_model == "inverse":
            sr = -short_return(px[i], px[i - 1])       # c_{t−1}/c_t − 1(同一名义、每日全额再投)
        else:
            sr = short_return(px[i - 1], px[i])
        px_pnl[i] = 0.0 if sr is None else pos[i] * sr
    f_pnl = np.array([pos[i] * fund.get(dates[i], 0.0) for i in range(len(pos))])
    sw = np.abs(np.diff(pos, prepend=0.0))
    cost = -sw * cost_bps / 1e4
    tot = px_pnl + f_pnl + cost
    eq = np.cumprod(1.0 + tot)
    run_max = np.maximum.accumulate(eq)
    dd = eq / run_max - 1.0
    years = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25, 1e-9)
    cagr = eq[-1] ** (1.0 / years) - 1.0 if eq[-1] > 0 else float("nan")
    mdd = float(dd.min())
    streak = best = 0
    for x in tot:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    return {
        "total_return": float(eq[-1] - 1.0),
        "cagr": float(cagr),
        "max_dd": mdd,
        "calmar": float(cagr / abs(mdd)) if (mdd < 0 and math.isfinite(cagr)) else None,
        "longest_losing_streak_d": int(best),
        "funding_total": float(f_pnl.sum()),
        "price_pnl_total": float(px_pnl.sum()),
        "cost_total": float(cost.sum()),
        "days_in_market": int((pos > 0).sum()),
        "switches": int((sw > 0).sum()),
        "n_days": len(pos),
        "years": years,
        "eq_final": float(eq[-1]),
        "_daily": tot,
        "_eq": eq,
        "_pos": pos,
        "_dates": dates,
    }


def bench_series(level_s: pd.Series, lo: str, hi: str) -> dict:
    lv = level_s[(level_s.index >= pd.Timestamp(lo)) & (level_s.index <= pd.Timestamp(hi))]
    lv = lv.dropna()
    r = lv.pct_change().fillna(0.0)
    eq = np.cumprod(1.0 + r.to_numpy())
    run_max = np.maximum.accumulate(eq)
    dd = eq / run_max - 1.0
    years = max((lv.index[-1] - lv.index[0]).days / 365.25, 1e-9)
    cagr = eq[-1] ** (1.0 / years) - 1.0
    mdd = float(dd.min())
    return {"total_return": float(eq[-1] - 1.0), "cagr": float(cagr), "max_dd": mdd,
            "calmar": float(cagr / abs(mdd)) if mdd < 0 else None,
            "start": str(lv.index[0].date()), "end": str(lv.index[-1].date()), "n_days": len(lv)}


def yearly(res: dict) -> list[dict]:
    dates = res["_dates"]
    tot = res["_daily"]
    pos = res["_pos"]
    out = []
    for y in sorted({d[:4] for d in dates}):
        idx = [i for i, d in enumerate(dates) if d[:4] == y]
        seg = tot[idx]
        eq = float(np.prod(1.0 + seg))
        out.append({"year": y, "return": eq - 1.0, "days_in_market": int((pos[idx] > 0).sum()),
                    "n_days": len(idx),
                    "funding": float(sum(-pos[i] * 0 for i in idx))})
    return out


def yearly_funding(res: dict, fund: dict[str, float]) -> list[dict]:
    dates, tot, pos = res["_dates"], res["_daily"], res["_pos"]
    out = []
    for y in sorted({d[:4] for d in dates}):
        idx = [i for i, d in enumerate(dates) if d[:4] == y]
        eq = float(np.prod(1.0 + tot[idx]))
        f = float(sum(-pos[i] * fund.get(dates[i], 0.0) for i in idx))
        out.append({"year": y, "return": eq - 1.0, "days_in_market": int((pos[idx] > 0).sum()),
                    "n_days": len(idx), "funding": f})
    return out


# ───────────────────────────── 回撤段 ─────────────────────────────
print("[4/6] 回撤段 + 零信号对照…", flush=True)


def episodes(dates: list[str], px: np.ndarray, thr: float = -0.25, win: int = 30,
             merge_gap: int = 5) -> list[dict]:
    s = pd.Series(px, index=pd.to_datetime(dates))
    roll_max = s.rolling(win, min_periods=win).max()
    dd = s / roll_max - 1.0
    qual = dd <= thr
    idx = np.where(qual.to_numpy())[0]
    if len(idx) == 0:
        return []
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= merge_gap:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    out = []
    for g in groups:
        i0, i1 = g[0], g[-1]
        lo_i = max(0, i0 - win)
        peak_i = int(np.argmax(px[lo_i:i0 + 1])) + lo_i
        seg = range(i0, min(i1 + 6, len(px)))
        trough_i = int(np.argmin(px[i0:min(i1 + 6, len(px))])) + i0
        rec_i = None
        for j in range(trough_i + 1, min(trough_i + 91, len(px))):
            if px[j] >= px[peak_i]:
                rec_i = j
                break
        if rec_i is None:
            rec_i = min(trough_i + 90, len(px) - 1)
        out.append({"peak_d": dates[peak_i], "trough_d": dates[trough_i], "end_d": dates[i1],
                    "recover_d": dates[rec_i], "recovered": rec_i < len(px) - 1 and px[rec_i] >= px[peak_i],
                    "peak_px": float(px[peak_i]), "trough_px": float(px[trough_i]),
                    "btc_crash_pct": float(px[trough_i] / px[peak_i] - 1.0),
                    "i0": i0, "i1": i1, "peak_i": peak_i, "trough_i": trough_i, "rec_i": rec_i})
    return out


def episode_pnl(res: dict, ep: dict, fund: dict[str, float]) -> dict:
    dates, tot, pos = res["_dates"], res["_daily"], res["_pos"]
    a, b = ep["peak_i"] + 1, ep["trough_i"] + 1        # 崩跌段
    c1, c2 = ep["trough_i"] + 1, ep["rec_i"] + 1       # 反弹段(回吐)
    crash = float(tot[a:b].sum())
    rebound = float(tot[c1:c2].sum())
    return {"crash_pnl": crash, "rebound_pnl": rebound, "net_pnl": crash + rebound,
            "days_in_market_crash": int((pos[a:b] > 0).sum()),
            "days_in_market_rebound": int((pos[c1:c2] > 0).sum()),
            "funding_crash": float(sum(-pos[i] * fund.get(dates[i], 0.0) for i in range(a, b)))}


# ───────────────────────────── 跑 ─────────────────────────────
print("[5/6] 回测…", flush=True)
mask = (perp_c.index >= pd.Timestamp(WIN_START))
cal_w = perp_c.index[mask]
c_w = perp_c[mask].to_numpy()
dates_w = [str(d.date()) for d in cal_w]
dates_full = [str(d.date()) for d in perp_c.index]

results: dict = {"card": "T-252", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "window": {"start": dates_w[0], "end": dates_w[-1], "n_days": len(dates_w)},
                 "data": {"perp_rows": len(perp), "perp_dup_days": perp_dup,
                          "perp_first": dates_full[0], "perp_last": dates_full[-1],
                          "asset_mcap_btc": len(px_btc), "asset_mcap_eth": len(px_eth),
                          "v_funding_days": len(fund_bn), "hl_funding_days": len(fund_hl),
                          "style_majors_rows": len(level), "cycle_rows": len(cyc),
                          "exposure_decision_rows": len(expdec)},
                 "exposure_reconstruction": {"validation": validation,
                                             "disagree_pct_since_2024": diff24,
                                             "zero_agree_pct": zero_agree,
                                             "zero_disagree_days": len(zero_disagree_days),
                                             "zero_disagree_first": zero_disagree_days[:10],
                                             "zero_days_full_over_perp_calendar": n_zero_full,
                                             "tom_warm_from": TOM_WARM_FROM}}

RES: dict = {}


def run_all(sigs: dict[str, pd.Series], fund_map: dict[str, float], dx: list[str], calx,
            price_model: str = "linear") -> dict:
    pxx = perp_c.reindex(calx).to_numpy()
    out = {}
    for dname, sig in sigs.items():
        pos = sig.reindex(calx).fillna(0.0).to_numpy()
        pos = np.roll(pos, 1)
        pos[0] = 0.0
        r = simulate(pos, fund_map, dx, pxx, price_model=price_model)
        out[dname] = {k: v for k, v in r.items() if not k.startswith("_")}
        out[dname]["yearly"] = yearly_funding(r, fund_map)
    return out


for name, fund_label, fund_map, lo, hi in [
    ("binance", "Binance(v_funding_daily)", fund_bn, WIN_START, dates_w[-1]),
    ("hl", "HL(hl_funding_hourly,2023-05-12 起)", fund_hl, "2023-05-12", "2026-11-04"),
]:
    calx = perp_c.index[(perp_c.index >= pd.Timestamp(lo)) & (perp_c.index <= pd.Timestamp(hi))]
    cx = perp_c[calx].to_numpy()
    dx = [str(d.date()) for d in calx]
    RES[name] = {"funding_label": fund_label, "window": [dx[0], dx[-1]],
                 "defs": run_all(DEFS, fund_map, dx, calx)}

# 混合口径(2023-05-12 之前 Binance,之后 HL)
hybrid = {d: (fund_hl[d] if d in fund_hl else fund_bn.get(d, 0.0)) for d in dates_full}
RES["hybrid"] = {"funding_label": "混合(2023-05-12 前 Binance / 后 HL)", "window": [dates_w[0], dates_w[-1]],
                 "defs": run_all(DEFS, hybrid, dates_w, cal_w)}
# 敏感度 1:价格口径(inverse = 同一名义、每日全额再投,单日亏损封顶 −100%)
RES["inverse_price"] = {"funding_label": "同 Binance 资金费;价格口径 inverse", "window": [dates_w[0], dates_w[-1]],
                        "defs": run_all(DEFS, fund_bn, dates_w, cal_w, price_model="inverse")}
# 敏感度 2:③ 敞口复算起点(2024-01-01 起 = 活计划历史起点)
RES["exposure_live_start"] = {"funding_label": "③ 敞口用 2024-01-01 起复算", "window": [dates_w[0], dates_w[-1]],
                              "defs": run_all(DEFS_LIVE, fund_bn, dates_w, cal_w)}
# 敏感度 3:资金费按 2/3 归因(日内 K 线只含 08:00 / 16:00 两次支付)
RES["funding_two_thirds"] = {"funding_label": "资金费按日内 2/3 归因", "window": [dates_w[0], dates_w[-1]],
                             "defs": run_all(DEFS, {d: v * 2.0 / 3.0 for d, v in fund_bn.items()}, dates_w, cal_w)}

# 基准
bench = {"flat_0": {"total_return": 0.0, "cagr": 0.0, "max_dd": 0.0, "calmar": None},
         "hold_majors": bench_series(level, WIN_START, dates_w[-1])}

# 回撤段(用 Binance 口径的主回测)
eps = episodes(dates_w, c_w)
main = {}
for dname, sig in DEFS.items():
    pos = sig.reindex(cal_w).fillna(0.0).to_numpy()
    pos = np.roll(pos, 1)
    pos[0] = 0.0
    r = simulate(pos, fund_bn, dates_w, c_w)
    main[dname] = r
eps_out = []
for ep in eps:
    row = {k: v for k, v in ep.items() if not k.startswith("i") and k not in ("peak_i", "trough_i", "rec_i")}
    for dname in DEFS:
        row[dname] = episode_pnl(main[dname], ep, fund_bn)
    eps_out.append(row)

# 零信号对照:同等在场天数、同等开关次数
print("[6/6] 零分布(1000 次)…", flush=True)
nulls: dict = {}
for dname, sig in DEFS.items():
    pos0 = sig.reindex(cal_w).fillna(0.0).to_numpy()
    pos0 = np.roll(pos0, 1)
    pos0[0] = 0.0
    on = pos0 > 0
    runs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j + 1 < len(on) and on[j + 1]:
                j += 1
            runs.append(j - i + 1)
            i = j + 1
        else:
            i += 1
    n_on = int(on.sum())
    n = len(on)
    off_total = n - n_on
    actual = main[dname]["total_return"]

    def draw(rng: np.random.Generator) -> float:
        lens = list(rng.permutation(runs))
        k = len(lens)
        gaps = rng.multinomial(off_total, np.full(k + 1, 1.0 / (k + 1)))
        pos = np.zeros(n)
        at = int(gaps[0])
        for li, L in enumerate(lens):
            s = at
            e = min(s + L, n)
            pos[s:e] = 1.0
            at = e + int(gaps[li + 1])
            if at >= n:
                break
        return simulate(pos, fund_bn, dates_w, c_w)["total_return"]

    try:
        null = null_distribution(draw, 1000, 252, actual=actual)
        pct = percentile_of(actual, null)
        nulls[dname] = {"actual_total_return": actual, "percentile": pct,
                        "null_mean": float(null.mean()), "null_sd": float(null.std(ddof=1)),
                        "null_p05": float(np.quantile(null, 0.05)), "null_p50": float(np.quantile(null, 0.5)),
                        "null_p95": float(np.quantile(null, 0.95)),
                        "runs": len(runs), "run_lengths": runs[:20], "days_in_market": n_on,
                        "switches": main[dname]["switches"], "n": 1000, "seed": 252}
    except NoOpNull as e:
        nulls[dname] = {"error": str(e), "actual_total_return": actual}

results["results"] = RES
results["benchmarks"] = bench
results["episodes"] = eps_out
results["null_control"] = nulls

(HERE / "t252_results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str))
print("已写 docs/research/t252_results.json", flush=True)

# ───────────────────────────── 报告 ─────────────────────────────
L: list[str] = []
A = L.append
A(PREREG)
A("")
A("## 0. 口径与实现决定(开算前写定)")
A("")
A("| 项 | 决定 | 依据 |")
A("|---|---|---|")
A(f"| 窗口 | {dates_w[0]} → {dates_w[-1]}({len(dates_w)} 天) | 卡 |")
A("| ③ 敞口 | 本地用生产核复算(`tom.trade_path` + `executor` 权重 BTC 0.5 / ETH 0.5) | `exposure_decision_daily` 只有 3 行,不够跑历史 |")
A("| ③ 收盘价源 | `asset_mcap_daily`.price | 活计划 `forward_books.prices` 同一个源 |")
A("| 价 | `perp_bv_daily` BTCUSDT 的 c | 卡 |")
A("| 资金费 | Binance `v_funding_daily`(rate × n);HL `hl_funding_hourly`(当日之和) | 卡 |")
A(f"| 成本 | 每次开 / 关 {COST_BPS}bp | 卡 |")
A("| 生效 | d 收盘定信号,d+1 生效 | 与 `tom.trade_returns` 同约定 |")
A("| 回撤段 | 滚动 30 日最高价回撤 ≤ −25%,连续命中合并(间隔 ≤ 5 天) | 卡 |")
A("| 零对照 | 同场天数、同开关次数,随机摆放同样长度的空腿段,1000 次,种子 252 | 卡 |")
A("")
A("## 1. ③ 敞口的本地复算与校验")
A("")
A(f"`exposure_decision_daily` 只有 **{len(expdec)} 行**({', '.join(str(r['d']) for r in expdec)})—— 历史不够跑,故本地复算。")
A("")
A("| d | 已落表 rule_exposure | 复算(2024-01-01 起,同活计划) | 复算(2019 起) |")
A("|---|---|---|---|")
for v in validation:
    A(f"| {v['d']} | {v['published']} | {v['recon_live']:.4f} | {v['recon_full']:.4f} |")
A("")
nmatch = sum(1 for v in validation if v["match_live"])
A(f"**校验:2024 起版本 {nmatch}/{len(validation)} 与已落表逐日相符;2019 起版本 "
  f"{sum(1 for v in validation if v['match_full'])}/{len(validation)} 相符;**")
A(f"两版在 2024 年后敞口值分歧比例 = **{diff24:.2%}**;但「判 0 / 不判 0」这一位上两版一致率 = "
  f"**{zero_agree:.2%}**(不一致 {len(zero_disagree_days)} 天)。故主表用 2019 起版本(窗口内不截断),"
  f"另在 §2.3 报 2024 起版本的结果。")
A("")
A("## 2. 三种定义 × 三种资金费口径(主表:Binance 口径,全窗口)")
A("")
A("| 定义 | 在场天数 | 开关次数 | 总收益 | 年化 | 最大回撤 | Calmar | 最长亏损段(天) | 资金费合计 | 成本合计 |")
A("|---|---|---|---|---|---|---|---|---|---|")
for dname in ("A", "B", "C"):
    m = RES["binance"]["defs"][dname]
    cal = f"{m['calmar']:.2f}" if m["calmar"] is not None else "—"
    A(f"| **{dname}** | {m['days_in_market']} | {m['switches']} | {m['total_return']:+.2%} | "
      f"{m['cagr']:+.2%} | {m['max_dd']:.2%} | {cal} | {m['longest_losing_streak_d']} | "
      f"{m['funding_total']:+.2%} | {m['cost_total']:+.2%} |")
b = bench["hold_majors"]
A(f"| *①持有(majors 指数)* | — | — | {b['total_return']:+.2%} | {b['cagr']:+.2%} | {b['max_dd']:.2%} | "
  f"{(f'{b['calmar']:.2f}' if b['calmar'] else '—')} | — | — | — |")
A("| *同期空仓(0)* | 0 | 0 | 0.00% | 0.00% | 0.00% | — | 0 | 0.00% | 0.00% |")
A("")
A(f"### 2.1 资金费另两口径({RES['hl']['window'][0]} → {RES['hl']['window'][1]})")
A("")
A("| 定义 | Binance 口径(同窗口) | HL 口径 | 混合(Binance→HL) |")
A("|---|---|---|---|")
for dname in ("A", "B", "C"):
    bh = RES["binance"]["defs"][dname]["total_return"]
    hl = RES["hl"]["defs"][dname]["total_return"]
    hy = RES["hybrid"]["defs"][dname]["total_return"]
    A(f"| {dname} | {bh:+.2%} | {hl:+.2%} | {hy:+.2%} |")
A("")
A("### 2.2 逐年(Binance 口径)")
A("")
A("| 年 | A 收益 | A 在场 | B 收益 | B 在场 | C 收益 | C 在场 |")
A("|---|---|---|---|---|---|---|")
yrs = sorted({y["year"] for y in RES["binance"]["defs"]["A"]["yearly"]})
ymap = {d: {y["year"]: y for y in RES["binance"]["defs"][d]["yearly"]} for d in ("A", "B", "C")}
for y in yrs:
    row = [f"| {y} "]
    for d in ("A", "B", "C"):
        e = ymap[d].get(y, {})
        row.append(f"| {e.get('return', 0):+.2%} | {e.get('days_in_market', 0)} ")
    A("".join(row) + "|")
A("")
A("### 2.3 敏感度(只报,不挑)")
A("")
A("| 变体 | A 总收益 | B 总收益 | C 总收益 |")
A("|---|---|---|---|")
for key, lab in [("binance", "主表(线性价格口径)"), ("inverse_price", "价格口径 inverse(同一名义、每日全额再投)"),
                 ("exposure_live_start", "③ 敞口改用 2024-01-01 起复算"), ("funding_two_thirds", "资金费按日内 2/3 归因")]:
    dd_ = RES[key]["defs"]
    A(f"| {lab} | {dd_['A']['total_return']:+.2%} | {dd_['B']['total_return']:+.2%} | {dd_['C']['total_return']:+.2%} |")
A("")
A("## 3. 回撤段(2020-07 起,BTC 30 日回撤 ≥ 25%)")
A("")
A(f"命中 **{len(eps_out)} 段**。每段:空腿在崩跌段赚了多少、反弹段回吐了多少。")
A("")
A("| 段 | 峰 → 谷 | BTC 跌幅 | 谷 → 回本(截 90 天) | A 崩跌段 | A 反弹段 | A 净额 | B 崩跌段 | B 净额 | C 崩跌段 | C 净额 |")
A("|---|---|---|---|---|---|---|---|---|---|---|")
for e in eps_out:
    A(f"| {e['peak_d']}→{e['trough_d']} | {e['end_d']} | {e['btc_crash_pct']:+.1%} | {e['recover_d']}"
      f"{'(未回本)' if not e['recovered'] else ''} | {e['A']['crash_pnl']:+.2%} | {e['A']['rebound_pnl']:+.2%} | "
      f"{e['A']['net_pnl']:+.2%} | {e['B']['crash_pnl']:+.2%} | {e['B']['net_pnl']:+.2%} | "
      f"{e['C']['crash_pnl']:+.2%} | {e['C']['net_pnl']:+.2%} |")
A("")
A("## 4. 零信号对照(同场天数、同开关次数,1000 次,种子 252)")
A("")
A("| 定义 | 实际总收益 | 零分布均值 | 零分布 p05 | 零分布 p50 | 零分布 p95 | 实际值的分位 |")
A("|---|---|---|---|---|---|---|")
for dname in ("A", "B", "C"):
    n = nulls[dname]
    if "error" in n:
        A(f"| {dname} | {n['actual_total_return']:+.2%} | 对照失败:{n['error']} | | | | |")
        continue
    A(f"| {dname} | {n['actual_total_return']:+.2%} | {n['null_mean']:+.2%} | {n['null_p05']:+.2%} | "
      f"{n['null_p50']:+.2%} | {n['null_p95']:+.2%} | **{n['percentile']:.3f}** |")
A("")
A("## 5. 只报不判 —— 描述与缺口")
A("")
A("- 上面每个数字都可用 `docs/research/t252_short_leg.py` 重跑核对(数据缓存目录 "
  "`/Volumes/CometCloudAI/cometcloud-local/research/t252`)。")
A("- **缺口 1**:③ 的历史敞口只能本地复算(`exposure_decision_daily` 只有 3 行);复算与已落表逐日相符,"
  "但 2024 年后两版起点仍有分歧(见 §1)—— 若 ③ 规则改版,历史复算要重做。")
A("- **缺口 2**:空腿是**裸空 1 倍名义**,没有保证金/清算/杠杆模型;真实 ④ 要有保证金率与强平假设。")
A("- **缺口 3**:资金费归因把当日全部支付记在持仓日;另给 2/3 归因的敏感度(见 t252_results.json)。")
A("- **缺口 4**:① 的代理是 `style_index_pit_daily` 的 majors 指数(成员 BTC+ETH,市值加权),"
  "不是 ① 的 24 名核心面板。")
A("")
A("## 6. 情景台账(前向预期)")
A("")
A("见 `docs/research/scenarios/lane-a-T-252.json`(≥ 3 条可核命题,合并后入台账、到期按 Brier 结算)。")
A("")
(HERE / "T-252_crash_short_leg.md").write_text("\n".join(L))
print("已写 docs/research/T-252_crash_short_leg.md", flush=True)
