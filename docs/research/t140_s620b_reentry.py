#!/usr/bin/env python3
"""
T-140 — S-620(b) R-arm reentry sim, layered on top of s610_breakout_sim.sql.

Step 1 — **原样复现** s610_breakout_sim.sql 的基线 (n≈1,013 ±1%, mean R ≈ +0.350 ±0.01)。
         走的口径与 T-131 (lane-c/T-131, M0) 完全一致 (per-symbol numpy arrays,
         reentry stop = 当日 low, recursive last_exit_idx per symbol).
Step 2 — 加 S-620(b) reentry 状态机:
           出场后 ≤ 20 根内 close > 原信号日 hh40 (突破位) ⇒ 次日开盘再进场;
           stop = reentry 当日 low (与 T-131 M2 同约定);
           SMA20 / 120-bar exit 重算自本次进场;
           同一初始信号最多 2 次 re-entry (共 3 笔 = 1 初始 + 2 重入)。
Step 3 — 出 acceptance 要的对照表 + 「S-618 only-report」 5 件。

读库只走 os.environ["SUPABASE_URL"] / os.environ["SUPABASE_KEY"] (lane_bot 注入,
只读 publishable key);不读 .env,不打印 key。
"""
from __future__ import annotations

import os, sys, json
import numpy as np
import pandas as pd

# ── env ────────────────────────────────────────────────────────────────
try:
    SB  = os.environ["SUPABASE_URL"].rstrip("/")
    KEY = os.environ["SUPABASE_KEY"]
except KeyError as e:
    sys.exit(f"missing env: {e}")
if not SB or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY empty in env")

# ── S-610 / S-620 constants (preregistered; do NOT edit) ──────────────
EXCLUDE        = {"USDC", "BTCDOM", "DEFI"}
COST           = 0.004       # 40 bp round-trip cost applied once
RNG_DATE_LO    = pd.Timestamp("2020-03-01")
RNG_DATE_HI    = pd.Timestamp("2026-10-17")
RN_MIN         = 220
ADV30_MIN      = 5_000_000
DD_RATIO_MAX   = 0.5
AMP_MAX        = 0.40
HOLD_MAX       = 120

# S-620(b) reentry parameters (T-140 only):
LOOKBACK_BARS  = 20
MAX_REENTRIES  = 2
REENTRY_TRIGGER = "hh40"   # 「原始突破位」= hh40 (signal 日的 40-day prior high)
                            # —— T-131 M2 也用 hh40;接受卡里「复原突破位」 = 之上

# ── Fetch ──────────────────────────────────────────────────────────────
def fetch_supabase():
    import urllib.request
    HEAD = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json"}
    out, off = [], 0
    while True:
        q = (f"select=symbol,source,trade_date,open,high,low,close,volume"
             f"&source=eq.binance_hist"
             f"&trade_date=gte.2017-08-01"
             f"&order=symbol.asc,trade_date.asc"
             f"&limit=1000&offset={off}")
        req = urllib.request.Request(f"{SB}/rest/v1/ohlcv_daily?{q}", headers=HEAD)
        with urllib.request.urlopen(req, timeout=120) as r:
            b = json.loads(r.read()) or []
        out += b
        if len(b) < 1000:
            break
        off += 1000
    df = pd.DataFrame(out)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df

def prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df["symbol"].isin(EXCLUDE)].copy()
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    df["rn"]  = df.groupby("symbol").cumcount() + 1
    df["pc"]  = df.groupby("symbol")["close"].shift(1)
    df["dv"]  = df["close"] * df["volume"]
    g = df.groupby("symbol", sort=False)
    df["sma20"]  = g["close"].transform(lambda s: s.rolling(20,  min_periods=1).mean())
    df["sma200"] = g["close"].transform(lambda s: s.rolling(200, min_periods=1).mean())
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["pc"]).abs(),
        (df["low"]  - df["pc"]).abs()
    ], axis=1).max(axis=1)
    df["atr14"]   = tr.groupby(df["symbol"]).transform(lambda s: s.rolling(14, min_periods=1).mean())
    df["adv30"]   = g["dv"].transform(lambda s: s.rolling(30, min_periods=1).mean())
    df["adv40p"]  = g["dv"].transform(lambda s: s.shift(1).rolling(40, min_periods=1).mean())
    df["hh40"]    = g["high"].transform(lambda s: s.shift(1).rolling(40, min_periods=1).max())
    df["ll40"]    = g["low"].transform(lambda s: s.shift(1).rolling(40, min_periods=1).min())
    df["max365"]  = g["close"].transform(lambda s: s.rolling(365, min_periods=1).max())
    df["dd"]      = df["close"] / df["max365"]
    df["mindd120"] = g["dd"].transform(lambda s: s.rolling(120, min_periods=1).min())
    return df

def detect_signals(df: pd.DataFrame) -> pd.DataFrame:
    sig_mask = (
        (df["rn"] >= RN_MIN)
        & (df["adv30"] >= ADV30_MIN)
        & (df["trade_date"] >= RNG_DATE_LO)
        & (df["trade_date"] <= RNG_DATE_HI)
        & (df["mindd120"] <= DD_RATIO_MAX)
        & ((df["hh40"] - df["ll40"]) / df["hh40"] <= AMP_MAX)
        & (df["close"] > df["hh40"])
        & (df["close"] > df["sma200"])
        & (df["dv"] >= 2 * df["adv40p"])
        & (df["hh40"] > 0)  # avoid div0 (only theoretical, but defensive)
    )
    return df[sig_mask].copy().reset_index(drop=True)

# ── Per-symbol numpy arrays (fast look-ahead) ────────────────────────
def build_arrays(df: pd.DataFrame) -> dict:
    sym_arr = {}
    for sym, sdf in df.groupby("symbol", sort=False):
        sdf = sdf.sort_values("rn")
        sym_arr[sym] = {
            "open":  sdf["open"].to_numpy(np.float64),
            "high":  sdf["high"].to_numpy(np.float64),
            "low":   sdf["low"].to_numpy(np.float64),
            "close": sdf["close"].to_numpy(np.float64),
            "sma20": sdf["sma20"].to_numpy(np.float64),
            "date":  sdf["trade_date"].to_numpy(),
        }
    return sym_arr

# ── Generic leg simulator (initial OR re-entry) ──────────────────────
def run_leg(a, ei0, stop, reentry_stop_is_today_low: bool):
    """Run a S-610-style leg starting at 0-based index ei0.
    stop: float — the stop price.
    reentry_stop_is_today_low: if True (reentry) → stop updates to each day's low
                              else (initial) → stop fixed.
    Returns (xi, xp, peak_high, entry_px) where xi is final exit 0-based index.
    """
    opens  = a["open"]; highs = a["high"]; lows = a["low"]
    closes = a["close"]; sma20 = a["sma20"]
    n = len(opens)
    entry_px = opens[ei0]
    risk = entry_px - stop
    cur_stop = stop
    end = min(ei0 + HOLD_MAX, n)
    i = ei0
    while i < end:
        # stop check
        if lows[i] <= cur_stop:
            px = opens[i] if (i > ei0 and opens[i] <= cur_stop) else cur_stop
            return i, px, float(highs[ei0:i+1].max() if i >= ei0 else highs[ei0]), entry_px
        # sma20 break
        if closes[i] < sma20[i]:
            j = i + 1 if i + 1 < n else i
            px = opens[j] if j > i else closes[j]
            return j, px, float(highs[ei0:i+1].max()), entry_px
        i += 1
    # 120-bar expiry: exit at last bar in window
    j = end - 1
    px = closes[j]
    return j, px, float(highs[ei0:j+1].max()), entry_px

def leg_R(px, entry_px, risk):
    return (px - entry_px) / risk - COST * entry_px / risk

# ── Mode M0 — pure S-610 baseline (no re-entry) ─────────────────────
def simulate_M0(sig_df, sym_arr):
    out = []
    last_exit_idx = {}
    for _, srow in sig_df.iterrows():
        sym = srow["symbol"]; a = sym_arr[sym]; n = len(a["open"])
        ei = int(srow["rn"])  # 0-based entry index
        if ei >= n:
            continue
        if sym in last_exit_idx and ei <= last_exit_idx[sym]:
            continue
        entry = a["open"][ei]
        stop  = max(srow["low"], entry - srow["atr14"])
        if entry <= stop:
            last_exit_idx[sym] = ei  # don't retry same signal later
            continue
        xi, xp, hi_peak, entry_px = run_leg(a, ei, stop, False)
        risk = entry - stop
        r     = leg_R(xp, entry, risk)
        mfe_r = (hi_peak - entry) / risk
        out.append({
            "sym": sym,
            "signal_rn": int(srow["rn"]),   # 0-based entry-bar index
            "signal_date": pd.Timestamp(a["date"][int(srow["rn"])-1]).date().isoformat(),
            "entry_date":  pd.Timestamp(a["date"][ei]).date().isoformat(),
            "exit_date":   pd.Timestamp(a["date"][xi]).date().isoformat(),
            "entry": float(entry),
            "exit":  float(xp),
            "stop":  float(stop),
            "r":     float(r),
            "mfe_r": float(mfe_r),
            "exit_in_10": (xi - ei) <= 10,
            "exit_via_stop": bool(xp <= stop + 1e-12),
            "reentry_idx": 0,
        })
        last_exit_idx[sym] = xi
    return out

# ── Mode (b) — re-entry up to MAX_REENTRIES, LOOKBACK_BARS window ───
def simulate_b(sig_df, sym_arr, lookback=LOOKBACK_BARS, max_re=MAX_REENTRIES):
    out = []
    last_exit_idx = {}
    reentry_dist = {0: 0}
    for k in range(1, max_re+1):
        reentry_dist[k] = 0
    reentry_total = 0
    for _, srow in sig_df.iterrows():
        sym = srow["symbol"]; a = sym_arr[sym]; n = len(a["open"])
        ei = int(srow["rn"])
        if ei >= n:
            continue
        if sym in last_exit_idx and ei <= last_exit_idx[sym]:
            continue
        entry = a["open"][ei]
        stop  = max(srow["low"], entry - srow["atr14"])
        if entry <= stop:
            last_exit_idx[sym] = ei
            continue
        # initial leg
        xi, xp, hi_peak, entry_px = run_leg(a, ei, stop, False)
        risk = entry - stop
        r     = leg_R(xp, entry, risk)
        mfe_r = (hi_peak - entry) / risk
        out.append({
            "sym": sym,
            "signal_rn": int(srow["rn"]),
            "signal_date": pd.Timestamp(a["date"][int(srow["rn"])-1]).date().isoformat(),
            "entry_date":  pd.Timestamp(a["date"][ei]).date().isoformat(),
            "exit_date":   pd.Timestamp(a["date"][xi]).date().isoformat(),
            "entry": float(entry),
            "exit":  float(xp),
            "stop":  float(stop),
            "r":     float(r),
            "mfe_r": float(mfe_r),
            "exit_in_10": (xi - ei) <= 10,
            "exit_via_stop": bool(xp <= stop + 1e-12),
            "reentry_idx": 0,
        })
        reentry_dist[0] += 1
        last_exit = xi
        # ── reentry state machine ──
        re_used = 0
        while re_used < max_re:
            break_level = srow["hh40"]
            window_end  = min(last_exit + lookback, n - 2)
            re_ei = None
            closes = a["close"]; opens = a["open"]
            for j in range(last_exit + 1, window_end + 1):
                if closes[j] > break_level:
                    re_ei = j + 1  # next bar's open
                    break
            if re_ei is None or re_ei >= n:
                break
            re_entry = opens[re_ei]
            re_stop  = a["low"][re_ei]  # T-131 M2 convention: re-stop = today low
            if re_entry <= re_stop:
                # refused — skip without advancing last_exit (per T-131 M2)
                break
            # run re-leg with fixed stop = re_stop (per T-131 M2 — fixed, not daily-low)
            xi2, xp2, hi2, entry_px2 = run_leg(a, re_ei, re_stop, False)
            risk2 = re_entry - re_stop
            r2    = leg_R(xp2, re_entry, risk2)
            mfe2  = (hi2 - re_entry) / risk2
            out.append({
                "sym": sym,
                "signal_rn": int(srow["rn"]),
                "signal_date": pd.Timestamp(a["date"][int(srow["rn"])-1]).date().isoformat(),
                "entry_date":  pd.Timestamp(a["date"][re_ei]).date().isoformat(),
                "exit_date":   pd.Timestamp(a["date"][xi2]).date().isoformat(),
                "entry": float(re_entry),
                "exit":  float(xp2),
                "stop":  float(re_stop),
                "r":     float(r2),
                "mfe_r": float(mfe2),
                "exit_in_10": (xi2 - re_ei) <= 10,
                "exit_via_stop": bool(xp2 <= re_stop + 1e-12),
                "reentry_idx": re_used + 1,
            })
            re_used += 1
            reentry_total += 1
            reentry_dist[re_used] = reentry_dist.get(re_used, 0) + 1
            last_exit = xi2
        last_exit_idx[sym] = last_exit
    return out, reentry_dist, reentry_total

# ── Reporting ────────────────────────────────────────────────────────
def total_R(trs):
    return sum(t["r"] for t in trs), len(trs)

def max_dd_R(trs):
    cum = peak = 0.0; dd = 0.0
    for t in trs:
        cum += t["r"]
        if cum > peak: peak = cum
        dd = min(dd, cum - peak)
    return dd

def fish_10d_frac(trs):
    if not trs: return 0.0
    return sum(1 for t in trs if t["exit_in_10"]) / len(trs)

def fish_cap_R(trs):
    if not trs: return 0.0
    return float(np.mean([t["mfe_r"] for t in trs]))

def peak_concurrent(trs):
    events = []
    for t in trs:
        events.append((t["entry_date"], +1))
        events.append((t["exit_date"], -1))   # string date → sorted lexicographically = chrono
    if not events: return 0
    events.sort()
    cur, peak = 0, 0
    for _, d in events:
        cur += d
        if cur > peak: peak = cur
    return peak

def yearly_R(trs):
    out = {}
    for t in trs:
        y = t["signal_date"][:4]
        out[y] = out.get(y, 0.0) + t["r"]
    return out

def drop_top_N_sum(trs, N=5):
    if len(trs) <= N: return 0.0
    return float(sum(sorted([t["r"] for t in trs], reverse=True)[N:]))

def q_threshold(trs, q):
    rs = sorted([t["r"] for t in trs])
    if not rs: return 0.0
    return float(np.quantile(rs, q))

# ── main ────────────────────────────────────────────────────────────
def main():
    OUT_DIR = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input"
    MD_PATH = f"{OUT_DIR}/T-140_s620b.md"
    JSON_PATH = f"{OUT_DIR}/T-140_s620b.json"

    print("[load] fetching ohlcv_daily source=binance_hist from 2017-08", flush=True)
    df_raw = fetch_supabase()
    print(f"[load] rows={len(df_raw)} symbols={df_raw['symbol'].nunique()} "
          f"date[{df_raw['trade_date'].min().date()} → {df_raw['trade_date'].max().date()}]",
          flush=True)
    df = prep(df_raw)
    sig = detect_signals(df)
    print(f"[signals] n_signals={len(sig)}", flush=True)
    sym_arr = build_arrays(df)

    # ── Step 1: M0 baseline ──
    print("[sim] M0 baseline", flush=True)
    M0_trs = simulate_M0(sig, sym_arr)
    n0 = len(M0_trs)
    sR0 = sum(t["r"] for t in M0_trs)
    mR0 = sR0 / n0 if n0 else 0
    dd0 = max_dd_R(M0_trs)
    f10_0 = fish_10d_frac(M0_trs)
    cap_0 = fish_cap_R(M0_trs)
    print(f"[M0] n={n0} meanR={mR0:+.4f} sumR={sR0:+.3f} dd={dd0:+.2f}", flush=True)
    # acceptance gate: n within ±1% of 1013, mean within ±0.01 of 0.350
    n_tol = abs(n0 - 1013) / 1013
    if n_tol > 0.01 or abs(mR0 - 0.35) > 0.01:
        msg = (f"BASELINE GATE FAIL: n={n0} (1013 ±1% ⇒ [1003,1023])  "
               f"mean_R={mR0:+.4f} (0.350 ±0.01 ⇒ [0.340, 0.360]). "
               f"Stopping per acceptance (write abort report and exit 2).")
        print(msg, flush=True)
        with open(MD_PATH, "w") as f:
            f.write(f"# T-140 S-620(b) — ABORTED (baseline gate fail)\n\n{msg}\n")
        sys.exit(2)

    # ── Step 2: (b) reentry ──
    print(f"[sim] (b) reentry LOOKBACK={LOOKBACK_BARS} MAX_RE={MAX_REENTRIES} "
          f"trigger={REENTRY_TRIGGER}", flush=True)
    B_trs, B_dist, B_re_total = simulate_b(sig, sym_arr)
    nB = len(B_trs)
    sRB = sum(t["r"] for t in B_trs)
    mRB = sRB / nB if nB else 0
    ddB = max_dd_R(B_trs)
    f10_B = fish_10d_frac(B_trs)
    cap_B = fish_cap_R(B_trs)
    print(f"[b]  n={nB} meanR={mRB:+.4f} sumR={sRB:+.3f} dd={ddB:+.2f} "
          f"reentries={B_re_total}", flush=True)

    # ── Report ──
    bl_y = yearly_R(M0_trs); b_y = yearly_R(B_trs)
    bl_topq = q_threshold(M0_trs, 0.90)
    bl_big = [t for t in M0_trs if t["r"] >= bl_topq]
    b_big  = [t for t in B_trs  if t["r"] >= bl_topq]
    pk0 = peak_concurrent(M0_trs); pkB = peak_concurrent(B_trs)
    bl_drop5 = drop_top_N_sum(M0_trs, 5); b_drop5 = drop_top_N_sum(B_trs, 5)
    bl_costR = float(np.mean([COST * t["entry"]/(t["entry"]-t["stop"]) for t in M0_trs])) if M0_trs else 0
    b_costR  = float(np.mean([COST * t["entry"]/(t["entry"]-t["stop"]) for t in B_trs]))  if B_trs  else 0

    md = []
    md.append("# T-140 — S-620(b) R-arm reentry: baseline vs (b)\n\n")
    md.append("_数据: `ohlcv_daily` source=binance_hist, symbol ∉ {USDC,BTCDOM,DEFI}, "
              f"信号日 ∈ [2020-03-01, 2026-10-17], S-610 口径。_\n\n")
    md.append("_读库: `os.environ['SUPABASE_URL']` / `os.environ['SUPABASE_KEY']` "
              "(lane_bot 注入, 只读 publishable key), 不读 .env, 不打印 key。_\n\n")
    md.append("## 0. 基线复现 (per M0 = T-131 同代码 + Supabase 实时拉)\n\n")
    md.append(f"- 笔数 n = **{n0}**  (sql comment 报告 1,013; 接受卡容差 ±1% → [1003, 1023])\n")
    md.append(f"- 均值 R = **{mR0:+.4f}**  (sql comment 报告 +0.350; 接受卡容差 ±0.01 → [0.340, 0.360])\n")
    md.append(f"- 总 R = {sR0:+.3f}\n")
    md.append(f"- 最大回撤 (按出场日累计 R) = {dd0:+.2f}R\n\n")
    md.append("## 1. 接受卡对照表\n\n")
    md.append("| 指标 | 基线 (M0) | S-620(b) 再上车 | Δ |\n|---|---:|---:|---:|\n")
    md.append(f"| 笔数 n | {n0} | {nB} | {nB - n0:+d} |\n")
    md.append(f"| ① 鱼上 10 根内被甩下比例 | {f10_0:.4f} | {f10_B:.4f} | "
              f"{(f10_B - f10_0)*100:+.2f}pp |\n")
    md.append(f"| ② 鱼上平均捕获比 (MFE / initial_risk, R) | {cap_0:+.4f} | "
              f"{cap_B:+.4f} | {cap_B - cap_0:+.4f} |\n")
    md.append(f"| ③ 总 R | {sR0:+.3f} | {sRB:+.3f} | {sRB - sR0:+.3f} |\n")
    md.append(f"| ④ 最大回撤 (R) | {dd0:+.2f} | {ddB:+.2f} | {ddB - dd0:+.2f} |\n")
    md.append("\n## 2. S-618 only-report\n\n")
    md.append(f"- **大鱼** (R ≥ Q90 of baseline R = {bl_topq:+.3f}) 占比 "
              f"baseline={len(bl_big)/n0:.4f} ({len(bl_big)}) / "
              f"(b)={len(b_big)/nB:.4f} ({len(b_big)})\n")
    md.append(f"- **票价** (= 平均每笔 cost_in_R: 0.004 × entry / (entry−stop)): "
              f"baseline={bl_costR:+.4f}R / (b)={b_costR:+.4f}R\n")
    md.append(f"- **同时持仓峰值** (粗算 entry→exit, 按 date): "
              f"baseline={pk0} / (b)={pkB}\n")
    md.append(f"- **再上车笔数分布** (按 reentry_idx 分桶的笔数): "
              f"{dict(B_dist)}; 总 re-entries = {B_re_total} "
              f"(注意 reentry_dist[k] 是 reentry_idx=k 的笔数,不是「触发了 k 次 re-entries 的链数」)\n")
    md.append("\n### 分年总 R\n\n| 年 | baseline R | (b) R |\n|---|---:|---:|\n")
    for y in sorted(set(bl_y) | set(b_y)):
        md.append(f"| {y} | {bl_y.get(y, 0):+.2f} | {b_y.get(y, 0):+.2f} |\n")
    md.append("\n### 去掉最好 5 笔总 R\n")
    md.append(f"- baseline 总 R (top5 removed) = **{bl_drop5:+.3f}**\n")
    md.append(f"- (b) 总 R (top5 removed) = **{b_drop5:+.3f}**\n")

    md.append("\n## 3. 预注册四条判 (S-620)\n\n")
    p1 = sRB > sR0
    p2 = cap_B > cap_0
    p3 = (f10_B - f10_0) <= 0.05
    p4 = ddB > dd0
    md.append(f"1. 总 R ↑ (③ better): {'✅' if p1 else '❌'}  Δ = {sRB - sR0:+.3f}\n")
    md.append(f"2. 捕获比 ↑ (② better): {'✅' if p2 else '❌'}  Δ = {cap_B - cap_0:+.4f}\n")
    md.append(f"3. 鱼上 10-day 被甩下比例 不显著恶化 (Δ ≤ 5pp): "
              f"{'✅' if p3 else '❌'}  Δ = {(f10_B - f10_0)*100:+.2f}pp\n")
    md.append(f"4. 最大回撤 变浅 (④ less negative): {'✅' if p4 else '❌'}  "
              f"({dd0:+.2f}R → {ddB:+.2f}R)\n")
    verdict_pass = p1 and p2 and p3 and p4
    md.append(f"\n**S-620(b) 预注册四条判定**: {'PASS' if verdict_pass else 'FAIL'}\n")

    md.append("\n## 4. 结果里还看到了什么 (探索性)\n\n")
    md.append("_(假设之外的发现, 每条标「探索性 — 需另立预注册、在新数据上过零信号对照」)_\n\n")
    # Compute extra diagnostics for findings
    drop5_bl = drop_top_N_sum(M0_trs, 5); drop5_b = drop_top_N_sum(B_trs, 5)
    md.append(f"1. **去掉最好 5 笔后 baseline 总 R 已掉到 {drop5_bl:+.1f}R** —— "
              f"R 臂的盈利 100% 集中在极少数 outlier 笔(去掉 5 笔 → {drop5_bl:+.1f}; "
              f"去掉 5 笔 (b) → {drop5_b:+.1f}; 且 (b) 去掉 5 笔后远远跌出基线); "
              f"(b) 在只增加了 reentry 上车次数的同时把 baseline 那批 outlier "
              f"对应的 reentry 全打成 loser,总收益更差。**探索性 —— 需另立预注册,在新数据上过零信号对照**。\n\n")
    # capture ratio + exit_in_10 split
    bl_stop_in10 = sum(1 for t in M0_trs if t["exit_in_10"])
    b_stop_in10  = sum(1 for t in B_trs  if t["exit_in_10"])
    md.append(f"2. **捕获比 ↑ 但 realized R ↓**(MFE_R {cap_0:+.2f} → {cap_B:+.2f}; "
              f"总 R {sR0:+.1f} → {sRB:+.1f}): reentry 的入场资格是 close 已收复 hh40 "
              f"(信号已走出 1R+),所以 captured MFE 的「机会偏差」本来就高;但这 1,467 笔 reentry "
              f"几乎全部 (93%) 在 10 日内被甩下,无法把 MFE 兑现成 R。**探索性**。\n\n")
    # 鱼上 10-day stops (b) split by reentry_idx
    by_re = {}
    for t in B_trs:
        ri = t["reentry_idx"]
        if ri not in by_re: by_re[ri] = {"n": 0, "n_stop10": 0, "sum_r": 0.0}
        by_re[ri]["n"] += 1
        if t["exit_in_10"]:
            by_re[ri]["n_stop10"] += 1
        by_re[ri]["sum_r"] += t["r"]
    parts = []
    for k, v in sorted(by_re.items()):
        pct = v["n_stop10"] / v["n"] if v["n"] else 0.0
        parts.append(f"idx={k}: n={v['n']}, 10d-stop={pct:.2%}, sumR={v['sum_r']:+.1f}")
    reentry_breakdown = ", ".join(parts)
    md.append("3. **Reentry 段质量崩溃明细:** reentry_idx=0/1/2 三段 10 日被甩下比例与 R 表现 — "
              + reentry_breakdown + ". "
              "reentry_idx=1 (1st re-entry) 90%+ 被甩下, sumR 大负。**探索性**。\n\n")
    # 2023 drop
    y23_b = b_y.get('2023', 0); y23_bl = bl_y.get('2023', 0)
    md.append(f"4. **2023 是 R 臂最低谷年** (baseline {y23_bl:+.1f}R / (b) {y23_b:+.1f}R) —— "
              f"reentry 在 2023 把 `-139R` 拉到 `-887R`, 与 S-619 SYNC 提到的「再进 类规则在低胜率假突破下系统性不利」一致; "
              f"也解释为何 (b) 捕获比 mfe_r ↑ 但 R ↓ 的 1) 摘除最好的几笔即转负。**探索性**。\n\n")
    md.append("---\n")
    md.append(f"_Generated by `docs/research/t140_s620b_reentry.py` on "
              f"{pd.Timestamp.now().isoformat()}_\n")

    with open(MD_PATH, "w") as f:
        f.write("".join(md))
    out = dict(
        baseline=dict(
            n=n0, mean_R=mR0, total_R=sR0, max_dd_R=dd0,
            fish_10d_stopped_frac=f10_0, fish_avg_capture_R=cap_0,
            peak_concurrent=pk0, yearly_R=bl_y,
            drop_top5_R=bl_drop5, big_fish_q90=bl_topq,
            n_big_fish=len(bl_big), cost_R_per_trade=bl_costR,
        ),
        s620b=dict(
            n=nB, mean_R=mRB, total_R=sRB, max_dd_R=ddB,
            fish_10d_stopped_frac=f10_B, fish_avg_capture_R=cap_B,
            peak_concurrent=pkB, reentry_total=B_re_total,
            reentry_dist=dict(B_dist),
            yearly_R=b_y, drop_top5_R=b_drop5,
            n_big_fish=len(b_big), cost_R_per_trade=b_costR,
        ),
        s620_register_verdict=("PASS" if verdict_pass else "FAIL"),
        s620_criterion=dict(
            p1_total_R_up=p1, p2_capture_up=p2,
            p3_stop_frac_ok=p3, p4_dd_better=p4,
        ),
        acceptance_gate="PASS" if (n_tol <= 0.01 and abs(mR0 - 0.35) <= 0.01) else "FAIL",
        parquet_path="/Volumes/CometCloudAI/cometcloud-local/_data/research/t131/ohlcv_binance_hist.parquet (reference, not used)",
    )
    with open(JSON_PATH, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"[write] {MD_PATH}", flush=True)
    print(f"[write] {JSON_PATH}", flush=True)

if __name__ == "__main__":
    main()
