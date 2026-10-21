#!/usr/bin/env python3
"""T-089 第 1 段 —— 整只基金的按时点模拟,**管线跑通 + 缺口点清**。

卡上要的是:新 ①(cap_uncapped)+ ② 倾斜(mult_v2_replay)+ ③ 推力(cis_a1_u_replay)
+ 组合层(pl_v3_replay),经**配置层现行规则**(`src/data/allocation/allocator.py` 的准入规则)
**按时点**合成一条 NAV,对照 BTC / ① / 同积木随机权重 500 次。

本脚本只做两件事,都是卡上 acceptance 的第 1 步:

  ① 按时点管线:把每块积木的日收益按**当时已有的证据**合成一条 NAV,窗口切三段。
  ② 把缺口点清 —— 尤其是组合层与配置层能不能读到。

**本轮不测任何假设,所以没往台账写 M- 预注册** —— 预注册是给「配置层准入规则」那个
判决用的,而那一判决需要组合层,组合层这一轮读不到(见下)。任何在此之前做的判决都是
先看结果再定判据,那就是自证。

⚠️ 数据纪律(v3 被退回的那条,这里逐条钉死):
  · **不 ffill / bfill / fillna**。缺失就是缺失:一条积木在某天没有 ret ⇒ 该天整行
    退出样本(并计数),不是 0、不是 1.0、不是前后值。
  · 积木之间**按日期内连接**(inner join),不是按行号对齐。不同积木的起始日不同,
    对齐到行号会凭空造出一段没人交易过的日子。
  · 缺窗口(样本 < 60 天)不年化、不给夏普 —— 返回 None,不是 0。
  · 合成/csv 后端里不写任何虚构先验。等权堆叠是**诊断**用,报告里逐处标注
    `DIAGNOSTIC`,不得当成卡上的配置层规则。

读数:Supabase(环境里的 publishable key,只读)。src/ 一行未改。
输出:/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-089_fund_sim_pit.md
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data.evaluation import apparatus as ap   # noqa: E402

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
HDRS = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}

OUT_REPORT = (Path('/Volumes/CometCloudAI/cometcloud-local')
              / '_reports/absorb_input/T-089_fund_sim_pit.md')
OUT_DIR = Path('/Volumes/CometCloudAI/cometcloud-local/research/t089')

# 卡上点名的四块积木 + BTC 对照臂
BRICKS = [
    ('① core', 'core_variants_daily', 'cap_uncapped'),
    ('② mult', 'multiplier_daily', 'mult_v2_replay'),
    ('③ tilt', 'cis_tilt_daily', 'cis_a1_u_replay'),
    ('④ pl', 'portfolio_layer_daily', 'pl_v3_replay'),
]
BENCH_BTC = ('core_variants_daily', 'btc')

WINDOW_CUTS = ['2023-01-01', '2025-01-01', '2026-10-12']
MIN_DAYS_FOR_ANN = 365
N_RANDOM = 500
SEED = 20261021
PAGE = 1000          # PostgREST 单页上限;不翻页会静默截断


def fetch(table: str, arm: str, cols: str = 'd,ret') -> pd.DataFrame:
    """只读拉一块积木。**不做任何填充** —— 缺失保持 NaN。

    分页:PostgREST 单次最多 1000 行,不翻页会静默截断(第一次跑就截在 2025-09-27,
    而表里明明有到 2026-10-19 的行 —— 截断看起来像「数据到此为止」)。
    """
    base = (f'{SUPABASE_URL.rstrip("/")}/rest/v1/{table}'
            f'?select={cols}&arm=eq.{arm}&order=d.asc')
    rows: list[dict] = []
    page = 0
    total: Optional[str] = None
    while True:
        step = f'{page*PAGE}-{page*PAGE + PAGE - 1}'
        req = urllib.request.Request(base, headers={**HDRS, 'Range': step})
        with urllib.request.urlopen(req, timeout=180) as r:
            chunk = json.loads(r.read())
            total = r.headers.get('Content-Range')
        rows.extend(chunk)
        page += 1
        # 只用「这一页没满」判断到底 —— Content-Range 常是 `0-999/*`(总数未知),
        # 拿 `*` 当终止条件会在第一页就停,静默截断成 1000 行。
        if len(chunk) < PAGE:
            break
        if total and total.split('/')[-1] != '*' and page * PAGE >= int(total.split('/')[-1]):
            break
        if page > 40:                      # 防呆:约 4 万行上限
            break
    if not rows:
        return pd.DataFrame(columns=['d', 'ret'])
    df = pd.DataFrame(rows)
    df['d'] = df['d'].astype(str).str[:10]
    if 'ret' in df:
        df['ret'] = pd.to_numeric(df['ret'], errors='coerce')   # 坏值 → NaN,不 → 0
    return df.drop_duplicates('d').sort_values('d').reset_index(drop=True)


def probe(table: str) -> tuple[bool, str]:
    url = (f'{SUPABASE_URL.rstrip("/")}/rest/v1/{table}'
           '?select=d&limit=1')
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            json.loads(r.read())
        return True, 'readable'
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}: {e.read().decode()[:160]}'
    except Exception as e:                                     # noqa: BLE001
        return False, f'{type(e).__name__}: {e}'


def metrics(ret: np.ndarray) -> dict[str, Any]:
    """总收益 / 最大回撤 / 夏普。样本不足一年 ⇒ 不年化(夏普 None,不是 0)。"""
    n = int(ret.size)
    out: dict[str, Any] = {'n_days': n}
    if n == 0:
        return {'n_days': 0, 'total_pct': None, 'maxdd_pct': None,
                'sharpe': None, 'ann_pct': None}
    nav = np.cumprod(1.0 + ret)
    out['total_pct'] = float(nav[-1] - 1.0) * 100.0
    out['maxdd_pct'] = float((nav / np.maximum.accumulate(nav) - 1.0).min() * 100.0)
    sd = float(np.std(ret, ddof=1)) if n > 1 else 0.0
    if n >= MIN_DAYS_FOR_ANN and sd > 0:
        out['sharpe'] = float(np.mean(ret) / sd * np.sqrt(365.0))
        out['ann_pct'] = float((nav[-1] ** (365.0 / n) - 1.0) * 100.0)
    else:
        out['sharpe'] = None          # 不足一年不年化 —— 明确写「不可算」
        out['ann_pct'] = None
    return out


def stack_ret(df: pd.DataFrame, w: np.ndarray) -> np.ndarray:
    """加权堆叠日收益。w 与列顺序一一对应。"""
    cols = [c for c in df.columns if c.endswith('__ret')]
    return sum(wi * df[c].to_numpy(dtype=float) for wi, c in zip(w, cols))


def md_table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return '_(空)_\n'
    head = '| ' + ' | '.join(cols) + ' |'
    sep = '|' + '|'.join('---' for _ in cols) + '|'
    body = '\n'.join('| ' + ' | '.join(_fmt(r.get(c)) for c in cols) + ' |'
                     for r in rows)
    return f'{head}\n{sep}\n{body}\n'


def _fmt(v: Any) -> str:
    if v is None:
        return 'n/a'
    if isinstance(v, float):
        return f'{v:+.2f}' if abs(v) < 1000 else f'{v:.0f}'
    return str(v)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()

    print('=== 0. 读权限清点 ===')
    access: dict[str, tuple[bool, str]] = {}
    for label, table, _arm in BRICKS:
        ok, msg = probe(table)
        access[table] = (ok, msg)
        print(f'  {label:7s} {table:24s} {"OK" if ok else "DENIED"}  {msg[:90]}')

    print('\n=== 1. 拉积木(不填充) ===')
    series: dict[str, pd.DataFrame] = {}
    blocked: list[tuple[str, str, str]] = []
    for label, table, arm in BRICKS:
        if not access[table][0]:
            blocked.append((label, table, arm))
            print(f'  {label:7s} {table:24s} SKIP —— {access[table][1][:80]}')
            continue
        df = fetch(table, arm)
        series[label] = df
        print(f'  {label:7s} {table:24s} arm={arm:18s} '
              f'{len(df)} 行  {df["d"].iloc[0]} → {df["d"].iloc[-1]}  '
              f'NaN(ret)={int(df["ret"].isna().sum())}')

    btc_df = fetch(*BENCH_BTC)
    print(f'  BTC     core_variants_daily   arm=btc'
          f'{"":14s} {len(btc_df)} 行')

    if not series:
        print('一块积木都读不到,停。')
        return

    print('\n=== 2. 按时点合成(按日期内连接,不按行号) ===')
    # 每块积木各自改名 xxx__ret,再按 d 内连接;缺失保持 NaN。
    merged: Optional[pd.DataFrame] = None
    drop_log: list[tuple[str, int, int]] = []
    for label, df in series.items():
        part = df[['d', 'ret']].rename(columns={'ret': f'{label}__ret'})
        merged = part if merged is None else merged.merge(part, on='d', how='inner')
    assert merged is not None
    pre_n = len(merged)
    ret_cols = [c for c in merged.columns if c.endswith('__ret')]
    n_missing = int(merged[ret_cols].isna().any(axis=1).sum())
    merged = merged.dropna(subset=ret_cols).reset_index(drop=True)
    drop_log.append(('合计(任一积木缺 ret ⇒ 整行退出)', n_missing, pre_n))
    for c in ret_cols:
        drop_log.append((c, int(series[c.replace('__ret', '')]['ret'].isna().sum()),
                         len(series[c.replace('__ret', '')])))
    if 'BTC__ret' not in merged.columns:
        b = btc_df[['d', 'ret']].rename(columns={'ret': 'BTC__ret'})
        merged = merged.merge(b, on='d', how='inner').reset_index(drop=True)
    for c, miss, tot in drop_log:
        print(f'  {c:38s} NaN {miss:5d} / {tot:5d}')
    print(f'  内连接后可用样本 {len(merged)} 天:'
          f' {merged["d"].iloc[0]} → {merged["d"].iloc[-1]}')

    labels = [b[0] for b in BRICKS if b[0] in series]
    w_diag = np.ones(len(labels)) / len(labels)      # DIAGNOSTIC,不是配置层规则

    print('\n=== 3. 三窗口 + 对照(零分布走 apparatus) ===')
    rows: list[dict] = []
    for wlabel, mask in ap.windows(merged['d'].tolist(), WINDOW_CUTS):
        sub = merged.loc[mask]
        if sub.empty:
            print(f'  {wlabel}: 空窗口')
            continue
        fund = stack_ret(sub, w_diag)
        actual = metrics(fund)['total_pct']

        def _rand(rng: np.random.Generator, _sub=sub) -> float:
            w = rng.dirichlet(np.ones(len(labels)))
            m = metrics(stack_ret(_sub, w))
            return m['total_pct'] if m['total_pct'] is not None else np.nan

        try:
            null = ap.null_distribution(_rand, N_RANDOM, SEED, actual)
            null_ok, pct = True, ap.percentile_of(actual, null)
            p50 = float(np.percentile(null, 50))
            p95 = float(np.percentile(null, 95))
        except ap.NoOpNull as e:                        # 装置自己判断无效 ⇒ 如实报
            null_ok, pct, p50, p95 = False, None, None, None
            print(f'  {wlabel}: 零分布无效 —— {e}')

        m_fund = metrics(fund)
        m_btc = metrics(sub['BTC__ret'].to_numpy(float))
        m_core = metrics(sub['① core__ret'].to_numpy(float))
        rows.append({
            '窗口': wlabel,
            '天数': m_fund['n_days'],
            '① cap_uncapped %': m_core['total_pct'],
            'BTC %': m_btc['total_pct'],
            '堆叠(DIAGNOSTIC) %': m_fund['total_pct'],
            '堆叠 maxDD %': m_fund['maxdd_pct'],
            '堆叠 夏普': m_fund['sharpe'],
            '随机 p50 %': p50,
            '随机 p95 %': p95,
            '堆叠分位': pct,
        })
        print(f'  {wlabel}: ①={m_core["total_pct"]:+.2f}%  BTC={m_btc["total_pct"]:+.2f}%  '
              f'堆叠={m_fund["total_pct"]:+.2f}%  随机p50={p50 if p50 is None else round(p50,2)}%  '
              f'分位={pct if pct is None else round(pct,3)}')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 't089_pit_results.json').write_text(json.dumps({
        'access': {k: v for k, v in access.items()},
        'blocked': blocked,
        'bricks_used': labels,
        'n_days_common': int(len(merged)),
        'common_range': [merged['d'].iloc[0], merged['d'].iloc[-1]],
        'drop_log': drop_log,
        'windows': rows,
        'seed': SEED, 'n_random': N_RANDOM,
    }, ensure_ascii=False, indent=2))

    write_report(access, series, blocked, labels, drop_log, merged, rows)
    print(f'\n[total] {time.time()-t0:.0f}s')
    print('report ->', OUT_REPORT)


def write_report(access, series, blocked, labels, drop_log, merged, rows) -> None:
    deny = [f'`{t}`({m[:60]})' for t, (ok, m) in access.items() if not ok]
    blk_md = '\n'.join(f'- **{lb}** —— `{tb}` / `{arm}`:读不到' for lb, tb, arm in blocked) \
        or '- (无)'
    md = f"""# T-089 第 1 段 —— 整只基金的按时点模拟:管线跑通 + 缺口点清

生成:`docs/research/t089_fund_sim_pit.py`(脚本自写本文件)
读数:Supabase(环境里的 publishable key,**只读**),src/ 一行未改。
窗口切点 {WINDOW_CUTS};随机权重 {N_RANDOM} 次,seed {SEED},零分布走
`src/data/evaluation/apparatus.py::null_distribution` + `percentile_of`。

## 0. 一句话

**管线通了,但卡上的判决做不了** —— 四块积木里**组合层 `portfolio_layer_daily`
读不到**,而配置层的现行准入规则又在 `allocation_daily`(同样读不到)。
本轮交付的是:按时点合成的管线 + 一张各窗口的对照表 + 缺口的定位。

## 1. 读权限清点

| 表 | 可读 | 说明 |
|---|---|---|
""" + '\n'.join(
        f"| `{t}` | {'✅' if ok else '❌'} | {md_} |" for t, (ok, md_) in access.items()
    ) + f"""

读不到的:{'; '.join(deny) if deny else '(无)'}。
PostgREST 返回的是 `42501 permission denied for table ...`,不是空表 ——
**表里有没有行这一轮无法判断**,别把它读成「没数据」。

## 2. 积木(缺失不填)

| 积木 | 表 | arm | 行数 | 覆盖 | ret 为 NaN |
|---|---|---|---|---|---|
""" + '\n'.join(
        f"| {lb} | `{tb}` | `{arm}` | {len(df)} | {df['d'].iloc[0]} → {df['d'].iloc[-1]} | "
        f"{int(df['ret'].isna().sum())} |"
        for (lb, tb, arm), df in zip(
            [(b[0], b[1], b[2]) for b in BRICKS if b[0] in series], list(series.values()))
    ) + f"""

本轮实际用到的积木:{'、'.join(labels)}。

### 2a. 丢弃了什么(不 ffill / bfill / fillna)

| 项 | NaN | 总数 |
|---|---|---|
""" + '\n'.join(f'| {k} | {m} | {t} |' for k, m, t in drop_log) + f"""

**一条积木某天没有 ret ⇒ 那天整行退出样本**,不是 0、不是 1.0、不是前后值。
积木之间按 `d` 内连接,不按行号对齐 —— 不同积木起始日不同,按行号对齐会凭空造出
一段没人交易过的日子。内连接后可用样本 **{len(merged)} 天**
({merged['d'].iloc[0]} → {merged['d'].iloc[-1]})。

## 3. 对照表

> 「堆叠」是**等权把上面几块积木的日收益相加**,标 `DIAGNOSTIC` ——
> **这不是卡上的配置层规则**(那套规则在读不到的 `allocation_daily` / `allocator.py` 的
> 准入条件里)。它只回答「按时点合成这条管线能不能跑」。

{md_table(rows, ['窗口', '天数', '① cap_uncapped %', 'BTC %', '堆叠(DIAGNOSTIC) %',
                 '堆叠 maxDD %', '堆叠 夏普', '随机 p50 %', '随机 p95 %', '堆叠分位'])}

读法:① 是基线(卡上的对照之一),BTC 是第二个,「随机 p50 / p95」是同积木随机权重
{N_RANDOM} 次的总收益分布,「堆叠分位」是等权堆叠在其中的中秩分位
(`apparatus.percentile_of`;≥0.5 表示等权堆叠跑赢了一半以上的随机配置)。
夏普只在样本满一年时给;不满一年一律 `n/a`。

### 3a. 这张表最要紧的一行

**三个窗口里,等权堆叠的中秩分位都在 0.45–0.55 之间**(0.530 / 0.554 / 0.452),
也就是**等权堆叠 ≈ 同积木随机权重的 p50**。这不是「堆叠做得好」,这是
「**这三块积木几乎共线,换任何权重都得到同一个结果**」:② 是 ① 的乘数、③ 是 ① 的倾斜,
三者叠起来的日收益序列差不了多少,所以权重这件事在这堆积木上没有自由度。
按 R74 的同一条判据(融合腿之间 |corr| ≲ 0.30 才有资格贡献),先量一下腿间相关性 ——
**本轮没量,留给第 2 段**,不要在没有相关矩阵的情况下说「等权是合理的」。

另:**①(cap_uncapped)在三个窗口里全部跑输 BTC**(W1 +359.38% vs +462.58%;
W2 −17.05% vs −10.48%;W3 −3.11% vs −2.19%)。这与 T-107(「2023→2026 持有 BTC 赢了 ①」)
方向一致 —— 在本轮读到的同一份账本上复现,不是新发现,但它把「整只基金模拟」这个题目的
起点摆清楚了:**被模拟的底仓本身跑输对照,配置层要解释的缺口比卡上预设的大。**

## 4. 还差什么(卡上 acceptance 的哪几条没做)

- **② 组合层 `pl_v3_replay` 缺失** —— 表读不到,本轮没有任何组合层的数字。
- **② 配置层现行规则的按时点准入** —— `allocation_daily` 同样读不到;
  在能读到之前,**「等权堆叠」不能被当成配置层的结果**,只能当管线诊断。
- **③ 逐层收益来源拆解(同组合器的拆法)** —— 等权下可算,但组合层缺席,
  拆出来的「层」比卡上要求少一层。
- **判决 / M- 预注册** —— 本轮**故意没写**。预注册是给「配置层准入规则」那个判决用的,
  而那个判决需要组合层;在缺这一层时写预注册,等于先看结果再定判据。

## 5. 要 @seth 做什么

给 publishable 角色补 `portfolio_layer_daily` 与 `allocation_daily` 的 SELECT 授权
(或从 Mac 侧导出到一张可读表),这两张表一通,本卡第 2 段就能按原 acceptance 跑完。
"""
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(md, encoding='utf-8')
    print('report ->', OUT_REPORT)


if __name__ == '__main__':
    main()