#!/usr/bin/env python3
"""T-141 / S-621 — R 臂宽止损在「同最大回撤 (−35%)」下比年化 + 热度上限 10 张。

预注册(REFUTATION_LEDGER.md S-621,写于任何计算之前):
  进场 = S-610 原样;初始止损 = 进场 − k × ATR14[t],k ∈ {1(=S-610 基线 max(t日低点, 进场−ATR)),
  2.0, 2.5, 3.0};出场(止损优先 / close<SMA20 次日开盘出 / 120 根)与同名不重叠同 S-610。
  H 版:同时持有的未平仓票数 ≤ 10(先来先得,超出记 skipped)。
  口径:每个 k 二分求每笔风险 f 使最大回撤 = −35%,报该 f 下年化。
  判三条:① k=2.5 年化 > k=1 ② k=2.0 与 3.0 也 > k=1(平滑)③ H 版(k=2.5+上限)年化 ≥ 无上限版的 80%。

§Seth-1020c 追加(本脚本新增,S-638 同口径):同一把尺子再按**逐日盯市**算一遍
  (逐日权益 = 已实现 + Σ 持仓 units × (当日收盘 − 进场价) − 已付进场成本),
  与「按出场日复利」并列。

数据(只读):
  * OHLCV 快照 = /Volumes/CometCloudAI/cometcloud-local/_data/research/t141/ohlcv_binance_hist.parquet
    (复制自 t131 的同名快照;报头写 sha256 / 行数 / 区间 / 拉取时间)
  * 闸门 = style_index_pit_daily (style=majors, weighting=cap),按 ret 复原 level,现取现缓存。
只读 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'];不读 .env、不打印 key。
"""
import os, sys, json, hashlib, shutil, datetime as dt
import numpy as np
import pandas as pd

DATA_ROOT = '/Volumes/CometCloudAI/cometcloud-local'
SCRATCH   = os.path.join(DATA_ROOT, '_data/research/t141')
REPORT    = os.path.join(DATA_ROOT, '_reports/absorb_input/T-141_s621.md')
SRC_PARQUET = os.path.join(DATA_ROOT, '_data/research/t131/ohlcv_binance_hist.parquet')
os.makedirs(SCRATCH, exist_ok=True)

# ── S-610 / S-621 写死的常量 ─────────────────────────────────────────────────
EXCLUDE  = {'USDC', 'BTCDOM', 'DEFI'}
COST_R   = 0.004          # R 公式里的单边合计 40bp
COST_EA  = 0.002          # 钱口径:进场 / 出场各 0.2% × 进场名义
D_LO, D_HI = pd.Timestamp('2020-03-01'), pd.Timestamp('2026-10-17')
DISC_HI  = pd.Timestamp('2026-06-20')   # 发现段 / 留出段切分(S-618 / S-627 / S-638)
RN_MIN, ADV30_MIN = 220, 5_000_000
DD_RATIO_MAX, AMP_MAX, HOLD_MAX = 0.5, 0.40, 120
KS       = [1.0, 2.0, 2.5, 3.0]
TARGET_DD = 0.35
CAPS     = [None, 10]

# ═══ 1. 快照 ═══════════════════════════════════════════════════════════════
snap_path = os.path.join(SCRATCH, 'ohlcv_binance_hist.parquet')
if not os.path.exists(snap_path):
    shutil.copy2(SRC_PARQUET, snap_path)
h = hashlib.sha256(open(snap_path, 'rb').read()).hexdigest()
st = os.stat(snap_path)
df = pd.read_parquet(snap_path)
df['trade_date'] = pd.to_datetime(df['trade_date'])
df = df[~df.symbol.isin(EXCLUDE)].copy().sort_values(['symbol', 'trade_date']).reset_index(drop=True)
PROV = {
    'snapshot_path': snap_path,
    'sha256': h,
    'rows': int(len(df)),
    'symbols': int(df.symbol.nunique()),
    'date_min': str(df.trade_date.min().date()),
    'date_max': str(df.trade_date.max().date()),
    'file_mtime_utc': dt.datetime.utcfromtimestamp(st.st_mtime).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'pulled_utc': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'provenance': f'复制自 t131 快照 {SRC_PARQUET};上游 = ohlcv_daily source=binance_hist',
}
print('SNAPSHOT', json.dumps(PROV, ensure_ascii=False), flush=True)

# 闸门序列(style_index_pit_daily,majors/cap)—— 现取现缓存
gate_path = os.path.join(SCRATCH, 'majors_cap_gate.json')
if os.path.exists(gate_path):
    G = json.load(open(gate_path))
else:
    import urllib.request
    su, sk = os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']
    rows, off = [], 0
    while True:
        req = urllib.request.Request(
            f'{su}/rest/v1/style_index_pit_daily?style=eq.majors&weighting=eq.cap'
            f'&ret=gt.-0.95&select=d,ret&order=d&limit=1000&offset={off}',
            headers={'apikey': sk, 'Authorization': 'Bearer ' + sk})
        chunk = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
        rows += chunk
        if len(chunk) < 1000:
            break
        off += 1000
    G = {'rows': len(rows), 'd': [r['d'] for r in rows], 'ret': [r['ret'] for r in rows]}
    json.dump(G, open(gate_path, 'w'))
gd = pd.to_datetime(G['d'])
lvl = np.exp(np.log1p(np.asarray(G['ret'])).cumsum())
sma = pd.Series(lvl).rolling(200, min_periods=1).mean().to_numpy()
nwin = pd.Series(lvl).rolling(200, min_periods=1).count().to_numpy()
gate_open = pd.Series((nwin < 200) | (lvl > sma), index=gd)
GATE = {d: bool(v) for d, v in gate_open.items()}
print(f'GATE rows={G["rows"]} {gd.min().date()}..{gd.max().date()}', flush=True)

# ═══ 2. 指标(与 k 无关,只算一次) ════════════════════════════════════════════
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

SIG_MASK = (
    (df.rn >= RN_MIN) & (df.adv30 >= ADV30_MIN) & (df.trade_date >= D_LO) & (df.trade_date <= D_HI)
    & (df.mindd120 <= DD_RATIO_MAX) & ((df.hh40 - df.ll40) / df.hh40 <= AMP_MAX)
    & (df.close > df.hh40) & (df.close > df.sma200) & (df.dv >= 2 * df.adv40p) & (df.atr14 > 0)
)
SIG_ALL = df[SIG_MASK].rename(columns={'trade_date': 'signal_d'}).copy()
print(f'SIGNALS pre-recursion = {len(SIG_ALL)}', flush=True)

# 每名 numpy 数组(1-based rn → 0-based 索引:数组[i] 对应 rn = i+1)
ARR = {}
for sym, s in df.groupby('symbol', sort=False):
    s = s.sort_values('rn')
    ARR[sym] = {k: s[k].to_numpy() for k in ('open', 'high', 'low', 'close', 'sma20', 'atr14')}
    ARR[sym]['date'] = s['trade_date'].to_numpy()
    # 大鱼:之后 120 根内最高收盘(只到数据末尾)
    c = s['close'].to_numpy()
    fwd = np.array([c[i:i + 121].max() if i < len(c) else c[-1] for i in range(len(c))])
    ARR[sym]['fwd_max120'] = fwd

# ═══ 3. 出场 / 递归(每个 k 一次) ════════════════════════════════════════════
def build_tickets(k, gated=False, baseline=False):
    """baseline=True ⇒ S-610 原样的 max(t日低点, 进场−ATR) 止损(仅 k=1)。"""
    by_sym = {s: sub.sort_values('signal_d') for s, sub in
              SIG_ALL.groupby('symbol', sort=False)}
    if gated:
        by_sym = {s: sub[sub.signal_d.map(GATE).fillna(True)] for s, sub in by_sym.items()}
    out = []
    for sym, sub in by_sym.items():
        a = ARR[sym]
        n = len(a['open'])
        ei_prev_exit = -1
        blocked = False
        for srow in sub.itertuples(index=False):
            if blocked:
                break
            ei = int(srow.rn)                      # entry bar 的 0-based 下标
            if ei >= n or ei <= ei_prev_exit:
                continue
            entry = a['open'][ei]
            stop = max(srow.low, entry - srow.atr14) if baseline else entry - k * srow.atr14
            if entry <= stop:
                continue
            end = min(ei + HOLD_MAX, n)
            xs, xp = None, None
            for i in range(ei, end):
                if a['low'][i] <= stop:
                    xs = i
                    xp = a['open'][i] if (i > ei and a['open'][i] <= stop) else stop
                    break
                if a['close'][i] < a['sma20'][i]:
                    if i + 1 < n:
                        xs, xp = i + 1, a['open'][i + 1]
                    break
            if xs is None:
                xs = min(ei + HOLD_MAX, n - 1)
                xp = a['close'][xs]
            R_ = (xp - entry) / (entry - stop) - COST_R * entry / (entry - stop)
            out.append({'symbol': sym, 'signal_d': srow.signal_d,
                        'entry_d': a['date'][ei], 'exit_d': a['date'][xs],
                        'entry_px': float(entry), 'stop_px': float(stop),
                        'exit_px': float(xp), 'R': float(R_)})
            ei_prev_exit = xs
            # 最后一根仍未平 ⇒ S-638 同口径:still_open,此后同名不再开票
            if xs == n - 1 and (ei + HOLD_MAX) > (n - 1):
                blocked = True
    t = pd.DataFrame(out).sort_values(['signal_d', 'symbol']).reset_index(drop=True)
    return t

# 实施检验 ①:S-610 基线必须对上 n = 1,013 / 均值 R +0.350
BASE = build_tickets(1.0, baseline=True)
chk_n, chk_r = len(BASE), float(BASE.R.mean())
print(f'S-610 REPRO  n={chk_n} (target 1013, Δ={chk_n-1013:+d})  meanR={chk_r:+.4f} '
      f'(target 0.350, Δ={chk_r-0.350:+.4f})', flush=True)
BASE_OK = (abs(chk_n - 1013) <= 10) and abs(chk_r - 0.350) <= 0.02
print(f'S-610 REPRO GATE = {"PASS" if BASE_OK else "FAIL(停下报告)"}', flush=True)

# ═══ 4. 大鱼(S-618 写死定义,只报项) ═════════════════════════════════════════
def fish_table():
    hits = []
    for sym, a in ARR.items():
        d = a['date']
        mask = (a['close'] > 0) & (a['fwd_max120'] >= 3 * a['close'])
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            continue
        grp, cur = [], [idx[0]]
        for i in idx[1:]:
            if i - cur[-1] <= 30:
                cur.append(i)
            else:
                grp.append(cur); cur = [i]
        grp.append(cur)
        for gseq in grp:
            s_i = gseq[0]
            last_hit = gseq[-1]
            span = d[s_i: min(last_hit + 121, len(d))]
            if len(span) == 0:
                continue
            peak_rel = int(np.argmax(a['close'][s_i:s_i + len(span)]))
            peak_i = s_i + peak_rel
            if pd.Timestamp(d[s_i]) < D_LO or pd.Timestamp(d[s_i]) > DISC_HI:
                continue
            hits.append({'symbol': sym, 's_i': s_i, 'peak_i': peak_i,
                         's_close': float(a['close'][s_i]),
                         'size': float(np.log(a['close'][peak_i] / a['close'][s_i]))})
    return pd.DataFrame(hits)

FISH = fish_table()
print(f'FISH (2020-03-01..{DISC_HI.date()}, 120 根内 3x) = {len(FISH)}', flush=True)

def fish_stats(tk):
    if len(FISH) == 0 or len(tk) == 0:
        return {}
    recs = []
    for f_ in FISH.itertuples(index=False):
        a = ARR[f_.symbol]
        w = tk[(tk.symbol == f_.symbol) & (tk.entry_i >= f_.s_i) & (tk.entry_i <= f_.peak_i)]
        if len(w) == 0:
            continue
        w = w.iloc[0]
        last_i = w.exit_i
        recs.append({
            'year': pd.Timestamp(a['date'][f_.s_i]).year,
            'size': f_.size,
            'capture': float(np.log(w.exit_px / w.entry_px) / f_.size) if f_.size > 0 else np.nan,
            'ticket': float(np.log(w.exit_px / w.entry_px)),
            'late': float(np.log(w.entry_px / f_.s_close) / f_.size) if f_.size > 0 else np.nan,
        })
    r = pd.DataFrame(recs)
    if not len(r):
        return {}
    return {'fish_total': int(len(FISH)), 'fish_caught': int(len(r)),
            'catch_rate': float(len(r) / len(FISH)), 'mean_capture': float(r.capture.mean()),
            'mean_ticket_ln': float(r.ticket.mean()), 'mean_late_frac': float(r.late.mean()),
            'by_year': {int(y): int(n) for y, n in r.groupby('year').size().items()}}

# ═══ 5. 净值内核(两种口径) ══════════════════════════════════════════════════
CAL = np.sort(df.trade_date.unique())
CAL_I = {d: i for i, d in enumerate(CAL)}

def mark_lookup(sym, day_i):
    """该名在 day_i(含)当天的最近一根收盘 —— 无 K 线 ⇒ 用最近一根。"""
    a = ARR[sym]
    j = np.searchsorted(a['date'], CAL[day_i], side='right') - 1
    return float(a['close'][max(j, 0)])

def add_idx(tk):
    if 'entry_i' in tk.columns:
        return tk
    tk = tk.copy()
    tk['entry_i'] = tk.entry_d.map(CAL_I)
    tk['exit_i']  = tk.exit_d.map(lambda d: CAL_I.get(d))
    tk['tid']     = np.arange(len(tk))
    return tk

# 盯市取「最近一根收盘」:预先把每个名的收盘 ffill 到全日历(无 K 线 ⇒ 用最近一根)
MARKC = {}
for _s, _a in ARR.items():
    _j = np.searchsorted(_a['date'], CAL, side='right') - 1
    MARKC[_s] = _a['close'][np.clip(_j, 0, len(_a['close']) - 1)].astype(float)

def nav(tk, f, cap, mtm):
    """逐日净值。mtm=True ⇒ 逐日盯市(已实现 + Σ 持仓浮盈 − 已付成本);
    mtm=False ⇒ 只按出场日复利(净值只在出场日变)。每票 units = f × 权益基准 /(进场−止损)。
    返回 (净值曲线, accepted, skipped, peak_open, peak_notional/equity)。"""
    cash = 1.0
    curve = np.empty(len(CAL))
    open_tk = []
    accepted = skipped = 0
    peak_open = 0
    peak_ratio = 0.0
    entries_by_day, exits_by_day = {}, {}
    for t_ in tk.itertuples(index=False):
        entries_by_day.setdefault(t_.entry_i, []).append(t_)
        if t_.exit_i is not None:
            exits_by_day.setdefault(t_.exit_i, []).append(t_)
    for lst in entries_by_day.values():                 # 同日:先信号日再名字
        lst.sort(key=lambda x: (x.signal_d, x.symbol))
    for d in range(len(CAL)):
        for t_ in exits_by_day.get(d, []):
            for o in list(open_tk):
                if o['tid'] == t_.tid:
                    cash += o['units'] * (t_.exit_px - o['entry_px']) - COST_EA * o['notional']
                    open_tk.remove(o); break
        occ = sum(1 for o in open_tk if o['entry_i'] < d <= o['exit_i'])
        for t_ in entries_by_day.get(d, []):
            if cap is not None and occ >= cap:
                skipped += 1; continue
            ref = curve[d - 1] if (mtm and d > 0) else cash
            if ref <= 1e-9:
                skipped += 1; continue
            units = f * ref / (t_.entry_px - t_.stop_px)
            notional = units * t_.entry_px
            cash -= COST_EA * notional
            open_tk.append({'tid': t_.tid, 'sym': t_.symbol, 'entry_i': d,
                            'exit_i': t_.exit_i, 'units': units,
                            'entry_px': t_.entry_px, 'exit_px': t_.exit_px, 'notional': notional})
            accepted += 1
            if cap is not None:
                occ += 1
        # 同日进同日出(SQL 允许 xi == ei,止损在进场那根就打到):当天结掉,别留在账上
        for o in [x for x in open_tk if x['exit_i'] is not None and x['exit_i'] <= d]:
            cash += o['units'] * (o['exit_px'] - o['entry_px']) - COST_EA * o['notional']
            open_tk.remove(o)
        if mtm:
            unreal = sum(o['units'] * (MARKC[o['sym']][d] - o['entry_px']) for o in open_tk)
            curve[d] = cash + unreal
        else:
            curve[d] = cash
        peak_open = max(peak_open, len(open_tk))
        notional_now = sum(o['notional'] for o in open_tk)
        if curve[d] > 0:
            peak_ratio = max(peak_ratio, notional_now / curve[d])
    return curve, accepted, skipped, peak_open, peak_ratio

def max_dd(curve):
    eq = np.maximum.accumulate(np.concatenate([[1.0], curve]))
    path = np.concatenate([[1.0], curve])
    return float(((eq - path) / eq).max())

def metrics(curve, start_i):
    """净值窗口 = 第一张票的进场日 → 数据最后一天(S-638 的 2020-03 → 2026-10-19 同口径)。"""
    seg = curve[start_i:]
    fin = float(seg[-1])
    days = float((CAL[-1] - CAL[start_i]) / np.timedelta64(1, 'D'))
    ann = (fin ** (365.25 / max(days, 1)) - 1) if fin > 0 else float('nan')
    return {'final': fin, 'ann': float(ann), 'max_dd': max_dd(seg), 'years': days / 365.25,
            'nav_start': str(CAL[start_i])[:10], 'nav_days': int(days)}

def run(tk, f, cap, mtm):
    tkx = add_idx(tk)
    c, acc, sk, po, pr = nav(tkx, f, cap, mtm)
    si = int(min(tkx.entry_i.min(), len(CAL) - 1)) if len(tkx) else 0
    m = metrics(c, si)
    m.update(accepted=acc, skipped=sk, peak_open=po, peak_notional_ratio=pr, n_tickets=len(tkx))
    return m

def fstar(tk, cap, mtm, target=TARGET_DD, lo=0.0005, hi=0.30):
    """二分求使最大回撤 = target 的 f;封顶(回撤随 f 涨不到 target)则报封顶。"""
    tkx = add_idx(tk)
    si = int(min(tkx.entry_i.min(), len(CAL) - 1)) if len(tkx) else 0
    if max_dd(nav(tkx, hi, cap, mtm)[0][si:]) < target:
        return {'f_star': None, 'capped': True, 'at_max_f': hi, **run(tkx, hi, cap, mtm)}
    a, b = lo, hi
    for _ in range(40):
        mid = 0.5 * (a + b)
        if max_dd(nav(tkx, mid, cap, mtm)[0][si:]) < target:
            a = mid
        else:
            b = mid
        if b - a < 1e-6:
            break
    fs = 0.5 * (a + b)
    return {'f_star': fs, 'capped': False, **run(tkx, fs, cap, mtm)}

def fstar_grid(tk, cap, mtm, target=TARGET_DD, step=0.0025, hi=0.30):
    """S-638 定义:0.25% 步长下,盯市回撤仍 ≤ target 的最大 f。"""
    tkx = add_idx(tk)
    si = int(min(tkx.entry_i.min(), len(CAL) - 1)) if len(tkx) else 0
    best, f = None, step
    while f <= hi + 1e-12:
        if max_dd(nav(tkx, f, cap, mtm)[0][si:]) <= target:
            best = f
        f += step
    return best

def stop_stats(tk):
    """止损宽度占进场价的比例 —— 决定名义敞口 = f × 进场/(进场−止损) 能放大到多少。"""
    d = (tk.entry_px - tk.stop_px) / tk.entry_px
    return {'stop_pct_p05': float(d.quantile(0.05)), 'stop_pct_p50': float(d.quantile(0.50)),
            'notional_x_p50': float((1 / d).median()), 'notional_x_p95': float((1 / d).quantile(0.95)),
            'notional_x_max': float((1 / d).max())}

# ═══ 6. 跑网格 ═════════════════════════════════════════════════════════════
rows, fstar_cells = [], {}
for k in KS:
    tk = build_tickets(k)
    tkx = add_idx(tk)
    for cap in CAPS:
        cell = {'k': k, 'cap': cap or 'none', 'n': len(tk), 'sum_R': float(tk.R.sum()),
                'mean_R': float(tk.R.mean())}
        for mtm, tag in ((False, 'exit'), (True, 'mtm')):
            fs = fstar(tk, cap, mtm)
            cell[f'{tag}_fstar'] = fs.get('f_star')
            cell[f'{tag}_capped'] = fs.get('capped')
            cell[f'{tag}_ann'] = fs['ann']
            cell[f'{tag}_dd'] = fs['max_dd']
            cell[f'{tag}_final'] = fs['final']
            if mtm:
                cell['mtm_accepted'] = fs['accepted']; cell['mtm_skipped'] = fs['skipped']
                cell['peak_open'] = fs['peak_open']; cell['peak_notional_ratio'] = fs['peak_notional_ratio']
            if fs.get('f_star'):
                cell[f'{tag}_fstar_grid'] = fstar_grid(tk, cap, mtm)
        cell['fish'] = fish_stats(tkx)
        cell['stop'] = stop_stats(tk)
        cell['by_year_R'] = {int(y): [int(row['size']), float(row['sum'])]
                             for y, row in tk.groupby(tk.signal_d.dt.year).R.agg(['size', 'sum']).iterrows()}
        rows.append(cell)
        fstar_cells[(k, str(cap))] = cell
        print(f'k={k} cap={cap or "none"} n={len(tk)} '
              f'| exit f*={cell["exit_fstar"]} ann={cell["exit_ann"]:.1%} dd={cell["exit_dd"]:.1%} '
              f'| mtm f*={cell["mtm_fstar"]} ann={cell["mtm_ann"]:.1%} dd={cell["mtm_dd"]:.1%}', flush=True)

# ═══ 7. 交叉核对:S-627 闸门版(k=2.5 + majors 200 日闸门)信号日 ≤ 2026-06-20
#    10 张上限、f = 1%,盯市 —— 对 S-638 / §Seth-1020-1635 的 −32.3% / +24.4% / 304 张
disc = add_idx(build_tickets(2.5, gated=True))
disc = disc[disc.signal_d <= DISC_HI].reset_index(drop=True)
disc['tid'] = np.arange(len(disc))
xc = {}
for lbl, tks in (('discovery_729', disc), ('all_770', add_idx(build_tickets(2.5, gated=True)))):
    t2 = tks.copy(); t2['tid'] = np.arange(len(t2))
    r = run(t2, 0.01, 10, True)
    r['f_grid_0p25_fstar'] = fstar_grid(t2, 10, True)
    r['realized_only_dd_at_f1'] = max_dd(nav(t2, 0.01, 10, False)[0][int(t2.entry_i.min()):])
    r['f_scan'] = {f'{f_:.4f}': {kk: run(t2, f_, 10, True)[kk]
                                 for kk in ('max_dd', 'ann', 'final', 'peak_notional_ratio',
                                            'realized_only_dd') if kk != 'realized_only_dd'}
                   for f_ in (0.0075, 0.01, 0.0125, 0.015, 0.0175, 0.02)}
    r['f_scan_realized_dd'] = {f'{f_:.4f}': max_dd(nav(t2, f_, 10, False)[0][int(t2.entry_i.min()):])
                               for f_ in (0.01, 0.0125, 0.015, 0.02)}
    xc[lbl] = r
    print(f'XCROSS {lbl}: n_tickets={len(t2)} accepted={r["accepted"]} skipped={r["skipped"]} '
          f'mtm_dd={r["max_dd"]:.1%} ann={r["ann"]:.1%} final={r["final"]:.3f} '
          f'peak_notional={r["peak_notional_ratio"]:.2f}', flush=True)
# 留出段(信号日 > 2026-06-20)张数
hold = add_idx(build_tickets(2.5, gated=True))
XC = {'discovery': xc['discovery_729'], 'all': xc['all_770'],
      'holdout_n': int((hold.signal_d > DISC_HI).sum()), 'total_n': int(len(hold))}
print(f'XCROSS holdout n={XC["holdout_n"]} total n={XC["total_n"]}', flush=True)

# ═══ 8. 落盘 ═══════════════════════════════════════════════════════════════
OUT = {'snapshot': PROV, 's610_repro': {'n': chk_n, 'mean_R': chk_r, 'gate': 'PASS' if BASE_OK else 'FAIL'},
       'grid': rows, 'crosscheck': XC}
json.dump(OUT, open(os.path.join(SCRATCH, 't141_results.json'), 'w'), indent=2, default=str)
for k, cap in ((2.5, None), (2.5, 10)):
    t = add_idx(build_tickets(k)) if cap is None else add_idx(build_tickets(k, gated=True))
    t.to_csv(os.path.join(SCRATCH, f'tickets_k{k}_cap{cap}.csv'), index=False)
print('WROTE', os.path.join(SCRATCH, 't141_results.json'), flush=True)

# ═══ 9. 报告 ═══════════════════════════════════════════════════════════════
def pct(x):
    return '—' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x:+.1%}'
def fx(x):
    return '—' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x:.2%}'

L = []
A = L.append
A('# T-141 / S-621 — R 臂宽止损:同最大回撤(−35%)下比年化 + 热度上限 10 张')
A('')
A(f'**快照** `{PROV["snapshot_path"]}` · sha256 `{PROV["sha256"]}` · **{PROV["rows"]:,} 行 / {PROV["symbols"]} 名** · '
  f'区间 {PROV["date_min"]} → {PROV["date_max"]} · 取用时间(UTC) **{PROV["pulled_utc"]}**')
A(f'来源:{PROV["provenance"]}。之后全部计算只用这份快照,不回查库。')
A(f'闸门序列 `style_index_pit_daily`(style=majors, weighting=cap)现取现缓存 → `{gate_path}`。')
A('')
A('## 0. 实施检验 ①(不过就停):复现 S-610 基线')
A('')
A(f'- n = **{chk_n}**(S-610 原文 1,013,Δ {chk_n-1013:+d})· 均值 R = **{chk_r:+.4f}**(原文 +0.350,Δ {chk_r-0.350:+.4f})· '
  f'→ **{"PASS" if BASE_OK else "FAIL"}**')
A('')
A('## 1. 主表:4 个 k × {无上限, 10 张上限},f★ 使最大回撤 = −35%')
A('')
A('「按出场日复利」= 净值只在出场日变(S-621 预注册的原始口径);「逐日盯市」= 逐日收盘盯市'
  '(§Seth-1020c / S-638 追加的口径,不替换预注册口径)。两种口径的每票风险基数各用各自曲线的权益。')
A('')
A('| k | 上限 | 票数 | ΣR | 出场日 f★ | 出场日年化 | 出场日回撤 | 盯市 f★ | 盯市年化 | 盯市回撤 | 盯市 f★(0.25%网格) | 峰值同时持仓 | 被上限挡掉 |')
A('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for r in rows:
    capn = '无' if r['cap'] == 'none' else str(r['cap'])
    A(f"| {r['k']} | {capn} | {r['n']} | {r['sum_R']:+.1f} | {fx(r['exit_fstar'])}{' (封顶)' if r['exit_capped'] else ''} | "
      f"{pct(r['exit_ann'])} | {pct(-r['exit_dd'])} | {fx(r['mtm_fstar'])}{' (封顶)' if r['mtm_capped'] else ''} | "
      f"{pct(r['mtm_ann'])} | {pct(-r['mtm_dd'])} | {fx(r.get('mtm_fstar_grid'))} | "
      f"{r.get('peak_open', '—')} | {r.get('mtm_skipped', '—')} |")
A('')
A('> 「封顶」= 回撤随 f 增大也涨不到 −35%(热度上限把可投放的风险锁住了),该行报的是 f=30% 处的数。')
A('')
A('## 2. S-621 三条判(左列用预注册口径,右列用盯市口径)')
A('')
def g(k, cap):
    for r in rows:
        if r['k'] == k and r['cap'] == cap:
            return r
    return None
b_e, b_m = g(1.0, 'none'), g(1.0, 'none')
A('| 判 | 按出场日复利 | 逐日盯市 | 过? |')
A('|---|---|---|---|')
for k in (2.0, 2.5, 3.0):
    c_e, c_m = g(k, 'none'), g(k, 'none')
    pe = '✅' if (c_e['exit_ann'] is not None and b_e['exit_ann'] is not None
                 and c_e['exit_ann'] > b_e['exit_ann']) else '❌'
    pm = '✅' if (c_m['mtm_ann'] is not None and b_m['mtm_ann'] is not None
                 and c_m['mtm_ann'] > b_m['mtm_ann']) else '❌'
    lab = '① 主判' if k == 2.5 else '② 平滑'
    A(f"| {lab} k={k} 年化 > k=1 | {pct(c_e['exit_ann'])} vs {pct(b_e['exit_ann'])} → {pe} | "
      f"{pct(c_m['mtm_ann'])} vs {pct(b_m['mtm_ann'])} → {pm} | {'✅' if pe == '✅' and pm == '✅' else '❌'} |")
c_h, c_n = g(2.5, '10'), g(2.5, 'none')
if c_h and c_n and c_h['mtm_ann'] and c_n['mtm_ann']:
    rm = c_h['mtm_ann'] / c_n['mtm_ann']
    re = (c_h['exit_ann'] / c_n['exit_ann']) if (c_h['exit_ann'] and c_n['exit_ann']) else float('nan')
    A(f"| ③ H 版(k=2.5 + 上限 10)年化 ≥ 无上限版的 80% | {pct(c_h['exit_ann'])} / {pct(c_n['exit_ann'])} = "
      f"{re:.0%} → {'✅' if re >= 0.8 else '❌'} | {pct(c_h['mtm_ann'])} / {pct(c_n['mtm_ann'])} = {rm:.0%} → "
      f"{'✅' if rm >= 0.8 else '❌'} | {'✅' if rm >= 0.8 else '❌'} |")
A('')
A('## 3. 交叉核对 —— S-627 闸门版(k=2.5 + majors 200 日闸门)、10 张上限、f = 1%')
A('')
d_, a_ = XC['discovery'], XC['all']
A('| 口径 | 票数 | 接了 | 被上限挡掉 | 盯市最大回撤 | 只算已实现的回撤 | 年化 | 期末净值 | 峰值同时持仓 | 峰值总名义/权益 |')
A('|---|---|---|---|---|---|---|---|---|---|')
A(f"| 发现段(信号日 ≤ 2026-06-20) | {d_['n_tickets']} | {d_['accepted']} | {d_['skipped']} | **{pct(-d_['max_dd'])}** | "
  f"{pct(-d_['realized_only_dd_at_f1'])} | **{pct(d_['ann'])}** | {d_['final']:.3f} | {d_['peak_open']} | {d_['peak_notional_ratio']:.2f} |")
A(f"| 全量(含留出段) | {XC['total_n']} | {a_['accepted']} | {a_['skipped']} | **{pct(-a_['max_dd'])}** | "
  f"{pct(-a_['realized_only_dd_at_f1'])} | **{pct(a_['ann'])}** | {a_['final']:.3f} | {a_['peak_open']} | {a_['peak_notional_ratio']:.2f} |")
A('')
A(f'留出段(信号日 > 2026-06-20)= **{XC["holdout_n"]}** 张。发现段 0.25% 网格 f★ = {fx(d_.get("f_grid_0p25_fstar"))}。')
A('')
A('**Seth 的内核(S-638 / §Seth-1020-1635,2026-10-20 16:29 UTC)给的是:盯市回撤 −32.3%、年化 +24.4%,'
  f'消息里写「接 304 张」。** 本报告同口径测到:盯市回撤 **{pct(-d_["max_dd"])}**、年化 **{pct(d_["ann"])}**、'
  f'接了 **{d_["accepted"]}** 张(发现段共 {XC["discovery"]["n_tickets"]} 张,被 10 张上限挡掉 {d_["skipped"]} 张)。')
A('')
A(f'**差多少**:回撤 {(d_["max_dd"] - 0.323) * 100:+.1f}pp · 年化 {(d_["ann"] - 0.244) * 100:+.1f}pp · '
  f'接票 {d_["accepted"]} vs 304(Δ {d_["accepted"] - 304:+d}) · 峰值总名义/权益 {d_["peak_notional_ratio"]:.2f} vs 0.99。')
A('')
A('## 4. 只报项(每个 k:找鱼数 / 被甩下比例 / 捕获比 / 票价 / 分年)')
A('')
A('| k | 上限 | 鱼总数 | 捕到的鱼 | 捕获率 | 平均捕获比 | 平均票价 ln(出/进) | 进场时已走完 | 分年捕到 |')
A('|---|---|---|---|---|---|---|---|---|')
for r in rows:
    fi = r.get('fish') or {}
    if not fi:
        A(f"| {r['k']} | {r['cap']} | — | — | — | — | — | — | — |")
        continue
    A(f"| {r['k']} | {r['cap']} | {fi['fish_total']} | {fi['fish_caught']} | {fi['catch_rate']:.1%} | "
      f"{fi['mean_capture']:.1%} | {fi['mean_ticket_ln']:+.3f} | {fi['mean_late_frac']:.1%} | {fi['by_year']} |")
A('')
A('**分年 ΣR / 票数**(按信号年):')
A('')
ky = sorted({y for r in rows for y in (r.get('by_year_R') or {})})
A('| k | 上限 | ' + ' | '.join(str(y) for y in ky) + ' |')
A('|---|---|' + '---|' * len(ky))
for r in rows:
    by = r.get('by_year_R') or {}
    A(f"| {r['k']} | {r['cap']} | " + ' | '.join((f"{by[y][1]:+.0f}R/{by[y][0]}" if y in by else '—') for y in ky) + ' |')
A('')
A('## 5. 结论草稿')
A('')
j1_e = g(2.5, 'none')['exit_ann'] > b_e['exit_ann']
j1_m = g(2.5, 'none')['mtm_ann'] > b_m['mtm_ann']
j2_e = all(g(k, 'none')['exit_ann'] > b_e['exit_ann'] for k in (2.0, 3.0))
j2_m = all(g(k, 'none')['mtm_ann'] > b_m['mtm_ann'] for k in (2.0, 3.0))
A(f'① k=2.5 > k=1:预注册口径 **{"过" if j1_e else "不过"}** / 盯市口径 **{"过" if j1_m else "不过"}**;'
  f'② k=2.0 与 3.0 也 > k=1(参数平滑):预注册口径 **{"过" if j2_e else "不过"}** / 盯市口径 **{"过" if j2_m else "不过"}**;')
if c_h and c_n and c_h['mtm_ann'] and c_n['mtm_ann']:
    A(f'③ 热度上限 10 张年化 ≥ 无上限版 80%:盯市 **{c_h["mtm_ann"] / c_n["mtm_ann"]:.0%}** → '
      f'**{"过" if c_h["mtm_ann"] / c_n["mtm_ann"] >= 0.8 else "不过"}**。')
A('')
A('**试验计数:凸性验证族第 4 次,1 条(联合)。**')
A('')
os.makedirs(os.path.join(DATA_ROOT, '_reports/absorb_input'), exist_ok=True)
open(REPORT, 'w').write('\n'.join(L) + '\n')
print('WROTE', REPORT, flush=True)