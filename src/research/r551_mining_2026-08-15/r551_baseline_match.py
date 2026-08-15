#!/usr/bin/env python3
"""
R551e — apples-to-apples baseline check.
R551 OOS was 2024-04-02 → 2025-09-15 (401d, 19-symbol universe constraint).
R550d baseline SR=+1.574 was on a different window. Compute R550d on THIS window
so the comparison is fair.
"""
import sqlite3, math, statistics, json
from collections import defaultdict
from pathlib import Path

OHLCV_DB = '/Users/sbb/Projects/looloomi-ai/Shadow/cometcloud-local/data/ohlcv_11yr.db'
OUT_DIR = Path(__file__).resolve().parent

B11_UNIVERSE = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT',
                'ATOM', 'LTC', 'NEAR', 'DOGE', 'BCH', 'COMP', 'MKR', 'ENA', 'SEI', 'AAVE']
LIQUID_UNIVERSE = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT',
                   'ATOM', 'LTC', 'NEAR', 'DOGE', 'BCH', 'COMP', 'AAVE']


def load_ohlcv():
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


def build_calendar(prices, universe):
    sets = [set(prices[s].keys()) for s in universe if s in prices]
    cal = sorted(set.intersection(*sets))
    return cal


def compute_volume_signals(volumes, dates, level_win, trend_win, ma_skip):
    sig = defaultdict(dict)
    for sym in volumes:
        daily_qv = []
        for d in dates:
            qv = volumes[sym].get(d)
            daily_qv.append((d, qv))
        for i, (d, qv) in enumerate(daily_qv):
            if qv is None or qv <= 0:
                continue
            lvl_qv = []
            for j in range(max(0, i - level_win), i + 1):
                qj = daily_qv[j][1]
                if qj is not None and qj > 0:
                    lvl_qv.append(qj)
            if len(lvl_qv) < level_win * 0.5:
                continue
            level = math.log(statistics.mean(lvl_qv) + 1)
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


def backtest_xs(sig, prices, dates, K, hold, cost_bps, score_mode, universe, oos_start, oos_end):
    daily_returns = []
    days_since_rebal = hold
    cur_long = None
    cur_short = None
    rng = 130
    for i in range(rng, len(dates) - 1):
        d, d_next = dates[i], dates[i + 1]
        if days_since_rebal >= hold:
            scored = []
            for sym in universe:
                if d in sig.get(sym, {}):
                    lvl, trd = sig[sym][d]
                    if score_mode == 'level_x_trend':
                        score = lvl * trd
                    elif score_mode == 'level_only':
                        score = lvl
                    elif score_mode == 'trend_only':
                        score = trd
                    else:
                        score = lvl + trd
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
    prices, volumes = load_ohlcv()

    print('=' * 80)
    print('R551e — apples-to-apples baseline check on the SAME 401d OOS window')
    print('=' * 80)
    print('OOS window: 2024-04-02 → 2025-09-15 (401 trading days)')
    print('Constraint: 19-symbol B11 universe intersection (MKR/ENA/SEI bottleneck)')
    print()

    # === B11 universe, R550d config ===
    dates_b11 = build_calendar(prices, B11_UNIVERSE)
    print(f'B11 universe: {len(dates_b11)} common dates = {dates_b11[0]} → {dates_b11[-1]}')
    oos_start = next(i for i, d in enumerate(dates_b11) if d >= '2024-06-01')
    oos_end = len(dates_b11) - 1
    print(f'  OOS: idx[{oos_start}:{oos_end}] = {dates_b11[oos_start]} → {dates_b11[oos_end]}')

    sig = compute_volume_signals(volumes, dates_b11, level_win=60, trend_win=30, ma_skip=20)
    dr = backtest_xs(sig, prices, dates_b11, 3, 14, 5, 'level_x_trend', B11_UNIVERSE, oos_start, oos_end)
    s = stats(dr, oos_start, oos_end)
    if s:
        print(f'  R550d (B11, lx_60_30 K=3 h=14, 401d): OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%  n={s["n"]}')

    # === Liquid16 sub-universe, same R550d config ===
    dates_liq = build_calendar(prices, LIQUID_UNIVERSE)
    print(f'\nLIQUID16 universe: {len(dates_liq)} common dates = {dates_liq[0]} → {dates_liq[-1]}')
    # Use same OOS dates for direct comparison
    oos_start_liq = next(i for i, d in enumerate(dates_liq) if d >= dates_b11[oos_start])
    oos_end_liq = next(i for i, d in enumerate(dates_liq) if d >= dates_b11[oos_end]) - 1
    print(f'  OOS mirror: idx[{oos_start_liq}:{oos_end_liq}] = {dates_liq[oos_start_liq]} → {dates_liq[oos_end_liq]}')

    sig_liq = compute_volume_signals(volumes, dates_liq, level_win=60, trend_win=30, ma_skip=20)
    dr = backtest_xs(sig_liq, prices, dates_liq, 3, 14, 5, 'level_x_trend', LIQUID_UNIVERSE, oos_start_liq, oos_end_liq)
    s = stats(dr, oos_start_liq, oos_end_liq)
    if s:
        print(f'  R550d (LIQ16, lx_60_30 K=3 h=14, 401d): OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%  n={s["n"]}')

    # === Liquid16 sub-universe, level_only — does level survive liquidity cut? ===
    print()
    print('Liquid16 ablations:')
    for K, h in [(3, 14), (3, 21), (5, 21)]:
        for level_win in [30, 60, 90, 120]:
            sig_liq = compute_volume_signals(volumes, dates_liq, level_win=level_win, trend_win=30, ma_skip=20)
            dr = backtest_xs(sig_liq, prices, dates_liq, K, h, 5, 'level_only', LIQUID_UNIVERSE, oos_start_liq, oos_end_liq)
            s = stats(dr, oos_start_liq, oos_end_liq)
            if s:
                print(f'  level_only  lvl={level_win} K={K} h={h}: OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%')

    # === B11 universe, level_only — the strong baseline ===
    print()
    print('B11 ablations (full universe baseline):')
    for K, h in [(3, 14), (3, 21), (5, 21)]:
        for level_win in [30, 60, 90, 120]:
            sig = compute_volume_signals(volumes, dates_b11, level_win=level_win, trend_win=30, ma_skip=20)
            dr = backtest_xs(sig, prices, dates_b11, K, h, 5, 'level_only', B11_UNIVERSE, oos_start, oos_end)
            s = stats(dr, oos_start, oos_end)
            if s:
                print(f'  level_only  lvl={level_win} K={K} h={h}: OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%')

    # === Liquid16, level_plus_trend (the R550d score mode) ===
    print()
    print('Liquid16, level_plus_trend (alternative score mode):')
    for K, h in [(3, 14), (3, 21)]:
        for level_win in [60]:
            for trend_win in [30, 60, 90]:
                sig_liq = compute_volume_signals(volumes, dates_liq, level_win=level_win, trend_win=trend_win, ma_skip=20)
                dr = backtest_xs(sig_liq, prices, dates_liq, K, h, 5, 'level_plus_trend', LIQUID_UNIVERSE, oos_start_liq, oos_end_liq)
                s = stats(dr, oos_start_liq, oos_end_liq)
                if s:
                    print(f'  level_plus_trend  lvl={level_win} trd={trend_win} K={K} h={h}: OOS SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%')


if __name__ == '__main__':
    main()
