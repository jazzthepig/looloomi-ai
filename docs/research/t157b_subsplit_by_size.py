#!/usr/bin/env python3
"""T-157b —— 把 T-157 的 ④ 子档拆解在**别的账户规模**上再跑一遍。

为什么需要:T-157 的主表测到「④ 限额随规模变大而恶化」(868 −6.49 → 100k −9.10 pp/年),
但那张表只有 ④ 一个合并档,看不出**是哪个子开关在规模上翻脸**。卡上的先验是
「小账户整数化 / 最小单」,实测 3k 上 ④c 最小单只有 +0.0047 pp、④b 日换手 0.0000 pp ——
小账户那两个子开关基本是零。要解释 100k 上 −9.10,只能把 4 个子开关在大账户上拆开。

本脚本**不重写任何逻辑**:直接 import t157 的 `run_subsplit`(它本来就是按 account
参数化的),换两个规模跑 —— 868(真钱账户现在的规模)与 100,000。同时跑一个
nav_cap=10×账户 的对照格,验证机制假设。

机制假设(`src/exec_host/core.py:76`):
    cash_eff = cash if not nav_cap else max(0.0, min(cash, nav_cap - held))
`nav_cap` 是**绝对美元**授权上限,而回放里 nav_cap 被设成 `account`(**初始**规模,不是当日 NAV)。
于是只要账户 NAV 涨过初始规模,`nav_cap - held < 0` → `cash_eff = 0` → **执行器永久冻结**
(还能卖,不能买)。如果这条对,100k 上 ④ 的恶化就不该来自 nav_cap(它相对同样触发),
而该来自 max_order_usd=2000 / max_daily_turnover_usd=6000 这两个**绝对**上限在大账户上
变成 2%/6% 的日进度条。本脚本两条一起测。

输出:`/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-157b_x1v_subsplit_by_size.md`
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import t137_x1v_replay as t137      # noqa: E402
import t157_x1v_limits_by_size as T157   # noqa: E402

OUT = Path('/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/'
           'T-157b_x1v_subsplit_by_size.md')
OUT_JSON = Path('/Volumes/CometCloudAI/cometcloud-local/research/t157/t157b_results.json')
# 规模由 CLI 给(11-05 恢复方案:630 / 3,000 / 100,000)。
DEFAULT_SIZES = [630.0, 3_000.0, 100_000.0]


def load_all_subsplits() -> dict[str, dict]:
    """收齐各规模的子拆:t157b_results_*.json 优先,缺的从 T-157 的
    t157_results_*.json['subsplit'] 补(同一份 run_subsplit,数字同源)。"""
    subs: dict[str, dict] = {}
    for f in sorted(OUT_JSON.parent.glob('t157b_results_*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        for k, v in (d.get('sizes') or {}).items():
            subs[str(int(float(k)))] = v
    for f in sorted(OUT_JSON.parent.glob('t157_results_*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        s = d.get('subsplit') or {}
        if s.get('account'):
            subs.setdefault(str(int(float(s['account']))), s)
    return subs


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', default=','.join(str(int(s)) for s in DEFAULT_SIZES),
                    help='账户规模 USDT,逗号分隔')
    ap.add_argument('--tag', default='', help='产物后缀(文件名用)')
    ap.add_argument('--merge', action='store_true',
                    help='把各规模的子拆结果合成一张表(不重跑 replay)')
    args = ap.parse_args()
    out_json = OUT_JSON.with_name(f't157b_results{args.tag}.json')
    out_md = OUT.with_name(f'T-157b_x1v_subsplit_by_size{args.tag}.md')

    t0 = time.time()
    out: dict[str, object] = {'sizes': {}}
    if args.merge:
        out['sizes'] = load_all_subsplits()
        sizes = sorted(float(k) for k in out['sizes'])
        if not sizes:
            raise SystemExit('merge: 没有子拆结果可合并')
        print('=== 合并子拆 ===', flush=True)
        for s in sizes:
            print(f'  {int(s):,} USDT  ④ = {out["sizes"][str(int(s))]["whole_4_pp"]:+.4f} pp',
                  flush=True)
    else:
        sizes = [float(s) for s in args.sizes.split(',')]
        ohlc = t137.fetch_ohlc(t137.SYMS, T157.START, T157.END)
        for size in sizes:
            ts = time.time()
            print(f'=== 子拆 @ {int(size):,} USDT ===', flush=True)
            r = T157.run_subsplit(ohlc, account=size)
            print(f"  ④ 整档 = {r['whole_4_pp']:+.4f} pp | "
                  f"闭环 {r['closure_ok']} | {time.time()-ts:.0f}s", flush=True)
            for row in r['forward_rows'][4:8]:
                print(f"    {row['打开']:<34} {row['delta_pp']:+.4f} pp", flush=True)
            out['sizes'][str(int(size))] = r

    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                        encoding='utf-8')

    # ── markdown ──────────────────────────────────────────────────────────
    idx_f = {'max_order': 4, 'max_daily': 5, 'min_notional': 6, 'nav_cap': 7}
    label = ' / '.join(f'{int(s):,}' for s in sizes)
    cols = ' | '.join(f'{int(s):,} USDT Δpp' for s in sizes)
    md = [f'# T-157b —— ④ 子开关按账户规模拆开({label} USDT)\n',
          '\n生成:`docs/research/t157b_subsplit_by_size.py`(import T-157 的 `run_subsplit`,'
          '不重写逻辑)\n',
          '读数、窗口、成本格与 T-157 完全同源。`src/` 一行未改。\n',
          '\n## 1. 四个子开关 × 账户规模\n',
          f'| 子开关 | {cols} | 随规模? |',
          '|' + '---|' * (len(sizes) + 2)]
    for k in ('max_order', 'max_daily', 'min_notional', 'nav_cap'):
        vals = [out['sizes'][str(int(s))]['forward_rows'][idx_f[k]]['delta_pp']
                for s in sizes]
        swing = max(vals) - min(vals)
        flag = '**是**' if swing > 0.5 else '否'
        md.append(f'| {T157.STEP_CN[k]} | ' +
                  ' | '.join(f'{v:+.4f}' for v in vals) + f' | {flag} |')

    for si, size in enumerate(sizes):
        r = out['sizes'][str(int(size))]
        md.append(f"\n## 2{si}. 账户 {int(size):,} USDT 正序全表\n")
        md.append('| step | 打开 | ann% | delta_pp |')
        md.append('|---|---|---|---|')
        for row in r['forward_rows']:
            md.append(f"| {row['step']} | {row['打开']} | {row['ann%']} | {row['delta_pp']:+.4f} |")
        md.append(f"\n④ 整档 = {r['whole_4_pp']:+.4f} pp;子档累加 = "
                  f"{r['forward_sub_cum_pp']:+.4f} pp(差 {r['forward_diff_pp']:+.4f} pp);"
                  f"反序差 {r['reverse_diff_pp']:+.4f} pp;闭环 {r['closure_ok']}。")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('report ->', out_md)
    print(f'[total] {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()