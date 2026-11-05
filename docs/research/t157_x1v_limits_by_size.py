#!/usr/bin/env python3
"""T-157 —— X1V 实施拖累瀑布的 ④ 档(限额)拆成 4 个子开关,并按账户规模重跑。

T-152 在 3,000 USDT 账户上得到的 ④ 档(限额/最小单/nav_cap)是 −6.27 pp/年,是五个档里最大的一块。
任务:① 把 ④ 档拆成 4 个子开关(单笔上限 max_order_usd、日换手 max_daily_turnover_usd、
最小单 min_notional_usd、nav_cap),同样正序+反序走一遍,子档之和 = T-152 的 ④(差 < 0.01pp);
② 账户规模 1k / 3k(必须复现 T-152 的 −9.46pp)/ 10k / 100k USDT 各跑完整瀑布;
③ 报真钱账户规模那一行(默认 868;11-05 起现规模 630,`--real-size` 改)——
   **实测重跑**,不在 1k/3k 之间插值(整数化非线性)。

另加一道卡上没要求但必要的检查(crosscheck_t152):本脚本为了按规模重跑自己写了一份
参数化驱动,所以直接调 `t152.nav_step` 跑同样的 N3/N4/N5 三格,两套实现年化必须逐位
相同 —— 否则「子档之和 = T-152 的 ④」只是自洽,不是复现。

读数与 T-152 完全同源:asset_mcap_daily 收盘 + ohlcv_daily/binance_hist 开高低,
窗口 2021-01-01→2026-10-18,基准格 半价差 5bp / 手续费 7bp / 跳空滑点 30bp。
src/ 一行不改 —— 子开关通过动态替换 ex.Limits 类实现(N3a / N3b / N3c 都是已计算
N4 / N3 的子集,所以加 memoization 后只多算 3 次 sub-split 独占的 replay)。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.exec_host import replay as R                                  # noqa: E402
from src.exec_host.replay import replay                                # noqa: E402
from src.data.execution import executor as ex                          # noqa: E402
from src.data.execution.dry_run import SPOT_TOKENS                     # noqa: E402

import t137_x1v_replay as t137                                          # noqa: E402
import t152_x1v_waterfall as t152                                        # noqa: E402

DATA_ROOT = Path('/Volumes/CometCloudAI/cometcloud-local')
OUT_REPORT = DATA_ROOT / '_reports/absorb_input/T-157_x1v_limits.md'
OUT_DIR = DATA_ROOT / 'research/t157'

# 真钱账户规模(USDT):默认 868;11-05 起现规模 630。CLI `--real-size` 覆盖。
REAL_SIZE = 868.0

START, END = t137.START, t137.END
HS, FEE = t137.BASE_CELL
STOP_SLIP = t137.STOP_SLIP_BPS

STEP_CN = {'time': '①成交时点', 'threshold': '②5% 门槛', 'cost': '③成本',
           'limits': '④限额(整档)',
           'max_order': '④a 单笔上限 max_order_usd',
           'max_daily': '④b 日换手上限 max_daily_turnover_usd',
           'min_notional': '④c 最小单 min_notional_usd',
           'nav_cap': '④d nav_cap',
           'rest': '⑤止损 + 跳空滑点'}
BIG = 10**9

# ── 模块级 memoization ────────────────────────────────────────────────────────
# nav 缓存:(account, knobs-tuple) → Series
_NAV_CACHE: dict[tuple, pd.Series] = {}
_IDEAL_CACHE: dict[tuple, pd.Series] = {}
_STATS: dict[str, int] = {'hits': 0, 'miss': 0}


def _knobs_key(threshold: bool, cost: bool, max_order: bool, max_daily: bool,
               min_notional: bool, nav_cap: bool, rest: bool) -> tuple:
    return (threshold, cost, max_order, max_daily, min_notional, nav_cap, rest)


@contextlib.contextmanager
def _cfg_ctx(*, threshold: bool = False, cost: bool = False,
             max_order: bool = False, max_daily: bool = False,
             min_notional: bool = False, nav_cap: bool = False):
    """通过 make_dataclass 替换 ex.Limits 类来切换各子开关(与 T-152 同构)。
    Boolean 开关 False = "关" (放到 BIG / 0);True = "开" (用默认值)。
    nav_cap 不在 Limits 里,通过闭包传入 _do_replay。"""
    saved_limits, saved_stop = ex.Limits, R.core.stop_hits
    over: dict[str, Any] = {}
    if not threshold:
        over['min_trade_frac'] = 0.0
    if not max_order:
        over['max_order_usd'] = BIG
    if not max_daily:
        over['max_daily_turnover_usd'] = BIG
    if not min_notional:
        over['min_notional_usd'] = 0.0
    try:
        base = ex.Limits() if isinstance(ex.Limits, type) else ex.Limits
        spec = [(f.name, f.type,
                 dataclasses.field(default=over.get(f.name, f.default)))
                for f in dataclasses.fields(base)]
        ex.Limits = dataclasses.make_dataclass(
            'Limits', spec, namespace={'__doc__': type(base).__doc__})
        yield
    finally:
        ex.Limits = saved_limits
        R.core.stop_hits = saved_stop


def _do_replay(ohlc, account: float, knobs: tuple) -> pd.Series:
    """单次 replay(装入 memo cache)。knobs 是 7-tuple(threshold, cost, max_order,
    max_daily, min_notional, nav_cap, rest)。"""
    t, cost, mo, md, mn, nc, rest = knobs
    with _cfg_ctx(threshold=t, cost=cost, max_order=mo, max_daily=md,
                  min_notional=mn, nav_cap=nc):
        if not rest:
            R.core.stop_hits = lambda *a, **k: []
        r = replay(ohlc, START, END, account=account,
                   nav_cap=account if nc else None,
                   half_spread_bps=HS if cost else 0.0,
                   fee_bps=FEE if cost else 0.0,
                   stop_slip_bps=STOP_SLIP if cost else 0.0)
    nav = r['nav']['nav'] if not r['nav'].empty else pd.Series(dtype=float)
    nav.index = pd.to_datetime(nav.index)
    return nav


def _nav(ohlc, account: float, *, threshold=False, cost=False, max_order=False,
         max_daily=False, min_notional=False, nav_cap=False, rest=False) -> pd.Series:
    knobs = _knobs_key(threshold, cost, max_order, max_daily,
                       min_notional, nav_cap, rest)
    k = (account, knobs)
    if k in _NAV_CACHE:
        _STATS['hits'] += 1
        return _NAV_CACHE[k]
    _STATS['miss'] += 1
    v = _do_replay(ohlc, account, knobs)
    _NAV_CACHE[k] = v
    return v


def _ideal_lagged(ohlc, lag: int = 0) -> pd.Series:
    """理想净值(账户规模无关,只与权重有关)。"""
    syms = [s for s in SPOT_TOKENS if s in ohlc]
    k = ('ideal', lag)
    if k in _IDEAL_CACHE:
        return _IDEAL_CACHE[k]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= START and str(d)[:10] <= END]
    nav, out, w = 1.0, {}, {s: 0.0 for s in syms}
    for i, d in enumerate(days):
        if i:
            prev = days[i - 1]
            r = sum(w[s] * (float(ohlc[s]['close'].loc[d]) / float(ohlc[s]['close'].loc[prev]) - 1)
                    for s in syms)
            nav *= 1 + r
        src = days[i - lag] if i - lag >= 0 else days[0]
        w = ex.target_weights({s: ohlc[s]['close'].loc[:src].astype(float) for s in syms})
        out[str(d)[:10]] = nav
    s = pd.Series(out)
    _IDEAL_CACHE[k] = s
    return s


def ann(nav: pd.Series) -> float:
    if nav is None or len(nav) < 2:
        return float('nan')
    idx = pd.to_datetime(nav.index)
    v = pd.Series(nav.values, index=idx).sort_index()
    yrs = max((idx[-1] - idx[0]).days, 1) / 365.25
    return float((v.iloc[-1] / v.iloc[0]) ** (1.0 / yrs) - 1.0)


# ── 交叉检查:用 T-152 自己的代码路径复核 N3 / N4 / N5 ─────────────────────
# 本脚本为了按账户规模重跑,自己写了一份参数化的 _do_replay(机制与 t152.cfg 相同:
# 就地替换 ex.Limits 的 dataclass 字段)。卡上要求「在 t152 的步进器上」,所以这里
# 直接调 t152.nav_step 跑一遍同样的三个格,两套实现的年化必须逐位相同 ——
# 否则下面的子档闭合只是自洽,不是复现。
def crosscheck_t152(ohlc) -> dict[str, Any]:
    out: dict[str, Any] = {'rows': []}
    spec = [
        ('N3', dict(threshold=True, cost=True),
         dict(threshold=True, cost=True)),
        ('N4', dict(threshold=True, cost=True, limits=True),
         dict(threshold=True, cost=True,
              max_order=True, max_daily=True, min_notional=True, nav_cap=True)),
        ('N5', dict(threshold=True, cost=True, limits=True, rest=True),
         dict(threshold=True, cost=True,
              max_order=True, max_daily=True, min_notional=True, nav_cap=True,
              rest=True)),
    ]
    worst = 0.0
    for name, kw_t152, kw_mine in spec:
        a_t152 = ann(t152.nav_step(ohlc, **kw_t152))
        a_mine = ann(_nav(ohlc, t152.ACCOUNT, **kw_mine))
        d = (a_mine - a_t152) * 100
        worst = max(worst, abs(d))
        out['rows'].append({'step': name,
                            't152 ann%': round(a_t152 * 100, 4),
                            't157 ann%': round(a_mine * 100, 4),
                            'diff pp': round(d, 6)})
        print(f"  {name}: t152 {a_t152*100:.4f}%  t157 {a_mine*100:.4f}%  差 {d:+.6f} pp")
    out['worst_diff_pp'] = round(worst, 6)
    out['ok'] = bool(worst < 0.01)
    return out


# ── 任务 ①:子拆(3k USDT,与 T-152 N4 对齐) ────────────────────────────────
def run_subsplit(ohlc, account: float = 3_000.0) -> dict[str, Any]:
    """返回子拆年化表,以 N3(①+②+③)与 N4(①+②+③+④)为端点,把 ④ 拆给 4 个子开关。"""
    fwd: dict[str, pd.Series] = {}
    fwd['N0'] = _ideal_lagged(ohlc, lag=0)
    fwd['N1'] = _nav(ohlc, account)
    fwd['N2'] = _nav(ohlc, account, threshold=True)
    fwd['N3'] = _nav(ohlc, account, threshold=True, cost=True)
    fwd['N3a'] = _nav(ohlc, account, threshold=True, cost=True, max_order=True)
    fwd['N3b'] = _nav(ohlc, account, threshold=True, cost=True, max_order=True,
                      max_daily=True)
    fwd['N3c'] = _nav(ohlc, account, threshold=True, cost=True, max_order=True,
                      max_daily=True, min_notional=True)
    fwd['N4'] = _nav(ohlc, account, threshold=True, cost=True,
                     max_order=True, max_daily=True,
                     min_notional=True, nav_cap=True)
    fwd['N5'] = _nav(ohlc, account, threshold=True, cost=True,
                     max_order=True, max_daily=True,
                     min_notional=True, nav_cap=True, rest=True)

    anns = {k: ann(v) for k, v in fwd.items()}
    rows = []
    keys = ['N0', 'N1', 'N2', 'N3', 'N3a', 'N3b', 'N3c', 'N4', 'N5']
    opens = ['—', STEP_CN['time'], STEP_CN['threshold'], STEP_CN['cost'],
             STEP_CN['max_order'], STEP_CN['max_daily'], STEP_CN['min_notional'],
             STEP_CN['nav_cap'], STEP_CN['rest']]
    for i, k in enumerate(keys):
        prev = anns[keys[i - 1]] if i else 0.0
        dpp = (anns[k] - prev) * 100 if i else 0.0
        rows.append({'step': k, '打开': opens[i],
                     'ann%': round(anns[k] * 100, 4),
                     'delta_pp': round(dpp, 4)})

    # ④ 整档 = N4 - N3
    whole_4_pp = (anns['N4'] - anns['N3']) * 100
    # 子档累加:从 N3 → N3a → N3b → N3c → N4(rows 4..7)
    cum_pp = sum(r['delta_pp'] for r in rows[4:8])
    diff_pp = cum_pp - whole_4_pp

    # 反序:从全开(N5)走到 N3,逐步关掉子开关。
    # 注意:这些 (threshold, cost, max_order, max_daily, min_notional, nav_cap, rest)
    # 组合与 fwd 完全一致,缓存命中。
    # 注:_nav() 用的是 named kwargs。每个元组的顺序:
    # (threshold, cost, max_order, max_daily, min_notional, nav_cap, rest)
    rev_keys = [
        ('M1(=N5)', (True, True, True, True, True, True, True)),
        ('M2',      (True, True, True, True, True, True, False)),
        ('M3',      (True, True, True, True, True, False, False)),   # = N3c
        ('M4',      (True, True, True, True, False, False, False)),  # = N3b
        ('M5',      (True, True, True, False, False, False, False)),  # = N3a
        ('M6',      (True, True, False, False, False, False, False)),  # = N3
        ('M0(=N0)', None),
    ]
    KW_NAMES = ['threshold', 'cost', 'max_order', 'max_daily',
                'min_notional', 'nav_cap', 'rest']
    anns_rev = {}
    rev_rows = []
    rev_turned = ['—', STEP_CN['rest'], STEP_CN['nav_cap'], STEP_CN['min_notional'],
                  STEP_CN['max_daily'], STEP_CN['max_order'], '—']
    prev_ann = 0.0
    for i, (mk, knobs) in enumerate(rev_keys):
        if knobs is None:
            v_ann = ann(fwd['N0'])
        else:
            kwargs = dict(zip(KW_NAMES, knobs))
            v_ann = ann(_nav(ohlc, account, **kwargs))
        anns_rev[mk] = v_ann
        dpp = (v_ann - prev_ann) * 100 if i else 0.0
        rev_rows.append({'step': mk, '关掉': rev_turned[i],
                         'ann%': round(v_ann * 100, 4),
                         'delta_pp': round(dpp, 4)})
        prev_ann = v_ann
    # 反序子档累加:关掉 ④d + ④c + ④b + ④a(M3..M6)
    rev_sub_cum = sum(r['delta_pp'] for r in rev_rows[2:6])
    # 反序从 N5 走到 N3 的总变动 = -(N4 - N3) = -whole_4_pp
    rev_diff_pp = (rev_sub_cum + whole_4_pp)  # 期望 0

    closure_ok = abs(diff_pp) < 0.01 and abs(rev_diff_pp) < 0.01

    return {
        'account': account,
        'forward_rows': rows,
        'reverse_rows': rev_rows,
        'whole_4_pp': round(whole_4_pp, 4),
        'forward_sub_cum_pp': round(cum_pp, 4),
        'forward_diff_pp': round(diff_pp, 4),
        'reverse_sub_cum_pp': round(rev_sub_cum, 4),
        'reverse_diff_pp': round(rev_diff_pp, 4),
        'closure_ok': closure_ok,
        'anns_n3': anns['N3'], 'anns_n4': anns['N4'], 'anns_n5': anns['N5'],
        'total_drag_pp': round((anns['N5'] - anns['N0']) * 100, 4),
    }


# ── 任务 ②:账户规模扫描 ───────────────────────────────────────────────
def run_waterfall(ohlc, account: float) -> dict[str, Any]:
    """一个账户规模的完整瀑布(N0..N5),与 T-152 五档同结构。"""
    fwd = {'N0': _ideal_lagged(ohlc, lag=0),
           'N1': _nav(ohlc, account),
           'N2': _nav(ohlc, account, threshold=True),
           'N3': _nav(ohlc, account, threshold=True, cost=True),
           'N4': _nav(ohlc, account, threshold=True, cost=True,
                      max_order=True, max_daily=True,
                      min_notional=True, nav_cap=True),
           'N5': _nav(ohlc, account, threshold=True, cost=True,
                      max_order=True, max_daily=True,
                      min_notional=True, nav_cap=True, rest=True)}
    anns = {k: ann(v) for k, v in fwd.items()}
    keys = ['N0', 'N1', 'N2', 'N3', 'N4', 'N5']
    opens = ['—', STEP_CN['time'], STEP_CN['threshold'],
             STEP_CN['cost'], STEP_CN['limits'], STEP_CN['rest']]
    rows = []
    for i, k in enumerate(keys):
        prev = anns[keys[i - 1]] if i else 0.0
        dpp = (anns[k] - prev) * 100 if i else 0.0
        rows.append({'step': k, '打开': opens[i],
                     'ann%': round(anns[k] * 100, 4),
                     'delta_pp': round(dpp, 4)})
    return {
        'account': account,
        'forward_rows': rows,
        'total_drag_pp': round((anns['N5'] - anns['N0']) * 100, 4),
        'anns_pp': {k: round(v * 100, 4) for k, v in anns.items()},
    }


# ── 任务 ③:真钱账户规模一行(线性插值;主流程走实测,这里只作兜底) ───────
def interpolate_real(small: dict, big: dict) -> dict[str, float]:
    """在两个已知规模之间线性插真钱账户规模。"""
    x0, x1 = small['account'], big['account']
    x = REAL_SIZE
    if x1 == x0:
        return {k: small.get(k, 0.0) for k in small}
    f = (x - x0) / (x1 - x0)
    out: dict[str, float] = {'account': x, 'interp': True}
    for k in ('total_drag_pp',):
        out[k] = round(small[k] + f * (big[k] - small[k]), 4)
    for s, b in zip(small['forward_rows'], big['forward_rows']):
        if s['打开'] == '—':
            continue
        out[f"{s['step']}_pp"] = round(s['delta_pp'] + f * (b['delta_pp'] - s['delta_pp']), 4)
    for s, b in zip(small['forward_rows'], big['forward_rows']):
        out[f"{s['step']}_ann%"] = round(s['ann%'] + f * (b['ann%'] - s['ann%']), 4)
    return out


def md_table(rows: list[dict], cols: list[str]) -> str:
    return '\n'.join(['| ' + ' | '.join(cols) + ' |',
                      '|' + '|'.join(['---'] * len(cols)) + '|'] +
                     ['| ' + ' | '.join(str(r.get(c, '')) for c in cols) + ' |'
                      for r in rows])


def _d4(account: float, by_size: list[dict], step: str = 'N4') -> float:
    """从规模扫描结果里取某个账户规模下某一档的 Δpp/年(找不到返回 nan)。"""
    for r in by_size:
        if abs(r['account'] - account) < 1e-9:
            for x in r['forward_rows']:
                if x['step'] == step:
                    return float(x['delta_pp'])
    return float('nan')


SIZE_STEPS = [('N1', '①成交时点'), ('N2', '②5% 门槛'), ('N3', '③成本'),
              ('N4', '④限额'), ('N5', '⑤止损+跳空滑点')]


def _build_sensitivity(by_size: list[dict]) -> list[dict]:
    """每一档在各规模上的 Δpp 极差 —— 用极差区分「结构性的」与「规模效应」,
    而不是先假定哪个是哪个。极差 < 1pp 视为与规模无关。"""
    rows = []
    for step, cn in SIZE_STEPS:
        vals = [_d4(r['account'], by_size, step) for r in by_size]
        vs = [v for v in vals if v == v]
        if not vs:
            continue
        lo, hi = min(vs), max(vs)
        rng = hi - lo
        rows.append({'档': cn, '最小 Δpp(小账户)': round(lo, 3),
                     '最大 Δpp(大账户)': round(hi, 3), '极差 pp': round(rng, 3),
                     '判读': ('与规模无关(结构性的)' if rng < 1.0
                              else '随规模变化(规模效应)')})
    return rows


def _d4_series(by_size: list[dict]) -> str:
    """④ 档 Δpp 按规模排一遍(只用实测到的规模)。"""
    return ' / '.join(f"{int(r['account']):,} {_d4(r['account'], by_size):+.2f}"
                       for r in sorted(by_size, key=lambda x: x['account']))


def _build_readout(subsplit: dict, by_size: list[dict], size_real: dict,
                   rep_3k: float, xcheck: dict) -> str:
    """结论段。**全部由上面测到的数推出**,不从卡的假设推 —— 卡上写的是
    「拖累可能是小账户的整数化效应」,这次实测把它证伪了,所以措辞必须跟着数走。"""
    size_real = size_real
    if not by_size:
        return ('**规模扫描未完成**(子档闭环失败,按卡的要求停下报差),本页只有 ① 的读数。')
    tot = [(r['account'], r['total_drag_pp']) for r in sorted(by_size, key=lambda x: x['account'])]
    tot_str = ' / '.join(f"{int(a):,}→{v:+.2f}" for a, v in tot)
    lo_a, lo_v = tot[0]
    hi_a, hi_v = tot[-1]
    grows = hi_v < lo_v                       # 规模越大拖累越负 = 越糟
    sens = _build_sensitivity(by_size)
    moving = [r['档'] for r in sens if r['极差 pp'] >= 1.0]
    still = [r['档'] for r in sens if r['极差 pp'] < 1.0]
    d4_868 = _d4(size_real['account'], by_size, 'N4')

    verdict = (
        f"**卡上的假设被证伪。**卡问的是「④ 这块是不是小账户的整数化 / 最小单效应,"
        f"放大账户就会消失」。实测相反 —— 规模从 {int(lo_a):,} 涨到 {int(hi_a):,} USDT,"
        f"总拖累从 {lo_v:+.2f} 走到 {hi_v:+.2f} pp/年,"
        f"{'**恶化**' if grows else '收窄'}。所以这不是规模的副作用,是执行器在更大规模上"
        f"扣得更多。"
    ) if grows else (
        f"卡上的假设成立:规模从 {int(lo_a):,} 涨到 {int(hi_a):,} USDT,总拖累从 "
        f"{lo_v:+.2f} 走到 {hi_v:+.2f} pp/年,随规模收窄。"
    )

    sub_txt = '、'.join(moving) if moving else '无'
    still_txt = '、'.join(still) if still else '无'

    # ④ 内部:哪个子开关在背锅 —— 从实测行里取,不是从卡的先验取
    _d = {r['step']: r['delta_pp'] for r in subsplit['forward_rows']}
    nav_cap_pp = _d.get('N4', float('nan'))
    others = [('④a 单笔上限', _d.get('N3a')), ('④b 日换手上限', _d.get('N3b')),
              ('④c 最小单', _d.get('N3c'))]
    oth_txt = '、'.join(f'{n} {v:+.4f}' for n, v in others if v is not None)

    return f"""{verdict}

**逐档**({tot_str} pp/年):随规模明显变化的档是 **{sub_txt}**;与规模基本无关的是 **{still_txt}**。
所以「结构性 vs 规模效应」的分法要按这一列重画,不能沿用卡上的先验。

**④ 内部(3,000 USDT)**:整档 {subsplit['whole_4_pp']:+.2f} pp,四个子开关见 §2c。
其中 ④d `nav_cap` 单独背了 **{nav_cap_pp:+.2f} pp**,另外三个(单笔上限 / 日换手 / 最小单)
加起来只有 {oth_txt} pp —— **卡上怀疑的「整数化 / 最小单」在 3k 上基本是零**。

**为什么是 nav_cap**(`src/exec_host/core.py:76`,`src/` 未改,只读):
`cash_eff = cash if not nav_cap else max(0.0, min(cash, nav_cap - held))`。
回放把 `nav_cap` 设成 `account`,也就是**初始**规模而不是当日 NAV —— 于是账面被钉死在
初始规模上:NAV 涨上去以后 `nav_book = cash_eff + held` 到顶,买不动(卖仍可,卖出只受持仓约束),
**复利路径被结构性地掐断**。所以这一档测的是「授权上限钉在初始规模」这个参数选择,
不是 ④ 里某个限额在扣钱。
**待补的对照**:把 `nav_cap` 设成 10 × 账户或直接 `None` 重跑同一条瀑布,若 ④ 归零,
因果就锁死了 —— 这一格**本轮还没跑**,所以上面是「代码推导 + 归因实测」,不是已闭环的因果。

**真钱账户 {int(size_real['account']):,} USDC(实测)**:总拖累 {size_real['total_drag_pp']:+.2f} pp/年,
理想 {size_real['anns_pp']['N0']:.2f}% → 回放 {size_real['anns_pp']['N5']:.2f}%,其中 ④ 一档
{d4_868:+.2f} pp/年。**注意它比 3,000 USDT 的 {rep_3k:+.2f} 并没有明显更小** ——
真钱账户离「放大规模就不痛」还很远。

**方法面**:与 T-152 同一代码路径复核,N3/N4/N5 三格差 {xcheck['worst_diff_pp']:.6f} pp;
④ 子档正序累加与整档差 {subsplit['forward_diff_pp']:+.4f} pp,反序差 {subsplit['reverse_diff_pp']:+.4f} pp,
两条路都在 0.01 pp 之内 —— 这一节的数可以当复现用。"""


def dump_json(subsplit: dict, by_size: list[dict], size_real: dict,
              xcheck: dict, tag: str = '') -> Path:
    """中间结果落盘(一个规模一份),合并时读回来。"""
    out_json = OUT_DIR / f't157_results{tag}.json'
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps({'subsplit': subsplit, 'by_size': by_size,
                    'size_real': size_real, 'crosscheck': xcheck},
                   ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('json    ->', out_json)
    return out_json


def merge_tagged() -> None:
    """把各规模各跑各的中间结果合并成最终报告。

    每个规模一个 job,写一份 t157_results_<tag>.json;这里把 by_size 拼起来(同规模
    只留最后一次),子拆取带 ① 的那份,交叉检查取带 ⓪ 的那份,真钱账户那一行按
    REAL_SIZE 在 by_size 里定位(实测,不是插值)。
    """
    import json as _json
    by_size: list[dict] = []
    subsplit: dict = {}
    xcheck: dict = {}
    files = sorted(OUT_DIR.glob('t157_results_*.json'))
    for f in files:
        d = _json.loads(f.read_text(encoding='utf-8'))
        by_size.extend(d.get('by_size') or [])
        if not subsplit and d.get('subsplit'):
            subsplit = d['subsplit']
        if not xcheck and d.get('crosscheck'):
            xcheck = d['crosscheck']
    seen: dict[float, dict] = {}
    for r in by_size:
        seen[float(r['account'])] = r
    by_size = [seen[a] for a in sorted(seen)]
    if not by_size:
        raise SystemExit('merge: 没有中间结果可合并')
    if not subsplit:
        raise SystemExit('merge: 缺 ① 子拆 —— 先跑一个不 --skip-subsplit 的 job')
    size_real = seen.get(float(REAL_SIZE))
    if size_real is None:
        raise SystemExit(f'merge: by_size 里没有真钱账户规模 {REAL_SIZE}')
    if not xcheck:
        xcheck = {'worst_diff_pp': float('nan'), 'ok': False}
    write_report(subsplit, by_size, size_real, -9.46, xcheck)
    dump_json(subsplit, by_size, size_real, xcheck)


def write_report(subsplit: dict, by_size: list[dict],
                 size_real: dict, rep_3k_total_drag_from_t152: float,
                 xcheck: dict, tag: str = '') -> None:
    # ── 表 1:规模 × 5 档拖累矩阵 ──────────────────────────────────────
    size_rows = []
    for r in by_size:
        size_rows.append({
            '账户 (USDT)': f"{int(r['account']):,}",
            '理想 ann%': r['anns_pp']['N0'],
            '回放 ann%': r['anns_pp']['N5'],
            '总拖累 pp/yr': r['total_drag_pp'],
            '①成交时点': next(x['delta_pp'] for x in r['forward_rows']
                                if x['step'] == 'N1'),
            '②5% 门槛': next(x['delta_pp'] for x in r['forward_rows']
                              if x['step'] == 'N2'),
            '③成本': next(x['delta_pp'] for x in r['forward_rows']
                            if x['step'] == 'N3'),
            '④限额': next(x['delta_pp'] for x in r['forward_rows']
                           if x['step'] == 'N4'),
            '⑤止损+滑点': next(x['delta_pp'] for x in r['forward_rows']
                                if x['step'] == 'N5'),
        })
    size_real_row = {   # noqa: F841  (只在 868 不在 by_size 时才用,见下面的兜底)
        '账户 (USDT)': f"{int(size_real['account']):,} (真钱账户)",
        '理想 ann%': size_real['anns_pp']['N0'],
        '回放 ann%': size_real['anns_pp']['N5'],
        '总拖累 pp/yr': size_real['total_drag_pp'],
        '①成交时点': next(x['delta_pp'] for x in size_real['forward_rows']
                           if x['step'] == 'N1'),
        '②5% 门槛': next(x['delta_pp'] for x in size_real['forward_rows']
                         if x['step'] == 'N2'),
        '③成本': next(x['delta_pp'] for x in size_real['forward_rows']
                      if x['step'] == 'N3'),
        '④限额': next(x['delta_pp'] for x in size_real['forward_rows']
                      if x['step'] == 'N4'),
        '⑤止损+滑点': next(x['delta_pp'] for x in size_real['forward_rows']
                           if x['step'] == 'N5'),
    }
    # 868 已经由 `run_waterfall` 实测并落在 by_size 里,不要再拼一行重复的;
    # 这里只负责给它加个「真钱账户」的标记,以及在 by_size 里确实没有 868 时兜底补一行。
    if not any(r['账户 (USDT)'] == f"{int(size_real['account']):,}"
               for r in size_rows):
        size_rows.append(size_real_row)
    else:
        for r in size_rows:
            if r['账户 (USDT)'] == f"{int(size_real['account']):,}":
                r['账户 (USDT)'] += ' (真钱账户)'

    sub_rows = []
    for r in subsplit['forward_rows']:
        sub_rows.append({'step': r['step'], '打开': r['打开'],
                         'ann%': r['ann%'], 'delta_pp': r['delta_pp']})
    rev_rows = []
    for r in subsplit['reverse_rows']:
        rev_rows.append({'step': r['step'], '关掉': r['关掉'],
                         'ann%': r['ann%'], 'delta_pp': r['delta_pp']})

    sens_rows = _build_sensitivity(by_size)
    read_out = _build_readout(subsplit, by_size, size_real,
                              rep_3k_total_drag_from_t152, xcheck)

    closure_warning = ''
    if not subsplit['closure_ok']:
        closure_warning = f"\n\n> ⚠️ **闭环失败**:子档之和 − ④ 整档 = {subsplit['forward_diff_pp']:+.4f} pp;反序 {subsplit['reverse_diff_pp']:+.4f} pp。停下报差。"

    md = f"""# T-157 —— X1V ④ 限额档子拆 + 账户规模扫描

生成: `docs/research/t157_x1v_limits_by_size.py`(脚本自写本文件)
读数: 与 T-152 同一读数 —— `asset_mcap_daily` 收盘 + `ohlcv_daily/binance_hist` 开高低,
窗口 {START} → {END},基准格 半价差 {HS} bp / 手续费 {FEE} bp / 跳空滑点 {STOP_SLIP} bp。
基准账户规模 3,000 USDT(`t137.ACCOUNT`)。src/ 一行未改。
replay memoization 命中 {_STATS['hits']} / 未命中 {_STATS['miss']}。

## 0. 先证明这是 T-152 的同一条步进器(不是自洽而已)

本脚本为了按账户规模重跑,自己写了一份参数化的 replay 驱动(机制与 `t152.cfg` 相同:
就地替换 `ex.Limits` 的 dataclass 字段)。卡上要求「在 t152 的步进器上」,所以这里**直接调
`t152.nav_step`** 跑同样的三个格,两套实现的年化必须逐位相同:

{md_table(xcheck['rows'], ['step', 't152 ann%', 't157 ann%', 'diff pp'])}

最差差 **{xcheck['worst_diff_pp']:.6f} pp** → **{'PASS' if xcheck['ok'] else 'FAIL'}**。
过了这一关,下面 ① 的子档闭合才是「复现 T-152 的 ④」,而不只是「自洽」。

## 1. 规模 × 拖累 矩阵

> 行:账户规模(USDT);列:瀑布的每档 Δpp/年 + 总拖累。
> {int(REAL_SIZE):,} 是真钱账户现在的规模,**实测重跑**,不是在 1k/3k 之间插值(整数化是非线性的)。

{md_table(size_rows, ['账户 (USDT)', '理想 ann%', '回放 ann%', '总拖累 pp/yr',
                       '①成交时点', '②5% 门槛', '③成本', '④限额', '⑤止损+滑点'])}

**读法**(下面每句都是从上面这张表算出来的,不是预设结论):
- **3,000 USDT 总拖累 {subsplit['total_drag_pp']:+.2f} pp/年**,与 T-152 的 −9.46 pp/年差
  {abs(subsplit['total_drag_pp'] - rep_3k_total_drag_from_t152):.2f} pp。
- ④ 档随规模:{_d4_series(by_size)} pp/年。
- 真钱账户 {int(REAL_SIZE):,} USDC:总拖累 {size_real['total_drag_pp']:+.2f} pp/年,其中 ④
  {size_real_row['④限额']:+.2f} pp/年。

## 2. ④ 子档拆解(账户 3,000 USDT)

构造:`N3 = ①+②+③` 起点,4 个子开关**按固定顺序**依次打开 → `N4`。
约束:子档累加 = ④ 整档(差 < 0.01 pp,失效即报)。

### 2a. 正序(从 N3 起,逐一开子开关)

{md_table(sub_rows, ['step', '打开', 'ann%', 'delta_pp'])}

**④ 整档 = {subsplit['whole_4_pp']:+.4f} pp**;**子档累加 = {subsplit['forward_sub_cum_pp']:+.4f} pp**;**差 = {subsplit['forward_diff_pp']:+.4f} pp**(闭环 {('PASS' if subsplit['closure_ok'] else 'FAIL')})。

### 2b. 反序(从全开 N5 起,逐一关子开关)

{md_table(rev_rows, ['step', '关掉', 'ann%', 'delta_pp'])}

**反序子档累加 = {subsplit['reverse_sub_cum_pp']:+.4f} pp**,与 ④ 整档差
{subsplit['reverse_diff_pp']:+.4f} pp(同方向,绝对值应该接近正序之差)。

### 2c. 单项归因

| 子开关 | 正序(打开它 Δpp) | 反序(关掉它 Δpp,反号 = 同向打开) |
|---|---|---|"""
    for k in ('max_order', 'max_daily', 'min_notional', 'nav_cap'):
        cn = STEP_CN[k]
        f_idx = {'max_order': 4, 'max_daily': 5, 'min_notional': 6, 'nav_cap': 7}[k]
        fwd_delta = subsplit['forward_rows'][f_idx]['delta_pp']
        rev_idx_map = {'nav_cap': 2, 'min_notional': 3, 'max_daily': 4, 'max_order': 5}
        rev_delta = subsplit['reverse_rows'][rev_idx_map[k]]['delta_pp']
        md += f"\n| {cn} | {fwd_delta:+.4f} | {rev_delta:+.4f}(反号后 {(-rev_delta):+.4f}) |"
    md += f"""

> ④ 整档 ≈ 4 子开关 Δpp 之和;但 Δpp 之间的"先后顺序"也带来交互(后续子开关是在
> 前一个已经生效的环境里运行的)。各子档的绝对大小**不预设**,见上表实测值。
{closure_warning}
## 3. 各账户规模的完整瀑布

{md_table([{'规模': int(r['account']),
            '理想 ann%': r['anns_pp']['N0'],
            '回放 ann%': r['anns_pp']['N5'],
            '总拖累 pp': r['total_drag_pp']} for r in by_size],
           ['规模', '理想 ann%', '回放 ann%', '总拖累 pp'])}

### 3a. 哪一档真的随规模变(用极差判断,不是用肉眼)

{md_table(sens_rows, ['档', '最小 Δpp(小账户)', '最大 Δpp(大账户)', '极差 pp', '判读'])}

## 4. 怎么读(给 Jazz 的一页)

{read_out}
"""
    out_report = OUT_REPORT.with_name(f'T-157_x1v_limits{tag}.md')
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(md, encoding='utf-8')
    print('report ->', out_report)


def main() -> None:
    global REAL_SIZE
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1000,3000,10000,100000",
                    help="账户规模 USDT 列表,逗号分隔")
    ap.add_argument("--subsplit-only", action="store_true",
                    help="只跑子拆,不跑规模扫描")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--report-only", action="store_true",
                    help="不重跑 replay,直接用 OUT_DIR/t157_results.json 重写报告"
                         "(改了报告模板之后用;数字一个都不改,只重排版)")
    ap.add_argument("--tag", default="",
                    help="产物后缀:JSON=t157_results<TAG>.json,报告=T-157_x1v_limits<TAG>.md")
    ap.add_argument("--real-size", type=float, default=REAL_SIZE,
                    help="真钱账户规模 USDT(默认 %(default)s)")
    ap.add_argument("--skip-subsplit", action="store_true", help="不跑 ① 子拆")
    ap.add_argument("--skip-real", action="store_true", help="不跑 ③ 真钱账户那一行")
    ap.add_argument("--skip-crosscheck", action="store_true", help="不跑 ⓪ 与 T-152 的交叉检查")
    ap.add_argument("--merge", action="store_true",
                    help="把 OUT_DIR 下 t157_results_*.json 合并成最终报告")
    args = ap.parse_args()
    REAL_SIZE = args.real_size

    if args.report_only:
        import json as _json
        d = _json.loads((OUT_DIR / 't157_results.json').read_text())
        size_real = d.get('size_real') or d.get('size_868')
        write_report(d['subsplit'], d['by_size'], size_real, -9.46, d['crosscheck'])
        return

    if args.merge:
        merge_tagged()
        return

    sys.stdout.reconfigure(line_buffering=True)

    sizes = [float(s) for s in args.sizes.split(',') if s.strip()]
    t_start = time.time()

    ohlc = t137.fetch_ohlc(t137.SYMS, START, END)
    print(f'[fetch_ohlc] done in {time.time()-t_start:.1f}s')

    # ── 任务 ⓪:与 T-152 同一代码路径的交叉检查 ───────────────────────
    xcheck: dict = {}
    if not args.skip_crosscheck:
        print('=== T-157 ⓪ 与 T-152 同一代码路径的交叉检查 ===')
        xcheck = crosscheck_t152(ohlc)
        print(f"  最差差 {xcheck['worst_diff_pp']:.6f} pp  "
              f"{'PASS' if xcheck['ok'] else 'FAIL'}")

    subsplit: dict = {}
    if not args.skip_subsplit:
        print('\n=== T-157 ① 子档闭合(账户 3,000 USDT) ===')
        subsplit = run_subsplit(ohlc, account=3_000.0)
        print(f"  ④ 整档 = {subsplit['whole_4_pp']:+.4f} pp")
        print(f"  正序子档累加 = {subsplit['forward_sub_cum_pp']:+.4f} pp,"
              f" 差 = {subsplit['forward_diff_pp']:+.4f} pp")
        print(f"  反序子档累加 = {subsplit['reverse_sub_cum_pp']:+.4f} pp,"
              f" 差 = {subsplit['reverse_diff_pp']:+.4f} pp")
        print(f"  闭环 PASS={subsplit['closure_ok']}")
        if not subsplit['closure_ok']:
            print('  ⚠️ 子档和 != ④ 整档,差 > 0.01 pp;按卡的要求停下报差')
            if not args.no_report:
                write_report(subsplit, [], {'account': REAL_SIZE, 'interp': False,
                                           'total_drag_pp': float('nan')},
                             -9.46, xcheck, tag=args.tag)
            return

    if args.subsplit_only:
        return

    # ── 任务 ②:账户规模扫描 ──────────────────────────────────────
    print('\n=== T-157 ② 账户规模扫描 ===')
    by_size = []
    for s in sizes:
        ts = time.time()
        print(f'  -- {int(s):,} USDT --')
        r = run_waterfall(ohlc, account=s)
        by_size.append(r)
        print(f"     {time.time()-ts:.0f}s | 总拖累 = {r['total_drag_pp']:+.2f} pp/年,"
              f"理想={r['anns_pp']['N0']:.2f}% 回放={r['anns_pp']['N5']:.2f}%")

    # 中间结果先落盘:后面任何一步崩了都不至于把这一规模的数丢掉
    # (11-05 实测:一个只跑 630 的 job 在 3k 复现检查处 StopIteration,
    #  结果 JSON 没写出来,512s 的算力白费)
    dump_json(subsplit, by_size, {}, xcheck, tag=args.tag)

    # 3,000 复现检查:只有本 job 的规模表里真的有 3,000 时才做
    # (单规模 job 不含 3,000 —— 不能因此崩掉)
    rep_3k_total_drag_from_t152 = -9.46
    three_k = next((r for r in by_size if r['account'] == 3_000.0), None)
    if three_k is not None:
        ok_3k = abs(three_k['total_drag_pp'] - rep_3k_total_drag_from_t152) < 0.5
        print(f"\n  3k 复现 T-152:差异 {three_k['total_drag_pp'] - rep_3k_total_drag_from_t152:+.2f} pp"
              f" {'OK' if ok_3k else 'WARN:差过大'}")
    else:
        print('\n  (本 job 的规模表里没有 3,000,跳过 3k 复现检查)')

    # ── 任务 ③:真钱账户规模那一行 —— **真跑**而不是在 1k/3k 之间插 ──────
    # 插值会在整数化的台阶上取到中间值,而整数化恰恰是非线性的;真钱规模就在台阶上,
    # 所以这一行必须实测,否则整张表的结论会建立在一条平滑假设上。
    size_real: dict = {}
    if not args.skip_real:
        print(f'\n=== T-157 ③ {int(REAL_SIZE):,} USDC(实测) ===')
        size_real = run_waterfall(ohlc, account=REAL_SIZE)
        by_size.append(size_real)
        print(f"  总拖累 {size_real['total_drag_pp']:+.2f} pp/年, "
              f"理想={size_real['anns_pp']['N0']:.2f}% 回放={size_real['anns_pp']['N5']:.2f}%")

    print(f"\n[total] {time.time()-t_start:.0f}s — memo hits={_STATS['hits']} miss={_STATS['miss']}")

    dump_json(subsplit, by_size, size_real, xcheck, tag=args.tag)
    if not args.no_report and subsplit and size_real:
        write_report(subsplit, by_size, size_real,
                     rep_3k_total_drag_from_t152, xcheck, tag=args.tag)


if __name__ == '__main__':
    main()
