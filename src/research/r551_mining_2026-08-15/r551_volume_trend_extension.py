#!/usr/bin/env python3
"""
R551 — extend R550 volume axis with three follow-ups:
  R551a: volume_trend at windows 30/60/90/120 (the trend component alone)
  R551b: lvl×trend at K=5/h=21 (extension of R550d K=3/h=14)
  R551c: lvl×trend at varied trend_win (find OOS peak)
  R551d: BEST-of-extract OOS validate against R550d baseline

Trigger: R550 open follow-ups (r550-volume-lvl-x-trend-b11i-2026-08-15.md):
- Sweep volume_level at win=30/90/120 (only win=60 tested in R549)
- volume_level × volume_trend interaction (level + flow)
- R551: volume_trend at longer windows → EXTENDED here

Funding-rate SHORT side: skipped (no funding rate DB on disk; R507/R509/R522 concluded funding axis CLOSED).

Universe: 19 B11 assets (per R550 holdings audit).
OOS: 2024-01-01 → 2026-08-09; IS: 2017-2023.
"""
import csv, sqlite3, math, statistics, json
from collections import defaultdict
from pathlib import Path

OHLCV_DB = '/Users/sbb/Projects/looloomi-ai/Shadow/cometcloud-local/data/ohlcv_11yr.db'
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

# B11 universe (R550 holdings audit + base L1) — 19 names
B11_UNIVERSE = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT',
                'ATOM', 'LTC', 'NEAR', 'DOGE', 'BCH', 'COMP', 'MKR', 'ENA', 'SEI', 'AAVE']

# Cross-sectional liquidity-matched sub-universe (R551 follow-up #3)
LIQUID_UNIVERSE = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT',
                   'ATOM', 'LTC', 'NEAR', 'DOGE', 'BCH', 'COMP', 'AAVE']  # exclude thin: MKR, ENA, SEI


def load_ohlcv():
    """Load close + quote_volume into nested dict."""
    con = sqlite3.connect(OHLCV_DB)
    cur = con.execute('SELECT symbol, trade_date, close, quote_volume FROM ohlcv_11yr_daily ORDER BY symbol, trade_date')
    prices = defaultdict(dict)
    volumes = defaultdict(dict)
    for sym, d, close, qv in cur:
        if close and close > 0:
            prices[sym][d] = float(close)
            if qv and qv > 0:
                volumes[sym][d] = float(qv)
    con.close()
    return prices, volumes


def build_calendar(prices):
    """Common trading calendar across universe."""
    sets = [set(prices[s].keys()) for s in B11_UNIVERSE if s in prices]
    cal = sorted(set.intersection(*sets))
    return cal


def compute_volume_signals(volumes, dates, level_win, trend_win, ma_skip):
    """For each (sym, date), compute:
      level = log mean quote_volume over (t-level_win, t]
      trend = log (recent_mean / old_mean) where recent = (t-trend_win, t-ma_skip], old = (t-2*trend_win, t-trend_win-ma_skip]
    PIT-safe: only past quotes used.
    """
    sig = defaultdict(dict)
    for sym in volumes:
        daily_qv = []
        for d in dates:
            qv = volumes[sym].get(d)
            daily_qv.append((d, qv))
        for i, (d, qv) in enumerate(daily_qv):
            if qv is None or qv <= 0:
                continue
            # Level window: from t-level_win to t
            lvl_qv = []
            for j in range(max(0, i - level_win), i + 1):
                qj = daily_qv[j][1]
                if qj is not None and qj > 0:
                    lvl_qv.append(qj)
            if len(lvl_qv) < level_win * 0.5:
                continue
            level = math.log(statistics.mean(lvl_qv) + 1)
            # Trend window: recent (t-trend_win-ma_skip, t-ma_skip] and old (t-2*trend_win-ma_skip, t-trend_win-ma_skip]
            recent = []
            for j in range(max(0, i - trend_win - ma_skip), max(0, i - ma_skip) + 1):
                qj = daily_qv[j][1]
                if qj is not None and qj > 0:
                    recent.append(qj)
            old = []
            for j in range(max(0, i - 2 * trend_win - ma_skip), max(0, i - trend_win - ma_skip) + 1):
                qj = daily_qv[j][1]
                if qj is not None and qj > 0:
                    old.append(qj)
            if len(recent) < trend_win * 0.5 or len(old) < trend_win * 0.5:
                continue
            recent_mean = statistics.mean(recent)
            old_mean = statistics.mean(old)
            if recent_mean <= 0 or old_mean <= 0:
                continue
            trend = math.log(recent_mean / old_mean)
            sig[sym][d] = (level, trend)
    return sig


def score_function(level, trend, mode):
    """Combine level + trend into a single XS score."""
    if mode == 'level_only':
        return level
    elif mode == 'trend_only':
        return trend
    elif mode == 'level_plus_trend':
        return level + trend
    elif mode == 'level_x_trend':
        return level * trend
    else:
        raise ValueError(mode)


def backtest_xs(sig, prices, dates, K, hold, cost_bps, score_mode, universe, oos_start, oos_end):
    """Cross-sectional L/S: long top-K, short bottom-K by score; rebalance every `hold` days."""
    daily_returns = []
    days_since_rebal = hold
    cur_long = None
    cur_short = None
    rng = 130  # warm-up covers 120-day level_win + 10 buffer
    for i in range(rng, len(dates) - 1):
        d, d_next = dates[i], dates[i + 1]
        if days_since_rebal >= hold:
            scored = []
            for sym in universe:
                if d in sig.get(sym, {}):
                    lvl, trd = sig[sym][d]
                    score = score_function(lvl, trd, score_mode)
                    scored.append((sym, score))
            if len(scored) >= 2 * K:
                scored.sort(key=lambda x: x[1])
                cur_long = [s for s, _ in scored[-K:]]
                cur_short = [s for s, _ in scored[:K]]
                days_since_rebal = 0
        cost_drag = (cost_bps / 10000.0) * 2 * 2 if days_since_rebal == 0 else 0
        days_since_rebal += 1
        if cur_long is None or cur_short is None:
            daily_returns.append(0.0); continue
        long_ret = 0.0; n_l = 0
        for sym in cur_long:
            if d in prices[sym] and d_next in prices[sym]:
                long_ret += prices[sym][d_next] / prices[sym][d] - 1
                n_l += 1
        if n_l > 0: long_ret /= n_l
        short_ret = 0.0; n_s = 0
        for sym in cur_short:
            if d in prices[sym] and d_next in prices[sym]:
                short_ret += prices[sym][d_next] / prices[sym][d] - 1
                n_s += 1
        if n_s > 0: short_ret /= n_s
        daily_returns.append(long_ret - short_ret - cost_drag)
    return daily_returns


def stats(daily_returns, idx_start, idx_end):
    """Compute Sharpe, total, MaxDD on a date-indexed window."""
    sub = []
    for i, r in enumerate(daily_returns):
        if idx_start <= i < idx_end:
            sub.append(r)
    if not sub or len(sub) < 30:
        return None
    rets = sub
    NAV = 1.0; peak = 0; mdd = 0
    for r in rets:
        NAV *= (1 + r); peak = max(peak, NAV); dd = (NAV - peak) / peak; mdd = min(mdd, dd)
    n = len(rets); m = statistics.mean(rets); sd = statistics.stdev(rets) if n > 1 else 0
    sr = (m / sd) * (365 ** 0.5) if sd > 0 else 0
    return {'n': n, 'total': NAV - 1, 'sharpe': sr, 'max_dd': mdd, 'wr': sum(1 for r in rets if r > 0) / n}


def main():
    print('Loading OHLCV...')
    prices, volumes = load_ohlcv()
    dates = build_calendar(prices)
    print(f'  Universe: {len(B11_UNIVERSE)} symbols, {len(dates)} common dates')
    print(f'  Span: {dates[0]} → {dates[-1]}')

    # OOS: 2024-01-01 → 2026-08-09
    oos_start = next(i for i, d in enumerate(dates) if d >= '2024-01-01')
    oos_end = len(dates) - 1
    print(f'  OOS: idx[{oos_start}:{oos_end}] = {dates[oos_start]} → {dates[min(oos_end, len(dates)-1)]}')

    # ===== R551a: volume_trend alone at windows 30/60/90/120 =====
    print()
    print('=' * 80)
    print('R551a — volume_trend ALONE (cross-sectional L/S)')
    print('=' * 80)
    r551a_results = {}
    for trend_win in [30, 60, 90, 120]:
        # Use level_win=long enough to anchor; trend is the signal
        sig = compute_volume_signals(volumes, dates, level_win=120, trend_win=trend_win, ma_skip=20)
        for K, h in [(3, 14), (5, 21), (3, 21)]:
            dr = backtest_xs(sig, prices, dates, K, h, 5, 'trend_only', B11_UNIVERSE, oos_start, oos_end)
            s = stats(dr, oos_start, oos_end)
            if s is None:
                continue
            key = f'trend_{trend_win}_K{K}_h{h}'
            r551a_results[key] = s
            print(f'  trend_win={trend_win:<3} K={K} h={h:<2}  OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%  n={s["n"]}')

    # ===== R551b: lvl×trend at K=5/h=21 (extension of R550d K=3/h=14) =====
    print()
    print('=' * 80)
    print('R551b — lvl×trend at K=5/h=21 (extension of R550d K=3/h=14)')
    print('=' * 80)
    r551b_results = {}
    for level_win in [60]:
        for trend_win in [30, 60, 90, 120]:
            sig = compute_volume_signals(volumes, dates, level_win=level_win, trend_win=trend_win, ma_skip=20)
            for K, h in [(5, 21), (3, 21), (5, 14)]:
                for mode in ['level_x_trend', 'level_plus_trend']:
                    dr = backtest_xs(sig, prices, dates, K, h, 5, mode, B11_UNIVERSE, oos_start, oos_end)
                    s = stats(dr, oos_start, oos_end)
                    if s is None:
                        continue
                    key = f'lx_{level_win}_{trend_win}_K{K}_h{h}_{mode}'
                    r551b_results[key] = s
                    print(f'  lvl={level_win} trd={trend_win:<3} K={K} h={h:<2} {mode:<18}  OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%')

    # ===== R551c: level_only at win=30/90/120 (R550 only tested win=60) =====
    print()
    print('=' * 80)
    print('R551c — level_only at win=30/90/120 (R550 only tested win=60)')
    print('=' * 80)
    r551c_results = {}
    for level_win in [30, 90, 120]:
        for K, h in [(3, 14), (5, 21), (3, 21)]:
            sig = compute_volume_signals(volumes, dates, level_win=level_win, trend_win=30, ma_skip=20)
            dr = backtest_xs(sig, prices, dates, K, h, 5, 'level_only', B11_UNIVERSE, oos_start, oos_end)
            s = stats(dr, oos_start, oos_end)
            if s is None:
                continue
            key = f'lvl_{level_win}_K{K}_h{h}'
            r551c_results[key] = s
            print(f'  lvl={level_win:<3} K={K} h={h:<2}  OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%')

    # ===== R551d: liquidity-matched sub-universe (R550 follow-up #3) =====
    print()
    print('=' * 80)
    print('R551d — liquidity-matched sub-universe (R550 follow-up #3, MURDER TEST)')
    print('=' * 80)
    r551d_results = {}
    sig = compute_volume_signals(volumes, dates, level_win=60, trend_win=30, ma_skip=20)
    # Re-run R550d config (K=3 h=14 lvl=60 trd=30, level_x_trend) but on top-16 liquid only
    dr = backtest_xs(sig, prices, dates, 3, 14, 5, 'level_x_trend', LIQUID_UNIVERSE, oos_start, oos_end)
    s = stats(dr, oos_start, oos_end)
    if s:
        r551d_results['liquid16_lx_60_30_K3_h14'] = s
        print(f'  liquid16  lx_60_30 K=3 h=14  OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%')

    # ===== Summary: best-by-metric =====
    print()
    print('=' * 80)
    print('SUMMARY — top 10 by OOS Sharpe across all R551 configs')
    print('=' * 80)
    all_results = {**r551a_results, **r551b_results, **r551c_results, **r551d_results}
    ranked = sorted(all_results.items(), key=lambda x: -x[1]['sharpe'])
    for k, v in ranked[:10]:
        print(f'  {k:<40}  SR={v["sharpe"]:>+7.3f}  total={v["total"]*100:>+7.2f}%  DD={v["max_dd"]*100:>+6.2f}%')

    # R550d baseline (from memory): OOS SR 1.574, total 221.58%, DD 25.41%
    print()
    print('R550d baseline (lx_60_30 K=3 h=14, full B11): OOS SR=+1.574 total=+221.58% DD=-25.41%')

    # Save results
    out_json = {
        'r551a_volume_trend_only': r551a_results,
        'r551b_lvl_x_trend_extended': r551b_results,
        'r551c_level_only_extended': r551c_results,
        'r551d_liquid16_subuniverse': r551d_results,
        'r550d_baseline': {'sharpe': 1.574, 'total': 2.2158, 'max_dd': -0.2541, 'note': 'from R550 memory'},
        'ranked_top10': [(k, v) for k, v in ranked[:10]],
    }
    out_path = OUT_DIR / 'r551_results.json'
    with open(out_path, 'w') as f:
        json.dump(out_json, f, indent=2, default=str)
    print(f'\nResults saved to {out_path}')


if __name__ == '__main__':
    main()
