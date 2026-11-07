#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-288 (S-767): 事件基率表 —— 整币下架 / 永续上线 / 现货上币。

只做整理:数据源仅限已合并的结果文件
  docs/research/t272_results.json (S-751 整币下架)
  docs/research/t279_results.json (S-758 永续上线, 主口径)
  docs/research/t284_results.json (S-763 现货上币)
  docs/research/t285_results.json (S-764 S-758 的盲复算)
  docs/research/t284_events.json   (S-763 逐事件明细, 仅当主文件未落盘所需字段时使用)
不新增检验、不改任何判定、不写库。
"""
import json, math
from pathlib import Path

SRC = Path('/Users/sbb/Projects/looloomi-ai/docs/research')
OUT = Path('/Users/sbb/Projects/looloomi-ai-lane-c/docs/research')

def q(xs, p):
    """线性插值分位(与 numpy 默认 'linear' 一致)。"""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * p
    f, c = int(math.floor(k)), int(math.ceil(k))
    return float(xs[f]) if f == c else float(xs[f] + (xs[c] - xs[f]) * (k - f))

def dist(xs, already_pct=False):
    """把一组超额值转成统一的「百分数」描述统计。"""
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    s = 1.0 if already_pct else 100.0
    neg = sum(1 for x in xs if x < 0)
    return {
        "n": len(xs),
        "median_pct": round(q(xs, 0.5) * s, 3),
        "p10_pct": round(q(xs, 0.10) * s, 3),
        "p25_pct": round(q(xs, 0.25) * s, 3),
        "p75_pct": round(q(xs, 0.75) * s, 3),
        "p90_pct": round(q(xs, 0.90) * s, 3),
        "min_pct": round(min(xs) * s, 3),
        "max_pct": round(max(xs) * s, 3),
        "pct_negative": round(neg / len(xs), 4),
    }

def terciles(rows, strat_key, out_key, already_pct=False, strat_scale=None):
    """按 strat_key 等频三分位分组，报各组 out_key 的中位数。

    already_pct: out_key 已是百分数(则不再乘 100)
    strat_scale : strat_key 换成百分数的乘数(缺省:与 out_key 同单位)
    """
    rows = [r for r in rows if r.get(strat_key) is not None and r.get(out_key) is not None]
    if len(rows) < 3:
        return None
    rows.sort(key=lambda r: r[strat_key])
    n = len(rows)
    cuts = [0, n // 3, (2 * n) // 3, n]
    names = ["低", "中", "高"]
    out = []
    for i in range(3):
        chunk = rows[cuts[i]:cuts[i + 1]]
        if not chunk:
            continue
        sv = [r[strat_key] for r in chunk]
        ov = [r[out_key] for r in chunk]
        s = 1.0 if already_pct else 100.0
        ss = s if strat_scale is None else strat_scale
        out.append({
            "bucket": names[i],
            "n": len(chunk),
            "strat_lo": round(min(sv) * ss, 3),
            "strat_hi": round(max(sv) * ss, 3),
            "strat_unit": "pct",
            "median_exc_pct": round(q(ov, 0.5) * s, 3),
            "pct_negative": round(sum(1 for x in ov if x < 0) / len(ov), 4),
        })
    return out

def in_bucket(m, b):
    lo, hi = b.get('mcap_lo'), b.get('mcap_hi')
    if m is None:
        return False
    if lo is not None and m < lo:
        return False
    if hi is not None and m >= hi:
        return False
    return True

def load(name):
    with open(SRC / name, encoding='utf-8') as f:
        return json.load(f)

checks = []
def check(label, got, want, tol=0.05):
    ok = (got is not None and want is not None and abs(got - want) <= tol)
    checks.append((label, got, want, ok))
    return ok

FAM = {}

# ---------------------------------------------------------------- 整币下架 (T-272 / S-751)
d272 = load('t272_results.json')
mcap_src = d272['sources']['mcap']
per_token = mcap_src['per_token']
dl_rows = []
for tok, rec in per_token.items():
    if rec.get('status') != 'ok':
        continue
    if rec.get('ret30') is None:
        continue
    dl_rows.append({
        "sym": tok,
        "exc30": rec['ret30'],
        "pre30_tok": rec.get('pre30_tok'),
        "pre30_exc": rec.get('pre30'),
    })
dl30 = dist([r['exc30'] for r in dl_rows])
check('T272 delisting exc30 median', dl30['median_pct'], round(mcap_src['median_exc30'] * 100, 3))
check('T272 delisting pct_negative', dl30['pct_negative'], round(mcap_src['pct_negative_exc30'], 4), 1e-3)

dl_mcap_strata = []
for name, b in d272['secondary']['mcap_tertile'].items():
    dl_mcap_strata.append({
        "bucket": {"low": "低", "mid": "中", "high": "高"}[name],
        "n": b['n'],
        "mcap_lo": b.get('mcap_lo'),
        "mcap_hi": b.get('mcap_hi'),
        "median_exc_pct": round(b['median_exc30'] * 100, 3),
    })
FAM['delisting_spot_full'] = {
    "label_zh": "整币下架(现货全币种)",
    "label_en": "Full-coin spot delisting",
    "source": {"card": "T-272", "ledger": "S-751", "file": "docs/research/t272_results.json",
               "price_arm": "mcap(主口径); ohlc 为副臂 n=32 中位 -54.25%"},
    "n": dl30['n'],
    "exc30": dl30,
    "exc90": None,
    "exc90_note": "T-272 结果文件只落盘 30 天口径(ret30)与 7 天/公告日跳空;90 天未落盘,本轮不重算(见 EVENT_BASE_RATES.md 缺口)。",
    "control_random_day": {
        "median_pct": round(mcap_src['control']['null_median_q']['q50'] * 100, 3),
        "p05_pct": round(mcap_src['control']['null_median_q']['q05'] * 100, 3),
        "p95_pct": round(mcap_src['control']['null_median_q']['q95'] * 100, 3),
        "n_draws": mcap_src['control']['n_draws_used'],
        "percentile_of_actual": mcap_src['control']['percentile_of_actual'],
    },
    "strata": {
        "by_pre_event_gain_tercile": terciles(dl_rows, "pre30_tok", "exc30"),
        "by_mcap_tercile": dl_mcap_strata,
    },
    "pre_event_gain_strata_note": "分层变量为公告前 30 天该币自身涨幅(pre30_tok,原始收益,非相对 BTC);市值分层沿用 T-272 自带三分位(mcap)。",
    "extra": {
        "exc7_median_pct": round(d272['secondary']['exc7_median'] * 100, 3),
        "pre30_excess_median_pct": round(d272['secondary']['pre30_exc_median'] * 100, 3),
        "announce_day_jump_median_pct": round(d272['secondary']['announce_day_jump_median'] * 100, 3),
        "perp_delisting_subset": {
            "n_computable": d272['secondary']['perp_delisting']['n_computable'],
            "median_exc30_pct": round(d272['secondary']['perp_delisting']['median_exc30'] * 100, 3),
            "pct_negative": d272['secondary']['perp_delisting']['pct_negative'],
        },
        "segments": {k: {"n": v["n"], "median_exc30_pct": round(v["median"] * 100, 3)}
                     for k, v in mcap_src['segments'].items()},
    },
}

# ---------------------------------------------------------------- 永续上线 (T-279 / S-758)
d279 = load('t279_results.json')
ev = d279['events_detail']
perp_rows = [{"sym": e['sym'], "d": e['d'], "exc30": e['ex30_pct'], "exc60": e['ex60_pct'],
              "pre30": e.get('pre30_ret_pct'), "mcap": e.get('mcap_pre')} for e in ev]
perp30 = dist([r['exc30'] for r in perp_rows], already_pct=True)
perp60 = dist([r['exc60'] for r in perp_rows], already_pct=True)
check('T279 perp exc30 median', perp30['median_pct'], round(d279['main']['entry_on_d']['h30']['median_pct'], 3))
check('T279 perp frac_negative', perp30['pct_negative'], round(d279['main']['entry_on_d']['h30']['frac_negative'], 4), 1e-3)

perp_mcap_strata = []
for b in d279['mcap_tertiles']['entry_on_d']:
    inb = [r for r in perp_rows if in_bucket(r.get('mcap'), b)]
    perp_mcap_strata.append({
        "bucket": b['bucket'], "n": b['n'],
        "mcap_lo": b.get('mcap_lo'), "mcap_hi": b.get('mcap_hi'),
        "median_exc_pct": round(b['median_pct'], 3),
        "pct_negative": round(sum(1 for r in inb if r['exc30'] < 0) / len(inb), 4) if inb else None,
        "_recomputed_n": len(inb),
    })

d285 = load('t285_results.json')
blind = {}
for rk, rv in d285['readings'].items():
    evs = rv.get('events') or []
    d30 = dist([e['ex30'] for e in evs]) if evs else None
    if d30:
        check('T285 %s exc30 median' % rk, d30['median_pct'], round(rv['median_30d'] * 100, 3))
    blind[rk] = {
        "n": rv.get('n'),
        "median_30d_pct": round(rv['median_30d'] * 100, 3),
        "mean_30d_pct": round(rv['mean_30d'] * 100, 3),
        "pct_negative": d30['pct_negative'] if d30 else None,
        "exc30": d30,
        "control_random_day_median_pct": round(rv['null_median'] * 100, 3),
        "control_random_day_p05_pct": round(rv['null_p05'] * 100, 3),
        "percentile_of_actual": rv['percentile'],
        "segments": {k: {"n": v['n'], "median_pct": round(v['median'] * 100, 3)}
                     for k, v in rv.items() if k.startswith('seg_')},
    }

FAM['perp_launch'] = {
    "label_zh": "永续合约上线",
    "label_en": "Perpetual futures launch",
    "source": {"card": "T-279", "ledger": "S-758", "file": "docs/research/t279_results.json",
               "entry_convention": "entry on d(主口径),d+1 为稳健性副本"},
    "n": perp30['n'],
    "exc30": perp30,
    "exc60": perp60,
    "exc90": None,
    "exc90_note": "T-279 只落盘 30/60 天;90 天未落盘,本轮不重算(见 EVENT_BASE_RATES.md 缺口)。",
    "control_random_day": {
        "median_pct": round(d279['null_control']['entry_on_d']['h30']['null_p50_pct'], 3),
        "p05_pct": round(d279['null_control']['entry_on_d']['h30']['null_p05_pct'], 3),
        "n_draws": d279['null_control']['entry_on_d']['h30']['n_null'],
        "percentile_of_actual": d279['null_control']['entry_on_d']['h30']['percentile_of_actual'],
    },
    "strata": {
        "by_pre_event_gain_tercile": terciles(perp_rows, "pre30", "exc30", already_pct=True),
        "by_mcap_tercile": perp_mcap_strata,
    },
    "pre_event_gain_strata_note": "分层变量为公告前 30 天该币自身涨幅(pre30_ret_pct);市值分层沿用 T-279 自带三分位(mcap_pre)。",
    "robustness": {
        "entry_on_d_plus_1_exc30_median_pct": round(d279['main']['entry_on_d_plus_1']['h30']['median_pct'], 3),
        "halves": [{"window": h['window'], "n": h['n'], "median_exc30_pct": round(h['median_pct'], 3)}
                   for h in d279['criteria']['entry_on_d']['halves']],
        "blind_recompute_T285": {
            "card": "T-285", "ledger": "S-764",
            "primary_reading": "B_db_symbols",
            "note": "S-764 是 S-758 的盲复算;主读法 B(db 代号)与合并信息一致(n=143、中位 -20.9%),A/C 为另两种取数口径。",
            "readings": blind,
            "ledger_reference_to_S758": {
                "n": d285['ledger_reference']['n'],
                "median_30d_pct": round(d285['ledger_reference']['median_30d'] * 100, 3),
                "null_p05_pct": round(d285['ledger_reference']['null_p05'] * 100, 3),
                "sub_mcap_terciles_pct": {k: round(v * 100, 3)
                                          for k, v in d285['ledger_reference']['sub_mcap_terciles'].items()},
            },
        },
    },
    "extra": {
        "funding7_vs_ex30_spearman": d279['funding']['entry_on_d']['spearman_funding7_vs_ex30'],
        "n_with_funding": d279['funding']['entry_on_d']['n'],
    },
}

# ---------------------------------------------------------------- 现货上币 (T-284 / S-763)
d284 = load('t284_results.json')
arm = d284['arms']['asset_mcap_daily']
f30 = arm['fwd30']
f90 = arm['fwd90_副']
spot_rows = []
ev284 = load('t284_events.json')
for e in ev284['events']:
    row = dict(e)
    for k in list(row.keys()):
        if k in ('exc30', 'exc60', 'exc90'):
            pass
    spot_rows.append(row)
# 逐事件若含 30/90 天超额与市值/前涨字段则直接算分位;否则用文件里的聚合分位
def pick(row, *names):
    for n in names:
        if row.get(n) is not None:
            return row[n]
    return None

spot_keys = sorted(spot_rows[0].keys()) if spot_rows else []
spot30 = {
    "n": f30['n'],
    "median_pct": round(f30['median_rel_pct'], 3),
    "mean_pct": round(f30['mean_rel_pct'], 3),
    "p25_pct": round(f30['q25_rel_pct'], 3),
    "p75_pct": round(f30['q75_rel_pct'], 3),
    "pct_negative": round(1 - f30['win_rate_rel'], 4),
    "p10_pct": None,
    "p90_pct": None,
    "_source": "t284_results.json arms.asset_mcap_daily.fwd30(相对基准超额)",
}
spot90 = {
    "n": f90['n'],
    "median_pct": round(f90['median_rel_pct'], 3),
    "p25_pct": round(f90['q25_rel_pct'], 3),
    "p75_pct": round(f90['q75_rel_pct'], 3),
    "pct_negative": round(1 - f90['win_rate_rel'], 4),
    "p10_pct": None,
    "p90_pct": None,
    "_source": "t284_results.json arms.asset_mcap_daily.fwd90_副(相对基准超额,副项)",
}
spot30_calc = spot90_calc = None
keys_needed = ('fwd30', 'fwd90', 'exc30', 'exc90', 'rel30', 'rel90', 'mcap', 'mcap_pre', 'pre30')
have = {k: any(r.get(k) is not None for r in spot_rows) for k in keys_needed}
if have.get('fwd30') or have.get('exc30'):
    k30 = 'fwd30' if have.get('fwd30') else 'exc30'
    spot30_calc = dist([pick(r, k30) for r in spot_rows], already_pct=True)
    check('T284 spot exc30 median', spot30_calc['median_pct'], round(f30['median_rel_pct'], 3), 1.0)
    if have.get('fwd90') or have.get('exc90'):
        k90 = 'fwd90' if have.get('fwd90') else 'exc90'
        spot90_calc = dist([pick(r, k90) for r in spot_rows], already_pct=True)
        check('T284 spot exc90 median', spot90_calc['median_pct'], round(f90['median_rel_pct'], 3), 1.0)

FAM['spot_listing'] = {
    "label_zh": "现货上币",
    "label_en": "Spot listing",
    "source": {"card": "T-284", "ledger": "S-763", "file": "docs/research/t284_results.json",
               "arm": "asset_mcap_daily(主臂);另两臂 coingecko_pro_ohlc / binance_hist 结果同文件",
               "event_universe": "kept_events=%d(events 行 %d,去掉 90 天内重复与无代号)" %
                                  (d284['meta']['event_counts']['kept_events'],
                                   d284['meta']['event_counts']['events_rows_total'])},
    "n": spot30['n'],
    "exc30": spot30_calc or spot30,
    "exc90": spot90_calc or spot90,
    "control_random_day": {
        "median_pct": round(f30['control_median_pct'], 3),
        "p05_pct": round(f30['control_p05_pct'], 3),
        "n_draws": f30['control_n'],
        "percentile_of_actual": f30['control_percentile'],
    },
    "strata": {
        "by_pre_event_gain_tercile": None,
        "by_mcap_tercile": None,
    },
    "pre_event_gain_strata_note": "T-284 落盘的是聚合量(pre30_副:中位 +41.0%,胜率 74.8%)与分市值时代的 fwd30/fwd90;逐事件字段仅落盘代号与日期,未落盘前涨幅/市值,故两张分层表本轮无法从结果文件复算。",
    "extra": {
        "pre30_median_pct": round(arm['pre30_副']['median_pct'], 3),
        "pre30_win_rate": arm['pre30_副']['win_rate'],
        "pre30_n": arm['pre30_副']['n'],
        "fwd30_median_abs_pct": round(f30['median_abs_pct'], 3),
        "fwd90_median_abs_pct": round(f90['median_abs_pct'], 3),
        "gap_vs_proxy_events": {k: (round(v, 4) if isinstance(v, float) else v)
                                for k, v in d284['gap_vs_proxy'].items() if k in ('n', 'median_days', 'pct_negative', 'pct_gt_30')},
    },
}

# ---------------------------------------------------------------- 汇总
def g(fam, path, default=None):
    cur = FAM[fam]
    for p in path:
        if cur is None:
            return default
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur if cur is not None else default

out = {
    "task": "T-288",
    "ledger": "S-767",
    "title_zh": "事件基率表:整币下架 / 永续上线 / 现货上币",
    "title_en": "Event base rates: full-coin delisting / perp launch / spot listing",
    "kind": "只报不判(report-only)的整理表;不新增检验、不改任何既有判定、不入库。",
    "generated_from": [
        "docs/research/t272_results.json (T-272 / S-751)",
        "docs/research/t279_results.json (T-279 / S-758)",
        "docs/research/t284_results.json (T-284 / S-763)",
        "docs/research/t285_results.json (T-285 / S-764)",
    ],
    "conventions": {
        "excess_return": "相对基准(现货上币族为 T-284 口径的相对基准;下架族为相对 BTC;永续族为 T-279 自身基准)超额,单位为百分数。",
        "quantile_method": "线性插值分位(numpy 'linear' 默认法)。",
        "control_random_day": "同一标的随机起点 d 的随机日对照,报其中位数与 5 分位。",
        "n_definitions": "n = 有价可算超额的事件/代币数,各族口径不同,已在各条 source 里写明。",
    },
    "families": FAM,
    "gaps": [
        "整币下架族与永续上线族的 90 天超额未在已合并结果文件里落盘(T-272 只到 30 天;T-279 只到 30/60 天);本轮按「不新增检验」原则留空,下一轮可按各自脚本口径重算。",
        "现货上币族的两张分层表无法从已合并结果文件复算(T-284 只落盘聚合量与代号/日期,未落盘逐事件前涨幅与市值)。",
    ],
    "self_check": [{"label": a, "recomputed": b, "from_file": c, "ok": ok} for a, b, c, ok in checks],
}
(OUT / 'event_base_rates.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
print("checks:", sum(1 for c in checks if c[3]), "/", len(checks))
for a, b, c, ok in checks:
    print("  ", "OK " if ok else "MISMATCH", a, b, c)
print("spot per-event keys:", spot_keys)
print("wrote event_base_rates.json")
