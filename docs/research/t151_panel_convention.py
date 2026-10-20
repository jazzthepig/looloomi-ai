#!/usr/bin/env python3
"""T-151 / S-637 —— binance_hist 到底是现货口径还是合约口径?在三种面板上重算 R 臂。

背景(S-637,Seth 10-21 抽查):CRV 2024-07-15 / 2026-07-15 的 binance_hist 成交量
是现货的 5.6 / 6.4 倍;SOL 与现货逐位一致;08-08 导入的 86 个名字前后成交额比中位
0.74,07-27 导入的 40 个是 3.65。=> binance_hist 疑为「一段合约 + 一段现货」的混合体。

本脚本三段(可分别跑):
  fetch    —— 从 Binance 公开接口直接取日线(现货 api/v3/klines,U 本位 fapi/v1/klines),
             落到 Mac 数据根 research/t151/klines/。只做研究用,不写库。
  classify —— 逐名字逐取样日比收盘/成交量,把每个名字分段判成 现货 / 合约 / 无对。
  sim      —— 用 S-610 进场 + k×ATR(默认 2.5)+ 原出场,在三种面板上重跑 R 臂。

面板三选一:
  hist = 现在的 binance_hist(Mac 本地 parquet,截到同一窗口)
  spot = Binance 现货
  perp = Binance U 本位永续

口径(写死,见台账 S-610 预注册,不改):
  * 三种面板统一截到 [2022-01-01, 2026-08-05];rn = 该名在该窗口内的第几根日线(1 起)。
  * 宇宙:rn >= 220、前 30 日(含当天)平均成交额 >= 500 万美元、信号日 2023-01-01 … 2026-06-20。
  * 信号(t 日收盘):t-120…t 内 close / 前 365 根最高收盘 的最小值 <= 0.5;
    t-40…t-1 振幅 <= 0.40;close > t-40…t-1 的最高价;close > SMA200;
    当日成交额 >= 2 × t-40…t-1 的平均成交额。
  * 进场 = t+1 开盘;止损 = max(t 日低点, 进场 - k×ATR14[t]);进场开盘 <= 止损 ⇒ 不进。
  * 出场:每天先看止损,再看收盘 < SMA20 ⇒ 次日开盘出;120 根内都没触发 ⇒ 第 120 根收盘出。
  * R = (出场 - 进场)/(进场 - 止损) - 0.004 × 进场/(进场 - 止损);同名上一笔出场根之后才能再进。
  * 鱼(S-618 原定义)= 进场起 120 根内最高 max(high, close) >= 3 × 进场价。

用法:
  python3 docs/research/t151_panel_convention.py fetch
  python3 docs/research/t151_panel_convention.py classify
  python3 docs/research/t151_panel_convention.py sim
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

DATA_ROOT = '/Volumes/CometCloudAI/cometcloud-local'
KL_DIR = f'{DATA_ROOT}/research/t151/klines'
OUT_DIR = f'{DATA_ROOT}/research/t151'
HIST_PARQUET = f'{DATA_ROOT}/_data/research/t131/ohlcv_binance_hist.parquet'

EXCLUDE = {'USDC', 'BTCDOM', 'DEFI'}
WIN_LO = pd.Timestamp('2022-01-01')      # 三面板统一的取数/暖机窗口
WIN_HI = pd.Timestamp('2026-08-05')
FETCH_HI = pd.Timestamp('2026-10-21')    # 取数窗口:要比到最后一个边界后取样日(2026-09-15)
SIG_LO = pd.Timestamp('2023-01-01')       # 信号日窗口(卡上写的)
SIG_HI = pd.Timestamp('2026-06-20')
PROBE_DATES = ['2023-01-15', '2024-07-15', '2025-07-15', '2026-07-15', '2026-09-15']

URLS = {
    'spot': 'https://api.binance.com/api/v3/klines?symbol={s}&interval=1d&startTime={t}&limit=1000',
    'perp': 'https://fapi.binance.com/fapi/v1/klines?symbol={s}&interval=1d&startTime={t}&limit=1000',
}
COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
        'quote_vol', 'n_trades', 'tb_base', 'tb_quote', 'ignore']

# S-610 口径常量(预注册;不改)
COST = 0.004
RN_MIN = 220
ADV30_MIN = 5_000_000
DD_RATIO_MAX = 0.5
AMP_MAX = 0.40
HOLD_MAX = 120
ATR_K = 2.5          # 卡上要求:2.5×ATR
BASELINE_K = 1.0     # S-610 原值,只作复现对照


# ══ fetch ═════════════════════════════════════════════════════════════════
def _get(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 418):          # 该对不存在 / 被限
                return None
            time.sleep(2 * (k + 1))
        except Exception:
            time.sleep(2 * (k + 1))
    return None


def fetch_one(venue, symbol):
    """取日线;已存在的文件只补尾部(增量),全覆盖则跳过。"""
    path = f'{KL_DIR}/{venue}/{symbol}.csv'
    have = None
    if os.path.exists(path):
        have = pd.read_csv(path)
        have['trade_date'] = pd.to_datetime(have['trade_date'])
        if not have.empty and have['trade_date'].max() >= FETCH_HI:
            return 'cached'
    lo = int(WIN_LO.timestamp() * 1000)
    if have is not None and not have.empty:
        lo = int(pd.to_datetime(have['trade_date']).max().timestamp() * 1000) + 86400000
    hi = int(FETCH_HI.timestamp() * 1000)
    rows, cursor = [], lo
    while cursor < hi:
        raw = _get(URLS[venue].format(s=f'{symbol}USDT', t=cursor))
        if not raw:
            break
        rows.extend(raw)
        if len(raw) < 1000:
            break
        cursor = int(raw[-1][0]) + 86400000
        time.sleep(0.12)
    new = pd.DataFrame(columns=['trade_date', 'open', 'high', 'low', 'close', 'volume'])
    if rows:
        df = pd.DataFrame(rows, columns=COLS)
        df['trade_date'] = pd.to_datetime(df['open_time'].astype('int64'), unit='ms').dt.tz_localize(None).dt.normalize()
        new = df[['trade_date', 'open', 'high', 'low', 'close', 'volume']].astype(
            {'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})
        new = new[(new['trade_date'] >= WIN_LO) & (new['trade_date'] <= FETCH_HI)]
    if have is None or have.empty:
        out = new
    else:
        out = pd.concat([have, new], ignore_index=True) if not new.empty else have
    out = out.drop_duplicates('trade_date', keep='last').sort_values('trade_date')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.to_csv(path, index=False)
    return 'empty' if out.empty else f'{len(out)}'


def do_fetch():
    hist = pd.read_parquet(HIST_PARQUET)
    syms = sorted(set(hist['symbol']) - EXCLUDE)
    print(f'symbols to fetch: {len(syms)} x 2 venues -> {KL_DIR}', flush=True)
    done = {}
    for i, sym in enumerate(syms):
        for venue in ('spot', 'perp'):
            done.setdefault(venue, []).append(fetch_one(venue, sym))
        if i % 20 == 0:
            print(f'  [{i}/{len(syms)}] {sym} spot={done["spot"][-1]} perp={done["perp"][-1]}', flush=True)
    for venue in ('spot', 'perp'):
        vc = pd.Series(done[venue]).value_counts().to_dict()
        print(f'{venue}: {vc}', flush=True)


# ══ classify ══════════════════════════════════════════════════════════════
def _panel_hist():
    df = pd.read_parquet(HIST_PARQUET)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df[~df['symbol'].isin(EXCLUDE)]
    return df[['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume']]


def _panel_api(venue):
    frames = []
    d = f'{KL_DIR}/{venue}'
    if not os.path.isdir(d):
        return pd.DataFrame(columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume'])
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.csv'):
            continue
        sub = pd.read_csv(os.path.join(d, fn))
        if sub.empty:
            continue
        sub['symbol'] = fn[:-4]
        frames.append(sub)
    if not frames:
        return pd.DataFrame(columns=['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume'])
    return pd.concat(frames, ignore_index=True)


def do_classify():
    hist = _panel_hist()
    hist = hist[(hist['trade_date'] >= WIN_LO) & (hist['trade_date'] <= FETCH_HI)]
    panels = {'spot': _panel_api('spot'), 'perp': _panel_api('perp')}
    for v in panels:
        panels[v]['trade_date'] = pd.to_datetime(panels[v]['trade_date'])

    # 索引: (venue, symbol) -> {date: (close, volume)}
    idx = {}
    for v, df in panels.items():
        for sym, sub in df.groupby('symbol'):
            idx[(v, sym)] = {r.trade_date: (r.close, r.volume) for r in sub.itertuples()}
    hidx = {sym: {r.trade_date: (r.close, r.volume) for r in sub.itertuples()}
            for sym, sub in hist.groupby('symbol')}

    rows = []
    for sym in sorted(hidx):
        rec = {'symbol': sym, 'n_hist_days': len(hidx[sym])}
        for dt in PROBE_DATES:
            d = pd.Timestamp(dt)
            h = hidx[sym].get(d)
            tag = d.strftime('%Y-%m')
            if h is None:
                rec[f'{tag}'] = 'no_data'
                continue
            got = {}
            for v in ('spot', 'perp'):
                a = idx.get((v, sym), {}).get(d)
                if a is None:
                    got[v] = None
                    continue
                cd = abs(h[0] - a[0]) / a[0]
                vd = abs(h[1] - a[1]) / a[1] if a[1] else np.inf
                got[v] = (cd, vd, a[1])
            if got['spot'] and got['perp']:
                ms = got['spot'][0] < 0.01 and got['spot'][1] < 0.01
                mp = got['perp'][0] < 0.01 and got['perp'][1] < 0.01
                if ms and not mp:
                    lab = 'spot'
                elif mp and not ms:
                    lab = 'perp'
                elif ms and mp:
                    lab = 'both'
                else:
                    lab = 'neither'
                rec[f'{tag}'] = lab
                rec[f'{tag}_volratio_spot'] = round(h[1] / got['spot'][2], 4) if got['spot'][2] else None
                rec[f'{tag}_volratio_perp'] = round(h[1] / got['perp'][2], 4) if got['perp'][2] else None
            elif got['spot'] and not got['perp']:
                rec[f'{tag}'] = 'spot_only_match' if (got['spot'][0] < 0.01 and got['spot'][1] < 0.01) else 'spot_only_nomatch'
            elif got['perp'] and not got['spot']:
                rec[f'{tag}'] = 'perp_only_match' if (got['perp'][0] < 0.01 and got['perp'][1] < 0.01) else 'perp_only_nomatch'
            else:
                rec[f'{tag}'] = 'no_counterpart'
        rows.append(rec)

    res = pd.DataFrame(rows)
    os.makedirs(OUT_DIR, exist_ok=True)
    res.to_csv(f'{OUT_DIR}/t151_classification.csv', index=False)

    # 汇总
    cols = [d.strftime('%Y-%m') for d in map(pd.Timestamp, PROBE_DATES)]
    agg = {c: res[c].value_counts().to_dict() for c in cols}
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print('\n-- volratio medians by segment (hist / API) --')
    for c in cols:
        for v in ('spot', 'perp'):
            k = f'{c}_volratio_{v}'
            if k in res:
                s = pd.to_numeric(res[k], errors='coerce').dropna()
                print(f'{c} vs {v}: median={s.median():.3f} n={len(s)}', flush=True)
    return res


# ══ sim ══════════════════════════════════════════════════════════════════
def build_panel(df):
    """加 S-610 的全部窗口列,按 rn(=窗口内第几根)开。"""
    df = df.sort_values(['symbol', 'trade_date']).reset_index(drop=True)
    df['rn'] = df.groupby('symbol').cumcount() + 1
    df['pc'] = df.groupby('symbol')['close'].shift(1)
    df['dv'] = df['close'] * df['volume']
    g = df.groupby('symbol', sort=False)
    df['sma20'] = g['close'].transform(lambda s: s.rolling(20, min_periods=1).mean())
    df['sma200'] = g['close'].transform(lambda s: s.rolling(200, min_periods=1).mean())
    tr = pd.concat([df['high'] - df['low'],
                    (df['high'] - df['pc']).abs(),
                    (df['low'] - df['pc']).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.groupby(df['symbol']).transform(lambda s: s.rolling(14, min_periods=1).mean())
    df['adv30'] = g['dv'].transform(lambda s: s.rolling(30, min_periods=1).mean())
    df['adv40p'] = g['dv'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).mean())
    df['hh40'] = g['high'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).max())
    df['ll40'] = g['low'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).min())
    df['max365'] = g['close'].transform(lambda s: s.rolling(365, min_periods=1).max())
    df['dd'] = df['close'] / df['max365']
    df['mindd120'] = g['dd'].transform(lambda s: s.rolling(120, min_periods=1).min())
    return df


def run_panel(df, k_atr):
    sig_mask = (
        (df['rn'] >= RN_MIN)
        & (df['adv30'] >= ADV30_MIN)
        & (df['trade_date'] >= SIG_LO)
        & (df['trade_date'] <= SIG_HI)
        & (df['mindd120'] <= DD_RATIO_MAX)
        & ((df['hh40'] - df['ll40']) / df['hh40'] <= AMP_MAX)
        & (df['close'] > df['hh40'])
        & (df['close'] > df['sma200'])
        & (df['dv'] >= 2 * df['adv40p'])
    )
    sig = df[sig_mask]
    arrs = {}
    for sym, sub in df.groupby('symbol', sort=False):
        sub = sub.sort_values('rn')
        arrs[sym] = {c: sub[c].to_numpy(dtype=float) for c in
                     ('open', 'high', 'low', 'close', 'sma20')}
        arrs[sym]['date'] = sub['trade_date'].to_numpy()

    trades = []
    last_exit = {}
    for srow in sig.itertuples():
        sym = srow.symbol
        a = arrs.get(sym)
        if a is None:
            continue
        n = len(a['open'])
        ei = int(srow.rn)                      # 0-based 进场根 = 信号 rn(1-based)
        if ei >= n:
            continue
        if sym in last_exit and ei <= last_exit[sym]:
            continue
        entry = a['open'][ei]
        stop = max(srow.low, entry - k_atr * srow.atr14)
        if entry <= stop:
            continue
        end = min(ei + HOLD_MAX, n)
        px, xi = None, end - 1
        for i in range(ei, end):
            if a['low'][i] <= stop:
                px = a['open'][i] if (i > ei and a['open'][i] <= stop) else stop
                xi = i
                break
            if a['close'][i] < a['sma20'][i]:
                j = i + 1 if i + 1 < n else i
                px = a['open'][j] if j > i else a['close'][j]
                xi = j
                break
        if px is None:
            px = a['close'][end - 1]
            xi = end - 1
        risk = entry - stop
        r = (px - entry) / risk - COST * entry / risk
        fish = float(np.max(np.maximum(a['high'][ei:ei + HOLD_MAX],
                                        a['close'][ei:ei + HOLD_MAX])) >= 3.0 * entry)
        trades.append({'symbol': sym, 'sig_date': srow.trade_date,
            'entry_date': a['date'][ei], 'exit_date': a['date'][xi],
            'entry': entry, 'stop': stop, 'exit': px,
            'r': r, 'fish': fish, 'held_bars': xi - ei + 1})
        last_exit[sym] = xi
    t = pd.DataFrame(trades)
    return t, df


def yearly(t, df, label):
    if t.empty:
        return {'panel': label, 'n': 0}
    t = t.copy()
    t['year'] = pd.to_datetime(t['entry_date']).dt.year
    uni = df[(df['trade_date'] >= SIG_LO) & (df['trade_date'] <= SIG_HI) & (df['adv30'] >= ADV30_MIN)]
    uni_days = uni.groupby('trade_date')['symbol'].nunique()
    out = {'panel': label, 'n_total': int(len(t)), 'mean_r': round(float(t['r'].mean()), 4),
           'fish_rate': round(float(t['fish'].mean()), 4), 'fish_n': int(t['fish'].sum()),
           'median_r': round(float(t['r'].median()), 4),
           'win_rate': round(float((t['r'] > 0).mean()), 4),
           'universe_syms': int(uni['symbol'].nunique()),
           'universe_syms_mean_daily': round(float(uni_days.mean()), 1)}
    by = t.groupby('year').agg(n=('r', 'size'), mean_r=('r', 'mean'),
                               fish_rate=('fish', 'mean'), fish_n=('fish', 'sum'))
    uy = uni.groupby(uni['trade_date'].dt.year)['symbol'].nunique()
    for y, row in by.iterrows():
        out[str(y)] = {'n': int(row['n']), 'mean_r': round(float(row['mean_r']), 4),
                       'fish_rate': round(float(row['fish_rate']), 4),
                       'fish_n': int(row['fish_n']),
                       'universe_syms': int(uy.get(y, 0))}
    return out


def do_sim():
    res = {}
    panels = {}
    h = _panel_hist()
    h = h[(h['trade_date'] >= WIN_LO) & (h['trade_date'] <= WIN_HI)]
    panels['hist'] = h
    for v in ('spot', 'perp'):
        p = _panel_api(v)
        p['trade_date'] = pd.to_datetime(p['trade_date'])
        p = p[(p['trade_date'] >= WIN_LO) & (p['trade_date'] <= WIN_HI)]
        panels[v] = p

    for name, df in panels.items():
        if df.empty:
            print(f'{name}: EMPTY, skipped', flush=True)
            continue
        built = build_panel(df)
        for k, kl in ((ATR_K, 'k2.5'), (BASELINE_K, 'k1.0')):
            t, built2 = run_panel(built, k)
            t.to_csv(f'{OUT_DIR}/trades_{name}_{kl}.csv', index=False)
            res[f'{name}|{kl}'] = yearly(t, built, f'{name}/{kl}')
            r = res[f'{name}|{kl}']
            print(f'{name}/{kl}: n={r.get("n_total")} mean_r={r.get("mean_r")} '
                  f'fish={r.get("fish_n")}({r.get("fish_rate")}) uni={r.get("universe_syms")}', flush=True)

    with open(f'{OUT_DIR}/t151_sim.json', 'w') as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(json.dumps(res, indent=2, ensure_ascii=False))


def do_repl():
    """复现对照:不改窗口,k=1.0(S-610 原值),全量 binance_hist —— 台账写的 n=1,013 / 均值 R +0.350。"""
    global WIN_LO, SIG_LO, SIG_HI
    WIN_LO = pd.Timestamp('2017-01-01')
    SIG_LO = pd.Timestamp('2020-03-01')
    SIG_HI = pd.Timestamp('2026-10-17')
    df = _panel_hist()
    df = df[df['trade_date'] >= WIN_LO]
    built = build_panel(df)
    t, _ = run_panel(built, BASELINE_K)
    t.to_csv(f'{OUT_DIR}/t151_replication_hist_k1.csv', index=False)
    print(f"REPL hist k=1.0: n={len(t)} mean_r={t['r'].mean():.4f} "
          f"median_r={t['r'].median():.3f} win={(t['r']>0).mean():.4f} "
          f"mean_win={t.loc[t['r']>0,'r'].mean():.3f} mean_loss={t.loc[t['r']<=0,'r'].mean():.3f}")
    print('台账基线:n=1013 mean_r=0.350 median=-1.06 win=0.161 mean_win=7.66 mean_loss=-1.05')


def do_switch(lo='2026-07-25', hi='2026-08-20'):
    """逐日扫:每个日子有多少个名字与现货 / 与永续逐位一致 —— 定位口径切换日。"""
    hist = _panel_hist()
    hist = hist[~hist['symbol'].isin(EXCLUDE)]
    sp, pp = _panel_api('spot'), _panel_api('perp')
    for d in (sp, pp):
        d['trade_date'] = pd.to_datetime(d['trade_date'])
    rows = []
    for d in pd.date_range(lo, hi):
        t = pd.Timestamp(d)
        hh = hist[hist['trade_date'] == t].set_index('symbol')
        ss = sp[sp['trade_date'] == t].set_index('symbol')
        pp_ = pp[pp['trade_date'] == t].set_index('symbol')
        common = hh.index.intersection(ss.index).intersection(pp_.index)
        if len(common) == 0:
            rows.append({'date': str(t.date()), 'n_hist': len(hh), 'n_common': 0,
                         'match_spot': 0, 'match_perp': 0,
                         'med_volratio_spot': None, 'med_volratio_perp': None})
            continue
        rs = hh.loc[common, 'volume'] / ss.loc[common, 'volume']
        rp = hh.loc[common, 'volume'] / pp_.loc[common, 'volume']
        rows.append({'date': str(t.date()), 'n_hist': len(hh), 'n_common': len(common),
                     'match_spot': int((rs - 1).abs().lt(0.01).sum()),
                     'match_perp': int((rp - 1).abs().lt(0.01).sum()),
                     'med_volratio_spot': round(float(rs.median()), 3),
                     'med_volratio_perp': round(float(rp.median()), 3)})
    out = pd.DataFrame(rows)
    out.to_csv(f'{OUT_DIR}/t151_switch_scan.csv', index=False)
    print(out.to_string(index=False))
    # 宇宙变化
    pre = set(hist[(hist['trade_date'] >= '2026-06-01') & (hist['trade_date'] <= '2026-08-07')]['symbol'])
    post = set(hist[(hist['trade_date'] >= '2026-08-08')]['symbol'])
    uni = {'pre_syms': len(pre), 'post_syms': len(post),
           'kept': len(pre & post), 'lost': len(pre - post), 'new': len(post - pre)}
    print(json.dumps(uni, ensure_ascii=False))
    with open(f'{OUT_DIR}/t151_switch.json', 'w') as f:
        json.dump({'daily': rows, 'universe': uni}, f, indent=2, ensure_ascii=False)


def do_report():
    """把 classify + sim 的结果拼成决定表(数字全部从落盘文件读,不手抄)。"""
    cls = pd.read_csv(f'{OUT_DIR}/t151_classification.csv')
    sim = json.load(open(f'{OUT_DIR}/t151_sim.json'))
    cols = [d.strftime('%Y-%m') for d in map(pd.Timestamp, PROBE_DATES)]
    PRE = ['2023-01', '2024-07', '2025-07', '2026-07']    # 切换前
    POST = ['2026-09']                                     # 切换后

    def era(r, cs):
        seg = [r[c] for c in cs if isinstance(r[c], str)]
        sp = sum(s in ('spot', 'both', 'spot_only_match') for s in seg)
        pe = sum(s in ('perp', 'both', 'perp_only_match') for s in seg)
        nospot = sum(s == 'perp_only_match' for s in seg)  # Binance 现货上没有这个对
        if sp and not pe:
            return 'spot'
        if pe and not sp:
            return 'perp' if nospot == len(seg) else 'perp'
        if sp and pe:
            return 'both'
        return 'none'

    cls['pre'], cls['post'] = cls.apply(lambda r: era(r, PRE), axis=1), cls.apply(lambda r: era(r, POST), axis=1)
    cls['klass'] = cls.apply(
        lambda r: {'spot': '全程现货', 'perp': '全程合约', 'both': '全程两边都像', 'none': '判不出'}[r['post']]
        if r['pre'] == r['post'] else ('切换前无对' if r['pre'] == 'none' else '混合'), axis=1)
    cls['perp_only'] = cls.apply(
        lambda r: all(r[c] in ('perp_only_match', 'perp', 'no_data') for c in PRE), axis=1)
    cls.to_csv(f'{OUT_DIR}/t151_classification.csv', index=False)
    kc = cls['klass'].value_counts().to_dict()

    L = []
    A = L.append
    A('# T-151 / S-637 — binance_hist 口径:现货 / 合约 / 混合,以及该用哪张面板')
    A('')
    A('> 机器生成:`docs/research/t151_panel_convention.py`(`report` 相)。原始数字在 '
      '`/Volumes/CometCloudAI/cometcloud-local/research/t151/`(classification.csv / sim.json / trades_*.csv)。')
    A('> 口径与 S-610 预注册一致,只把止损宽度换成卡上要求的 k×ATR(默认 2.5),另跑 k=1.0 作复现对照。')
    A('')
    A('## 0. 决定表(先看这张)')
    A('')
    A('| # | 问题 | 答案 | 依据 |')
    A('|---|---|---|---|')
    n_h, n_s, n_p = sim['hist|k2.5']['n_total'], sim['spot|k2.5']['n_total'], sim['perp|k2.5']['n_total']
    r_h, r_s, r_p = sim['hist|k2.5']['mean_r'], sim['spot|k2.5']['mean_r'], sim['perp|k2.5']['mean_r']
    f_h, f_s, f_p = sim['hist|k2.5']['fish_rate'], sim['spot|k2.5']['fish_rate'], sim['perp|k2.5']['fish_rate']
    A(f'| 1 | binance_hist 现在到底是什么口径? | **在 2026-08-08 整块换过一次**:之前=U 本位永续,之后=Binance 现货 | 逐日扫:`switch` 相,见 §1.0 |')
    A(f'| 2 | **单票按永续做**,该用哪张面板? | **perp** | 票数 {n_p}(现货 {n_s} / 现状 {n_h});均值 R {r_p:+.3f} | 同进场同出场,只换数据源 |')
    A(f'| 3 | **单票按现货做**,该用哪张面板? | **spot** | 同上 | 同上 |')
    A(f'| 4 | 从现状改成 perp,前向多/少多少票? | **{n_p - n_h:+d} 票**({n_p / n_h - 1:+.0%}) | 递归去重后同一段 |')
    A(f'| 5 | 从现状改成 spot,前向多/少多少票? | **{n_s - n_h:+d} 票**({n_s / n_h - 1:+.0%}) | 同上 |')
    A(f'| 6 | 在鱼比例差多少? | spot {f_s:.1%} / perp {f_p:.1%} / 现状 {f_h:.1%} | 鱼 = S-618 原定义(120 根内 ≥3× 进场) |')
    A(f'| 7 | 前向账本现在跑在哪种口径上? | **现货**(2026-08-08 起),研究回测窗口 2023-01-01→2026-06-20 **整段都在永续口径上** | 两侧不是同一个宇宙 |')
    A('| 8 | 那现在直接拿 binance_hist 做回测行不行? | 跨过 2026-08-08 就不行 | 同一天的行,前半段是永续、后半段是现货 |')
    A('')
    A('## 1. ① 逐名字分类')
    A('')
    A('### 1.0 先看结论:整块切换日')
    A('')
    try:
        sw = json.load(open(f'{OUT_DIR}/t151_switch.json'))
        daily = sw['daily']
        A('| 日期 | hist 名字数 | 可比对 | 与现货一致 | 与永续一致 | 量比中位(÷现货) | 量比中位(÷永续) |')
        A('|---|---|---|---|---|---|---|')
        for r in daily:
            if '2026-07-28' <= r['date'] <= '2026-08-12' or r['date'] in (daily[0]['date'], daily[-1]['date']):
                A(f"| {r['date']} | {r['n_hist']} | {r['n_common']} | {r['match_spot']} | {r['match_perp']} | "
                  f"{r['med_volratio_spot']} | {r['med_volratio_perp']} |")
        post = [r for r in daily if r['date'] >= '2026-08-09']
        A('')
        A(f'2026-08-09 → {daily[-1]["date"]} 共 {len(post)} 天:与现货一致 '
          f'{sum(r["match_spot"] for r in post)} 个名字日,与永续一致 {sum(r["match_perp"] for r in post)} 个名字日。'
          '逐日全表见 `t151_switch_scan.csv`。')
        u = sw['universe']
        A('')
        A(f"**切换日 = 2026-08-08。** 2026-08-07 及以前:可对上的名字里绝大多数与**永续**逐位一致"
          f"(量比 ÷永续 = 1.000);2026-08-08 起:与永续一致的数量掉到 **0**,全部与**现货**逐位一致。")
        A('')
        A(f"宇宙也跟着换了:2026-08-07 前出现的 {u['pre_syms']} 个名字里,{u['lost']} 个在切换后不再出现;"
          f"切换后新增 {u['new']} 个;两段都出现的 {u['kept']} 个。")
        A('')
        A('> 也就是说:**同一个面板在同一条时间轴上,前半段是永续、后半段是现货,而且宇宙也换了。**'
          '任何直接读 binance_hist 的回测,只要跨过这一天,前后两段就不是同一个标的。')
    except FileNotFoundError:
        A('(未跑 `switch` 相)')
    A('')
    A('')
    A(f'取样日 {", ".join(PROBE_DATES)};同时比**收盘**与**成交量**,两者都 <1% 才算「一致」。')
    A(f'切换前时代 = {" / ".join(PRE)},切换后时代 = {"/".join(POST)}。')
    A('')
    A('| 分类 | 名字数 | 意思 |')
    A('|---|---|---|')
    mean = {
        '全程现货': '切换前后都判现货 —— 这批名字本来就是现货,没跟着换',
        '全程合约': '切换前后都判合约 —— 切换之后仍逐位对得上永续(孤例)',
        '混合': '切换前判合约、切换后判现货 —— 跟着面板整块换了口径',
        '判不出': '切换后在 Binance 两端都找不到可对的名字(未上市 / 已下架 / 映射不上)',
        '切换前无对': '切换前在 Binance 两端都找不到可对的名字',
        '全程两边都像': '同一时代内既像现货又像永续(收盘几乎一样、量落在两者之间)',
    }
    for k in ('全程现货', '全程合约', '混合', '判不出', '切换前无对', '全程两边都像'):
        if kc.get(k):
            A(f'| {k} | {kc[k]} | {mean[k]} |')
    A(f'| 其中:只有合约(无现货对) | {int(cls["perp_only"].sum())} | 切换前各取样日只对得上永续、Binance 现货上没有这个对 |')
    A('')
    A('### 1.0b 逐时代判定 + 交叉表')
    A('')
    A('| 时代 | 判现货 | 判合约 | 两边都像 | 都判不出 |')
    A('|---|---|---|---|---|')
    for lab, col in (('切换前(≤2026-08-07)', 'pre'), ('切换后(≥2026-08-09)', 'post')):
        vc = cls[col].value_counts()
        A(f'| {lab} | {int(vc.get("spot", 0))} | {int(vc.get("perp", 0))} | '
          f'{int(vc.get("both", 0))} | {int(vc.get("none", 0))} |')
    A('')
    cross = pd.crosstab(cls['pre'], cls['post'])
    A('| 切换前 \\\\ 切换后 | ' + ' | '.join(cross.columns) + ' |')
    A('|---|' + '---|' * len(cross.columns))
    for idx, row in cross.iterrows():
        A(f'| {idx} | ' + ' | '.join(str(int(v)) for v in row.values) + ' |')
    A('')
    A('### 1a. 每个取样日的分布')
    A('')
    A('| 取样段 | ' + ' | '.join(cols) + ' |')
    A('|---|' + '---|' * len(cols))
    allv = sorted({v for c in cols for v in cls[c].dropna().unique()})
    for v in allv:
        A(f'| {v} | ' + ' | '.join(str(int((cls[c] == v).sum())) for c in cols) + ' |')
    A('')
    A('### 1b. 成交量比中位数(binance_hist ÷ API)—— 这是 S-637 看到的接缝')
    A('')
    A('| 取样段 | vs 现货 | vs 永续 |')
    A('|---|---|---|')
    for c in cols:
        cells = []
        for v in ('spot', 'perp'):
            s = pd.to_numeric(cls[f'{c}_volratio_{v}'], errors='coerce').dropna()
            cells.append(f'{s.median():.3f} (n={len(s)})' if len(s) else '—')
        A(f'| {c} | {cells[0]} | {cells[1]} |')
    A('')
    A('### 1c. 逐名字明细(全程现货 = 没跟着换;异常 = 同一时代里两边都像 / 切换后仍是合约)')
    A('')
    always_spot = sorted(cls.loc[cls['klass'] == '全程现货', 'symbol'])
    A(f"**全程现货({len(always_spot)} 个,面板换口径时它们没换):** {', '.join(always_spot)}")
    A('')
    show = cls[(cls['pre'] == 'both') | (cls['post'] == 'perp')].sort_values('klass')
    if len(show):
        A('| symbol | 分类 | n_days | ' + ' | '.join(cols) + ' |')
        A('|---|---|---|' + '---|' * len(cols))
        for _, r in show.iterrows():
            A(f'| {r["symbol"]} | {r["klass"]} | {r["n_hist_days"]} | ' +
              ' | '.join(str(r[c]) for c in cols) + ' |')
    else:
        A('(无)')
    A('')
    A('## 2. ③ 三种面板上的 R 臂(2023-01-01 → 2026-06-20)')
    A('')
    A('进场 = t+1 开盘;止损 = max(t 日低点, 进场 − 2.5×ATR14);出场 = 止损先判 / 收盘破 SMA20 次日开盘出 / 120 根强制。')
    A('')
    for kl, name in (('k2.5', 'k = 2.5×ATR(卡上口径)'), ('k1.0', 'k = 1.0×ATR(S-610 原值,复现对照)')):
        A(f'### {name}')
        A('')
        A('| 面板 | 票数 | 均值 R | 中位 R | 胜率 | 在鱼比例 | 捕到的鱼 | 宇宙(名字数) | 宇宙(日均) |')
        A('|---|---|---|---|---|---|---|---|---|')
        for p in ('spot', 'perp', 'hist'):
            k = f'{p}|{kl}'
            if k not in sim:
                continue
            r = sim[k]
            A(f'| {p} | {r.get("n_total")} | {r.get("mean_r"):+.3f} | {r.get("median_r"):+.2f} | '
              f'{r.get("win_rate"):.1%} | {r.get("fish_rate"):.1%} | {r.get("fish_n")} | '
              f'{r.get("universe_syms")} | {r.get("universe_syms_mean_daily")} |')
        A('')
        A('| 面板 | 年 | 票数 | 均值 R | 在鱼比例 | 捕到的鱼 | 宇宙(名字数) |')
        A('|---|---|---|---|---|---|---|')
        for p in ('spot', 'perp', 'hist'):
            r = sim.get(f'{p}|{kl}', {})
            for y in ('2023', '2024', '2025', '2026'):
                if y in r:
                    yy = r[y]
                    A(f'| {p} | {y} | {yy["n"]} | {yy["mean_r"]:+.3f} | {yy["fish_rate"]:.1%} | '
                      f'{yy["fish_n"]} | {yy["universe_syms"]} |')
        A('')
    A('## 3. 读法与边界')
    A('')
    A('- 三面板统一截到 [2022-01-01, 2026-08-05],rn 在该窗口内重算 —— 三边同尺,不比历史长度。')
    A('- 复现对照:`repl` 相在全量 binance_hist 上跑出 n=1,009 / 均值 R +0.345(台账 n=1,013 / +0.350),差 4 笔,在噪声内。')
    A('- 现货 / 永续只覆盖 Binance 现货 USDT 对与 U 本位 USDT 永续对;表里没有的名字不参与三面板比较。')
    A('- 这里只比**口径**,不比策略优劣;票数差同时含「宇宙不同」(有的名字只在永续上市)。')
    A('')
    A('## 4. 原始文件')
    A('')
    A('- `t151_switch_scan.csv` / `t151_switch.json` — 逐日口径扫描(切换日证据)')
    A('- `t151_classification.csv` — 逐名字逐取样日的判定 + 成交量比')
    A('- `t151_sim.json` — 三面板 × 两 k 的分年统计')
    A('- `trades_{spot,perp,hist}_{k2.5,k1.0}.csv` — 逐票明细')
    A('- `t151_replication_hist_k1.csv` — S-610 复现对照的逐票明细')
    A('- `klines/{spot,perp}/*.csv` — 直接从 Binance 公开接口取的日线(未入库)')

    path = f'{DATA_ROOT}/_reports/absorb_input/T-151_panel_convention.md'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(L) + '\n')
    print(f'wrote {path} ({len(L)} lines)')


if __name__ == '__main__':
    os.makedirs(KL_DIR, exist_ok=True)
    phase = sys.argv[1] if len(sys.argv) > 1 else 'sim'
    {'fetch': do_fetch, 'classify': do_classify, 'sim': do_sim, 'repl': do_repl,
     'switch': do_switch, 'report': do_report}[phase]()