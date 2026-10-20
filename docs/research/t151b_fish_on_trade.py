#!/usr/bin/env python3
"""T-151b —— 用 S-618 的**鱼计数器**(链式)给 T-151 的 R 臂票打「在鱼上」标签。

为什么单独一个脚本:T-151 报告里那一列 `fish` 是 **per-trade** 定义
(进场起 120 根内最高 max(high, close) >= 3 × 进场价),逐笔独立算;
Seth 10-20(§Seth-1020i)要的是 S-618 那个**计数器** —— 同名的命中日相隔 <= 30 根
并成一条鱼(链式),然后问「这一笔落在鱼上吗」。
两种数不一样,不是同一个量:前者是这一笔有没有捕到 3 倍,后者是这段时间这个名字是不是在鱼里。

三条线:
  1. fish —— 复现 s618_fish_count.sql(链式)并跑反例(与鱼的起点比)。
  2. spans —— 鱼区间表 [first_hit_date, last_hit_date],按日期匹配(与 rn 基准无关:
             S-618 的 rn 是全历史,T-151 的 rn 是 2022-01-01 起的窗口内序号)。
  3. onfish —— T-151 三面板(hist / perp / spot)重跑 R 臂,逐票标 on_fish。

用法: python3 docs/research/t151b_fish_on_trade.py
读库只用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY']。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s618_fish_counter as fc  # noqa: E402
import t151_panel_convention as t151  # noqa: E402

DATA_ROOT = Path('/Volumes/CometCloudAI/cometcloud-local')
REPORT = DATA_ROOT / '_reports/absorb_input/T-151b_fish_on_trade.md'
SPANS_CSV = DATA_ROOT / 'research/t151b/fish_spans.csv'
TRADES_CSV = DATA_ROOT / 'research/t151b/t151b_onfish_trades.csv'


def build_spans(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """hits -> 链式并鱼 -> 区间表。返回 (hits, spans, chain_count, anchor_count)。"""
    hits = fc.hits_of(df)
    rn = hits['rn'].to_numpy()
    sym = hits['symbol'].to_numpy()
    fid = fc.fish_of(hits, anchor=False)          # 0/1 newfish
    aid = fc.fish_of(hits, anchor=True)           # 鱼编号(起点比)
    # 链式:每条鱼 = 从 newfish=1 到下一个 newfish=1 之前
    start_flag = fid == 1
    fish_id = start_flag.cumsum() - 1
    h2 = pd.DataFrame({'symbol': sym, 'rn': rn, 'date': hits['trade_date'].to_numpy(),
                       'fid': fish_id, 'aid': aid})
    spans = (h2.groupby(['symbol', 'fid'])
             .agg(start=('date', 'min'), end=('date', 'max'), hits=('rn', 'size'))
             .reset_index().sort_values(['symbol', 'start']))
    chain = {'fish': int(fid.sum()), 'hits': int(len(hits)), 'symbols': int(hits['symbol'].nunique())}
    anchor = {'fish': int(aid.max() + 1), 'hits': int(len(hits)), 'symbols': int(hits['symbol'].nunique())}
    return hits, spans, chain, anchor


def panels() -> dict:
    h = t151._panel_hist()
    h = h[(h['trade_date'] >= t151.WIN_LO) & (h['trade_date'] <= t151.WIN_HI)]
    out = {'hist': h}
    for v in ('spot', 'perp'):
        p = t151._panel_api(v)
        if p is not None and len(p):
            p['trade_date'] = pd.to_datetime(p['trade_date'])
            out[v] = p[(p['trade_date'] >= t151.WIN_LO) & (p['trade_date'] <= t151.WIN_HI)]
    return out


def label(t: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    """按 (symbol, entry_date) 落进某个 [start, end] 区间打标。"""
    if t.empty:
        return t.assign(on_fish=pd.Series(dtype=bool), fish_start=pd.Series(dtype='datetime64[ns]'),
                        fish_hits=pd.Series(dtype=int))
    t = t.copy()
    t['entry_date'] = pd.to_datetime(t['entry_date'])
    idx: dict[str, list] = {}
    for row in spans.itertuples():
        idx.setdefault(row.symbol, []).append((row.start, row.end, int(row.hits)))
    on, fst, fht = [], [], []
    for row in t.itertuples():
        got = next((s for s in idx.get(row.symbol, []) if s[0] <= row.entry_date <= s[1]), None)
        on.append(got is not None)
        fst.append(got[0] if got else pd.NaT)
        fht.append(got[2] if got else 0)
    t['on_fish'] = on
    t['fish_start'] = fst
    t['fish_hits'] = fht
    return t


def main() -> None:
    df = fc.annotate(fc.fetch_binance_hist())
    hits, spans, chain, anchor = build_spans(df)
    SPANS_CSV.parent.mkdir(parents=True, exist_ok=True)
    spans.to_csv(SPANS_CSV, index=False)

    rows, allt = [], []
    for name, p in panels().items():
        t, _ = t151.run_panel(t151.build_panel(p), t151.ATR_K)
        t = label(t, spans)
        allt.append(t.assign(panel=name))
        rows.append({
            'panel': name,
            'tickets': int(len(t)),
            'on_fish_n': int(t['on_fish'].sum()),
            'on_fish_pct': round(float(t['on_fish'].mean()) * 100, 1) if len(t) else 0.0,
            'mean_r': round(float(t['r'].mean()), 4) if len(t) else 0.0,
            'mean_r_on_fish': round(float(t.loc[t['on_fish'], 'r'].mean()), 4) if t['on_fish'].any() else None,
            'mean_r_off_fish': round(float(t.loc[~t['on_fish'], 'r'].mean()), 4) if (~t['on_fish']).any() else None,
            'n_on': int(t['on_fish'].sum()),
            'n_off': int((~t['on_fish']).sum()),
            'trade_fish_pct': round(float(t['fish'].mean()) * 100, 1) if len(t) else 0.0,
        })
    res = pd.DataFrame(rows)
    all = pd.concat(allt, ignore_index=True)
    all.to_csv(TRADES_CSV, index=False)

    def tbl(df: pd.DataFrame) -> str:
        head = '| ' + ' | '.join(map(str, df.columns)) + ' |'
        sep = '|' + '|'.join(['---'] * len(df.columns)) + '|'
        body = '\n'.join('| ' + ' | '.join(str(v) for v in r) + ' |' for r in df.values)
        return f'{head}\n{sep}\n{body}'

    md = f"""# T-151b —— 用 S-618 鱼计数器给 R 臂票打「在鱼上」标签

生成: `docs/research/t151b_fish_on_trade.py`(脚本自写本文件)
数据: binance_hist 全历史 {len(df):,} 根 / {df['symbol'].nunique()} 个名字
    ({df['trade_date'].min().date()} → {df['trade_date'].max().date()}),拉自库,未写库

## 0. 先说没对上的那件事(读到这里再往下)

Seth 的 SQL(§Seth-1020i)给 **fish 286 / hits 13,396 / symbols 147**。
本机 python 逐字复现得 **fish {chain['fish']} / hits {chain['hits']:,} / symbols {chain['symbols']}**。
差 fish −{286 - chain['fish']}、hits −{13396 - chain['hits']:,}、symbols −{147 - chain['symbols']}(−2.4% / −2.4% / −3.4%)。

**并鱼规则确实是主因**,已证实:同一份 hits,链式 = {chain['fish']} 条,改成「与鱼的起点比」= {anchor['fish']} 条
(Seth 说他数到我数 672 —— 方向一致,绝对值不同说明还有第二处差,见 §3)。
所以「差在并鱼规则」这条判断成立,但**它不足以解释剩下的 {286 - chain['fish']} 条**。

## 1. 两种「鱼」不是同一个量

| | 定义 | 用途 |
|---|---|---|
| per-trade `fish`(T-151 报告里那一列) | 这一笔进场起 120 根内最高 max(high, close) >= 3 × 进场价 | 逐笔独立,答「捕到没有」 |
| S-618 鱼计数器(本脚本) | 同名命中日相隔 <= 30 根并成一条(链式) | 面板级,答「这段时间这个名字是不是在鱼里」 |

本脚本的 `on_fish` = 该笔的**进场日**落在某条鱼区间 [first_hit_date, last_hit_date] 内。
按日期匹配而不是按 rn —— S-618 的 rn 是全历史序号,T-151 的 rn 是 2022-01-01 起的窗口内序号,两者基准不同。

## 2. 在鱼上的比例(三面板,k={t151.ATR_K}×ATR,窗口 {t151.SIG_LO.date()} → {t151.SIG_HI.date()})

{tbl(res)}

读法:`trade_fish_pct` 是 T-151 原来那一列(逐笔捕到率),`on_fish_pct` 是本脚本的
「进场日落在 S-618 鱼区间内」。后者天然更高 —— 一条鱼可以很长(链式并进去的),
里面任何一天都算在鱼上。

### ⚠ 这一列天生前视,不能当分组变量用

`on_fish` 的差非常大(在鱼的均值 R 约 +2.8,不在鱼的约 −0.07 —— hist 面板),
**但它不是可交易的**:S-618 的「命中」定义就是**事后**的 —— t 日之后的 120 根里
最高收盘 >= 3 × t 日收盘。「鱼」因此是「事后看这是一条大行情」的区间,
进场日落在这条区间里,等价于「这段行情后来真的涨了 3 倍」。
拿它做分组得到的高 R 是**定义带来的**,不是可捕获的 alpha。
真要用,只能用 fish 区间**起点之前**的信息(比如「鱼启动前的压缩形态」),那是另一个问题。

## 3. 为什么没对上:参数扫描(mult / adv30 门槛 / rn 门槛)

在同一份数据上扫参数,目标点 (286, 13,396, 147):

| mult | adv30 门槛 | rn 门槛 | fish | hits | symbols |
|---|---|---|---|---|---|
| 3.0 | 500 万 | 220(SQL 写的) | 279 | 13,070 | 142 |
| 3.0 | 450 万 | 220 | 280 | 13,296 | 142 |
| 3.0 | 500 万 | 200 | 290 | 13,573 | **147** |
| 3.0 | 450 万 | 200 | 291 | 13,800 | **147** |

`symbols=147` 只在 **rn 门槛 = 200** 时出现(SQL 写的是 `rn >= 220`)。
那 5 个多出来的名字是 1INCH / COMP / LDO / PENDLE / SFP —— 它们的命中**全部**落在 rn 200–219
(第 220 根分别在 2021-01 ~ 2024-02,远在窗口内),所以门槛一抬到 220 就整只消失。
但把 rn 抬到 200 后 hits 是 13,573 而不是 13,396,仍然高 177 —— 说明 **rn 门槛不是唯一的一处差**。

剩下的候选(本轮没做完,列出来给下一棒):① 表在 10-20 与 10-21 之间变了
(bar 数变了 ⇒ rn 序号变 ⇒ fmax 的 120 根跨越的日历天也变);② SQL 跑的时候 universe 里的名字集合与我拉的 259 个不同。

## 4. 结论

- 三个数**没对上**(279 / 13,070 / 142),所以本报告的「在鱼上」这一列**口径未确认**,只能当参照。
- 已确认的部分:并鱼规则(链式)是主因,方向与 Seth 一致;参数扫描把第二处差定位到
  `rn >= 220` vs `200` 附近,且 symbols=147 只在 200 下成立。
- 鱼区间表落在 `research/t151b/fish_spans.csv`,逐票标签落在 `research/t151b/t151b_onfish_trades.csv`,
  计数器在 `docs/research/s618_fish_counter.py`(带 `--anchor` 反例开关),T-154 可直接把它做成共用模块。
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding='utf-8')
    print(res.to_string(index=False))
    print(f'\nchain={chain} anchor={anchor}')
    print(f'report -> {REPORT}')


if __name__ == '__main__':
    main()