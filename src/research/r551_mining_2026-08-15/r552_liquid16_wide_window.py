#!/usr/bin/env python3
"""
R552 — extend R551 LIQUID16 findings to wider OOS window.

R551 finding: LIQUID16 + level_only lvl=30 K=5 h=21 = SR=+0.933 on 470d window.
R551 caveat: 401d window in B11 universe is bottlenecked by ENA/MKR/SEI.

R552 goal: extend the OOS window by using LIQUID16 (available 2020-10-15 → 2026-08-09).
Test whether:
  (a) R550d (level_x_trend lvl=60 trd=30 K=3 h=14) survives on LIQUID16 with 6y window
  (b) level_only lvl=30 K=5 h=21 (R551 best) survives on LIQUID16 with 6y window
  (c) Other level_only configurations hold up wider window

This is the apples-to-apples test R551 could not answer.
"""
import sqlite3, math, statistics, json
from collections import defaultdict
from pathlib import Path

OHLCV_DB = '/Users/sbb/Projects/looloomi-ai/Shadow/cometcloud-local/data/ohlcv_11yr.db'
OUT_DIR = Path(__file__).resolve().parent

LIQUID16 = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT',
            'ATOM', 'LTC', 'NEAR', 'DOGE', 'BCH', 'COMP', 'AAVE']
B11 = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'AVAX', 'LINK', 'DOT',
       'ATOM', 'LTC', 'NEAR', 'DOGE', 'BCH', 'COMP', 'MKR', 'ENA', 'SEI', 'AAVE']


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
    return sorted(set.intersection(*sets))


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
    print('R552 — LIQUID16 wider OOS window (full 2020-10 → 2026-08 history)')
    print('=' * 80)

    # LIQUID16 universe has data from 2020-10-15 → 2026-08-09
    dates_liq = build_calendar(prices, LIQUID16)
    print(f'LIQUID16 cal: {len(dates_liq)} dates = {dates_liq[0]} → {dates_liq[-1]}')

    # Use full OOS: 2022-01-01 → 2026-08-09 (~4.5 years)
    oos_start = next(i for i, d in enumerate(dates_liq) if d >= '2022-01-01')
    oos_end = len(dates_liq) - 1
    print(f'OOS: idx[{oos_start}:{oos_end}] = {dates_liq[oos_start]} → {dates_liq[oos_end]} ({oos_end - oos_start} days)')

    # ============== R550d on LIQUID16 wide window ==============
    print()
    print('=== R550d (level_x_trend lvl=60 trd=30 K=3 h=14) on LIQUID16 wide ===')
    sig = compute_volume_signals(volumes, dates_liq, level_win=60, trend_win=30, ma_skip=20)
    dr = backtest_xs(sig, prices, dates_liq, 3, 14, 5, 'level_x_trend', LIQUID16, oos_start, oos_end)
    s = stats(dr, oos_start, oos_end)
    if s:
        print(f'  R550d_LIQ16_wide: SR={s["sharpe"]:>+7.3f}  total={s["total"]*100:>+7.2f}%  DD={s["max_dd"]*100:>+6.2f}%  n={s["n"]}')

    # ============== Per-year breakdown R550d on LIQUID16 ==============
    print()
    print('=== R550d per-year (LIQUID16 wide) ===')
    for year in [2022, 2023, 2024, 2025, 2026]:
        y_start = next((i for i, d in enumerate(dates_liq) if d >= f'{year}-01-01'), None)
        y_end = next((i for i, d in enumerate(dates_liq) if d >= f'{year+1}-01-01'), len(dates_liq))
        if y_start is None or y_start >= oos_end:
            continue
        sy = stats(dr, y_start, min(y_end, oos_end))
        if sy:
            print(f'  {year}: SR={sy["sharpe"]:>+7.3f}  total={sy["total"]*100:>+7.2f}%  DD={sy["max_dd"]*100:>+6.2f}%  n={sy["n"]}')

    # ============== level_only sweep on LIQUID16 wide ==============
    print()
    print('=== level_only sweep on LIQUID16 wide window ===')
    ranked = []
    for level_win in [30, 60, 90, 120]:
        for K, h in [(3, 14), (3, 21), (5, 14), (5, 21)]:
            sig = compute_volume_signals(volumes, dates_liq, level_win=level_win, trend_win=30, ma_skip=20)
            dr = backtest_xs(sig, prices, dates_liq, K, h, 5, 'level_only', LIQUID16, oos_start, oos_end)
            s = stats(dr, oos_start, oos_end)
            if s:
                ranked.append((f'lvl_{level_win}_K{K}_h{h}', s))
    ranked.sort(key=lambda x: -x[1]['sharpe'])
    for k, v in ranked[:10]:
        print(f'  {k:<28}  SR={v["sharpe"]:>+7.3f}  total={v["total"]*100:>+7.2f}%  DD={v["max_dd"]*100:>+6.2f}%  n={v["n"]}')

    # ============== Per-year breakdown — top-3 level_only on LIQUID16 wide ==============
    print()
    print('=== Per-year breakdown of top-3 level_only (LIQUID16 wide) ===')
    for k, _ in ranked[:3]:
        parts = k.split('_')
        level_win = int(parts[1])
        K = int(parts[2][1:]); h = int(parts[3][1:])
        sig = compute_volume_signals(volumes, dates_liq, level_win=level_win, trend_win=30, ma_skip=20)
        dr = backtest_xs(sig, prices, dates_liq, K, h, 5, 'level_only', LIQUID16, oos_start, oos_end)
        print(f'\n  {k}:')
        for year in [2022, 2023, 2024, 2025, 2026]:
            y_start = next((i for i, d in enumerate(dates_liq) if d >= f'{year}-01-01'), None)
            y_end = next((i for i, d in enumerate(dates_liq) if d >= f'{year+1}-01-01'), len(dates_liq))
            if y_start is None or y_start >= oos_end:
                continue
            sy = stats(dr, y_start, min(y_end, oos_end))
            if sy:
                print(f'    {year}: SR={sy["sharpe"]:>+6.2f}  total={sy["total"]*100:>+6.1f}%  DD={sy["max_dd"]*100:>+5.1f}%')

    # ============== Hold the verdict ==============
    print()
    print('=' * 80)
    print('R552 verdict')
    print('=' * 80)
    print('R550d on LIQUID16 wide window SR=+1.367 was on 470d (2024-06-01 → 2025-09-14).')
    print('Wide window SR above is the apples-to-apples test.')
    print('If R550d.wide > level_only.top1.wide: R550d IS a real signal, my LIQUID16 R551 was wrong.')
    print('If R550d.wide < level_only.top1.wide: R551 verdict confirmed.')


if __name__ == '__main__':
    main()
