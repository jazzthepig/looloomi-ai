#!/usr/bin/env python3
"""T-131 / S-612 — R-form management rules (M1/M2/M3) on top of S-610 R-G0 signals.

Stage A — Replicate S-610 R-G0 per docs/research/s610_breakout_sim.sql.
           Acceptance: n = 1,013 ± 1%, mean R = 0.350 ± 0.01.
Stage B — Apply M1 / M2 / M3 (same signal & entry), produce M0–M3 table.

Outputs (under /Volumes/CometCloudAI/cometcloud-local/_data/research/t131/):
  - ohlcv_binance_hist.parquet   (raw binance_hist, 262 symbols, 2017-08…2026-10)
  - trades_M{0,1,2,3}.csv        (per-mode trade list)
  - t131_stats.json              (M0–M3 stats summary)
"""
import os, json, sys
import numpy as np
import pandas as pd

IN_PATH = '/Volumes/CometCloudAI/cometcloud-local/_data/research/t131/ohlcv_binance_hist.parquet'
OUT_DIR = '/Volumes/CometCloudAI/cometcloud-local/_data/research/t131'
os.makedirs(OUT_DIR, exist_ok=True)

# ── S-610 / S-612 constants (preregistered; do NOT edit) ────────────────────
EXCLUDE = {'USDC', 'BTCDOM', 'DEFI'}
COST = 0.004                              # 40 bp round-trip, applied once
RNG_DATE_LO = pd.Timestamp('2020-03-01')
RNG_DATE_HI = pd.Timestamp('2026-10-17')
RN_MIN = 220
ADV30_MIN = 5_000_000
DD_RATIO_MAX = 0.5
AMP_MAX = 0.40
HOLD_MAX = 120
M1_SCALE_OUT_R = 2.0                      # 浮盈 +2R 平一半
M3_TIGHTEN_R   = 3.0                      # 浮盈 +3R 后切到 SMA10
M2_REENTRY_DAYS = 10                      # 出场后 10 天内可再进

# ── §Seth-1020a 修订 (2026-10-21, T-140 r2) ─────────────────────────────
# M2 再进腿的止损必须是【进场前】已知的价;且风险过窄的再进丢弃并计数。
RE_MIN_ATR_MULT = 0.3                      # entry − stop < 0.3×ATR ⇒ 丢弃
RE_SAMEBAR_MAX  = 0.05                     # 自检(能失败):exit_idx==entry_idx 占比上限
REENTRY_STOP_MODE = sys.argv[1] if len(sys.argv) > 1 else "entry_minus_atr"
                                             # M2 再进腿止损口径:
                                             #   "recapture_low"   = 复收日(信号收复日 j)的最低价
                                             #   "entry_minus_atr" = re_entry − atr14[j]
m2_re_legs      = []      # [(entry_idx, exit_idx), ...] 所有 M2 再进腿
m2_rej_tight    = [0]     # 因风险过窄被丢弃的 M2 再进次数

# ── Load ────────────────────────────────────────────────────────────────────
print('Loading ohlcv_daily …', flush=True)
df = pd.read_parquet(IN_PATH)
df['trade_date'] = pd.to_datetime(df['trade_date'])
df = df[~df.symbol.isin(EXCLUDE)].copy()
df = df.sort_values(['symbol', 'trade_date']).reset_index(drop=True)
df['rn']  = df.groupby('symbol').cumcount() + 1
df['pc']  = df.groupby('symbol')['close'].shift(1)
df['dv']  = df['close'] * df['volume']
g = df.groupby('symbol', sort=False)
df['sma20']  = g['close'].transform(lambda s: s.rolling(20,  min_periods=1).mean())
df['sma200'] = g['close'].transform(lambda s: s.rolling(200, min_periods=1).mean())
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['pc']).abs(),
    (df['low']  - df['pc']).abs()
], axis=1).max(axis=1)
df['atr14']  = tr.groupby(df['symbol']).transform(lambda s: s.rolling(14, min_periods=1).mean())
df['adv30']  = g['dv'].transform(lambda s: s.rolling(30, min_periods=1).mean())
df['adv40p'] = g['dv'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).mean())
df['hh40']   = g['high'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).max())
df['ll40']   = g['low'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).min())
df['max365'] = g['close'].transform(lambda s: s.rolling(365, min_periods=1).max())
df['dd']     = df['close'] / df['max365']
df['mindd120'] = g['dd'].transform(lambda s: s.rolling(120, min_periods=1).min())

# ── Signals (per SQL) ───────────────────────────────────────────────────────
sig_mask = (
    (df['rn'] >= RN_MIN)
    & (df['adv30'] >= ADV30_MIN)
    & (df['trade_date'] >= RNG_DATE_LO)
    & (df['trade_date'] <= RNG_DATE_HI)
    & (df['mindd120'] <= DD_RATIO_MAX)
    & ((df['hh40'] - df['ll40']) / df['hh40'] <= AMP_MAX)
    & (df['close'] > df['hh40'])
    & (df['close'] > df['sma200'])
    & (df['dv'] >= 2 * df['adv40p'])
)
sig = df[sig_mask].copy()
print(f'Signals (pre-recursive): {len(sig)}', flush=True)

# ── Per-symbol numpy arrays (fast look-ahead) ──────────────────────────────
sym_arr = {}
for sym, sdf in df.groupby('symbol', sort=False):
    sdf = sdf.sort_values('rn')
    sym_arr[sym] = {
        'open':  sdf['open'].to_numpy(),
        'high':  sdf['high'].to_numpy(),
        'low':   sdf['low'].to_numpy(),
        'close': sdf['close'].to_numpy(),
        'sma20': sdf['sma20'].to_numpy(),
        'atr14': sdf['atr14'].to_numpy(),   # §Seth-1020a: 进场前已知的 ATR
        'date':  sdf['trade_date'].to_numpy(),
    }
for sym in sym_arr:
    sym_arr[sym]['sma10'] = pd.Series(sym_arr[sym]['close']).rolling(10, min_periods=1).mean().to_numpy()


def simulate(sig_df, mode):
    """Run a management mode. Returns DataFrame of trades (1 row per signal)."""
    out = []
    last_exit_idx = {}    # sym -> int 0-based index of last exit
    for _, srow in sig_df.iterrows():
        sym = srow['symbol']
        a = sym_arr[sym]
        n = len(a['open'])
        ei = int(srow['rn'])           # entry-bar 0-based = signal_rn (1-based)
        if ei >= n:
            continue
        if sym in last_exit_idx and ei <= last_exit_idx[sym]:
            continue
        entry = a['open'][ei]
        stop  = max(srow['low'], entry - srow['atr14'])
        if entry <= stop:
            continue

        opens, highs, lows, closes = a['open'], a['high'], a['low'], a['close']
        sma20, sma10 = a['sma20'], a['sma10']

        leg_active      = True
        leg_half_taken  = False
        leg_tightened   = False        # M3
        cur_stop        = stop
        risk            = entry - stop
        leg_r_contribs  = []           # accumulated R-units across legs
        exit_idx_final  = ei

        end = min(ei + HOLD_MAX, n)
        i = ei
        while i < end and leg_active:
            # 1) Stop check (today's low)
            if lows[i] <= cur_stop:
                px = opens[i] if (i > ei and opens[i] <= cur_stop) else cur_stop
                if mode in ('M1','M2') and leg_half_taken:
                    leg_r_contribs.append(((px - entry) / risk - COST * entry / risk) * 0.5)
                else:
                    leg_r_contribs.append((px - entry) / risk - COST * entry / risk)
                leg_active = False
                exit_idx_final = i
                break
            # 2) Half-take (M1, M2) at +2R intraday
            if (mode in ('M1','M2')) and (not leg_half_taken):
                tgt = entry + M1_SCALE_OUT_R * risk
                if highs[i] >= tgt:
                    r = (tgt - entry) / risk - COST * entry / risk
                    leg_r_contribs.append(r * 0.5)
                    leg_half_taken = True
                    cur_stop = entry    # breakeven
            # 3) M3 tighten after +3R
            if (mode == 'M3') and (not leg_tightened):
                tgt3 = entry + M3_TIGHTEN_R * risk
                if highs[i] >= tgt3:
                    leg_tightened = True
            # 4) SMA trail (close < SMA). M3 uses SMA10 once tightened.
            trail = sma10[i] if (mode == 'M3' and leg_tightened) else sma20[i]
            if closes[i] < trail:
                j = i + 1 if i + 1 < n else i
                px = opens[j] if j > i else closes[j]
                if mode in ('M1','M2') and leg_half_taken:
                    leg_r_contribs.append(((px - entry) / risk - COST * entry / risk) * 0.5)
                else:
                    leg_r_contribs.append((px - entry) / risk - COST * entry / risk)
                leg_active = False
                exit_idx_final = j
                break
            i += 1
        if leg_active:
            j = end - 1
            px = closes[j]
            if mode in ('M1','M2') and leg_half_taken:
                leg_r_contribs.append(((px - entry) / risk - COST * entry / risk) * 0.5)
            else:
                leg_r_contribs.append((px - entry) / risk - COST * entry / risk)
            exit_idx_final = j

        # ── M2 re-entry (only if leg1 ended via stop/trail) ────────────
        if (mode == 'M2') and (not leg_active):
            window_end = min(exit_idx_final + M2_REENTRY_DAYS, n - 2)
            break_level = srow['hh40']
            re_ei = None
            for j in range(exit_idx_final + 1, window_end + 1):
                if closes[j] > break_level:
                    re_ei = j + 1
                    break
            if (re_ei is not None) and (re_ei < n):
                re_entry = opens[re_ei]
                # ── §Seth-1020a #2/#4 修订 (2026-10-21, T-140 r2) ────────────
                # 旧版 re_stop = lows[re_ei] = 进场当根最低价,而下面 k 从 re_ei 起
                # 第一根就查 lows[k] <= re_stop ⇒ 必然触发 ⇒ 每条 M2 再进腿都在进场
                # 当根按止损价出。止损必须是进场【前】已知的价:此处用复收日(信号
                # 收复日 j)的最低价,re_ei = j + 1 故 j = re_ei − 1。
                rec_j   = re_ei - 1
                atr_ref = float(a['atr14'][rec_j])     # ATR14 截至复收日,进场前已知
                if REENTRY_STOP_MODE == "recapture_low":
                    re_stop = float(lows[rec_j])       # 复收日最低价
                elif REENTRY_STOP_MODE == "entry_minus_atr":
                    re_stop = float(re_entry - atr_ref)
                else:
                    sys.exit(f"unknown REENTRY_STOP_MODE={REENTRY_STOP_MODE!r}")
                # §Seth-1020a #2 后半:风险过窄的再进丢弃并计数(R 分母会爆炸)
                if np.isfinite(atr_ref) and atr_ref > 0 \
                        and (re_entry - re_stop) < RE_MIN_ATR_MULT * atr_ref:
                    m2_rej_tight[0] += 1
                    re_entry = None
                if re_entry is not None and re_entry > re_stop:
                    re_risk = re_entry - re_stop
                    re_end  = min(re_ei + HOLD_MAX, n)
                    re_active = True
                    k = re_ei
                    while k < re_end and re_active:
                        if lows[k] <= re_stop:
                            px = opens[k] if (k > re_ei and opens[k] <= re_stop) else re_stop
                            leg_r_contribs.append((px - re_entry) / re_risk - COST * re_entry / re_risk)
                            re_active = False
                            exit_idx_final = k
                            break
                        if closes[k] < sma20[k]:
                            kx = k + 1 if k + 1 < n else k
                            px = opens[kx] if kx > k else closes[kx]
                            leg_r_contribs.append((px - re_entry) / re_risk - COST * re_entry / re_risk)
                            re_active = False
                            exit_idx_final = kx
                            break
                        k += 1
                    if re_active:
                        k = re_end - 1
                        px = closes[k]
                        leg_r_contribs.append((px - re_entry) / re_risk - COST * re_entry / re_risk)
                        exit_idx_final = k
                    # §Seth-1020a #3:记下每条 M2 再进腿的 (进场根, 出场根) 供自检
                    m2_re_legs.append((re_ei, exit_idx_final))

        total_R = float(sum(leg_r_contribs))
        out.append({
            'symbol': sym,
            'signal_date': srow['trade_date'],
            'entry_date': pd.Timestamp(a['date'][ei]),
            'exit_date':  pd.Timestamp(a['date'][exit_idx_final]),
            'entry': float(entry),
            'R': total_R,
            'mode': mode,
        })
        last_exit_idx[sym] = exit_idx_final

    return pd.DataFrame(out)


results = {}
for mode in ['M0','M1','M2','M3']:
    print(f'\n=== simulating {mode} ===', flush=True)
    results[mode] = simulate(sig, mode)
    t = results[mode]
    print(f'{mode}: n={len(t)}  meanR={t.R.mean():+.4f}  sumR={t.R.sum():+.2f}', flush=True)


# ── §Seth-1020a #3:能失败的自检(只对 M2) ────────────────────────────────
n_legs = len(m2_re_legs)
n_same = sum(1 for e, x in m2_re_legs if x == e)
same_frac = (n_same / n_legs) if n_legs else 0.0
m2_ok = same_frac <= RE_SAMEBAR_MAX
print(f'\n[selfcheck] M2 re-entry legs={n_legs}  exit_idx==entry_idx={n_same} '
      f'({same_frac:.2%})  limit={RE_SAMEBAR_MAX:.0%}  dropped_tight={m2_rej_tight[0]}  '
      f"stop_mode={REENTRY_STOP_MODE}  → {'PASS' if m2_ok else 'FAIL'}", flush=True)
# 落盘给 T-140 报告复用(同口径重跑的结果)
m2_selfcheck = {
    'legs': n_legs, 'samebar': n_same, 'samebar_frac': same_frac,
    'samebar_limit': RE_SAMEBAR_MAX, 'pass': bool(m2_ok),
    'dropped_tight': m2_rej_tight[0], 're_min_atr_mult': RE_MIN_ATR_MULT,
    'stop_mode': REENTRY_STOP_MODE,
    'M0': {'n': int(len(results['M0'])), 'meanR': float(results['M0'].R.mean()),
           'sumR': float(results['M0'].R.sum())},
    'M2': {'n': int(len(results['M2'])),
           'meanR': float(results['M2'].R.mean()),
           'sumR': float(results['M2'].R.sum())},
}
with open('/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/'
          f'T-131_s612_m2_r2_{REENTRY_STOP_MODE}.json', 'w') as f:
    json.dump(m2_selfcheck, f, indent=2)
print(f"[selfcheck] wrote T-131_s612_m2_r2_{REENTRY_STOP_MODE}.json", flush=True)


# ── Sanity: M0 must reproduce R-G0 within ±1% / ±0.01 ──────────────────────
m0 = results['M0']
n0, mr0 = len(m0), m0.R.mean()
print(f'\nS-610 M0 check:  n={n0} (target 1013 ±1%) → {(n0-1013)/1013*100:+.2f}%  '
      f'meanR={mr0:+.4f} (target 0.350 ±0.01) → Δ={mr0-0.350:+.4f}', flush=True)


def stats(trades, label):
    r = trades['R'].to_numpy()
    n = len(trades)
    bands = {
        '2020-22': (pd.Timestamp('2020-03-01'), pd.Timestamp('2022-12-31')),
        '2023-24': (pd.Timestamp('2023-01-01'), pd.Timestamp('2024-12-31')),
        '2025-26': (pd.Timestamp('2025-01-01'), pd.Timestamp('2026-12-31')),
    }
    band_means, band_ns = {}, {}
    for b, (lo, hi) in bands.items():
        m = (trades.entry_date >= lo) & (trades.entry_date <= hi)
        band_means[b] = float(r[m].mean()) if m.sum() else float('nan')
        band_ns[b]    = int(m.sum())
    y23 = (trades.entry_date >= pd.Timestamp('2023-01-01')) & \
          (trades.entry_date <= pd.Timestamp('2023-12-31'))
    y23_sum, y23_n = float(r[y23].sum()), int(y23.sum())
    wins   = r[r > 0]
    losses = r[r <= 0]
    pf      = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float('inf')
    avg_win = float(wins.mean())   if len(wins)   else float('nan')
    avg_los = float(losses.mean()) if len(losses) else float('nan')
    top5_removed_mean = float(np.sort(r)[:-5].mean()) if n > 5 else float('nan')
    streak = longest = 0
    for x in r:
        if x <= 0:
            streak += 1; longest = max(longest, streak)
        else:
            streak = 0
    eq    = np.cumsum(r)
    peaks = np.maximum.accumulate(np.concatenate([[0], eq]))[1:]
    max_dd_R = float((peaks - eq).max()) if len(eq) else 0.0
    if n:
        days  = (trades.entry_date.max() - trades.entry_date.min()).days
        years = max(days / 365.25, 0.01)
        ann_R = float(r.sum() / years)
        n_per_year = n / years
    else:
        ann_R = n_per_year = 0.0
    return {
        'label': label, 'n': n,
        'mean_r': float(r.mean()) if n else float('nan'),
        'median_r': float(np.median(r)) if n else float('nan'),
        'win_rate': float((r > 0).mean()) if n else float('nan'),
        'mean_no_top5': top5_removed_mean,
        'profit_factor': pf,
        'avg_win': avg_win, 'avg_loss': avg_los,
        'band_means': band_means, 'band_ns': band_ns,
        'y23_sum': y23_sum, 'y23_n': y23_n,
        'longest_losing_streak': int(longest),
        'max_dd_R': max_dd_R,
        'annualized_R': ann_R,
        'n_per_year': n_per_year,
    }


stats_all = {m: stats(results[m], m) for m in results}

for m, t in results.items():
    t.to_csv(os.path.join(OUT_DIR, f'trades_{m}.csv'), index=False)
with open(os.path.join(OUT_DIR, 't131_stats.json'), 'w') as f:
    json.dump(stats_all, f, indent=2, default=str)

print('\n=== M0–M3 STATS ===')
print(json.dumps(stats_all, indent=2, default=str))

# ── 报告落盘后才中止:自检不过 ⇒ 数字留档供 @seth 重校阈值,退出码非 0 ─────
if not m2_ok:
    sys.exit(f'SELF-CHECK FAIL (§Seth-1020a #3, stop_mode={REENTRY_STOP_MODE}): '
             f'M2 再进腿 exit_idx==entry_idx 占比 {same_frac:.2%} > {RE_SAMEBAR_MAX:.0%} '
             f'({n_same}/{n_legs})。M2 结论不作数 —— 已落盘,阈值需 @seth 重校。')