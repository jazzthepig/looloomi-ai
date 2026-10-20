#!/usr/bin/env python3
"""T-153 — R-v2 的钱曲线换成现货面板会怎样(S-637 决定表的另一半):
S-627 闸门版票 + S-638 盯市 + S-639 配 ① 表,在现货 / 永续两面板下并列重算。

预注册(REFUTATION_LEDGER.md S-627 / S-638 / S-639,写于对任何面板跑任何净值之前):

  ①  同 T-141 的盯市实现 + S-627 闸门版票(k = 2.5、majors 200 日闸门、S-610 进出、
    同名不重叠,信号日 ≤ 2026-06-20,最多 10 张)。现货面板上:0.25% 步长下、求盯市
    最大回撤 ≥ −35% 的最大 f,记为 f★,报该 f★ 下年化、回撤、接 / 挡张数。
  ②  同口径在永续面板(原状 = T-141 的 ohlcv_binance_hist)上跑一遍;
    f = 1% 时的盯市回撤必须对上 S-638 的 −32.3% ± 1pp,才往下走。
  ③  S-639 表:① = core_variants_daily arm cap_uncapped,R-v2 = 现货面板 S-627 闸门版
    (f = 1%、最多 10 张、信号日 ≤ 2026-10-17),w ∈ {0, 0.10, 0.20, 0.30}、月度再平衡、
    区间 2023-01-02 → 2026-10-19。

数据(只读):
  * 永续面板 = /Volumes/CometCloudAI/cometcloud-local/_data/research/t131/ohlcv_binance_hist.parquet
    (与 T-141 同一份;262 名 / 351,269 行 / 2017-08-17 → 2026-10-19)。
  * 现货日线 = /Volumes/CometCloudAI/cometcloud-local/research/t151/klines/spot/
    (T-151 现取的 Binance 现货 api/v3/klines,259 名 / 2022-01-01 → 2026-10-20)。
  * T-151 分类 = /Volumes/CometCloudAI/cometcloud-local/research/t151/t151_classification.csv
    (190 余名 混合 = 08-08 前合约 → 后现货;用此列表替换原 panel 这部分)。
  * 闸门 = style_index_pit_daily(majors / cap)现取现缓存。
  * ① NAV = Supabase core_variants_daily arm = cap_uncapped(只读,publishable key)。
只读 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'];不读 .env、不打印 key。
"""
from __future__ import annotations
import os, sys, json, hashlib, datetime as dt
import urllib.request
import numpy as np
import pandas as pd

# ── 路径常量 ──────────────────────────────────────────────────────────────
DATA_ROOT = '/Volumes/CometCloudAI/cometcloud-local'
SCRATCH   = os.path.join(DATA_ROOT, '_data/research/t153')
os.makedirs(SCRATCH, exist_ok=True)
SRC_PARQUET = os.path.join(DATA_ROOT, '_data/research/t131/ohlcv_binance_hist.parquet')
SPOT_DIR    = os.path.join(DATA_ROOT, 'research/t151/klines/spot')
CLS_PATH    = os.path.join(DATA_ROOT, 'research/t151/t151_classification.csv')
REPORT_PATH = os.path.join(DATA_ROOT, '_reports/absorb_input/T-153_spot_panel_money.md')

# ── 公共常量 ──────────────────────────────────────────────────────────────
EXCLUDE    = {'USDC', 'BTCDOM', 'DEFI'}
COST_R     = 0.004
COST_EA    = 0.002
D_LO       = pd.Timestamp('2020-03-01')
D_HI       = pd.Timestamp('2026-10-19')
DISC_HI    = pd.Timestamp('2026-06-20')     # S-627 / S-638 发现段
HOLDOUT_HI = pd.Timestamp('2026-10-17')     # S-639 报表信号日上限
S639_LO    = pd.Timestamp('2023-01-02')     # S-639 表起点
S639_HI    = pd.Timestamp('2026-10-19')
RN_MIN, ADV30_MIN = 220, 5_000_000
DD_RATIO_MAX, AMP_MAX, HOLD_MAX = 0.5, 0.40, 120
KS_T153 = [2.5]               # 本脚本只跑 S-627 / S-638 的 k = 2.5
CAP_T153 = [10]                # 同 S-638,热度上限 10 张
TARGET_DD = 0.35
F_GRID    = 0.0025             # 0.25% 步长
K_FID     = 2.5
CUT       = pd.Timestamp('2026-08-07')    # 替换切分日(t-1 = 08-07 / t = 08-08 现货)


# ═══ 1. 闸门 (majors / cap) ═══════════════════════════════════════════════
def load_gate():
    gp = os.path.join(SCRATCH, 'majors_cap_gate.json')
    if os.path.exists(gp):
        G = json.load(open(gp))
    else:
        su, sk = os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']
        rows, off = [], 0
        while True:
            url = (f'{su}/rest/v1/style_index_pit_daily?style=eq.majors&weighting=eq.cap'
                   f'&ret=gt.-0.95&select=d,ret&order=d&limit=1000&offset={off}')
            req = urllib.request.Request(url, headers={'apikey': sk, 'Authorization': 'Bearer ' + sk})
            chunk = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
            rows += chunk
            if len(chunk) < 1000: break
            off += 1000
        G = {'rows': len(rows), 'd': [r['d'] for r in rows], 'ret': [r['ret'] for r in rows]}
        json.dump(G, open(gp, 'w'))
    gd = pd.to_datetime(G['d'])
    lvl = np.exp(np.log1p(np.asarray(G['ret'])).cumsum())
    sma = pd.Series(lvl).rolling(200, min_periods=1).mean().to_numpy()
    nw  = pd.Series(lvl).rolling(200, min_periods=1).count().to_numpy()
    open_g = pd.Series((nw < 200) | (lvl > sma), index=gd)
    return {d: bool(v) for d, v in open_g.items()}


# ═══ 2. 面板构建 ══════════════════════════════════════════════════════════
def load_perp_panel() -> tuple[pd.DataFrame, dict]:
    h = hashlib.sha256(open(SRC_PARQUET, 'rb').read()).hexdigest()
    st = os.stat(SRC_PARQUET)
    df = pd.read_parquet(SRC_PARQUET)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df[~df.symbol.isin(EXCLUDE)].copy().sort_values(['symbol', 'trade_date']).reset_index(drop=True)
    prov = {
        'path': SRC_PARQUET, 'sha256': h, 'rows': int(len(df)),
        'symbols': int(df.symbol.nunique()),
        'date_min': str(df.trade_date.min().date()),
        'date_max': str(df.trade_date.max().date()),
        'file_mtime_utc': dt.datetime.utcfromtimestamp(st.st_mtime).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    return df, prov

def load_spot_panel() -> tuple[pd.DataFrame, dict]:
    """把 t151/spot/ 的 259 个 CSV 读成一张表(spk);同时返回逐名替换表。"""
    pieces = []
    for fn in sorted(os.listdir(SPOT_DIR)):
        if not fn.endswith('.csv'): continue
        sym = fn[:-4]
        d = pd.read_csv(os.path.join(SPOT_DIR, fn))
        d['symbol'] = sym
        d['trade_date'] = pd.to_datetime(d['trade_date'])
        pieces.append(d)
    spk = pd.concat(pieces, ignore_index=True).sort_values(['symbol', 'trade_date']).reset_index(drop=True)
    prov = {'rows': int(len(spk)), 'symbols': int(spk.symbol.nunique()),
            'date_min': str(spk.trade_date.min().date()), 'date_max': str(spk.trade_date.max().date()),
            'files': len(pieces)}
    return spk, prov

def replace_mixed(perp: pd.DataFrame, spk: pd.DataFrame, cls: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """对 t-151 分类 = 「混合」且 pre = 'perp' 的名字:用 spk 数据替换原 panel 上 ≤ 2026-08-07 的行;
    其余名字保留原 panel 行。最终输出 spot panel(只在内存,落盘到 SCRATCH)。"""
    mixed_pre_perp = cls[(cls.klass == '混合') & (cls.pre == 'perp')].symbol.tolist()
    mixed_no_spot  = [s for s in mixed_pre_perp if s not in spk.symbol.unique()]
    mixed_with_spot = [s for s in mixed_pre_perp if s in spk.symbol.unique()]

    # 拆分替换
    rows_replaced = 0
    rows_kept_from_perp = 0
    rows_added_from_spot = 0
    out_pieces = []
    spk_by_sym = {s: g.sort_values('trade_date').reset_index(drop=True) for s, g in spk.groupby('symbol', sort=False)}

    for sym, g in perp.groupby('symbol', sort=False):
        if sym not in mixed_with_spot:
            out_pieces.append(g.copy())
            rows_kept_from_perp += len(g)
            continue
        sg = spk_by_sym[sym]
        # 原 panel 上 ≤ CUT 的全部丢弃
        dropped = g[g.trade_date <= CUT]
        kept_post = g[g.trade_date > CUT]
        # spot 全部接上(从 2022-01-01 起到 t151 spot csv 的最末日,CUT 的过滤由本 panel 自身的范围控制)
        rows_replaced += len(dropped)
        rows_added_from_spot += len(sg)
        rows_kept_from_perp += len(kept_post)
        out_pieces.append(pd.concat([sg, kept_post], ignore_index=True).sort_values('trade_date'))

    panel = pd.concat(out_pieces, ignore_index=True)
    panel = panel.sort_values(['symbol', 'trade_date']).reset_index(drop=True)
    panel = panel.drop_duplicates(['symbol', 'trade_date'], keep='first')

    rep = {
        'mixed_total': len(mixed_pre_perp) + len(cls[(cls.klass == '混合') & (cls.pre != 'perp')].symbol),
        'mixed_pre_perp_total': len(mixed_pre_perp) + len([s for s in mixed_no_spot]),
        'mixed_with_spot_replaced': len(mixed_with_spot),
        'mixed_no_spot_kept_perp': len(mixed_no_spot),
        'rows_dropped_perp_replaced': rows_replaced,
        'rows_added_from_spot_csv': rows_added_from_spot,
        'rows_kept_from_perp_as_is': rows_kept_from_perp,
        'panel_rows': int(len(panel)),
        'panel_symbols': int(panel.symbol.nunique()),
        'panel_date_min': str(panel.trade_date.min().date()),
        'panel_date_max': str(panel.trade_date.max().date()),
    }
    return panel, rep


# ═══ 3. 指标 / 信号 ─ 与 T-141 同款 ══════════════════════════════════════
def add_indicators(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['symbol', 'trade_date']).reset_index(drop=True)
    df['rn'] = df.groupby('symbol').cumcount() + 1
    df['pc'] = df.groupby('symbol')['close'].shift(1)
    df['dv'] = df['close'] * df['volume']
    g = df.groupby('symbol', sort=False)
    R = lambda col, win: g[col].transform(lambda s, w=win: s.rolling(w, min_periods=1).mean())
    df['sma20']  = R('close', 20)
    df['sma200'] = R('close', 200)
    tr = pd.concat([df.high - df.low, (df.high - df.pc).abs(), (df.low - df.pc).abs()], axis=1).max(axis=1)
    df['atr14']  = tr.groupby(df['symbol']).transform(lambda s: s.rolling(14, min_periods=1).mean())
    df['adv30']  = R('dv', 30)
    df['adv40p'] = g['dv'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).mean())
    df['hh40']   = g['high'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).max())
    df['ll40']   = g['low'].transform(lambda s: s.shift(1).rolling(40, min_periods=1).min())
    df['max365'] = g['close'].transform(lambda s: s.rolling(365, min_periods=1).max())
    df['mindd120'] = (df['close'] / df['max365']).groupby(df['symbol']).transform(
                      lambda s: s.rolling(120, min_periods=1).min())
    mask = (
        (df.rn >= RN_MIN) & (df.adv30 >= ADV30_MIN)
        & (df.trade_date >= D_LO) & (df.trade_date <= D_HI)
        & (df.mindd120 <= DD_RATIO_MAX) & ((df.hh40 - df.ll40) / df.hh40 <= AMP_MAX)
        & (df.close > df.hh40) & (df.close > df.sma200) & (df.dv >= 2 * df.adv40p) & (df.atr14 > 0)
    )
    sig = df[mask].rename(columns={'trade_date': 'signal_d'}).copy()
    return df, sig


# ═══ 4. 票面生成:同 T-141 S-610 进场 + S-621 止损 + 同名不重叠 ══════════════
def build_arrays(df: pd.DataFrame) -> dict:
    out = {}
    for sym, s in df.groupby('symbol', sort=False):
        s = s.sort_values('rn')
        d = {'open': s['open'].to_numpy(), 'high': s['high'].to_numpy(),
             'low': s['low'].to_numpy(), 'close': s['close'].to_numpy(),
             'sma20': s['sma20'].to_numpy(), 'atr14': s['atr14'].to_numpy(),
             'date': s['trade_date'].to_numpy()}
        # 持仓日序号 0-based:intraday bar index
        d['rn'] = s['rn'].to_numpy()
        out[sym] = d
    return out


def build_tickets(df: pd.DataFrame, sig: pd.DataFrame, arr: dict, k: float,
                  gated: bool, gate_map: dict, cal_i: dict | None = None) -> pd.DataFrame:
    by_sym = {s: sub.sort_values('signal_d') for s, sub in sig.groupby('symbol', sort=False)}
    if gated:
        by_sym = {s: sub[sub.signal_d.map(gate_map).fillna(True)] for s, sub in by_sym.items()}
    out = []
    for sym, sub in by_sym.items():
        a = arr[sym]; n = len(a['open'])
        ei_prev_exit = -1
        for srow in sub.itertuples(index=False):
            ei = int(srow.rn)  # per-symbol 0-based 索引(对应信号次日 bar)
            if ei < 0 or ei >= n or ei <= ei_prev_exit: continue
            entry = float(a['open'][ei]); stop = entry - k * srow.atr14
            if entry <= stop: continue
            end = min(ei + HOLD_MAX, n)
            xs = xp = None
            for i in range(ei, end):
                if a['low'][i] <= stop:
                    xs = i
                    xp = a['open'][i] if (i > ei and a['open'][i] <= stop) else stop
                    break
                if a['close'][i] < a['sma20'][i]:
                    if i + 1 < n: xs, xp = i + 1, a['open'][i + 1]
                    break
            if xs is None:
                xs = min(ei + HOLD_MAX, n - 1); xp = float(a['close'][xs])
            R_ = (xp - entry) / (entry - stop) - COST_R * entry / (entry - stop)
            entry_d = a['date'][ei]; exit_d = a['date'][xs]
            # T-141 add_idx 用全局日历把 entry_d → entry_i(0-based across 全 panel)
            # 这里当场算好,这样 NAV 用全局 d 索引也不会错位
            entry_g = cal_i[pd.Timestamp(entry_d)] if cal_i is not None else ei
            exit_g  = cal_i[pd.Timestamp(exit_d)]  if cal_i is not None else xs
            out.append({'symbol': sym, 'signal_d': srow.signal_d,
                        'entry_d': entry_d, 'exit_d': exit_d,
                        'entry_px': entry, 'stop_px': float(stop),
                        'exit_px': float(xp), 'R': float(R_),
                        'entry_i': entry_g, 'exit_i': exit_g})
            ei_prev_exit = xs
    t = pd.DataFrame(out).sort_values(['signal_d', 'symbol']).reset_index(drop=True)
    t['tid'] = np.arange(len(t))
    return t


# ═══ 5. 净值内核(逐日盯市) — 与 T-141 盯市同口径 ═════════════════════════════
def make_calendar(df: pd.DataFrame) -> tuple[np.ndarray, dict]:
    cal = np.sort(df.trade_date.unique())
    return cal, {d: i for i, d in enumerate(cal)}

def make_mark(arr: dict, cal: np.ndarray) -> dict:
    mc = {}
    for s, a in arr.items():
        j = np.searchsorted(a['date'], cal, side='right') - 1
        mc[s] = a['close'][np.clip(j, 0, len(a['close']) - 1)].astype(float)
    return mc

def nav_mtm(tk: pd.DataFrame, arr: dict, mark: dict, cal: np.ndarray, cal_i: dict,
            f: float, cap: int | None) -> dict:
    """盯市净值 + 接 / 挡 + 峰值。"""
    cash = 1.0; curve = np.empty(len(cal))
    open_tk: list = []; accepted = skipped = 0
    peak_open = 0; peak_ratio = 0.0
    by_entry, by_exit = {}, {}
    for t_ in tk.itertuples(index=False):
        by_entry.setdefault(t_.entry_i, []).append(t_)
        if t_.exit_i is not None:
            by_exit.setdefault(t_.exit_i, []).append(t_)
    for lst in by_entry.values():
        lst.sort(key=lambda x: (x.signal_d, x.symbol))
    for d in range(len(cal)):
        for t_ in by_exit.get(d, []):
            for o in list(open_tk):
                if o['tid'] == t_.tid:
                    cash += o['units'] * (t_.exit_px - o['entry_px']) - COST_EA * o['notional']
                    open_tk.remove(o); break
        occ = sum(1 for o in open_tk if o['entry_i'] < d <= o['exit_i'])
        for t_ in by_entry.get(d, []):
            if cap is not None and occ >= cap:
                skipped += 1; continue
            ref = curve[d - 1] if d > 0 else cash
            if ref <= 1e-9:
                skipped += 1; continue
            units = f * ref / (t_.entry_px - t_.stop_px)
            notional = units * t_.entry_px
            cash -= COST_EA * notional
            open_tk.append({'tid': t_.tid, 'sym': t_.symbol, 'entry_i': d,
                            'exit_i': t_.exit_i, 'units': units,
                            'entry_px': t_.entry_px, 'exit_px': t_.exit_px,
                            'notional': notional})
            accepted += 1
            if cap is not None: occ += 1
        for o in [x for x in open_tk if x['exit_i'] is not None and x['exit_i'] <= d]:
            cash += o['units'] * (o['exit_px'] - o['entry_px']) - COST_EA * o['notional']
            open_tk.remove(o)
        unreal = sum(o['units'] * (mark[o['sym']][d] - o['entry_px']) for o in open_tk)
        curve[d] = cash + unreal
        peak_open = max(peak_open, len(open_tk))
        notional_now = sum(o['notional'] for o in open_tk)
        if curve[d] > 0:
            peak_ratio = max(peak_ratio, notional_now / curve[d])
    return {'curve': curve, 'accepted': accepted, 'skipped': skipped,
            'peak_open': peak_open, 'peak_ratio': peak_ratio}

def max_dd(curve: np.ndarray) -> float:
    eq = np.maximum.accumulate(np.concatenate([[1.0], curve]))
    p  = np.concatenate([[1.0], curve])
    return float(((eq - p) / eq).max())

def ann_metrics(curve: np.ndarray, start_i: int, cal: np.ndarray) -> dict:
    seg = curve[start_i:]
    fin = float(seg[-1])
    days = float((cal[-1] - cal[start_i]) / np.timedelta64(1, 'D'))
    ann = (fin ** (365.25 / max(days, 1)) - 1) if fin > 0 else float('nan')
    return {'final': fin, 'years': days / 365.25, 'ann': float(ann), 'max_dd': max_dd(seg)}

def fstar_025(curve_finder, target=TARGET_DD, hi=0.30) -> float | None:
    """S-638 定义:0.25% 步长下,盯市回撤仍 ≤ target 的最大 f(T-141 同款)。"""
    best = None; f = F_GRID
    while f <= hi + 1e-12:
        cv, _ = curve_finder(f)
        if max_dd(cv) <= target:
            best = f
        f += F_GRID
    return best


# ═══ 6. S-639 配 ① 表(只报、不判) ═════════════════════════════════════════
def fetch_cap_uncapped(d_lo, d_hi) -> pd.DataFrame:
    su, sk = os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']
    rows, off = [], 0
    while True:
        url = (f'{su}/rest/v1/core_variants_daily?arm=eq.cap_uncapped'
               f'&d=gte.{d_lo.date().isoformat()}&d=lte.{d_hi.date().isoformat()}'
               f'&select=d,ret&order=d&limit=1000&offset={off}')
        req = urllib.request.Request(url, headers={'apikey': sk, 'Authorization': 'Bearer ' + sk})
        chunk = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
        rows += chunk
        if len(chunk) < 1000: break
        off += 1000
    df = pd.DataFrame(rows).rename(columns={'d': 'date'})
    df['date'] = pd.to_datetime(df['date']); df = df.sort_values('date').reset_index(drop=True)
    return df

def combined_s639(core_ret: pd.Series, rv2_nav_at_cal_d: pd.Series, w: float) -> dict:
    """S-639 / T-153 口径:w = R-v2 配比(原 S-639 表头),
    ((1 − w) × core_ret + w × rv2_ret)。月度再平衡 = 权数不变(每日复利)。"""
    # 把两条对齐到同一日历
    df = pd.DataFrame({'core': core_ret, 'rv2': rv2_nav_at_cal_d}).dropna()
    df['rv2_ret'] = df['rv2'].pct_change().fillna(0.0)
    df['w'] = w
    df['comb_ret'] = (1 - w) * df['core'] + w * df['rv2_ret']
    df['nav'] = (1 + df['comb_ret']).cumprod()
    fin = float(df['nav'].iloc[-1])
    days = float((df.index[-1] - df.index[0]) / np.timedelta64(1, 'D'))
    ann = (fin ** (365.25 / max(days, 1)) - 1) if fin > 0 else float('nan')
    daily_vol = float(df['comb_ret'].std(ddof=1))
    ann_vol = daily_vol * np.sqrt(365.25)
    dd = max_dd(df['nav'].to_numpy())
    mret = (1 + df['comb_ret']).resample('MS').prod() - 1
    worst_m = float(mret.min()) if len(mret) else float('nan')
    return {'w_rv2': w, 'ann': ann, 'ann_vol': ann_vol, 'max_dd': dd,
            'final': fin, 'years': days / 365.25, 'worst_month': worst_m,
            'n_days': int(len(df))}


# ═══ 7. 跑 ═══════════════════════════════════════════════════════════════
def run_one_panel(panel: pd.DataFrame, gate_map: dict, panel_label: str) -> dict:
    print(f'\n===== {panel_label} =====', flush=True)
    df, sig = add_indicators(panel)
    print(f'  sig={len(sig)} syms={df.symbol.nunique()} '
          f'date_range={df.trade_date.min().date()}..{df.trade_date.max().date()}', flush=True)
    arr = build_arrays(df)
    cal, cal_i = make_calendar(df)
    mark = make_mark(arr, cal)
    # 发现段(信号日 ≤ 2026-06-20)
    tk_disc = build_tickets(df, sig, arr, K_FID, gated=True, gate_map=gate_map, cal_i=cal_i)
    tk_disc = tk_disc[tk_disc.signal_d <= DISC_HI].reset_index(drop=True)
    tk_disc['tid'] = np.arange(len(tk_disc))
    # 全量(含留出段)
    tk_all  = build_tickets(df, sig, arr, K_FID, gated=True, gate_map=gate_map, cal_i=cal_i)
    tk_all = tk_all[tk_all.signal_d <= HOLDOUT_HI].reset_index(drop=True)
    tk_all['tid'] = np.arange(len(tk_all))

    def finder(f, tko=tk_disc, capv=10):
        si = int(tko.entry_i.min()) if len(tko) else 0
        return nav_mtm(tko, arr, mark, cal, cal_i, f, capv)['curve'][si:], si

    # ① 0.25% 步长求 f★
    fs_disc = fstar_025(lambda f: finder(f, tk_disc, 10))
    fs_all  = fstar_025(lambda f: finder(f, tk_all, 10))

    res = {'n_signals': int(len(sig)),
           'n_disc': int(len(tk_disc)), 'n_all': int(len(tk_all)),
           'holdout_n': int((tk_all.signal_d > DISC_HI).sum())}
    # 在该 f★ 上跑完整指标(f★ = None 时用最小的 F_GRID 当下界也能用)
    for label, tk, fs in (('disc', tk_disc, fs_disc), ('all', tk_all, fs_all)):
        use_f = fs if fs is not None else F_GRID
        res[f'{label}_fstar'] = fs  # may be None
        res[f'{label}_capped']  = (fs is None)  # True ⇒ 即使 f=F_GRID DD 仍 < −35%(信号不够或 cap 限制使 DD 反向)
        cv, si = finder(use_f, tk, 10)
        r = nav_mtm(tk, arr, mark, cal, cal_i, use_f, 10)
        m = ann_metrics(cv, si, cal)
        res[f'{label}_acc'] = r['accepted']
        res[f'{label}_skp'] = r['skipped']
        res[f'{label}_peak_open'] = r['peak_open']
        res[f'{label}_peak_ratio'] = r['peak_ratio']
        res[f'{label}_ann'] = m['ann']
        res[f'{label}_dd']  = m['max_dd']
        res[f'{label}_final'] = m['final']

    # ② S-638 复现:f = 1% 在发现段 / 全量
    for label, tk in (('disc', tk_disc), ('all', tk_all)):
        cv, si = finder(0.01, tk, 10)
        r = nav_mtm(tk, arr, mark, cal, cal_i, 0.01, 10)
        m = ann_metrics(cv, si, cal)
        res[f's638_{label}_f1_acc']   = r['accepted']
        res[f's638_{label}_f1_skp']   = r['skipped']
        res[f's638_{label}_f1_dd']    = m['max_dd']
        res[f's638_{label}_f1_ann']   = m['ann']
        res[f's638_{label}_f1_final'] = m['final']

    # ③ S-639 的票:信号日 ≤ 2026-10-17(全量包含留出段)
    tk_s639 = tk_all.copy()

    def f1_nav(tk):
        cv, si = finder(0.01, tk, 10)
        return cv, si

    r_s639 = nav_mtm(tk_s639, arr, mark, cal, cal_i, 0.01, 10)
    nav_1pct = r_s639['curve']
    si_s639 = int(tk_s639.entry_i.min()) if len(tk_s639) else 0
    nav_series = pd.Series(nav_1pct, index=pd.DatetimeIndex(cal))
    res['s639_curve'] = nav_series
    res['s639_accepted'] = r_s639['accepted']
    res['s639_skipped']  = r_s639['skipped']
    res['s639_start_i']  = si_s639

    return res


# ═══ 8. 落盘 + 报告 ══════════════════════════════════════════════════════
def main():
    print('# === T-153 start ===', flush=True)
    perp, prov_perp = load_perp_panel()
    print(f'PERP rows={len(perp)} syms={perp.symbol.nunique()}', flush=True)

    spk, prov_spot = load_spot_panel()
    print(f'SPOT csvs={prov_spot["files"]} rows={prov_spot["rows"]}', flush=True)

    cls = pd.read_csv(CLS_PATH)
    spot, rep = replace_mixed(perp, spk, cls)
    print(f'SPOT panel rows={rep["panel_rows"]} syms={rep["panel_symbols"]}', flush=True)
    print(f'    dropped-perp-replaced={rep["rows_dropped_perp_replaced"]} '
          f'added-from-spot={rep["rows_added_from_spot_csv"]} '
          f'kept-perp={rep["rows_kept_from_perp_as_is"]}', flush=True)
    print(f'    mixed_pre_perp={rep["mixed_pre_perp_total"]} '
          f'replaced={rep["mixed_with_spot_replaced"]} no-spot={rep["mixed_no_spot_kept_perp"]}', flush=True)

    # 快存到 SCRATCH(便于复现 / 审计)
    spot.to_parquet(os.path.join(SCRATCH, 'panel_spot.parquet'))
    json.dump({'perp': prov_perp, 'spot_csv': prov_spot, 'replace': rep,
               'pulled_utc': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
              open(os.path.join(SCRATCH, 'panel_provenance.json'), 'w'), indent=2)

    gate_map = load_gate()

    res_perp = run_one_panel(perp, gate_map, 'PERP (现状=t141 原 panel)')
    res_spot = run_one_panel(spot, gate_map, 'SPOT (T-153 替换后的现货面板)')

    # ③ S-639 表(永续 vs 现货 两份对照)
    core = fetch_cap_uncapped(S639_LO, S639_HI).set_index('date')['ret']
    print(f'\nCORE cap_uncapped rows={len(core)} {core.index.min().date()}..{core.index.max().date()}', flush=True)

    s639_perp = run_s639_table(res_perp, core)
    s639_spot = run_s639_table(res_spot, core)

    write_report(perp, spot, prov_perp, prov_spot, rep, res_perp, res_spot, s639_perp, s639_spot, core)
    json.dump({'perp': res_perp_clean(res_perp), 'spot': res_spot_clean(res_spot),
               's639_perp': s639_perp, 's639_spot': s639_spot,
               'replace': rep},
              open(os.path.join(SCRATCH, 't153_results.json'), 'w'), indent=2, default=str)
    print('DONE', flush=True)


def res_perp_clean(r):
    d = {k: v for k, v in r.items() if k != 's639_curve'}
    d['s639_curve_start'] = str(r['s639_curve'].index.min().date())
    d['s639_curve_end']   = str(r['s639_curve'].index.max().date())
    return d

def res_spot_clean(r):
    return res_perp_clean(r)

def run_s639_table(res: dict, core: pd.Series) -> dict:
    nav = res['s639_curve']
    nav_at_d = nav.reindex(core.index).ffill()
    # 把 R-v2 NAV 在 S639 起点归一到 1.0
    base = float(nav_at_d.iloc[0])
    nav_norm = nav_at_d / base
    out = {}
    for w in (0.0, 0.10, 0.20, 0.30):
        out[f'w_{w:.2f}'] = combined_s639(core, nav_norm, w)
    return out


def write_report(perp, spot, prov_perp, prov_spot, rep, res_perp, res_spot, s639_perp, s639_spot, core):
    def pct(x):
        return '—' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x:+.1%}'
    def fx(x):
        return '—' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x:.2%}'

    L = []
    A = L.append
    A('# T-153 — R-v2 的钱曲线换成现货面板会怎样(S-637 决定表的另一半)')
    A('')
    A(f'**任务:** T-153 · 2026-10-21 · lane-b · 仅报不判')
    A(f'**口径:** S-627 闸门版票(k = 2.5、majors 200 日闸门、S-610 进场、出场 = 进场 − k·ATR14 / 收盘<SMA20 次日开盘 / 120 根)')
    A(f'       同名不重叠、同时最多 10 张、f★ 按盯市最大回撤 ≥ −35% 找最大 f、0.25% 步长。')
    A('')
    A('## 0. 永续 vs 现货 对照表(主表 —— §1.1 同基线下两面板并列)')
    A('')
    A('| 项 | 永续(现状 = T-141 的 ohlcv_binance_hist) | 现货(T-153 替换后) |')
    A('|---|---|---|')
    def row(k, p, s):
        vp = res_perp.get(k); vs = res_spot.get(k)
        if isinstance(vp, float) or isinstance(vp, int):
            if 'dd' in k:
                return f'| {k} | {pct(-vp) if vp else "—"} | {pct(-vs) if vs else "—"} |'
            if 'ann' in k:
                return f'| {k} | {pct(vp)} | {pct(vs)} |'
            return f'| {k} | {vp} | {vs} |'
        return ''
    A(f"| 面板行数 | {len(perp):,} | {rep['panel_rows']:,} |")
    A(f"| 名字数 | {perp.symbol.nunique()} | {rep['panel_symbols']} |")
    A(f"| 日期区间 | {prov_perp['date_min']} → {prov_perp['date_max']} | "
      f"{rep['panel_date_min']} → {rep['panel_date_max']} |")
    A(f"| sha256 / 取用 | `{prov_perp['sha256'][:12]}…` / {prov_perp['file_mtime_utc']} | "
      f"spot CSV 行数={prov_spot['rows']:,},无 sha256(Binance 公开接口即时拉) |")
    A(f"| 信号总数(2020-03 → 2026-10-19) | {res_perp['n_signals']} | {res_spot['n_signals']} |")
    A(f"| 发现段(≤ 2026-06-20)票数 | {res_perp['n_disc']} | {res_spot['n_disc']} |")
    A(f"| 全量(≤ 2026-10-17 含留出段)票数 | {res_perp['n_all']} | {res_spot['n_all']} |")
    A(f"| **发现段 f★(0.25% 步长)** | {fx(res_perp['disc_fstar'])} | {fx(res_spot['disc_fstar'])} |")
    A(f"| f★ 下年化 | {pct(res_perp['disc_ann'])} | {pct(res_spot['disc_ann'])} |")
    A(f"| f★ 下盯市最大回撤 | {pct(-res_perp['disc_dd'])} | {pct(-res_spot['disc_dd'])} |")
    A(f"| f★ 下接 / 挡 | {res_perp.get('disc_acc','—')} / {res_perp.get('disc_skp','—')} | "
      f"{res_spot.get('disc_acc','—')} / {res_spot.get('disc_skp','—')} |")
    A(f"| f★ 下峰值同时持仓 | {res_perp.get('disc_peak_open','—')} | {res_spot.get('disc_peak_open','—')} |")
    A(f"| f★ 下峰值总名义 / 权益 | {res_perp.get('disc_peak_ratio', float('nan')):.2f} | "
      f"{res_spot.get('disc_peak_ratio', float('nan')):.2f} |")
    A('')
    A('## 1. S-627 闸门版 + 10 张上限 — 在两面板上 ① 与 ② 跑全')
    A('')
    A('### 1.1 主表:f★(0.25% 步长,盯市回撤 ≥ −35%)下的年化 / 回撤 / 接挡')
    A('')
    A('| 面板 | 票段 | 票数 | f★(0.25% 网格)| f★下接 | f★下挡 | f★下年化 | f★下回撤 | 期末净值 | 峰值持仓 | 峰值名义/权益 |')
    A('|---|---|---|---|---|---|---|---|---|---|---|')
    for label, res in (('永续', res_perp), ('现货', res_spot)):
        for tk_label in ('disc', 'all'):
            fs = res.get(f'{tk_label}_fstar')
            capped = res.get(f'{tk_label}_capped', False)
            if fs is None:
                # 封顶:小 f 也跌穿 −35%(信号规模足够独立推深回撤)或全无信号
                A(f"| {label} | {tk_label} | {res[f'n_{tk_label}']} | "
                  f"封顶 ≥ 0.30% (DD 仍 > −35%) | {res[f'{tk_label}_acc']} | {res[f'{tk_label}_skp']} | "
                  f"{pct(res[f'{tk_label}_ann'])} | {pct(-res[f'{tk_label}_dd'])} | "
                  f"{res[f'{tk_label}_final']:.3f} | {res[f'{tk_label}_peak_open']} | "
                  f"{res[f'{tk_label}_peak_ratio']:.2f} |")
                continue
            tag = ' (触上限 0.30%)' if capped else ''
            A(f"| {label} | {tk_label} | {res[f'n_{tk_label}']} | "
              f"{fx(fs)}{tag} | {res[f'{tk_label}_acc']} | {res[f'{tk_label}_skp']} | "
              f"{pct(res[f'{tk_label}_ann'])} | {pct(-res[f'{tk_label}_dd'])} | "
              f"{res[f'{tk_label}_final']:.3f} | {res[f'{tk_label}_peak_open']} | "
              f"{res[f'{tk_label}_peak_ratio']:.2f} |")
    A('')
    A('> 「f★(0.25% 网格)」= 步长 0.25%、盯市最大回撤仍 ≤ −35% 的最大 f(T-141 同款)。')
    A('> 「封顶 ≥ 0.30% (DD 仍 > −35%)」= 即使 f = 0.25% 最小一步,DD 也比 −35% 还深 —— 说明该面板 / 票段在这种 k / 闸门下回撤控制不住;这里报 f = F_GRID(0.25%) 处的数。')
    A('')
    A('### 1.2 S-638 复现(交叉核对):f = 1%,盯市回撤必须对上 −32.3% ± 1pp 才往下')
    A('')
    A('| 面板 | 票段 | f = 1% 接 | f = 1% 挡 | f = 1% 盯市回撤 | 目标 −32.3% ± 1pp | 差 | f = 1% 年化 |')
    A('|---|---|---|---|---|---|---|---|')
    for label, res in (('永续', res_perp), ('现货', res_spot)):
        for tk_label in ('disc', 'all'):
            ddp = res[f's638_{tk_label}_f1_dd']
            target = 0.323
            ok = abs(ddp - target) <= 0.01
            A(f"| {label} | {tk_label} | {res[f's638_{tk_label}_f1_acc']} | "
              f"{res[f's638_{tk_label}_f1_skp']} | {pct(-ddp)} | "
              f"{pct(-target)} ± 1pp | {(ddp - target)*100:+.2f}pp {'✅' if ok else '❌'} | "
              f"{pct(res[f's638_{tk_label}_f1_ann'])} |")
    A('')
    A('> 「差」正 = 实际回撤比目标深(永续 vs 现货哪个更深)。'+ '✅ = 永续面板发现段接到 S-638 目标 ± 1pp 内,可继续。')
    A('')
    A('## 2. S-639 表 — ① = cap_uncapped 与 R-v2 配, w ∈ {0, 0.10, 0.20, 0.30}')
    A('')
    A(f'区间:{S639_LO.date()} → {S639_HI.date()} · 月度再平衡 · R-v2:信号日 ≤ 2026-10-17,f = 1%,最多 10 张 · **w = R-v2 配比**(原 S-639 表头)')
    A(f'核心臂行数:{len(core)} · 起点净值 = 1.0 · R-v2 在 {S639_LO.date()} 由自身净值归一到 1.0')
    A('')
    A('### 2.1 永续面板')
    A('')
    A('| w (R-v2 配比) | 年化 | 年化波动 | 最大回撤 | 最差月 | 期末 NAV | 年数 |')
    A('|---|---|---|---|---|---|---|')
    for w_label, r in sorted(s639_perp.items()):
        A(f"| {w_label.replace('w_','w=')} | {pct(r['ann'])} | {pct(r['ann_vol'])} | "
          f"{pct(-r['max_dd'])} | {pct(r['worst_month'])} | {r['final']:.3f} | {r['years']:.2f} |")
    A('')
    A('### 2.2 现货面板')
    A('')
    A('| w (R-v2 配比) | 年化 | 年化波动 | 最大回撤 | 最差月 | 期末 NAV | 年数 |')
    A('|---|---|---|---|---|---|---|')
    for w_label, r in sorted(s639_spot.items()):
        A(f"| {w_label.replace('w_','w=')} | {pct(r['ann'])} | {pct(r['ann_vol'])} | "
          f"{pct(-r['max_dd'])} | {pct(r['worst_month'])} | {r['final']:.3f} | {r['years']:.2f} |")
    A('')
    A('### 2.3 决定表 — 给 R-v2 配比 x 时两面板的差距')
    A('')
    A('| w (R-v2) | 永续回撤 | 现货回撤 | 永续年化 | 现货年化 | 永续波动 | 现货波动 |')
    A('|---|---|---|---|---|---|---|')
    ws = sorted(s639_perp.keys())
    for w in ws:
        rp = s639_perp[w]; rs = s639_spot[w]
        A(f"| {w.replace('w_','w=')} | {pct(-rp['max_dd'])} | {pct(-rs['max_dd'])} | "
          f"{pct(rp['ann'])} | {pct(rs['ann'])} | {pct(rp['ann_vol'])} | {pct(rs['ann_vol'])} |")
    A('')
    A('## 3. 方法 / 数据来源 / 唯一编号')
    A('')
    A('### 3.1 数据')
    A('')
    A(f'- 永续面板:`{SRC_PARQUET}` · sha256 `{prov_perp["sha256"][:32]}…` · '
      f'*{prov_perp["rows"]:,} 行 / {prov_perp["symbols"]} 名* · '
      f'{prov_perp["date_min"]} → {prov_perp["date_max"]} · 上游 = `ohlcv_daily source=binance_hist`')
    A(f'- 现货日线:`{SPOT_DIR}`(T-151 现取的 Binance api/v3/klines,共 {prov_spot["files"]} 文件 / '
      f'{prov_spot["rows"]:,} 行,{prov_spot["date_min"]} → {prov_spot["date_max"]})')
    A(f'- T-151 分类:`{CLS_PATH}` · 259 名,四类 = 混合 {rep["mixed_total"]}、全程现货 40、判不出 21、切换前无对 6')
    A(f'- 替换执行(pre-08-08 行被 t151 spot csv 替换):{rep["mixed_with_spot_replaced"]} 名 / '
      f'无 spot 对、保留 perp 的:{rep["mixed_no_spot_kept_perp"]} 名 · '
      f'被替换的原行数 = {rep["rows_dropped_perp_replaced"]:,}')
    A(f'- 闸门序列 = `style_index_pit_daily`(style=majors, weighting=cap)现取现缓存。')
    A(f'- ① NAV = Supabase `core_variants_daily` arm = `cap_uncapped`(只读 publishable key)。')
    A('')
    A('### 3.2 不替换部分与已知偏置')
    A('')
    A(f'- 永续面板里有 {rep["mixed_total"]} 个「混合」名,pre = perp 且 t151/spot 里有现货数据的 {rep["mixed_with_spot_replaced"]} 名,'
      f'其 pre-08-08 全部接 t151 现货 csv(2017-2021 行若 t151 csv 没覆盖则一并丢弃 —— 整个 spot panel 在这些名上从 2022-01-01 起)。')
    A(f'- {rep["mixed_no_spot_kept_perp"]} 个「混合」名在 t151 里没有对应现货对,其 pre-08-08 仍用永续数据 —— 严格说它们也带 perp 偏置,但面板里数量不大。')
    A(f'- 40 个「全程现货」名沿用原 panel(其 pre-08-08 在原 binance_hist 里就是现货口径)。')
    A('- 信号定义、出场、止损、热度上限、手续费、盯市口径全部同 T-141(`docs/research/t141_s621_equal_dd.py`)。')
    A('')
    A(f'### 3.3 主面板(写入 SCRATCH,不写库)')
    A('')
    A(f'- `{SCRATCH}/panel_spot.parquet` 与 `{SCRATCH}/t153_results.json`')
    A('')
    A('### 3.4 任务范围与边界')
    A('')
    A('- 本脚本不修改 `T-141`、`T-148`、`S-627` 的票定义;只在 S-627 闸门 + 10 张上限之上做面板替换。')
    A('- S-639 表只报配比 / 年化 / 波动 / 回撤 / 最差月,**不断言**最优 w(那是 Jazz 的事)。')
    A('- 闸门 `GATE` 用当日 d 的 ret 复原的 level 与 SMA200 比较;现取现缓存,复用 T-141 的 cache dir。')
    A('')
    A(f'**T-153 task 状态:** `in_review` · 推 `{os.environ.get("BRANCH","lane-b/T-153")}` · '
      f'执行时区 UTC:{dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}')

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    open(REPORT_PATH, 'w').write('\n'.join(L) + '\n')
    print('WROTE', REPORT_PATH, flush=True)


if __name__ == '__main__':
    main()
