#!/usr/bin/env python3
"""T-214 — 在引用档案里标注被取代的条目(不改动原始 quotes)。

背景:2026-10-30T03:48Z 抓取的 hl_spot_ctx_px 条目用 zip(universe, ctxs) 按位置配对,
universe 347 条、ctxs 1186 条长度与顺序都不同 => 每个交易对的标签上贴的是另一个交易对的价格。
原始 quotes 保留(它是抓取事实),另加 superseded 字段指向复核轮的��确值。

只读本地文件 + 写同一个 JSON。不发任何网络请求。
"""
import json
import io

P = 'docs/research/t214_cites.json'
CORRECTED_AT = '2026-10-30T04:12:47Z'
REASON = ('抓取脚本按位置 zip(universe, ctxs) 配对;universe 347 条、ctxs 1186 条,长度与顺序都不同 '
          '=> 标签与价格不配对。脚本已修(t214_cites_gap.py 改为按 ctx 的 coin 字段配对)。')

with io.open(P, encoding='utf-8') as f:
    d = json.load(f)

v = d['pages']['hl_spot_ctx_px']
v['superseded'] = {
    'status': 'MIS_PAIRED',
    'reason': REASON,
    'superseded_by': 'docs/research/t214_verify.json',
    'corrected_values': {
        'fetched_at_utc': CORRECTED_AT,
        '@182 XAUT0/USDC': {'midPx': '3990.25', 'dayNtlVlm': '400666.46'},
        '@209 XAUT0/USDT0': {'midPx': '3921.5', 'dayNtlVlm': '0.0'},
        '@279 SPY/USDC': {'midPx': '755.73', 'dayNtlVlm': '0.0'},
        '@703 SPYX/USDC': {'midPx': '767.12', 'dayNtlVlm': '134063.7142'},
    },
}

note = d.get('note', '')
tail = ('hl_spot_ctx_px 条目为 mis-paired 原始记录,已被 t214_verify.json 的正确配对取代'
        '(见该条 superseded 字段);原始 quotes 保留未改。')
if tail not in note:
    d['note'] = (note + ' | ' + tail).strip(' |')

with io.open(P, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=1)

print('annotated hl_spot_ctx_px; pages =', len(d['pages']))
