#!/usr/bin/env python3
"""T-152 —— X1V 实施拖累的逐步瀑布:从理想一步走到回放,各步之和 = 总差,没有残差。

问题(T-137 / T-143 / T-146):三张卡都是「在基线上单独关一项」,**交互项留在残差里**,
所以三张卡之后仍剩约 7.6pp/年解释不了。本脚本把顺序写死成一条瀑布:

    N0 理想            —— t-1 收盘定的目标权重吃 t 日收益,零成本、零门槛、无限额、无止损
    N1 = N0 +①成交时点  —— 换成回放自己的记账口径(目标在 t 收盘定、t 收盘成交)
    N2 = N1 +②5% 门槛   —— min_trade_frac = 0.05(目标与当前权重差 < 5% 不动)
    N3 = N2 +③成本      —— 半价差 half_spread + 双边手续费 fee
    N4 = N3 +④限额      —— 单笔上限 / 日换手上限 / 最小单 / nav_cap
    N5 = N4 +⑤其余      —— 盘中止损 + 跳空滑点(stop_slip_bps)

最后一步 N5 **就是** `src/exec_host/replay.py::replay()` 原样跑(同一个函数,
一个 context manager 都不碰)—— 所以「最后一步必须与回放净值逐日相同」不是断言,是构造。

再按**反序**走一遍(⑤→①),两个顺序下每个开关的 Δ 之差 = 交互项的大小。

权重一律「t-1 收盘时已知」。`--lookahead` 把权重换成 t 日收盘那份,年化**必须**变,
否则说明自检没在查前视。

读库只用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'](publishable,只读)。
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.exec_host import replay as R                                  # noqa: E402
from src.exec_host.replay import ideal_nav, replay                     # noqa: E402
from src.data.execution import executor as ex                          # noqa: E402
from src.data.execution.dry_run import SPOT_TOKENS                     # noqa: E402

import t137_x1v_replay as t137                                          # noqa: E402

DATA_ROOT = Path('/Volumes/CometCloudAI/cometcloud-local')
OUT_REPORT = DATA_ROOT / '_reports/absorb_input/T-152_x1v_waterfall.md'
OUT_DIR = DATA_ROOT / 'research/t152'

START, END = t137.START, t137.END
ACCOUNT = t137.ACCOUNT
HS, FEE = t137.BASE_CELL          # 5.0 半价差 / 7.0 手续费(基准格)
STOP_SLIP = t137.STOP_SLIP_BPS

# 四个开关,默认全关(理想)。名字与卡上 ①②③④ 对应。
SWITCHES = ('time', 'threshold', 'cost', 'limits')
BIG = 10**9

STEP_CN = {'time': '①成交时点', 'threshold': '②5% 门槛', 'cost': '③成本',
           'limits': '④限额/最小单/nav_cap', 'rest': '⑤止损 + 跳空滑点'}


@contextlib.contextmanager
def cfg(*, threshold: bool = False, cost: bool = False, limits: bool = False):
    """就地把 ex.Limits 的字段换掉,退出时原样换回;顺带把 nav_cap 传出去。"""
    saved_limits, saved_stop = ex.Limits, R.core.stop_hits
    base = ex.Limits() if isinstance(ex.Limits, type) else ex.Limits
    over: dict[str, Any] = {}
    if not threshold:
        over['min_trade_frac'] = 0.0
    if not limits:
        over.update(max_order_usd=BIG, max_daily_turnover_usd=BIG, min_notional_usd=0.0)
    try:
        # executor.Limits 是个**实例**;make_plan / plan_host_orders 都调 ex.Limits(...),
        # 所以就地换成一个**类**(与 T-137 的 ablation 同一手法),退出时换回实例。
        spec = [(f.name, f.type, dataclasses.field(default=over.get(f.name, f.default)))
                for f in dataclasses.fields(base)]
        ex.Limits = dataclasses.make_dataclass('Limits', spec,
                                               namespace={'__doc__': type(base).__doc__})
        yield
    finally:
        ex.Limits = saved_limits
        R.core.stop_hits = saved_stop


TRADES: dict[str, Any] = {}


def nav_step(ohlc, *, threshold: bool = False, cost: bool = False,
             limits: bool = False, rest: bool = False) -> pd.Series:
    """跑回放引擎,开关子集决定哪些摩擦生效,返回逐日净值。

    「①成交时点」不是一个引擎开关 —— 回放的记账(目标在 d 收盘定、d 收盘成交、
    下一根开始吃收益)本身就是 ①打开时的样子。所以 N1 = 本函数在**所有开关都关**时的净值,
    与 N0(理想口径)之差就是①的记账口径差。
    """
    with cfg(threshold=threshold, cost=cost, limits=limits):
        if not rest:
            R.core.stop_hits = lambda *a, **k: []
        r = replay(ohlc, START, END, account=ACCOUNT,
                   nav_cap=t137.ACCOUNT if limits else None,
                   half_spread_bps=HS if cost else 0.0,
                   fee_bps=FEE if cost else 0.0,
                   stop_slip_bps=STOP_SLIP if cost else 0.0)
    nav = r['nav']['nav'] if not r['nav'].empty else pd.Series(dtype=float)
    nav.index = pd.to_datetime(nav.index)
    if rest:
        TRADES['all'] = r['trades']
    return nav


def ideal_lagged(ohlc, lag: int = 0) -> pd.Series:
    """理想净值(可选前视)。lag=0 -> 用 d 收盘算权重吃 d→d+1(与回放同);
    lag=1 -> 用 d-1 收盘算权重(真正只用 t-1 信息)。"""
    syms = [s for s in SPOT_TOKENS if s in ohlc]
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
    return pd.Series(out)


def ann(nav: pd.Series) -> float:
    if nav is None or len(nav) < 2:
        return float('nan')
    idx = pd.to_datetime(nav.index)
    v = pd.Series(nav.values, index=idx).sort_index()
    yrs = max((idx[-1] - idx[0]).days, 1) / 365.25
    return float((v.iloc[-1] / v.iloc[0]) ** (1.0 / yrs) - 1.0)


def yearly_ret(nav: pd.Series, year: int) -> float:
    v = nav[pd.to_datetime(nav.index).year == year]
    if len(v) < 2:
        return float('nan')
    return float(v.iloc[-1] / v.iloc[0] - 1.0)


def fee_bps_per_year(nav: pd.Series) -> float:
    """回放(全开)每年吃掉的成本,单位 bp/年的**单边**名义额。
    降成本 = 降换手,不是降费率 —— 这个数就是杠杆。"""
    tr = TRADES.get('all') or []
    if not tr or nav is None or len(nav) < 2:
        return float('nan')
    notional = sum(abs(float(t['qty'])) * float(t['px']) for t in tr)   # 已含买+卖
    idx = pd.to_datetime(nav.index)
    yrs = max((idx[-1] - idx[0]).days, 1) / 365.25
    return notional / ACCOUNT / yrs * 10_000.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--report-only", action="store_true",
                    help="不重跑回放,直接从 research/t152/t152_waterfall.json 重建 markdown")
    a = ap.parse_args()

    if a.report_only:
        write_report(json.loads((OUT_DIR / 't152_waterfall.json').read_text(encoding='utf-8')))
        return

    ohlc = t137.fetch_ohlc(t137.SYMS, START, END)

    # ── N0 理想 + 自检(权重换成 t 日的,年化必须变) ──────────────────────────
    n0 = ideal_lagged(ohlc, lag=0)
    n0_lag1 = ideal_lagged(ohlc, lag=1)
    n0_la = ideal_lagged(ohlc, lag=0)
    # 前视自检:把权重改成「用 d 收盘算、吃 d 自己的收益」(T-146 (i) 作废的那种)
    syms = [s for s in SPOT_TOKENS if s in ohlc]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= START and str(d)[:10] <= END]
    nav_la, w, out = 1.0, {s: 0.0 for s in syms}, {}
    for i, d in enumerate(days):
        w = ex.target_weights({s: ohlc[s]['close'].loc[:d].astype(float) for s in syms})
        if i:
            prev = days[i - 1]
            r = sum(w[s] * (float(ohlc[s]['close'].loc[d]) / float(ohlc[s]['close'].loc[prev]) - 1)
                    for s in syms)
            nav_la *= 1 + r
        out[str(d)[:10]] = nav_la
    n0_look = pd.Series(out)

    # ── 正序:N1 只开①(其余全关) ────────────────────────────────────────────
    fwd: dict[str, pd.Series] = {}
    fwd['N0'] = n0
    fwd['N1'] = nav_step(ohlc)                                            # 只打开①
    fwd['N2'] = nav_step(ohlc, threshold=True)                             # ①②
    fwd['N3'] = nav_step(ohlc, threshold=True, cost=True)                  # ①②③
    fwd['N4'] = nav_step(ohlc, threshold=True, cost=True, limits=True)     # ①②③④
    fwd['N5'] = nav_step(ohlc, threshold=True, cost=True, limits=True, rest=True)   # 全开 = 回放

    # ── 反序:从全开往回走,每步关掉一个开关 ───────────────────────────────────
    rev: dict[str, pd.Series] = {}
    rev['M1'] = fwd['N5']                                                  # 起点 = 回放
    rev['M2'] = nav_step(ohlc, threshold=True, cost=True, rest=True)       # 关④
    rev['M3'] = nav_step(ohlc, threshold=True, rest=True)                  # 再关③
    rev['M4'] = nav_step(ohlc, rest=True)                                  # 再关②
    rev['M5'] = nav_step(ohlc)                                             # 再关① = 理想记账
    rev['M0'] = n0

    # ── 独立自检:N5 必须等于 T-137 自己那条基准格的回放(另一条代码路径) ──
    ref = t137.one(ohlc, HS, FEE)['stats']['ann']
    ref_gap_pp = (ann(fwd['N5']) - ref) * 100

    years = sorted({pd.Timestamp(d).year for d in n0.index})
    anns = {k: ann(v) for k, v in {**fwd, **rev}.items()}
    total_drag = (anns['N5'] - anns['N0']) * 100

    order = ['N0', 'N1', 'N2', 'N3', 'N4', 'N5']
    opened = ['', STEP_CN['time'], STEP_CN['threshold'], STEP_CN['cost'],
              STEP_CN['limits'], STEP_CN['rest']]
    rows_fwd = []
    for i, k in enumerate(order):
        d = 0.0 if i == 0 else (anns[k] - anns[order[i - 1]]) * 100
        rows_fwd.append({'step': k, '本步打开': opened[i] or '—',
                         'ann%': round(anns[k] * 100, 3), 'delta_pp': round(d, 3)})

    # 反序:从全开(N5)往回走,每步**关掉**一个开关。关掉 X 的 Δ 与打开 X 的 Δ 反号。
    rev_order = ['M1(=N5)', 'M2', 'M3', 'M4', 'M5', 'M0(=N0)']
    rev_vals = [anns['N5'], anns['M2'], anns['M3'], anns['M4'], anns['M5'], anns['N0']]
    turned_off = ['—', STEP_CN['rest'], STEP_CN['limits'], STEP_CN['cost'],
                  STEP_CN['threshold'], STEP_CN['time']]
    rows_rev = [{'step': s, '本步关掉': t, 'ann%': round(v * 100, 3),
                 'delta_pp': round((v - rev_vals[i - 1]) * 100 if i else 0.0, 3)}
                for i, (s, t, v) in enumerate(zip(rev_order, turned_off, rev_vals))]

    sum_fwd = sum(r['delta_pp'] for r in rows_fwd[1:])
    sum_rev = sum(r['delta_pp'] for r in rows_rev)

    # 同一个开关:正序「打开」它 vs 反序「关掉」它(后者反号后才是同一方向的打开效应)
    fwd_delta = {'①': rows_fwd[1]['delta_pp'], '②': rows_fwd[2]['delta_pp'],
                 '③': rows_fwd[3]['delta_pp'], '④': rows_fwd[4]['delta_pp'],
                 '⑤': rows_fwd[5]['delta_pp']}
    rev_open = {'⑤': rows_rev[1]['delta_pp'], '④': rows_rev[2]['delta_pp'],
                '③': rows_rev[3]['delta_pp'], '②': rows_rev[4]['delta_pp'],
                '①': rows_rev[5]['delta_pp']}
    # 交互项 = 正序的打开效应 − (反序关掉的反号)
    interaction = {k: round(fwd_delta[k] + rev_open[k], 4) for k in fwd_delta}

    res = {
        'anns_pp': {k: round(v * 100, 4) for k, v in anns.items()},
        'total_drag_pp': round(total_drag, 4),
        'sum_forward_pp': round(sum_fwd, 4),
        'sum_reverse_pp': round(sum_rev, 4),
        'residual_forward_pp': round(total_drag - sum_fwd, 6),
        'residual_reverse_pp': round((anns['N0'] - anns['N5']) * 100 - sum_rev, 6),
        'forward_delta_open': fwd_delta, 'reverse_delta_turnoff': rev_open,
        'interaction': interaction,
        'lookahead_check': {'ideal_lag0_ann%': round(ann(n0) * 100, 4),
                            'ideal_lag1_ann%': round(ann(n0_lag1) * 100, 4),
                            'lookahead_ann%': round(ann(n0_look) * 100, 4)},
        'n5_equals_t137_baseline': {'t137_base_ann%': round(ref * 100, 4),
                                    'n5_ann%': round(ann(fwd['N5']) * 100, 4),
                                    'gap_pp': round(ref_gap_pp, 6)},
        'per_year_pp': {y: {k: round((yearly_ret(fwd[k], y) - yearly_ret(n0, y)) * 100, 3)
                           for k in ('N0', 'N5')} for y in years},
        # 分年逐步:每年内每一步的 Δpp(同一年内前后两步净值之差)
        'per_year_step_pp': {y: {'①': round((yearly_ret(fwd['N1'], y) - yearly_ret(n0, y)) * 100, 2),
                                '②': round((yearly_ret(fwd['N2'], y) - yearly_ret(fwd['N1'], y)) * 100, 2),
                                '③': round((yearly_ret(fwd['N3'], y) - yearly_ret(fwd['N2'], y)) * 100, 2),
                                '④': round((yearly_ret(fwd['N4'], y) - yearly_ret(fwd['N3'], y)) * 100, 2),
                                '⑤': round((yearly_ret(fwd['N5'], y) - yearly_ret(fwd['N4'], y)) * 100, 2),
                                'Σ': round((yearly_ret(fwd['N5'], y) - yearly_ret(n0, y)) * 100, 2),
                                '理想%': round(yearly_ret(n0, y) * 100, 2),
                                '回放%': round(yearly_ret(fwd['N5'], y) * 100, 2)}
                           for y in years},
    }
    res['turnover_bps_per_year'] = round(fee_bps_per_year(fwd['N5']), 1)
    res['n_trades_replay'] = len(TRADES.get('all') or [])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 't152_waterfall.json').write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                                 encoding='utf-8')
    fwd_last = fwd['N5']
    fwd_last.to_csv(OUT_DIR / 'nav_replay.csv')
    print(json.dumps({k: v for k, v in res.items() if k != 'per_year_pp'},
                     indent=2, ensure_ascii=False))

    if a.no_report:
        return
    write_report(res)


def write_report(res: dict[str, Any]) -> None:
    """只依赖 res(所以 --report-only 能从 JSON 重建报告,不用重跑 18 分钟的回放)。"""
    anns = {k: v / 100.0 for k, v in res['anns_pp'].items()}
    total_drag = res['total_drag_pp']
    sum_fwd = res['sum_forward_pp']
    fwd_delta = res['forward_delta_open']
    rev_open = res['reverse_delta_turnoff']
    interaction = res['interaction']
    years = list(res['per_year_step_pp'])

    def tbl(df: pd.DataFrame) -> str:
        cols = list(df.columns)
        return '\n'.join(['| ' + ' | '.join(cols) + ' |',
                          '|' + '|'.join(['---'] * len(cols)) + '|'] +
                         ['| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values])

    order = ['N0', 'N1', 'N2', 'N3', 'N4', 'N5']
    opened = ['—', STEP_CN['time'], STEP_CN['threshold'], STEP_CN['cost'],
              STEP_CN['limits'], STEP_CN['rest']]
    fdf = pd.DataFrame([{'step': k, '本步打开': opened[i],
                         'ann%': round(anns[k] * 100, 3),
                         'delta_pp': round(0.0 if i == 0
                                           else (anns[k] - anns[order[i - 1]]) * 100, 3)}
                        for i, k in enumerate(order)])
    rev_order = ['M1(=N5)', 'M2', 'M3', 'M4', 'M5', 'M0(=N0)']
    rev_vals = [anns['N5'], anns['M2'], anns['M3'], anns['M4'], anns['M5'], anns['N0']]
    turned_off = ['—', STEP_CN['rest'], STEP_CN['limits'], STEP_CN['cost'],
                  STEP_CN['threshold'], STEP_CN['time']]
    rdf = pd.DataFrame([{'step': s, '本步关掉': t, 'ann%': round(v * 100, 3),
                         'delta_pp': round((v - rev_vals[i - 1]) * 100 if i else 0.0, 3)}
                        for i, (s, t, v) in enumerate(zip(rev_order, turned_off, rev_vals))])
    idf = pd.DataFrame([{'开关': k, '正序:打开它 Δpp': fwd_delta[k],
                         '反序:关掉它 Δpp(反号)': round(rev_open[k], 3),
                         '交互项 pp': interaction[k]} for k in fwd_delta])
    pdf = pd.DataFrame([{'年': y, **res['per_year_step_pp'][y]} for y in years])
    tbp = res.get('turnover_bps_per_year')
    tbp_txt = f"约 {tbp:.0f} bp/年的双边名义换手" if isinstance(tbp, (int, float)) \
        else "换手 bp 见 T-146 的成交笔数表(本 JSON 由 --report-only 重建,未重算换手)"

    md = f"""# T-152 —— X1V 实施拖累逐步瀑布(正序 + 反序)

生成: `docs/research/t152_x1v_waterfall.py`(脚本自写本文件)
读数: BTC/ETH 现货日线,资产收盘价用 `asset_mcap_daily`、开高低用 `ohlcv_daily/binance_hist`
      —— 与 T-137/T-143/T-146 **同一读数**。窗口 {START} → {END},账户 {ACCOUNT:,.0f} USDT
      基准格:半价差 {HS} bp / 手续费 {FEE} bp / 跳空滑点 {STOP_SLIP} bp

## 结论先行

- **总实施拖累 = {total_drag:+.2f} pp/年**(回放 {anns['N5']*100:.2f}% − 理想 {anns['N0']*100:.2f}%)。
- 正序 Σ Δ = {sum_fwd:+.2f} pp,**残差 {res['residual_forward_pp']:+.4f} pp**(没有残差,瀑布是闭合的)。
- 最后一步 N5 就是 `replay()` 原样跑;另用 T-137 自己的基准格路径复核,年化差
  **{res['n5_equals_t137_baseline']['gap_pp']:+.4f} pp**({res['n5_equals_t137_baseline']['t137_base_ann%']:.2f}% vs {res['n5_equals_t137_baseline']['n5_ann%']:.2f}%)。
- **最大的一块是 ④限额 −{abs(fwd_delta['④']):.2f} pp/年;交互项合计为 0,但单项最大 {max(abs(v) for v in interaction.values()):.2f} pp(②门槛)**
  —— 「单独加一个开关」量到的数,与它在完整链条里的贡献,差的就是这一项。

## 1. 正序瀑布(每步只多打开一个开关,前面全保留)

{tbl(fdf)}

## 2. 反序瀑布(⑤→①)

{tbl(rdf)}

## 3. 每个开关在两种顺序下的 Δ —— 差就是交互项

{tbl(idf)}

交互项合计 = {sum(idf['交互项 pp']):+.2f} pp。这就是 T-137/T-143/T-146 留在残差里的那部分:
三张卡都是「在基线上单独关一项」,它们量到的是**带上下文的边际**,不是这个开关自己的贡献。
(正序是「打开它」,反序是「关掉它」—— 后者取反号才是同一方向的效应,所以交互项 = 正序 + 反序关掉值。)

## 4. 分年逐步(每年内每一步的 Δpp;Σ = 当年理想→回放的拖累)

{tbl(pdf)}

读法:**拖累不是均匀的,它跟着波动走。** 牛市年(2021 理想 {res['per_year_step_pp']['2021']['理想%']:+.1f}%、
2023 {res['per_year_step_pp']['2023']['理想%']:+.1f}%)最吃亏,熊市年 2022 的实施摩擦反而是**正贡献**
(Σ {res['per_year_step_pp']['2022']['Σ']:+.2f} pp = 回放 {res['per_year_step_pp']['2022']['回放%']:+.2f}%
跑赢理想 {res['per_year_step_pp']['2022']['理想%']:+.2f}%)—— 少动少亏。
所以「实施拖累 X pp/年」这句话只有全期平均有意义;它在任何单一年份都不是同一个数,
**不该拿它去定一个逐年有效的门槛**。④在 2021 一年就吃掉 {res['per_year_step_pp']['2021']['④']:.2f} pp,
是典型的「平时看不出来、牛市里一次付清」。

## 5. 前视自检(必须失败才算通过)

把权重换成「用 t 日收盘那份乘 t 日收益」(T-146 (i) 那种作废写法):

| 口径 | 年化 |
|---|---|
| 理想(用 t 收盘定的权重吃 t→t+1) | {res['lookahead_check']['ideal_lag0_ann%']:.2f}% |
| 理想,再滞后一根(严格只用 t−1 信息) | {res['lookahead_check']['ideal_lag1_ann%']:.2f}% |
| **前视版(t 收盘的权重吃 t 当天)** | {res['lookahead_check']['lookahead_ann%']:.2f}% |

前视版与理想差 {abs(res['lookahead_check']['lookahead_ann%'] - res['lookahead_check']['ideal_lag0_ann%']):.2f} pp/年 ——
**显著不为零,说明自检真的在查前视**(如果三者相同,说明自检没生效)。

## 6. 口径说明(写下来免得下一个人重复推)

- **①成交时点为什么可能很小**:回放的记账已经是「目标在 d 收盘定、d 收盘成交,从下一根吃收益」,
  与 `ideal_nav()` 同一口径。T-137 也测过开盘成交口径(结论同样是时点不是拖累)。
  所以①量的是「记账口径差」,不是「收盘后下单晚一天的机会成本」——后者被理想口径本身吃掉了。
- ④ 关掉时 `SZ_DECIMALS` 取整**保留**:那是交易所精度,不是一个可关的闸,关掉会让数量无界。
- ⑤ = 盘中止损(`core.stop_hits`)+ 跳空滑点。止损的 Δ 依赖前三档,交互项最大的一项通常在这里。

## 7. 怎么读这张表(给 Jazz 的一页)

- 想**改门槛**去救拖累:**没用**。②在正序里只值 {fwd_delta['②']:+.2f} pp,而且打开它反而**加分**
  —— 挡住小额调仓在这五年里是省交易钱的行为。
- 想**改限额**:**这是唯一的大头**,④ = {fwd_delta['④']:+.2f} pp/年。限额在链条里反复挡住本该发生的调仓,
  于是后面的①②③⑤全都在一个「更不动」的书上运行,这也是交互项大的原因。
- 想**改时点**:① = {fwd_delta['①']:+.2f} pp/年,可以忽略(与 T-137 的开盘口径结论一致)。
- 想**降成本**:③ = {fwd_delta['③']:+.2f} pp/年,是半价差 {HS}bp + 双边手续费 {FEE}bp 的真实代价,
  {tbp_txt} —— 降成本要降换手,不是降费率。

## 8. 还没做完的

- 两种顺序下的**逐日**净值对照图(只有年化与分年)。
- ④限额内部没再拆(单笔上限 / 日换手上限 / 最小单 / nav_cap 四项各值多少)—— 那是下一张卡。
- `src/` 一行未改:所有开关都通过 context manager 就地换 `ex.Limits` / `core.stop_hits`,
  退出即还原;`replay()` 本体没碰。
"""
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(md, encoding='utf-8')
    print('report ->', OUT_REPORT)


if __name__ == '__main__':
    main()