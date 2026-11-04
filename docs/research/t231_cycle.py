#!/usr/bin/env python3
"""T-231 · S-713 回放:⓪ 周期向量的 turning 相位在 2020 起每段 ≥30% 回撤里亮不亮。

口径逐字照 S-713(预注册在 PROJECT_STATE.md「⓪ 周期向量」段与 tasks/T-231.json):
  · 闸门:`cycle_vector_daily` 行数 ≥ 2,000(表就是预注册口径,不自己重算向量);
  · 事件段:BTC 自滚动 200 日高点回撤 ≥ 30% 的每一段,峰到谷,机械切;
  · 规则 R:turning ⇒ 次日敞口 0.5,normal ⇒ 1.0;2020-01-01 → 2026-10-31;10bp × |Δ敞口|;
  · 判据:(b) 最大三段里 ≥ 2 段回撤相对浅 ≥ 15%;(c) 非事件段亮灯 ≤ 15%;(d) Calmar 过随机 95 分位。

只读(SELECT)。零分布 / 分位 / A-B 一律走 src/data/evaluation/apparatus.py。

用法:
    python3 docs/research/t231_cycle.py              # 跑;闸门没开就只出 BTC 段 + 校准,状态写 gate_failed
    python3 docs/research/t231_cycle.py --selftest   # 合成相位的冒烟测试(不是结果,只验代码跑得通)
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    ab_test,
    null_distribution,
    percentile_of,
)

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

# ── S-713 预注册常量 ────────────────────────────────────────────────────────────
WIN = 200            # 滚动高点窗口(交易日)
THR = -0.30          # 回撤阈值:≥ 30%
START, END = "2020-01-01", "2026-10-31"
GATE_ROWS = 2000     # cycle_vector_daily 闸门:行数
COST_BPS = 10.0      # 换手成本:10bp × |Δ敞口|
N_NULL = 1000        # 随机对照抽样次数
SEED = 713           # 种子(S-713 写死)
TURN_DET, TURN_SHIFT_PCT, EXIT_DET = -0.5, 0.75, 0.0
TURN_DAYS = 3        # 连续 3 天进相(S-713)
SHALLOW = 0.15       # (b) 相对浅 ≥ 15%
MAX_LIT = 0.15       # (c) 非事件段亮灯 ≤ 15%
NULL_PCTL = 0.95     # (d) Calmar 过随机 95 分位
SIGN = {"stable_supply_30d": 1, "fed_liq_60d": 1, "breadth": 1, "taker_buy": 1, "mom_60": 1,
        "funding": -1, "oi_chg": -1, "lend_apy": -1, "vratio": -1}


# ── 只读取数(翻页一律带 order=) ────────────────────────────────────────────────
def _rest(table: str, params: dict[str, Any], page: int = 1000) -> list[dict]:
    out: list[dict] = []
    lo = 0
    while True:
        q = dict(params)
        url = f"{URL}/rest/v1/{table}?" + urllib.parse.urlencode(q, safe="(),.*")
        req = urllib.request.Request(url, method="GET")
        req.add_header("apikey", KEY)
        req.add_header("Authorization", f"Bearer {KEY}")
        req.add_header("Accept", "application/json")
        req.add_header("Range", f"{lo}-{lo + page - 1}")
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode()
        rows = json.loads(body) if body else []
        out.extend(rows)
        if len(rows) < page:
            break
        lo += page
    return out


def load_btc() -> list[tuple[str, float]]:
    """BTC 现货收盘(ohlcv_daily, source=binance_hist, symbol=BTC),按 trade_date 升序。"""
    rows = _rest("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC",
                                 "source": "eq.binance_hist", "order": "trade_date.asc"})
    out = []
    for r in rows:
        c = r.get("close")
        if c is None:
            continue
        out.append((str(r.get("trade_date"))[:10], float(c)))
    out.sort(key=lambda x: x[0])
    return out


def load_cycle_vector() -> list[dict]:
    """⓪ 周期向量表(预注册口径):d / phase / deterioration / shift_pct / z。"""
    rows = _rest("cycle_vector_daily", {"select": "d,phase,deterioration,shift_pct,z,components",
                                         "order": "d.asc"})
    for r in rows:
        r["d"] = str(r.get("d"))[:10]
        for k in ("z", "components"):
            if isinstance(r.get(k), str):
                try:
                    r[k] = json.loads(r[k])
                except Exception:
                    r[k] = {}
        if not isinstance(r.get("z"), dict):
            r["z"] = {}
    return rows


# ── ② 事件段:BTC 自滚动 200 日高点回撤 ≥ 30%,峰到谷,机械切 ──────────────────
def rolling_max_idx(closes: list[float], win: int) -> list[Optional[int]]:
    """每个 i:窗口 [i-win+1, i] 内最大值所在的索引(并列取最近)。"""
    from collections import deque

    dq: deque[int] = deque()
    out: list[Optional[int]] = []
    for i, c in enumerate(closes):
        while dq and closes[dq[-1]] <= c:
            dq.pop()
        dq.append(i)
        while dq[0] < i - win + 1:
            dq.popleft()
        out.append(dq[0])
    return out


def drawdown_segments(dates: list[str], closes: list[float]) -> list[dict]:
    """机械切:连续满足 dd ≤ −30% 的日子为一段。段峰 = 滚动高点的锚日,段谷 = 段内最低收盘。"""
    mi = rolling_max_idx(closes, WIN)
    segs: list[dict] = []
    i = 0
    n = len(closes)
    while i < n:
        peak_i = mi[i]
        dd = closes[i] / closes[peak_i] - 1.0 if peak_i is not None else 0.0
        if dd <= THR:
            j = i
            while j + 1 < n:
                pj = mi[j + 1]
                d2 = closes[j + 1] / closes[pj] - 1.0 if pj is not None else 0.0
                if d2 <= THR:
                    j += 1
                else:
                    break
            peak_i = mi[i]
            trough_rel = min(range(i, j + 1), key=lambda k: closes[k])
            segs.append({
                "seg_start": dates[i], "seg_end": dates[j],
                "peak_date": dates[peak_i], "peak_close": round(closes[peak_i], 2),
                "trough_date": dates[trough_rel], "trough_close": round(closes[trough_rel], 2),
                "depth": round(closes[trough_rel] / closes[peak_i] - 1.0, 4),
                "n_days": j - i + 1,
                "_i0": i, "_i1": j, "_peak_i": peak_i, "_trough_i": trough_rel,
            })
            i = j + 1
        else:
            i += 1
    return segs


# ── 规则 R 的收益路径 ──────────────────────────────────────────────────────────
def path_stats(dates: list[str], rets: list[float], expo: list[float], cost_bps: float = COST_BPS) -> dict:
    """给定日收益与每日敞口 → 总收益 / MDD / Calmar。成本 = cost_bps × |Δ敞口|(万分比)。"""
    wealth = 1.0
    peak = 1.0
    mdd = 0.0
    prev_e = expo[0] if expo else 1.0
    for r, e in zip(rets, expo):
        c = cost_bps / 1e4 * abs(e - prev_e)
        wealth *= (1.0 + e * r - c)
        peak = max(peak, wealth)
        if peak > 0:
            mdd = max(mdd, 1.0 - wealth / peak)
        prev_e = e
    total = wealth - 1.0
    years = len(rets) / 365.0 if rets else 0.0
    ann = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 and total > -1 else float("nan")
    calmar = ann / mdd if mdd > 1e-12 and years > 0 else None
    return {"total_return": round(total, 4), "mdd": round(mdd, 4),
            "ann_return": None if math.isnan(ann) else round(ann, 4),
            "calmar": None if calmar is None else round(calmar, 4), "n_days": len(rets)}


def segment_path(dates: list[str], closes: list[float], i0: int, i1: int,
                 expo: list[float]) -> dict:
    """段内回撤(峰 → 谷):从段峰收盘起算,按敞口逐日走,算 MDD。"""
    wealth, peak, mdd = 1.0, 1.0, 0.0
    prev_e = expo[i0] if i0 < len(expo) else 1.0
    for i in range(i0 + 1, i1 + 1):
        r = closes[i] / closes[i - 1] - 1.0
        e = expo[i]
        c = COST_BPS / 1e4 * abs(e - prev_e)
        wealth *= (1.0 + e * r - c)
        peak = max(peak, wealth)
        if peak > 0:
            mdd = max(mdd, 1.0 - wealth / peak)
        prev_e = e
    return {"mdd": round(mdd, 4)}


# ── 相位规则(与 src/data/state/cycle_vector.py 的 zscores() 同一条状态机) ──────
def derive_phase(days: list[str], det: dict[str, Optional[float]], pct: dict[str, Optional[float]],
                 turn_days: int = TURN_DAYS) -> dict[str, str]:
    """hit = 恶化 ≤ −0.5 且搬家分位 ≥ 0.75;连续 turn_days 天 ⇒ turning;恶化回到 > 0 ⇒ normal。"""
    phase: dict[str, str] = {}
    state, streak = "normal", 0
    for d in days:
        x, p = det.get(d), pct.get(d)
        if x is None or p is None:
            phase[d] = state
            continue
        hit = x <= TURN_DET and p >= TURN_SHIFT_PCT
        streak = streak + 1 if hit else 0
        if state == "normal" and streak >= turn_days:
            state = "turning"
        elif state == "turning" and x > EXIT_DET:
            state, streak = "normal", 0
        phase[d] = state
    return phase


def det_from_z(z: dict[str, Any], drop: Optional[str] = None) -> Optional[float]:
    """用表里的 z 自己重组恶化分(去某个分量时,只在该分量上少一项)。"""
    vals = []
    for k, v in (z or {}).items():
        if k not in SIGN or (drop and k == drop):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        vals.append(SIGN[k] * fv)
    if not vals:
        return None
    return sum(vals) / len(vals)


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def in_window_segments(dates: list[str], closes: list[float]) -> tuple[list[dict], list[dict]]:
    """窗口内的事件段。主口径:段的**起始日**(第一次跌破 −30% 那天)落在 2020-01-01 → 2026-10-31。
    副口径(敏感性):段与窗口有任何重叠就算(多出 2019-11 → 2020-01-13 那一段)。"""
    allsegs = drawdown_segments(dates, closes)
    primary = [s for s in allsegs if START <= s["seg_start"] <= END]
    alt = [s for s in allsegs if s["seg_end"] >= START and s["seg_start"] <= END]
    return primary, alt


def calibration_rows(segs: list[dict]) -> list[dict]:
    """(b) 的机械上界:规则 R 把亮灯日的跌幅砍一半 ⇒ 段内回撤相对浅 15% 需要亮灯日承担段内跌幅的多少份额。
    一阶近似(log 口径:亮灯日的下跌只付一半)。"""
    rows = []
    for s in sorted(segs, key=lambda x: x["depth"]):
        mdd_hold = abs(s["depth"])
        l_hold = -math.log(max(1.0 - mdd_hold, 1e-9))
        l_rmax = -math.log(max(1.0 - mdd_hold * (1.0 - SHALLOW), 1e-9))
        need_t = max(0.0, (l_hold - l_rmax) / 0.5)
        rows.append({
            "peak_date": s["peak_date"], "trough_date": s["trough_date"],
            "seg_start": s["seg_start"], "seg_end": s["seg_end"],
            "depth": s["depth"], "n_days": s["n_days"],
            "need_turn_loss_share_for_15pct": round(min(1.0, need_t / l_hold), 3) if l_hold > 1e-12 else None,
            "max_rel_shallower_possible": 0.5,
        })
    return rows


def build(btc: list[tuple[str, float]], cv: list[dict], phase_override: Optional[dict[str, str]] = None) -> dict:
    dates = [d for d, _ in btc]
    closes = [c for _, c in btc]
    idx = {d: i for i, d in enumerate(dates)}

    segs, segs_alt = in_window_segments(dates, closes)
    calib = {(r["peak_date"], r["seg_start"]): r for r in calibration_rows(segs)}

    # 窗口内的日子
    w = [(i, dates[i]) for i in range(len(dates)) if START <= dates[i] <= END]
    if not w:
        raise SystemExit("窗口内没有 BTC 收盘")
    i_start, i_end = w[0][0], w[-1][0]

    # 相位 → 敞口(turning ⇒ 次日敞口 0.5)
    if phase_override is not None:
        phase = phase_override
    else:
        phase = {r["d"]: (r.get("phase") or "normal") for r in cv}
    expo = [1.0] * len(dates)
    for i, d in enumerate(dates):
        prev = dates[i - 1] if i > 0 else None
        if prev is not None and phase.get(prev) == "turning":
            expo[i] = 0.5

    # 事件段里的日子 / 非事件段的日子
    in_event = set()
    for s in segs:
        for i in range(s["_i0"], s["_i1"] + 1):
            in_event.add(i)
    non_event_idx = [i for i, _ in w if i not in in_event]

    # ①/② (a) 每段 turning 占比
    a_rows = []
    for s in sorted(segs, key=lambda x: x["depth"]):
        days_in = [dates[i] for i in range(s["_i0"], s["_i1"] + 1)]
        lit = sum(1 for i in range(s["_i0"], s["_i1"] + 1) if expo[i] < 1.0)
        p2t = list(range(s["_peak_i"], s["_trough_i"] + 1))
        lit_p2t = sum(1 for i in p2t if expo[i] < 1.0)
        # 段内跌幅里由亮灯日承担的份额(校准:规则 R 能削掉多少回撤)
        loss = 0.0
        loss_lit = 0.0
        for i in range(s["_peak_i"], s["_trough_i"] + 1):
            if i <= s["_peak_i"]:
                lr = 0.0
            else:
                lr = math.log(closes[i - 1] / closes[i])  # 正数 = 下跌
            loss += max(lr, 0.0)
            if expo[i] < 1.0:
                loss_lit += max(lr, 0.0)
        share = loss_lit / loss if loss > 1e-12 else None
        cb = calib.get((s["peak_date"], s["seg_start"]), {})
        a_rows.append({
            "peak_date": s["peak_date"], "trough_date": s["trough_date"],
            "seg_start": s["seg_start"], "seg_end": s["seg_end"],
            "depth": s["depth"], "n_days": s["n_days"],
            "turn_days": lit, "turn_share": round(lit / len(days_in), 3) if days_in else None,
            "turn_share_peak_to_trough": round(lit_p2t / len(p2t), 3) if p2t else None,
            "peak_to_trough_days": len(p2t),
            "loss_share_on_lit_days": None if share is None else round(share, 3),
            "need_turn_loss_share_for_15pct": cb.get("need_turn_loss_share_for_15pct"),
        })

    # (b) 最大三段:段内回撤相对浅多少
    top3 = sorted(segs, key=lambda x: x["depth"])[:3]
    b_rows = []
    for s in top3:
        mdd_hold = abs(s["depth"])
        sr = segment_path(dates, closes, s["_peak_i"], s["_trough_i"], expo)
        mdd_r = sr["mdd"]
        rel = (mdd_hold - mdd_r) / mdd_hold if mdd_hold > 1e-12 else None
        b_rows.append({"peak_date": s["peak_date"], "trough_date": s["trough_date"],
                       "depth_hold": s["depth"], "mdd_hold": round(mdd_hold, 4),
                       "mdd_R": mdd_r,
                       "rel_shallower": None if rel is None else round(rel, 4),
                       "pass_15pct": bool(rel is not None and rel >= SHALLOW)})
    b_pass = sum(1 for r in b_rows if r["pass_15pct"]) >= 2

    # (c) 非事件段亮灯占比
    lit_ne = sum(1 for i in non_event_idx if expo[i] < 1.0)
    c_share = lit_ne / len(non_event_idx) if non_event_idx else None
    c_pass = c_share is not None and c_share <= MAX_LIT
    # 敏感性:副口径(段与窗口有任何重叠)下同一条
    in_event_alt = set()
    for s in segs_alt:
        for i in range(s["_i0"], s["_i1"] + 1):
            in_event_alt.add(i)
    ne_alt = [i for i, _ in w if i not in in_event_alt]
    c_share_alt = (sum(1 for i in ne_alt if expo[i] < 1.0) / len(ne_alt)) if ne_alt else None

    # (d) 全区间持有 vs R
    rets = []
    expo_w = []
    for i in range(i_start, i_end + 1):
        rets.append(closes[i] / closes[i - 1] - 1.0)
        expo_w.append(expo[i])
    hold = path_stats(dates, rets, [1.0] * len(rets))
    arm = path_stats(dates, rets, expo_w)

    # 随机对照:同样 turning 总天数、段长从实际抽
    lit_idx = [i for i in range(i_start, i_end + 1) if expo[i] < 1.0]
    runs: list[int] = []
    prev_lit: Optional[int] = None
    for i in lit_idx:
        if prev_lit is not None and i == prev_lit + 1:
            runs[-1] += 1
        else:
            runs.append(1)
        prev_lit = i
    non_lit_idx = [i for i in range(i_start, i_end + 1) if expo[i] >= 1.0]

    def shuffled_expo(rng) -> list[float]:
        """把 turning 的天按实际段长随机摊到非 turning 的日子里(总天数与段长都保持,段之间至少隔一天)。"""
        import numpy as np
        m = len(non_lit_idx)
        slots: list[Optional[int]] = list(non_lit_idx)
        if runs and m + 1 >= len(runs):
            gaps = sorted(int(g) for g in rng.choice(m + 1, size=len(runs), replace=False))
            merged: list[Optional[int]] = []
            prev = 0
            for g, L in zip(gaps, runs):
                merged.extend(slots[prev:g])
                merged.extend([None] * int(L))
                prev = g
            merged.extend(slots[prev:])
            slots = merged
        else:  # 兜底:非 turning 的日子不够放,直接随机撒
            for L in runs:
                g = int(rng.integers(0, len(slots) + 1))
                slots[g:g] = [None] * int(L)
        out = [1.0] * (i_end - i_start + 1)
        for pos, v in enumerate(slots[:len(out)]):
            out[pos] = 0.5 if v is None else expo[v]
        return out

    null_pctl = None
    null_note = None
    try:
        def _null(rng) -> float:
            st = path_stats(dates, rets, shuffled_expo(rng))
            return float(st["calmar"]) if st["calmar"] is not None else float("nan")

        null = null_distribution(_null, N_NULL, SEED, actual=arm["calmar"])
        null_pctl = percentile_of(arm["calmar"], null)
    except Exception as e:  # NoOpNull 等
        null_note = f"{type(e).__name__}: {e}"
    d_pass = null_pctl is not None and null_pctl > NULL_PCTL

    try:
        ab = ab_test(rets, [expo_w[k] * rets[k] for k in range(len(rets))], n_boot=2000, seed=SEED)
    except Exception as e:
        ab = {"error": f"{type(e).__name__}: {e}"}

    return {
        "window": {"start": dates[i_start], "end": dates[i_end], "n_days": len(rets)},
        "n_segments": len(segs),
        "segments": a_rows,
        "a_turn_share_by_segment": {r["peak_date"]: r["turn_share"] for r in a_rows},
        "b_top3": b_rows, "b_pass": b_pass,
        "c_non_event_lit_share": None if c_share is None else round(c_share, 4), "c_pass": c_pass,
        "c_non_event_lit_share_alt_reading": None if c_share_alt is None else round(c_share_alt, 4),
        "n_segments_alt_reading": len(segs_alt),
        "d_hold": hold, "d_R": arm, "d_null_calmar_pctl": null_pctl, "d_null_note": null_note,
        "d_pass": d_pass, "d_ab": ab,
        "turn_days_total": len(lit_idx),
        "verdict_all_pass": bool(b_pass and c_pass and d_pass),
    }


def selftest() -> None:
    """合成相位的冒烟测试:只验代码跑得通,结果不作数。"""
    btc = load_btc()
    dates = [d for d, _ in btc]
    closes = [c for _, c in btc]
    segs = drawdown_segments(dates, closes)
    ph = {}
    for d in dates:
        ph[d] = "turning" if d in {s["seg_start"] for s in segs} else "normal"
    out = build(btc, [], phase_override=ph)
    print("SELFTEST(合成相位,不是结果):")
    print(json.dumps({k: out[k] for k in ("n_segments", "b_pass", "c_non_event_lit_share",
                                         "c_pass", "d_hold", "d_R", "d_null_calmar_pctl", "d_pass")},
                     ensure_ascii=False, indent=2))


def variants(btc: list[tuple[str, float]], cv: list[dict]) -> dict:
    """⑤ 副列(只报不判):去 Fed 分量 / 去资金费分量 / TURN_DAYS 1 / 5。"""
    days = [r["d"] for r in cv]
    pct = {r["d"]: r.get("shift_pct") for r in cv}
    det_tab = {r["d"]: r.get("deterioration") for r in cv}
    det_nofed = {r["d"]: det_from_z(r.get("z") or {}, drop="fed_liq_60d") for r in cv}
    det_nofun = {r["d"]: det_from_z(r.get("z") or {}, drop="funding") for r in cv}

    def run(name: str, det: dict, td: int) -> dict:
        ph = derive_phase(days, det, pct, turn_days=td)
        res = build(btc, cv, phase_override=ph)
        return {"variant": name, "turn_days": td,
                "b_pass": res["b_pass"], "c_non_event_lit_share": res["c_non_event_lit_share"],
                "c_pass": res["c_pass"], "d_R_calmar": res["d_R"]["calmar"],
                "d_null_calmar_pctl": res["d_null_calmar_pctl"], "d_pass": res["d_pass"],
                "turn_days_total": res["turn_days_total"]}

    return {
        "note": "只报不判;规则不变(恶化 ≤ −0.5 且搬家分位 ≥ 0.75,连续 N 天进相,恶化 > 0 出相)",
        "rows": [
            run("baseline(表里的 phase)", det_tab, TURN_DAYS),
            run("去 Fed 分量", det_nofed, TURN_DAYS),
            run("去资金费分量", det_nofun, TURN_DAYS),
            run("TURN_DAYS=1", det_tab, 1),
            run("TURN_DAYS=5", det_tab, 5),
        ],
    }


def main() -> None:
    if "--selftest" in sys.argv:
        selftest()
        return
    btc = load_btc()
    cv = load_cycle_vector()
    out: dict[str, Any] = {
        "card": "T-231",
        "prereg": "S-713(PROJECT_STATE.md 11-04 · tasks/T-231.json)",
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "data": {
            "btc_rows": len(btc),
            "btc_first": btc[0][0] if btc else None,
            "btc_last": btc[-1][0] if btc else None,
            "btc_last_close": btc[-1][1] if btc else None,
            "cycle_vector_rows": len(cv),
            "cycle_vector_first": cv[0]["d"] if cv else None,
            "cycle_vector_last": cv[-1]["d"] if cv else None,
            "cycle_vector_turning_rows": sum(1 for r in cv if r.get("phase") == "turning"),
        },
        "gate": {"required_rows": GATE_ROWS, "actual_rows": len(cv),
                 "passed": len(cv) >= GATE_ROWS},
    }
    if len(cv) >= GATE_ROWS:
        out["status"] = "computed"
        out.update(build(btc, cv))
        out["sub_columns"] = variants(btc, cv)
    else:
        # 闸门没开:只出与相位无关的 ② 事件段与 (b) 的校准
        out["status"] = "gate_failed"
        out["why"] = (f"cycle_vector_daily 只有 {len(cv)} 行(要求 ≥ {GATE_ROWS});"
                      "⓪ 管道未落地 → (a)(b)(c)(d) 不能判,只出 BTC 事件段与校准")
        dates = [d for d, _ in btc]
        closes = [c for _, c in btc]
        segs, segs_alt = in_window_segments(dates, closes)
        out["segments"] = [{
            "peak_date": s["peak_date"], "trough_date": s["trough_date"],
            "seg_start": s["seg_start"], "seg_end": s["seg_end"],
            "depth": s["depth"], "n_days": s["n_days"],
        } for s in sorted(segs, key=lambda x: x["depth"])]
        out["segments_top3_depth"] = [s["peak_date"] for s in sorted(segs, key=lambda x: x["depth"])[:3]]
        out["n_segments_alt_reading"] = len(segs_alt)
        out["calibration"] = {
            "note": ("(b) 的机械上界:规则 R 把亮灯日的跌幅砍一半 ⇒ 段内回撤相对浅 15% 需要亮灯日承担段内跌幅的这份份额"
                     "(一阶近似,log 口径)"),
            "rows": calibration_rows(segs),
        }
    dest = Path(__file__).resolve().parent / "t231_results.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "gate": out["gate"],
                      "n_segments": out.get("n_segments", len(out.get("segments", []))),
                      "dest": str(dest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
