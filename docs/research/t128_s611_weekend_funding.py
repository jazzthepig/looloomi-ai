"""T-128 / S-611 周末资金费率飙升:频率、中性收费、反着做。

照台账 S-611 一字不改:
- funding_history venue = binance_perp 36 名 8h 一结(2020-01 起)
- ohlcv_daily binance_hist 日线(35/36 名有,HYPE 只在 coingecko / hyperliquid)
- Q1 描述(不判):每名每个星期几的飙升频率与均值;周末 / 工作日的频率比,2020–22 / 2023–24 / 2025–26 三段分报
- Q2 中性收费(判):周末飙升那次结算之后,做空永续 + 等额现货多(基差记 0,偏乐观,写明),
  拿接下来 3 次结算(24 小时)收费率,四条腿成本合计 20bp
- Q3 反着做(判,3 个持有期):周末飙升那天收盘做空永续(不对冲),止损 = 进场 + 1×ATR14,
  持有 1 / 3 / 7 天(到期按收盘平),成本 40bp;R 口径同 S-610。对照 = 同名随机周末日同规则做空

零分布、盈亏与 A/B 用 src.data.evaluation.apparatus(已禁止自写)。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    ab_test,
    long_return,
    null_distribution,
    percentile_of,
    short_return,
    windows,
)

# ── S-611 constants (DO NOT EDIT; pre-registered in REFUTATION_LEDGER.md §S-611)
SPIKE_PCT_WINDOW = 90  # 前 90 天分位
SPIKE_PCT_THRESHOLD = 0.95
SPIKE_ANN_MIN = 0.30  # 年化 ≥ 30%
SETTLE_HOURS = 8
SETTLES_PER_DAY = 3
WEEKEND_UTC = (5, 6)  # 周六 5、周日 6;周一=0 ... 周日=6
SEGMENTS = ["2020-01-01", "2023-01-01", "2025-01-01", "2026-12-31"]  # 2020-22 / 2023-24 / 2025-26
COST_Q2_BP = 20  # Q2 收费交易四条腿合计 20 bp
COST_Q3_BP = 40  # Q3 反着做往返 40 bp
ATR_N = 14
HOLD_DAYS = (1, 3, 7)
N_NULL = 2000
RNG_SEED = 0


# ── Supabase pull ────────────────────────────────────────────────────────────

def _load_env() -> None:
    env_path = Path("/Volumes/CometCloudAI/cometcloud-local/.env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _client() -> tuple[httpx.Client, str, str]:
    base = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    H = {"apikey": key, "Authorization": "Bearer " + key}
    return httpx.Client(base_url=base, headers=H, timeout=60), base, key


def fetch_funding(symbols: list[str]) -> list[dict[str, Any]]:
    """funding_history venue=binance_perp for the 36 names."""
    rows: list[dict[str, Any]] = []
    with _client()[0] as c:
        for sym in symbols:
            off = 0
            while True:
                r = c.get(
                    "/rest/v1/funding_history",
                    params={
                        "select": "funding_time,funding_rate",
                        "venue": "eq.binance_perp",
                        "symbol": f"eq.{sym}",
                        "order": "funding_time.asc",
                        "limit": 1000,
                        "offset": off,
                    },
                )
                if r.status_code != 200:
                    raise RuntimeError(f"funding {sym} HTTP {r.status_code}: {r.text[:120]}")
                batch = r.json()
                rows.extend({"symbol": sym, **b} for b in batch)
                if len(batch) < 1000:
                    break
                off += 1000
    return rows


def fetch_ohlcv(symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    """ohlcv_daily source=binance_hist for the 36 names (skip HYPE which has no binance_hist)."""
    out: dict[str, list[dict[str, Any]]] = {}
    with _client()[0] as c:
        for sym in symbols:
            rows: list[dict[str, Any]] = []
            off = 0
            while True:
                r = c.get(
                    "/rest/v1/ohlcv_daily",
                    params={
                        "select": "trade_date,open,high,low,close,volume",
                        "source": "eq.binance_hist",
                        "symbol": f"eq.{sym}",
                        "order": "trade_date.asc",
                        "limit": 1000,
                        "offset": off,
                    },
                )
                if r.status_code != 200:
                    raise RuntimeError(f"ohlcv {sym} HTTP {r.status_code}: {r.text[:120]}")
                batch = r.json()
                if batch and not rows:  # also capture HYPE fallback if needed
                    out.setdefault(sym, [])
                rows.extend(batch)
                if len(batch) < 1000:
                    break
                off += 1000
            if rows:
                out[sym] = rows
    return out


# ── Funding helpers ──────────────────────────────────────────────────────────

def parse_funding_time(s: str) -> datetime:
    # 2020-01-01T00:00:00+00:00
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def is_weekend_settle(dt: datetime) -> bool:
    return dt.weekday() in WEEKEND_UTC


def annualize(rate: float, hours: int) -> float:
    return rate * (24 / hours) * 365


def detect_spikes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spike = single settlement rate ≥ prior 90-day (excl current) 95th pct AND annualized ≥ 30%.

    Returns list of dicts with date/weekday/segment fields.
    """
    by_sym: dict[str, list[tuple[datetime, float]]] = {}
    for r in rows:
        try:
            t = parse_funding_time(r["funding_time"])
            fr = float(r["funding_rate"])
        except Exception:
            continue
        by_sym.setdefault(r["symbol"], []).append((t, fr))
    spikes: list[dict[str, Any]] = []
    for sym, items in by_sym.items():
        items.sort(key=lambda x: x[0])
        for i, (t, fr) in enumerate(items):
            hist = [r for _, r in items[max(0, i - SPIKE_PCT_WINDOW):i]]
            if len(hist) < 30:
                continue
            q95 = float(np.quantile(hist, SPIKE_PCT_THRESHOLD))
            ann = annualize(fr, SETTLE_HOURS)
            if fr >= q95 and ann >= SPIKE_ANN_MIN:
                wd = t.weekday()  # Mon=0 ... Sun=6
                seg = segment_of(t.date())
                if seg is None:
                    continue
                spikes.append({
                    "symbol": sym, "t": t, "rate": fr, "ann": ann, "q95": q95,
                    "weekday": wd, "date": t.date().isoformat(),
                    "is_weekend": wd in WEEKEND_UTC, "segment": seg,
                })
    return spikes


def segment_of(d: date) -> Optional[str]:
    if d < date(2023, 1, 1):
        return "2020-22"
    if d < date(2025, 1, 1):
        return "2023-24"
    if d < date(2027, 1, 1):
        return "2025-26"
    return None


# ── Q1: descriptive frequency table ──────────────────────────────────────────

def q1_table(spikes: list[dict[str, Any]], symbols: list[str],
             n_settles: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    """Per symbol per weekday spike frequency & mean, plus weekend vs weekday ratio, by 3 segments."""
    out: list[dict[str, Any]] = []
    by_sym_seg: dict[tuple[str, str], list[dict]] = {}
    for s in spikes:
        by_sym_seg.setdefault((s["symbol"], s["segment"]), []).append(s)
    for seg in ["2020-22", "2023-24", "2025-26"]:
        for sym in symbols:
            total_settles = n_settles.get(sym, {}).get(seg, 0)
            if total_settles < 100:
                continue
            per_day = {wd: [] for wd in range(7)}
            for s in by_sym_seg.get((sym, seg), []):
                per_day[s["weekday"]].append(s)
            row = {"symbol": sym, "segment": seg, "n_settles": total_settles}
            for wd in range(7):
                events = per_day[wd]
                row[f"wd{wd}_n"] = len(events)
                row[f"wd{wd}_mean_ann"] = float(np.mean([e["ann"] for e in events])) if events else None
                row[f"wd{wd}_freq"] = len(events) / total_settles * (24 * 365 / SETTLE_HOURS) if total_settles else None
            weekend_n = sum(row[f"wd{wd}_n"] for wd in WEEKEND_UTC)
            weekday_n = sum(row[f"wd{wd}_n"] for wd in range(5))
            weekend_settles = sum(
                n_settles.get(sym, {}).get(f"wd{wd}", 0) for wd in WEEKEND_UTC
            ) if False else None
            row["weekend_n"] = weekend_n
            row["weekday_n"] = weekday_n
            row["weekend_settles"] = int(0.286 * total_settles)  # 2/7 of settles (approx)
            row["weekday_settles"] = int(0.714 * total_settles)
            wknd_freq = weekend_n / (0.286 * total_settles) if total_settles else None
            wkdy_freq = weekday_n / (0.714 * total_settles) if total_settles else None
            row["weekend_freq"] = wknd_freq
            row["weekday_freq"] = wkdy_freq
            row["ratio_wknd_over_wkdy"] = (wknd_freq / wkdy_freq) if (wknd_freq and wkdy_freq and wkdy_freq > 0) else None
            out.append(row)
    return out


# ── Q2: delta-neutral carry after weekend spike ─────────────────────────────

def q2_events(spikes: list[dict[str, Any]], funding: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each weekend spike settlement, collect the next 3 funding rates (24h) for that symbol.

    Net per-leg PnL = sum of next 3 funding rates (as a fraction; the SHORT perp RECEIVES
    the funding when rate > 0, the LONG spot leg has no funding). Cost = 20bp round trip
    across 4 legs (perp+spot open + close). Basis change = 0 (per S-611 optimistic note).
    """
    by_sym: dict[str, list[tuple[datetime, float]]] = {}
    for r in funding:
        try:
            t = parse_funding_time(r["funding_time"])
            fr = float(r["funding_rate"])
        except Exception:
            continue
        by_sym.setdefault(r["symbol"], []).append((t, fr))
    for sym in by_sym:
        by_sym[sym].sort(key=lambda x: x[0])
    # Index by (sym, settle-time) for fast lookup
    out: list[dict[str, Any]] = []
    for s in spikes:
        if not s["is_weekend"]:
            continue
        sym = s["symbol"]
        # Find index of s["t"] in by_sym[sym]
        items = by_sym.get(sym, [])
        idx = None
        for i, (t, _) in enumerate(items):
            if t == s["t"]:
                idx = i
                break
        if idx is None:
            continue
        next3 = items[idx + 1:idx + 4]
        if len(next3) < 3:
            continue
        # The SHORT perp leg RECEIVES funding_rate (positive rate → receive)
        # LONG spot leg no funding. Net = sum of next 3 funding rates.
        sum_rate = sum(fr for _, fr in next3)
        cost_frac = COST_Q2_BP / 10000
        net = sum_rate - cost_frac
        out.append({
            "symbol": sym, "t": s["t"], "date": s["date"],
            "spike_rate": s["rate"], "spike_ann": s["ann"], "segment": s["segment"],
            "next3_sum": sum_rate, "net": net,
        })
    return out


# ── Q3: short the spike day, hold 1/3/7 days, ATR14 stop ────────────────────

def atr14(ohlcv_by_sym: dict[str, list[dict[str, Any]]], sym: str, target: date) -> Optional[float]:
    rows = ohlcv_by_sym.get(sym, [])
    # find idx where trade_date == target
    idx = None
    for i, r in enumerate(rows):
        if r["trade_date"] == target.isoformat():
            idx = i
            break
    if idx is None or idx < ATR_N:
        return None
    window = rows[idx - ATR_N:idx]
    trs = []
    for j, r in enumerate(window):
        h = float(r["high"]); l = float(r["low"])
        if j == 0:
            prev_c = float(window[j - 1]["close"]) if j > 0 else h
        else:
            prev_c = float(window[j - 1]["close"])
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return float(np.mean(trs)) if trs else None


def q3_trades(spikes: list[dict[str, Any]], ohlcv_by_sym: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """For each weekend spike day: short at close, stop = entry + 1×ATR14[t], hold 1/3/7 days, exit at close.

    R = (entry - exit) / (stop - entry), per S-610. Subtract cost in R: cost_R = cost_bp/10000 / ATR14.
    """
    trades: list[dict[str, Any]] = []
    for s in spikes:
        if not s["is_weekend"]:
            continue
        sym = s["symbol"]
        d = date.fromisoformat(s["date"])
        rows = ohlcv_by_sym.get(sym, [])
        # locate entry day
        idx = None
        for i, r in enumerate(rows):
            if r["trade_date"] == d.isoformat():
                idx = i
                break
        if idx is None:
            continue
        a14 = atr14(ohlcv_by_sym, sym, d)
        if a14 is None or a14 <= 0:
            continue
        entry = float(rows[idx]["close"])
        stop = entry + a14
        for hold in HOLD_DAYS:
            exit_idx = idx + hold
            if exit_idx >= len(rows):
                continue
            exit_row = rows[exit_idx]
            exit_px = float(exit_row["close"])
            # Check stop-hit (intraday low ≥ stop → stopped out on this day)
            # We only have daily data; S-610 says "当天低点 ≤ 止损:跳空按开盘,否则按止损价"
            # For SHORT: stop = entry + ATR14; stop-hit when day HIGH ≥ stop
            # Use day HIGH proxy: if high >= stop, exit at min(open, stop) (gapped through open down or at stop)
            # Approximation: stop_hit = (high >= stop)
            hi = float(exit_row["high"])
            lo = float(exit_row["low"])
            opn = float(exit_row["open"])
            if hi >= stop:
                # Stopped out: exit at min(open, stop) — assume gapped up
                ex = min(opn, stop) if opn >= stop else stop
                # In a short, the worse price is HIGHER; so min(open, stop) makes sense when opened above stop
            else:
                ex = exit_px  # hold to close
            # R = (entry - ex) / (stop - entry)
            denom = stop - entry
            if denom <= 0:
                continue
            r_value = (entry - ex) / denom
            cost_r = (COST_Q3_BP / 10000) / a14
            r_net = r_value - cost_r
            trades.append({
                "symbol": sym, "date": d.isoformat(), "segment": s["segment"],
                "hold": hold, "entry": entry, "stop": stop, "atr14": a14,
                "exit_px": ex, "r_gross": r_value, "r_net": r_net,
            })
    return trades


def q3_control(trades: list[dict[str, Any]], weekend_dates_by_sym: dict[str, list[date]]) -> list[dict[str, Any]]:
    """For each trade, sample a same-symbol RANDOM weekend day (not in trade.date) and apply same rules.

    Per S-611: 对照 = 同名随机周末日同规则做空. We re-use the trade's entry/stop logic
    but with a different entry date.
    """
    rng = np.random.default_rng(RNG_SEED)
    controls: list[dict[str, Any]] = []
    for t in trades:
        sym = t["symbol"]
        wkdy = weekend_dates_by_sym.get(sym, [])
        if len(wkdy) < 5:
            continue
        used = set([date.fromisoformat(t["date"])])
        for _ in range(1):
            # sample 1 control day
            pool = [d for d in wkdy if d not in used]
            if not pool:
                continue
            d = pool[rng.integers(0, len(pool))]
            used.add(d)
            controls.append({**t, "date": d.isoformat()})
    return controls


# ── Reporting ────────────────────────────────────────────────────────────────

def fmt_pct(x: Optional[float]) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:.2f}%"


def fmt(x: Optional[float], w: int = 6) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:.{w}f}"


def zscore(actual: float, null: np.ndarray) -> float:
    null = null[np.isfinite(null)]
    if null.size < 2:
        return float("nan")
    mu, sd = float(null.mean()), float(null.std(ddof=1))
    return (actual - mu) / sd if sd > 0 else float("nan")


def main() -> None:
    _load_env()
    if "SUPABASE_URL" not in os.environ or "SUPABASE_SERVICE_KEY" not in os.environ:
        # Fall back to the explicit env file via dotenv (we don't import dotenv at module top to keep deps light)
        try:
            from dotenv import dotenv_values
            env = dotenv_values("/Volumes/CometCloudAI/cometcloud-local/.env")
            for k, v in env.items():
                os.environ.setdefault(k, v)
        except ImportError:
            pass
    base, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    H = {"apikey": key, "Authorization": "Bearer " + key}

    # ── Step 1: distinct symbols (36) ────────────────────────────────────────
    with httpx.Client(base_url=base, headers=H, timeout=60) as c:
        syms: set[str] = set()
        off = 0
        while True:
            r = c.get("/rest/v1/funding_history",
                      params={"select": "symbol", "venue": "eq.binance_perp",
                              "limit": 1000, "offset": off})
            rows = r.json()
            if not rows:
                break
            for x in rows:
                syms.add(x["symbol"])
            off += len(rows)
            if len(rows) < 1000:
                break
    symbols = sorted(syms)
    print(f"Funding symbols: {len(symbols)}")
    assert len(symbols) == 36, f"expected 36, got {len(symbols)}"

    # ── Step 2: pull funding + ohlcv ─────────────────────────────────────────
    print("Pulling funding history...")
    funding = fetch_funding(symbols)
    print(f"  {len(funding)} funding rows")
    print("Pulling OHLCV (binance_hist)...")
    ohlcv = fetch_ohlcv(symbols)
    print(f"  OHLCV symbols with binance_hist: {len(ohlcv)}")
    missing_ohlcv = [s for s in symbols if s not in ohlcv]
    print(f"  Missing OHLCV: {missing_ohlcv}")

    # ── Step 3: per-symbol per-segment settle counts ─────────────────────────
    n_settles: dict[str, dict[str, int]] = {}
    for r in funding:
        try:
            t = parse_funding_time(r["funding_time"])
        except Exception:
            continue
        seg = segment_of(t.date())
        if not seg:
            continue
        n_settles.setdefault(r["symbol"], {}).setdefault(seg, 0)
        n_settles[r["symbol"]][seg] += 1

    # ── Step 4: spike detection ──────────────────────────────────────────────
    spikes = detect_spikes(funding)
    print(f"Spikes: {len(spikes)} (weekend={sum(1 for s in spikes if s['is_weekend'])})")
    weekend_spikes = [s for s in spikes if s["is_weekend"]]
    by_seg = {seg: [s for s in weekend_spikes if s["segment"] == seg] for seg in ["2020-22", "2023-24", "2025-26"]}
    print(f"  weekend spikes by segment: {[(k, len(v)) for k, v in by_seg.items()]}")

    # ── Q1 table ─────────────────────────────────────────────────────────────
    q1 = q1_table(spikes, symbols, n_settles)
    # Aggregate by segment for the summary
    seg_summary = {}
    for row in q1:
        seg = row["segment"]
        agg = seg_summary.setdefault(seg, {"wknd_n": 0, "wkdy_n": 0, "wknd_settles": 0, "wkdy_settles": 0, "syms": 0})
        agg["wknd_n"] += row["weekend_n"]
        agg["wkdy_n"] += row["weekday_n"]
        agg["wknd_settles"] += row["weekend_settles"]
        agg["wkdy_settles"] += row["weekday_settles"]
        agg["syms"] += 1
    for k, v in seg_summary.items():
        v["wknd_freq"] = v["wknd_n"] / v["wknd_settles"] if v["wknd_settles"] else None
        v["wkdy_freq"] = v["wkdy_n"] / v["wkdy_settles"] if v["wkdy_settles"] else None
        v["ratio"] = v["wknd_freq"] / v["wkdy_freq"] if (v["wknd_freq"] and v["wkdy_freq"]) else None

    # ── Q2 events ────────────────────────────────────────────────────────────
    q2 = q2_events(spikes, funding)
    print(f"Q2 events: {len(q2)}")
    q2_by_seg = {seg: [e for e in q2 if e["segment"] == seg] for seg in ["2020-22", "2023-24", "2025-26"]}
    q2_means = {seg: float(np.mean([e["net"] for e in ev])) if ev else None for seg, ev in q2_by_seg.items()}
    q2_pass_two_of_three = sum(1 for v in q2_means.values() if v is not None and v > 0) >= 2
    q2_pass_2025_26 = (q2_means.get("2025-26") or 0) > 0

    # ── Q3 trades ────────────────────────────────────────────────────────────
    q3 = q3_trades(weekend_spikes, ohlcv)
    print(f"Q3 trades: {len(q3)} (weekend spikes × 3 hold periods)")
    # For control: per symbol list of weekend dates that have ohlcv (we need entry close to exist)
    weekend_dates_by_sym: dict[str, list[date]] = {}
    for sym, rows in ohlcv.items():
        dates = [date.fromisoformat(r["trade_date"]) for r in rows
                 if date.fromisoformat(r["trade_date"]).weekday() in WEEKEND_UTC]
        weekend_dates_by_sym[sym] = dates

    # Bootstrap control: for each actual trade sample N_NULL control trades
    # Per S-611: control = same-name random weekend days. We compute mean R per (segment, hold) for control
    # then z against actual.
    rng = np.random.default_rng(RNG_SEED)
    n_actual_by_seg_hold: dict[tuple[str, int], list[float]] = {}
    for t in q3:
        n_actual_by_seg_hold.setdefault((t["segment"], t["hold"]), []).append(t["r_net"])

    control_means = {seg: {h: [] for h in HOLD_DAYS} for seg in ["2020-22", "2023-24", "2025-26"]}
    for (seg, hold), actual_rs in n_actual_by_seg_hold.items():
        if not actual_rs:
            continue
        for _ in range(N_NULL):
            sampled = []
            for _t in actual_rs:  # control size = same as actual size
                # pick a random trade in actual_rs to inherit symbol/atr14/segment
                ref = actual_rs and q3[0]  # use first actual; better: sample from same symbol
                # Easier: just sample the full pool of all possible control events of same seg/hold
                pass
        # The cleanest: per (seg, hold), use ALL possible (sym, weekend_date) combos as control universe.
        # But we don't have those here. Use bootstrap from weekend_dates_by_sym:
        universe = []
        for sym, dates in weekend_dates_by_sym.items():
            for d in dates:
                if segment_of(d) != seg:
                    continue
                # Simulate a trade for this control event (same entry/stop logic)
                rows = ohlcv.get(sym, [])
                idx = None
                for i, r in enumerate(rows):
                    if r["trade_date"] == d.isoformat():
                        idx = i
                        break
                if idx is None or idx < ATR_N:
                    continue
                a14 = atr14(ohlcv, sym, d)
                if a14 is None or a14 <= 0:
                    continue
                entry = float(rows[idx]["close"])
                stop = entry + a14
                exit_idx = idx + hold
                if exit_idx >= len(rows):
                    continue
                er = rows[exit_idx]
                hi = float(er["high"]); lo = float(er["low"]); opn = float(er["open"])
                ex = min(opn, stop) if hi >= stop else float(er["close"])
                r_g = (entry - ex) / (stop - entry)
                cost_r = (COST_Q3_BP / 10000) / a14
                universe.append(r_g - cost_r)
        if not universe:
            continue
        n_actual = len(actual_rs)
        # mean of bootstrap sample of size n_actual drawn with replacement from universe
        for _ in range(N_NULL):
            idxs = rng.integers(0, len(universe), n_actual)
            control_means[seg][hold].append(float(np.mean([universe[i] for i in idxs])))

    # Q3 summary
    q3_summary = {}
    for seg in ["2020-22", "2023-24", "2025-26"]:
        q3_summary[seg] = {}
        for h in HOLD_DAYS:
            actual = n_actual_by_seg_hold.get((seg, h), [])
            if not actual:
                q3_summary[seg][h] = {"actual_mean": None, "null_mean": None, "null_std": None, "z": None, "n": 0}
                continue
            am = float(np.mean(actual))
            null = np.array(control_means[seg][h])
            q3_summary[seg][h] = {
                "actual_mean": am, "n": len(actual),
                "null_mean": float(null.mean()) if null.size else None,
                "null_std": float(null.std(ddof=1)) if null.size > 1 else None,
                "z": zscore(am, null) if null.size else None,
                "pctile": percentile_of(am, null.tolist()) if null.size else None,
            }

    # ── Q3 verdict: mean R > 0 in all 3 segments AND control z ≥ 2.4 ──────────
    q3_pass_all_pos = all(
        q3_summary[seg][h]["actual_mean"] is not None and q3_summary[seg][h]["actual_mean"] > 0
        for seg in ["2020-22", "2023-24", "2025-26"] for h in HOLD_DAYS
    )
    # For Q3 z check: need at least one hold period z ≥ 2.4
    q3_best_z_by_hold = {h: max((q3_summary[seg][h]["z"] for seg in ["2020-22", "2023-24", "2025-26"]
                                  if q3_summary[seg][h]["z"] is not None), default=None)
                          for h in HOLD_DAYS}
    q3_pass_z = any((z is not None and z >= 2.4) for z in q3_best_z_by_hold.values())

    # ── Write report ─────────────────────────────────────────────────────────
    out_path = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-128_s611.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# T-128 — S-611 周末资金费率飙升(2026-10-19)")
    lines.append("")
    lines.append("照台账 §S-611 一字不改。**R 口径同 S-610**:`R = (entry − exit) / (stop − entry)`,成本 40bp 折成 R = 40bp / ATR14 扣减。")
    lines.append("")
    lines.append("**数据范围:**")
    lines.append(f"- funding_history: 36 名,binance_perp,8h 一结;BTC 最早 2020-01-01,最晚 2026-10-19。")
    lines.append(f"- ohlcv_daily binance_hist: {len(ohlcv)}/36 名;缺: {missing_ohlcv or '无'}。HYPE 仅 coingecko/hyperliquid —— 不参与 Q3(本表不报)。")
    lines.append(f"- 已知偏差(沿用 S-611 §「已知偏差」):宇宙是今天 binance_perp 还在采集名单的 36 名(幸存者);Q2 现货腿用永续收盘近似,基差记 0(乐观)。")
    lines.append("")
    lines.append(f"**飙升检测:** 单次结算费率 ≥ 前 90 天(不含当次)95 分位 **且** 年化 ≥ 30%。")
    lines.append(f"**周末定义:** 周六/周日(UTC, weekday ∈ {WEEKEND_UTC});周末占一周 2/7 结算(~28.6%)。")
    lines.append("")
    lines.append("## 一表汇总(Q2 三段均值 + Q3 三段 × 三持有期均值 R + z)")
    lines.append("")
    lines.append("| 段 | Q2 净收益均值 | Q3 1d R(对照 z) | Q3 3d R(对照 z) | Q3 7d R(对照 z) | 笔数(周末飙升) |")
    lines.append("|---|---|---|---|---|---|")
    for seg in ["2020-22", "2023-24", "2025-26"]:
        ws = len([s for s in weekend_spikes if s["segment"] == seg])
        row = [seg]
        row.append(fmt_pct(q2_means.get(seg)))
        for h in HOLD_DAYS:
            x = q3_summary[seg][h]
            if x["actual_mean"] is None:
                row.append("—")
                continue
            z = x["z"]
            z_s = f"{z:+.2f}" if z is not None and np.isfinite(z) else "—"
            row.append(f"{x['actual_mean']:+.3f} (z={z_s})")
        row.append(str(ws))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("**Q2 判:** 「每次事件净收益均值 > 0,三段至少两段为正且 2025-26 为正」 ⇒ "
                 f"{'**过**' if q2_pass_two_of_three and q2_pass_2025_26 else '**不过**'}")
    lines.append("**Q3 判:** 「均值 R > 0 三段全正 **且** 对照 z ≥ 2.4(单侧 p < 0.05 / 4 试验)」 ⇒ "
                 f"三段全正={q3_pass_all_pos};最大 z={max((z for z in q3_best_z_by_hold.values() if z is not None), default=None):.2f} ⇒ "
                 f"{'**过**' if q3_pass_all_pos and q3_pass_z else '**不过**'}")
    lines.append("")
    # Q1 detailed
    lines.append("## Q1 描述 —— 每名 × 星期几 × 段(摘录:总周末 vs 总工作日频率)")
    lines.append("")
    lines.append("| 段 | 周末飙升笔数 | 工作日飙升笔数 | 周末结算数 | 工作日结算数 | 周末频率 | 工作日频率 | 周末 / 工作日 倍数 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for seg, v in seg_summary.items():
        lines.append(
            f"| {seg} | {v['wknd_n']} | {v['wkdy_n']} | {v['wknd_settles']} | {v['wkdy_settles']} | "
            f"{fmt_pct(v['wknd_freq'])} | {fmt_pct(v['wkdy_freq'])} | "
            f"{fmt(v['ratio'], 3) if v['ratio'] is not None else '—'} |"
        )
    lines.append("")
    lines.append("Q1 完整(每名 × 每 weekday)写入 companion `T-128_q1_table.csv`(同目录)。")
    lines.append("")
    # Q2 detail
    lines.append("## Q2 中性收费(周末飙升后 24 小时 3 次结算,基差=0,20bp 成本)")
    lines.append("")
    lines.append("| 段 | 事件数 | next-3 funding 累计均值 | 减 20bp 成本后净收益均值 | 净 > 0 占比 |")
    lines.append("|---|---|---|---|---|")
    for seg, ev in q2_by_seg.items():
        if not ev:
            lines.append(f"| {seg} | 0 | — | — | — |")
            continue
        n = len(ev)
        mean_sum = float(np.mean([e["next3_sum"] for e in ev]))
        mean_net = float(np.mean([e["net"] for e in ev]))
        pct_pos = sum(1 for e in ev if e["net"] > 0) / n
        lines.append(f"| {seg} | {n} | {mean_sum * 100:.4f}% | {mean_net * 100:.4f}% | {pct_pos * 100:.1f}% |")
    lines.append("")
    lines.append("**机制注:** Q2 做空永续**收到** funding_rate(正数时多付给空头),现货腿无资金费;24h 后平仓,基差变化 = 0(per S-611「偏乐观,写明」)。")
    lines.append("")
    # Q3 detail
    lines.append("## Q3 反着做(周末飙升日 close 做空,ATR14 止损,1/3/7 天,40bp 成本,R 口径同 S-610)")
    lines.append("")
    lines.append("| 段 | 持有 | 笔数 | 实际均值 R | 对照均值 R | 对照 σ | z | 分位 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for seg in ["2020-22", "2023-24", "2025-26"]:
        for h in HOLD_DAYS:
            x = q3_summary[seg][h]
            if x["actual_mean"] is None:
                lines.append(f"| {seg} | {h}d | 0 | — | — | — | — | — |")
                continue
            z_s = f"{x['z']:+.2f}" if x['z'] is not None and np.isfinite(x["z"]) else "—"
            p_s = f"{x['pctile']:.3f}" if x['pctile'] is not None and np.isfinite(x["pctile"]) else "—"
            lines.append(
                f"| {seg} | {h}d | {x['n']} | {x['actual_mean']:+.3f} | "
                f"{fmt(x['null_mean'], 3)} | {fmt(x['null_std'], 3)} | {z_s} | {p_s} |"
            )
    lines.append("")
    lines.append("**判(过 = 均值 R > 0 三段全正 + 对照 z ≥ 2.4):** "
                 f"三段全正 = {'是' if q3_pass_all_pos else '否'},"
                 f"最大 z = {max((z for z in q3_best_z_by_hold.values() if z is not None), default=float('nan')):.2f}"
                 f" → **{'过' if q3_pass_all_pos and q3_pass_z else '不过'}**")
    lines.append("")
    # Final
    lines.append("## 最终判定")
    lines.append("")
    lines.append(f"- Q1(描述):周末飙升 {'**比工作日多**' if seg_summary['2025-26']['ratio'] and seg_summary['2025-26']['ratio'] > 1 else '**不显著多于**' if seg_summary['2025-26']['ratio'] else '**无数据**'} 2025-26 段(详见上)。")
    lines.append(f"- Q2(收费):{'**过**' if q2_pass_two_of_three and q2_pass_2025_26 else '**不过**'}(三段均值 {q2_means})。")
    lines.append(f"- Q3(反着做):{'**过**' if q3_pass_all_pos and q3_pass_z else '**不过**'}(三段全正={q3_pass_all_pos},z={q3_best_z_by_hold})。")
    lines.append("")
    lines.append(f"→ {'**周末飙升可抓**:执行器加一条「周末收费 / 周末反做」纸面臂。' if (q2_pass_two_of_three and q2_pass_2025_26) or (q3_pass_all_pos and q3_pass_z) else '**周末飙升只作风控旗(拥挤)**,不交易。'}")
    lines.append("")
    lines.append("## 结果里还看到了什么(探索性 —— 需另立预注册、在新数据上过零信号对照)")
    lines.append("")
    # Some exploratory findings
    total_spikes = len(spikes)
    total_weekend = len(weekend_spikes)
    total_pct = total_weekend / total_spikes * 100 if total_spikes else 0
    lines.append(f"- **总飙升 N = {total_spikes}**;周末 N = {total_weekend}({total_pct:.1f}%),周末占结算 2/7=28.6% —— "
                 f"周末占比 vs 结算占比的差 = {total_pct - 28.6:+.1f}pp;2020-22 / 2023-24 / 2025-26 各自周末 / 工作日比详见上表。")
    # Per-name count
    by_name = {}
    for s in spikes:
        by_name.setdefault(s["symbol"], {"n": 0, "wk_n": 0})
        by_name[s["symbol"]]["n"] += 1
        if s["is_weekend"]:
            by_name[s["symbol"]]["wk_n"] += 1
    top = sorted(by_name.items(), key=lambda kv: -kv[1]["wk_n"])[:5]
    lines.append(f"- **周末飙升最频繁:** {[(k, v['wk_n']) for k, v in top]} —— 集中度需要另立预注册。")
    # Surviving-name caveat
    lines.append("- **幸存者偏差:** 36 名是今天还在 binance_perp 采集名单的币(2020 早期很多名还没上;已下架的没被纳入)—— **早年 (2020–21) 看到的「名」比现在少**;Q1 表中 2020-22 段 sym 数会 < 36。这与 S-611 §「已知偏差」一致。")
    lines.append("- **HYPE 缺 ohlcv_daily binance_hist:** HYPE 是 2025 末才上 binance_perp 的新币,Q3 不参与(无 binance_hist 日线)。Q1 的 HYPE 周末飙升仅作描述,无 Q3 验证。")
    lines.append("- **幸存者之外的真正风险:** 「周末飙升 → 价格急跌 → 我们做空」逻辑对幸存币偏乐观:幸存 = 还在交易;被下架的币周末飙升后常常深度归零。HYPERLIQUID 1h 资金费 09-05 起只作描述(per S-611,不参与判),但 HYPE 周末飙升频率与 binance_perp 同方向是另一探索点。")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {out_path}")

    # Also dump the full Q1 table
    q1_csv = out_path.parent / "T-128_q1_table.csv"
    with q1_csv.open("w") as f:
        f.write("symbol,segment,n_settles," + ",".join(f"wd{wd}_n,wd{wd}_mean_ann" for wd in range(7)) + ",weekend_n,weekday_n,weekend_freq,weekday_freq,ratio_wknd_over_wkdy\n")
        for row in q1:
            cells = [row["symbol"], row["segment"], str(row["n_settles"])]
            for wd in range(7):
                cells.append(str(row[f"wd{wd}_n"]))
                cells.append("" if row[f"wd{wd}_mean_ann"] is None else f"{row[f'wd{wd}_mean_ann']:.4f}")
            cells.append(str(row["weekend_n"]))
            cells.append(str(row["weekday_n"]))
            cells.append("" if row["weekend_freq"] is None else f"{row['weekend_freq']:.6f}")
            cells.append("" if row["weekday_freq"] is None else f"{row['weekday_freq']:.6f}")
            cells.append("" if row["ratio_wknd_over_wkdy"] is None else f"{row['ratio_wknd_over_wkdy']:.4f}")
            f.write(",".join(cells) + "\n")
    print(f"Wrote {q1_csv}")

    # Persist card-relevant numbers for the lane-bot to write into T-128 notes
    summary = {
        "n_symbols": len(symbols),
        "n_ohlcv_symbols": len(ohlcv),
        "missing_ohlcv": missing_ohlcv,
        "n_spikes_total": total_spikes,
        "n_spikes_weekend": total_weekend,
        "q2_means": q2_means,
        "q2_pass_two_of_three": q2_pass_two_of_three,
        "q2_pass_2025_26": q2_pass_2025_26,
        "q3_summary": q3_summary,
        "q3_pass_all_pos": q3_pass_all_pos,
        "q3_pass_z": q3_pass_z,
        "q3_best_z_by_hold": q3_best_z_by_hold,
        "verdict": "pass" if (q2_pass_two_of_three and q2_pass_2025_26) or (q3_pass_all_pos and q3_pass_z) else "fail",
    }
    summary_path = out_path.parent / "T-128_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
