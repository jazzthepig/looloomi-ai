#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-204 / S-689 独立复算 —— OI/市值在**面板外**名字上、**控制规模**后的截面 IC

严格照 REFUTATION_LEDGER.md 的 **S-689**(2026-10-26 13:41 UTC 预注册)一字不改实现。
C 道独立复算(T-204):交付前不读 docs/research/s689_*。

用法:
    python3 t204_oi_mcap_outofpanel.py --mode selftest   # 统计机器自检(合成数据,已知答案)
    python3 t204_oi_mcap_outofpanel.py --mode gate       # 只查开工条件
    python3 t204_oi_mcap_outofpanel.py --mode panel      # 只跑面板对照(台账明写的"附带(不判)")
    python3 t204_oi_mcap_outofpanel.py --mode names      # 干跑:只走名字层,不算任何统计量
    python3 t204_oi_mcap_outofpanel.py --mode pregate    # 闸门未开时的诊断(10-28 兜底路径,不是交付物)
    python3 t204_oi_mcap_outofpanel.py --mode full       # 闸门通过后跑全量 + 对照,写 t204_results.json

开工条件(卡上写死):`perp_cg_map` 里没有 verdict='pending' 的行,或已过 2026-10-28 00:00 UTC。
不满足 ⇒ `--mode full` 拒绝输出主统计量(退出码 3)。
`--mode panel` 不受闸门约束:面板 25 名与补数无关,且台账明写它是"附带(不判)"的对照。

数据源(只读,publishable key):
    deriv_metrics_daily   Binance Vision,USDT 本位 —— oi_close / oi_value_close
    asset_mcap_daily      source = coingecko_pro_market_chart —— price / mcap(按 symbol)
    cg_coin_mcap_daily    source = coingecko_pro_market_chart —— price / mcap(按 coin_id)
    perp_cg_map           symbol → coin_id 的映射与价格校验结果
"""

import argparse
import datetime as dt
import json
import math
import os
import random
import statistics
import sys
import urllib.parse
import urllib.request

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    print("缺少 SUPABASE_URL / SUPABASE_KEY,退出", file=sys.stderr)
    sys.exit(2)

HDRS = {"apikey": KEY, "Authorization": "Bearer " + KEY}
PAGE = 1000  # PostgREST 服务端硬上限:limit 再大也只回 1000 行(实测 2026-10-26)

# ── 协议常量(全部来自 S-689 / T-204 卡,不许改) ───────────────────────────
PANEL = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE",
         "INJ", "LDO", "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL",
         "STRK", "SUI", "TIA", "UNI", "XRP"]
START = "2023-01-01"
HOLD_DAYS = 30
MCAP_FLOOR = 20_000_000.0
MIN_OVERLAP = 30
MAX_MED_ERR = 0.05
MIN_NAMES_PER_DAY = 30
# 面板对照(附带,不判):台账没写这一档的门槛 —— 面板只有 25 名,永远到不了 30,
# 故沿用 S-688 面板自己的门槛"≥ 8 个名字"。见报告「协议问题」。
PANEL_MIN_NAMES = 8
HALF_CUT_MONTH = "2024-07"
BTC_COIN_ID = "bitcoin"
GATE_DEADLINE = "2026-10-28T00:00:00+00:00"

# ── 敏感性(不改协议;主统计量照台账一字不改,另算一档并标注) ──────────────
# 面板里换过 ticker 的资产:永续宇宙的旧代号 ↔ 面板里的新代号。
# MKR(MakerDAO 旧代号,CG coin 'maker')与面板里的 SKY(CG coin 'sky')是同一个项目:
# CG 两个 coin 的日线在 2024-09-23 起并行(761 天重叠),改币后价格按固定比例换算。
# 永续 MKR 的隐含价与 CG 'maker' 逐位吻合(2026-10-26 实测 median|err| ≈ 0.001)——
# 价格校验认的是**同一个 token**,抓不到「同一项目被看过」这件事。
# ⇒ 主统计量按台账保留 MKR(不改预注册),另算一档「剔 MKR」的敏感性。
# (MATIC↔POL 已核:MATIC 在 deriv_metrics_daily 里 0 行 ⇒ 不进宇宙,无同类问题。)
ALIAS_PAIRS = [("MKR", "SKY")]
SENSITIVITY_EXCLUDE = ["MKR"]


def log(*a):
    print(*a, file=sys.stderr)


# ── Supabase 读取(翻页一律带 order=) ─────────────────────────────────────
def _get(path, params):
    u = URL + "/rest/v1/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(u, headers=HDRS)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode()), resp.headers.get("Content-Range")


def fetch(table, where, order, cols="*"):
    """分页读全表。where: dict;order: 'col.asc,col2.asc'(必须带,否则翻页边界会漂)。
    服务端每次最多回 PAGE 行 ⇒ 按 Content-Range 的总数翻。"""
    out, off = [], 0
    while True:
        p = {"select": cols, "order": order, "limit": PAGE, "offset": off}
        p.update(where)
        rows, cr = _get(table, p)
        if not rows:
            break
        out.extend(rows)
        off += len(rows)
        total = None
        if cr and "/" in cr:
            tail = cr.rsplit("/", 1)[1]
            if tail.isdigit():
                total = int(tail)
        if total is not None and off >= total:
            break
        if len(rows) < PAGE:
            break
    return out


# ── 统计:平均名次 + Spearman + 偏 Spearman ──────────────────────────────
def avg_rank(xs):
    """平均名次(1 起,并列取平均)。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def partial_spearman(ry, rs, ys):
    """偏 Spearman ρ(y | s) = (ρ_ry − ρ_rs·ρ_ys) / √((1−ρ_rs²)(1−ρ_ys²))。"""
    den = (1 - rs * rs) * (1 - ys * ys)
    if den <= 0:
        return None
    return (ry - rs * ys) / math.sqrt(den)


def monthly(values_by_day):
    """日值 → 自然月均值 + 每月有效天数 + 月份序列。"""
    bym = {}
    for d, v in values_by_day.items():
        bym.setdefault(d[:7], []).append(v)
    months = sorted(bym)
    return ({m: sum(bym[m]) / len(bym[m]) for m in months},
            {m: len(bym[m]) for m in months}, months)


def month_t(mvals, months):
    """t = 月均 / 月标准差 × √月数(ddof=1)。"""
    xs = [mvals[m] for m in months]
    n = len(xs)
    if n < 2:
        return None
    sd = statistics.stdev(xs)
    if sd == 0:
        return None
    return (sum(xs) / n) / sd * math.sqrt(n)


# ── 名字层:价格校验 + 行构造 ────────────────────────────────────────────
def mult_for(symbol):
    """1000 前缀倍数 1000(台账原文)。"""
    return 1000.0 if symbol.startswith("1000") else 1.0


def price_check(symbol, deriv, cg_price, mult=1.0):
    """映射校验:隐含价 = oi_value_close / oi_close;
    median |CG价×倍数/隐含价 − 1|;≥ 30 个重叠日且 ≤ 0.05 才留。
    mult = 该名字**所用价格源**的倍数(台账 px 两分支不同:
      asset_mcap_daily 分支 mult = 1;cg_coin_mcap_daily 分支 mult = perp_cg_map.mult)。
    返回 (ok, n_overlap, med_err, reason)。"""
    errs = []
    for d, (oi_c, oi_v) in deriv.items():
        p = cg_price.get(d)
        if p is None or p <= 0 or oi_c is None or oi_v is None or oi_c <= 0:
            continue
        implied = oi_v / oi_c
        if implied <= 0:
            continue
        errs.append(abs(p * mult / implied - 1.0))
    n = len(errs)
    if n < MIN_OVERLAP:
        return False, n, None, "重叠日 %d < %d" % (n, MIN_OVERLAP)
    med = statistics.median(errs)
    if med > MAX_MED_ERR:
        return False, n, med, "median 相对误差 %.4f > %.2f" % (med, MAX_MED_ERR)
    return True, n, med, None


def build_rows(symbol, deriv, cg):
    """行:(symbol, d)。d ≥ 2023-01-01、d 与 d+30 的 CG 价都在、CG 市值 ≥ 2000 万、OI 值 > 0。"""
    rows = []
    for d in sorted(deriv):
        if d < START:
            continue
        d2 = (dt.date.fromisoformat(d) + dt.timedelta(days=HOLD_DAYS)).isoformat()
        e, e2 = cg.get(d), cg.get(d2)
        if e is None or e2 is None:
            continue
        p1, mc1 = e
        p2 = e2[0]
        if p1 is None or p2 is None or p1 <= 0 or p2 <= 0:
            continue
        if mc1 is None or mc1 < MCAP_FLOOR:
            continue
        oi_c, oi_v = deriv[d]
        if oi_v is None or oi_v <= 0:
            continue
        rows.append((d, p1, p2, mc1, oi_v))
    return rows


# ── 截面统计 ────────────────────────────────────────────────────────────
def cross_section(per_name, btc, min_names=MIN_NAMES_PER_DAY, mults=None, r_mode="as_is"):
    """per_name: {symbol: rows}。mults: {symbol: mult}(价格源的倍数)。
    r_mode='as_is'   ⇒ 台账口径:r = oi_value_close / mcap(mcap 是「1 枚币」的市值);
    r_mode='nominal' ⇒ 名义市值口径:r = oi_value_close / (mcap × mult)
                        (1000 前缀名字的持仓名义市值是 1000 枚币,台账口径下 r 被放大 1000 倍)。
    返回 {d: {main, raw, size, n}}。"""
    mults = mults or {}
    by_day = {}
    for sym, rows in per_name.items():
        m = float(mults.get(sym, 1.0))
        for (d, p1, p2, mc1, oi_v) in rows:
            bp1 = btc.get(d)
            bp2 = btc.get((dt.date.fromisoformat(d) + dt.timedelta(days=HOLD_DAYS)).isoformat())
            if bp1 is None or bp2 is None or bp1 <= 0:
                continue
            out = (p2 / p1 - 1.0) - (bp2 / bp1 - 1.0)
            den = (mc1 * m) if r_mode == "nominal" else mc1
            by_day.setdefault(d, []).append((oi_v / den, out, math.log(mc1)))
    res = {}
    for d, vals in by_day.items():
        if len(vals) < min_names:
            continue
        rs = [v[0] for v in vals]
        ro = [v[1] for v in vals]
        sz = [v[2] for v in vals]
        ry = pearson(avg_rank(rs), avg_rank(ro))
        rr = pearson(avg_rank(rs), avg_rank(sz))
        ys = pearson(avg_rank(sz), avg_rank(ro))
        if ry is None or rr is None or ys is None:
            continue
        p = partial_spearman(ry, rr, ys)
        if p is None:
            continue
        res[d] = {"main": p, "raw": ry, "size": ys, "n": len(vals)}
    return res


def summarize(daily):
    """日值 → 逐月值、月数、月 t、两半(2024-07-01 切)。"""
    out = {}
    for key in ("main", "raw", "size"):
        vals = {d: v[key] for d, v in daily.items()}
        mvals, mdays, months = monthly(vals)
        halves = {}
        for tag, sel in (("h1", [m for m in months if m < HALF_CUT_MONTH]),
                         ("h2", [m for m in months if m >= HALF_CUT_MONTH])):
            hm = [mvals[m] for m in sel]
            halves[tag] = {
                "n_months": len(sel),
                "months": sel,
                "monthly": {m: round(mvals[m], 6) for m in sel},
                "month_mean": (sum(hm) / len(hm)) if hm else None,
                "month_t": month_t(mvals, sel),
                "n_days": sum(mdays[m] for m in sel),
            }
        out[key] = {
            "n_days": len(vals),
            "n_months": len(months),
            "monthly": {m: round(mvals[m], 6) for m in months},
            "month_days": mdays,
            "month_mean": (sum(mvals.values()) / len(months)) if months else None,
            "month_t": month_t(mvals, months),
            "halves": halves,
        }
    return out


# ── 取数 ────────────────────────────────────────────────────────────────
def load_deriv(symbols=None):
    where = {"d": "gte." + START}
    if symbols is not None:
        where["symbol"] = "in.(" + ",".join(sorted(symbols)) + ")"
    rows = fetch("deriv_metrics_daily", where, "symbol.asc,d.asc",
                 "symbol,d,oi_close,oi_value_close")
    out = {}
    for r in rows:
        out.setdefault(r["symbol"], {})[r["d"]] = (r["oi_close"], r["oi_value_close"])
    return out


def load_cg_by_symbol(symbols):
    """asset_mcap_daily(source=coingecko_pro_market_chart) 按 symbol 取 price/mcap。"""
    out, multi = {}, {}
    for s in symbols:
        rows = fetch("asset_mcap_daily",
                     {"symbol": "eq." + s, "source": "eq.coingecko_pro_market_chart"},
                     "symbol.asc,d.asc", "coin_id,d,price,mcap")
        by_coin = {}
        for r in rows:
            by_coin.setdefault(r["coin_id"], {})[r["d"]] = (r["price"], r["mcap"])
        if not by_coin:
            continue
        if len(by_coin) > 1:
            multi[s] = sorted(by_coin.keys())
        # 台账未写"一个 symbol 多个 coin_id"怎么取 ⇒ 取行数最多的那个(确定性规则)
        out[s] = max(by_coin.items(), key=lambda kv: (len(kv[1]), kv[0]))[1]
    return out, multi


def load_cg_by_coin(coin_ids):
    out = {}
    for c in coin_ids:
        rows = fetch("cg_coin_mcap_daily", {"coin_id": "eq." + c},
                     "coin_id.asc,d.asc", "d,price,mcap")
        out[c] = {r["d"]: (r["price"], r["mcap"]) for r in rows}
    return out


def load_btc():
    rows = fetch("asset_mcap_daily",
                 {"coin_id": "eq." + BTC_COIN_ID, "source": "eq.coingecko_pro_market_chart"},
                 "coin_id.asc,d.asc", "d,price")
    return {r["d"]: r["price"] for r in rows if r["price"] is not None}


def build_set(symbols, deriv_all, cg_sym, cg_coin, resolved):
    """价格校验 + 行构造。返回 (kept, dropped)。
    mult 按台账 px 的两个分支分别取:asset_mcap_daily 分支 = 1;
    cg_coin_mcap_daily 分支 = perp_cg_map.mult(台账 px 第二分支的 p.mult)。"""
    kept, dropped = {}, []
    for s in symbols:
        d = deriv_all.get(s, {})
        cg, src, mult = cg_sym.get(s), "asset_mcap_daily", 1.0
        if cg is None and s in resolved:
            cg = cg_coin.get(resolved[s]["coin_id"])
            src = "cg_coin_mcap_daily"
            rm = resolved[s].get("mult")
            mult = float(rm) if rm else mult_for(s)
        if not cg:
            dropped.append({"symbol": s, "n_overlap": 0, "med_err": None, "src": None,
                            "reason": "无 CG 价源(asset_mcap_daily 无此 symbol;perp_cg_map 未 resolved)"})
            continue
        ok, n_ov, med, why = price_check(s, d, {k: v[0] for k, v in cg.items()}, mult)
        if not ok:
            dropped.append({"symbol": s, "n_overlap": n_ov, "med_err": med, "src": src, "reason": why})
            continue
        rows = build_rows(s, d, cg)
        if not rows:
            dropped.append({"symbol": s, "n_overlap": n_ov, "med_err": med, "src": src,
                            "reason": "价格校验通过但无可用行(mcap≥2e7 / OI>0 / d+30 有价)"})
            continue
        kept[s] = {"rows": rows, "src": src, "mult": mult, "n_overlap": n_ov, "med_err": med,
                   "n_rows": len(rows),
                   # 诊断(不改协议):mcap/price = 隐含流通量;若某名字的单位错/量纲错,这里会炸
                   "supply_med": statistics.median([r[3] / r[1] for r in rows if r[1] > 0])}
    return kept, dropped


# ── 敏感性(不改协议;主统计量照台账一字不改,另算一档并标注) ──────────────
def sensitivity_block(kept, btc):
    """剔掉面板里换过 ticker 的旧代号后重算一遍(标注清楚:这不是预注册统计量)。"""
    sens_kept = {k: v for k, v in kept.items() if k not in SENSITIVITY_EXCLUDE}
    if len(sens_kept) == len(kept):
        return {}
    s_daily = cross_section({k: v["rows"] for k, v in sens_kept.items()}, btc)
    return {
        "note": "敏感性(不是预注册统计量):剔掉面板里换过 ticker 的旧代号 "
                + ",".join(SENSITIVITY_EXCLUDE) + ";主统计量仍按台账保留它们",
        "excluded": SENSITIVITY_EXCLUDE,
        "n_kept": len(sens_kept),
        "rows_total": sum(len(v["rows"]) for v in sens_kept.values()),
        "n_cross_section_days": len(s_daily),
        "stats": summarize(s_daily),
    }


# ── 别名证据(诊断,不改协议) ───────────────────────────────────────────
def dimension_block(kept, btc):
    """量纲敏感性(不是预注册统计量):台账口径 r = oi_value/mcap 里,1000 前缀名字的
    市值来自 cg_coin_mcap_daily(是「1 枚币」的市值),而持仓名义价值是 1000 枚币的
    ⇒ 台账口径下这批名字的 r 比同口径大 mult 倍,秩被推到一端(见报告 §8 协议问题)。
    两档:
      nominal_mcap:r = oi_value/(mcap×mult)(名义市值口径);
      exclude_1000:台账口径,但剔除 1000 前缀名字。
    主统计量一律照台账一字不改。"""
    mults = dict((k, v.get("mult", 1.0)) for k, v in kept.items())
    out = {}
    nm = cross_section(dict((k, v["rows"]) for k, v in kept.items()), btc,
                       mults=mults, r_mode="nominal")
    out["nominal_mcap"] = {
        "note": "敏感性(不是预注册统计量):r = oi_value_close/(mcap×mult)(名义市值口径);"
                "主统计量仍照台账一字不改",
        "n_kept": len(kept),
        "rows_total": sum(len(v["rows"]) for v in kept.values()),
        "n_cross_section_days": len(nm),
        "stats": summarize(nm),
    }
    names_1000 = sorted(k for k in kept if k.startswith("1000"))
    sub = dict((k, v) for k, v in kept.items() if not k.startswith("1000"))
    if names_1000 and len(sub) != len(kept):
        sd = cross_section(dict((k, v["rows"]) for k, v in sub.items()), btc)
        out["exclude_1000"] = {
            "note": "敏感性(不是预注册统计量):台账口径,但剔除 1000 前缀名字 "
                    + ",".join(names_1000),
            "excluded": names_1000,
            "n_kept": len(sub),
            "rows_total": sum(len(v["rows"]) for v in sub.values()),
            "n_cross_section_days": len(sd),
            "stats": summarize(sd),
        }
    return out


def alias_evidence(deriv_all, cg_sym, panel_syms):
    """面板里换过 ticker 的资产:用数据复核「永续旧代号 ↔ 面板新代号」是不是同一个项目。

    证据链:
      ① 永续旧代号的隐含价 vs CG(旧代号 coin)逐位吻合 ⇒ 永续认的就是这个 token;
      ② 两个 CG coin 的日线在同一段时间并行 ⇒ 同一个项目(改币/改名);
      ③ 两个 CG coin 的价格比在重叠段近似常数 ⇒ 换算比例固定(同一底层资产)。
    """
    out = []
    for uni, pan in ALIAS_PAIRS:
        e = {"universe_symbol": uni, "panel_symbol": pan}
        d = deriv_all.get(uni, {})
        e["deriv_rows"] = len(d)
        e["deriv_days"] = [min(d), max(d)] if d else None
        for tag, sym in (("universe_cg", uni), ("panel_cg", pan)):
            rows = fetch("asset_mcap_daily",
                         {"symbol": "eq." + sym, "source": "eq.coingecko_pro_market_chart"},
                         "symbol.asc,d.asc", "coin_id,d,price")
            ds = sorted(r["d"] for r in rows)
            e[tag] = {"n_rows": len(rows), "coin_ids": sorted({r["coin_id"] for r in rows}),
                      "first": ds[0] if ds else None, "last": ds[-1] if ds else None,
                      "series": {r["d"]: r["price"] for r in rows if r.get("price")}}
        u, p = e["universe_cg"]["series"], e["panel_cg"]["series"]
        common = sorted(set(u) & set(p))
        e["cg_overlap_days"] = len(common)
        e["cg_overlap_window"] = [common[0], common[-1]] if common else None
        if common:
            rat = [p[d] / u[d] for d in common if u[d] > 0]
            rat_s = sorted(rat)
            e["cg_ratio_median"] = rat_s[len(rat_s) // 2]
            e["cg_ratio_min"] = rat_s[0]
            e["cg_ratio_max"] = rat_s[-1]
        # ① 隐含价 vs CG(永续旧代号的 coin)
        errs = []
        for day, (oi_c, oi_v) in d.items():
            if not oi_c or not oi_v or oi_c <= 0:
                continue
            pr = u.get(day)
            if not pr or pr <= 0:
                continue
            errs.append(abs(pr / (oi_v / oi_c) - 1.0))
        e["perp_vs_cg_overlap_days"] = len(errs)
        e["perp_vs_cg_median_rel_err"] = statistics.median(errs) if errs else None
        e["verdict"] = ("same_project_alias" if e["cg_overlap_days"] > 0 else "no_cg_overlap")
        out.append(e)
    return out


# ── 自检(合成数据,已知答案) ───────────────────────────────────────────
def selftest():
    rng = random.Random(20261026)
    ok = True

    # ① r 与 out 都由 size 驱动 ⇒ 原始 ρ 大、偏相关 ≈ 0
    days = 60
    names = 60
    daily = {}
    for di in range(days):
        vals = []
        for ni in range(names):
            size = rng.gauss(10, 1)
            r = 0.6 * size + rng.gauss(0, 0.5)
            out = 0.9 * size + rng.gauss(0, 0.5)
            vals.append((r, out, size))
        rs = [v[0] for v in vals]
        ro = [v[1] for v in vals]
        sz = [v[2] for v in vals]
        ry = pearson(avg_rank(rs), avg_rank(ro))
        rr = pearson(avg_rank(rs), avg_rank(sz))
        ys = pearson(avg_rank(sz), avg_rank(ro))
        daily[di] = {"main": partial_spearman(ry, rr, ys), "raw": ry, "size": ys, "n": names}
    raw_mean = sum(d["raw"] for d in daily.values()) / days
    par_mean = sum(d["main"] for d in daily.values()) / days
    print("① size 驱动 ⇒ raw ρ 均值 %.4f (应显著 >0);偏相关均值 %.4f (应 ≈0)" % (raw_mean, par_mean))
    ok &= (raw_mean > 0.5) and (abs(par_mean) < 0.05)

    # ② out 直接由 r 驱动、size 独立 ⇒ 偏相关 ≈ 原始 ρ
    daily2 = {}
    for di in range(days):
        vals = []
        for ni in range(names):
            size = rng.gauss(10, 1)
            r = rng.gauss(0, 1)
            out = 1.2 * r + rng.gauss(0, 0.4)
            vals.append((r, out, size))
        rs = [v[0] for v in vals]
        ro = [v[1] for v in vals]
        sz = [v[2] for v in vals]
        ry = pearson(avg_rank(rs), avg_rank(ro))
        rr = pearson(avg_rank(rs), avg_rank(sz))
        ys = pearson(avg_rank(sz), avg_rank(ro))
        daily2[di] = {"main": partial_spearman(ry, rr, ys), "raw": ry, "size": ys, "n": names}
    raw2 = sum(d["raw"] for d in daily.values() and daily2.values()) / days
    par2 = sum(d["main"] for d in daily2.values()) / days
    print("② r 驱动 out ⇒ raw ρ 均值 %.4f ;偏相关均值 %.4f (两者应接近)" % (raw2, par2))
    ok &= abs(raw2 - par2) < 0.08

    # ③ 逐月 t 的方向与量级
    print("③ 月 t 走一遍:", end=" ")
    dd = {}
    for i in range(400):
        d = (dt.date(2023, 1, 1) + dt.timedelta(days=i)).isoformat()
        dd[d] = {"main": -0.05 + rng.gauss(0, 0.02), "raw": -0.05 + rng.gauss(0, 0.02),
                 "size": 0.0, "n": 60}
    su = summarize(dd)
    t = su["main"]["month_t"]
    print("月均 %.4f 月 t %.3f (应显著为负)" % (su["main"]["month_mean"], t))
    ok &= (su["main"]["month_mean"] < 0) and (t < -2.0)
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ── 主流程 ──────────────────────────────────────────────────────────────
def run(mode):
    now = dt.datetime.now(dt.timezone.utc)
    log("[gate] now(UTC) =", now.isoformat())

    pm = fetch("perp_cg_map", {}, "symbol.asc", "symbol,coin_id,verdict,mult,med_err,n_overlap")
    pending = [r["symbol"] for r in pm if (r.get("verdict") or "") == "pending"]
    deadline = dt.datetime.fromisoformat(GATE_DEADLINE)
    gate_ok = (len(pending) == 0) or (now >= deadline)
    log("[gate] perp_cg_map rows=%d pending=%d deadline=%s gate_ok=%s"
        % (len(pm), len(pending), GATE_DEADLINE, gate_ok))

    if mode == "gate":
        print(json.dumps({"now_utc": now.isoformat(), "perp_cg_map_rows": len(pm),
                          "pending": pending, "gate_ok": gate_ok,
                          "gate_rule": "no pending rows OR now >= 2026-10-28T00:00:00Z"},
                         ensure_ascii=False, indent=2))
        return 0 if gate_ok else 3

    btc = load_btc()
    log("[data] BTC(coin_id=%s) days=%d" % (BTC_COIN_ID, len(btc)))

    # ── 面板对照(台账:附带(不判);BTC 是基准,不入对照) ────────────────
    panel_syms = [s for s in PANEL if s != "BTC"]
    pderiv = load_deriv(panel_syms)
    pcg, pmulti = load_cg_by_symbol(panel_syms)
    pkept, pdropped = build_set(panel_syms, pderiv, pcg, {}, {})
    pdaily = cross_section({k: v["rows"] for k, v in pkept.items()}, btc, PANEL_MIN_NAMES)
    psumm = summarize(pdaily)
    log("[data] panel kept=%d dropped=%d 截面日=%d (门槛 ≥%d 名)"
        % (len(pkept), len(pdropped), len(pdaily), PANEL_MIN_NAMES))
    for x in pdropped:
        log("   panel drop %-10s %s" % (x["symbol"], x["reason"]))

    res = {
        "task": "T-204",
        "prereg": "S-689 (REFUTATION_LEDGER.md, 2026-10-26 13:41 UTC)",
        "run_utc": now.isoformat(),
        "gate": {"perp_cg_map_rows": len(pm), "pending": pending, "deadline": GATE_DEADLINE,
                 "gate_ok": gate_ok},
        "panel_control": {
            "note": "附带(不判):S-688 面板 25 名去掉 BTC(基准)后的同样偏相关;名字门槛用 S-688 面板的 ≥8(台账未写这一档)",
            "names_kept": sorted(pkept.keys()),
            "names_dropped": sorted(pdropped, key=lambda x: x["symbol"]),
            "rows_total": sum(len(v["rows"]) for v in pkept.values()),
            "per_name_rows": {k: v["n_rows"] for k, v in sorted(pkept.items())},
            "symbol_multi_coinid": pmulti,
            "stats": psumm,
        },
    }

    if mode == "panel":
        res["status"] = "incomplete_gate_not_met"
        res["out_of_panel"] = {
            "status": "skipped_gate_not_met",
            "reason": "闸门未满足(perp_cg_map 仍有 verdict=pending 的行);按卡「不满足就直接停」不落面板外主统计量",
        }
        return res

    if not gate_ok and mode == "full":
        log("[gate] 开工条件未满足 ⇒ 拒绝输出面板外主统计量。")
        res["status"] = "incomplete_gate_not_met"
        res["out_of_panel"] = {"status": "skipped_gate_not_met"}
        return res

    # ── 面板外全量 ────────────────────────────────────────────────────
    deriv_all = load_deriv()
    symbols = sorted(deriv_all)
    panel_set = set(PANEL)
    universe = [s for s in symbols if s not in panel_set]
    log("[data] deriv symbols since %s: %d (panel 剔除 %d ⇒ 面板外 %d)"
        % (START, len(symbols), len(symbols) - len(universe), len(universe)))

    cg_sym, multi = load_cg_by_symbol(universe)
    missing = [s for s in universe if s not in cg_sym]
    log("[data] CG via asset_mcap_daily(symbol): %d ; missing: %d" % (len(cg_sym), len(missing)))

    resolved = {r["symbol"]: r for r in pm if (r.get("verdict") or "") == "resolved"}
    need_coin = [s for s in missing if s in resolved]
    cg_coin = load_cg_by_coin(sorted({resolved[s]["coin_id"] for s in need_coin}))
    log("[data] CG via cg_coin_mcap_daily(perp_cg_map resolved): %d" % len(need_coin))

    kept, dropped = build_set(universe, deriv_all, cg_sym, cg_coin, resolved)
    log("[data] kept=%d dropped=%d" % (len(kept), len(dropped)))
    for x in dropped:
        log("   drop %-12s %s (n_ov=%s med=%s)" % (x["symbol"], x["reason"], x["n_overlap"], x["med_err"]))

    if mode in ("names", "pregate"):
        # 干跑:只验管道(名字层 + 行构造),不算任何统计量 —— 不污染预注册。
        res["out_of_panel"] = {
            "status": "names_dryrun_no_statistics",
            "deriv_symbols_since_2023": len(symbols),
            "panel_excluded": sorted(s for s in symbols if s in panel_set),
            "n_universe": len(universe),
            "names_kept": sorted(kept.keys()),
            "names_dropped": sorted(dropped, key=lambda x: x["symbol"]),
            "per_name_rows": {k: v["n_rows"] for k, v in sorted(kept.items())},
            "n_kept": len(kept),
            "n_dropped": len(dropped),
            "rows_total": sum(len(v["rows"]) for v in kept.values()),
            "symbol_multi_coinid": multi,
        }
        if mode == "names":
            return res
        # ── pregate:闸门未开时的**诊断**(不是交付物) ───────────────────
        # 台账的兜底是「2026-10-28 00:00 UTC 到点 ⇒ 没补上的名字列名剔除」。
        # 这个分支算的就是那一条兜底路径上的数,写进单独的文件,标死
        # "NOT_DELIVERABLE" —— 交付物是闸门开后的 --mode full(重跑,同一套代码)。
        if gate_ok:
            log("[gate] 闸门已开 ⇒ 用 --mode full(pregate 只是闸门未开时的诊断分支)。")
            res["status"] = "gate_open_use_full"
            res["out_of_panel"]["status"] = "gate_open_use_full"
            return res
        pg_daily = cross_section({k: v["rows"] for k, v in kept.items()}, btc)
        res["status"] = "pre_gate_diagnostic_NOT_DELIVERABLE"
        res["out_of_panel"]["status"] = "pre_gate_diagnostic_NOT_DELIVERABLE"
        res["out_of_panel"]["note"] = (
            "闸门未开时的诊断:宇宙里缺那 %d 个待补名字(多为已下架)⇒ 幸存者偏差未修。"
            "**这不是交付物**,交付物是闸门开后的 --mode full。" % len(pending))
        res["out_of_panel"]["stats_diagnostic_pre_gate"] = summarize(pg_daily)
        res["out_of_panel"]["sensitivity_exclude_seen_alias"] = sensitivity_block(kept, btc)
        res["out_of_panel"]["dimension_sensitivity"] = dimension_block(kept, btc)
        res["out_of_panel"]["alias_evidence"] = alias_evidence(deriv_all, cg_sym, PANEL)
        log("[data] 诊断分支:截面日=%d(非交付物)" % len(pg_daily))
        return res

    daily = cross_section({k: v["rows"] for k, v in kept.items()}, btc)
    log("[data] 截面日(≥%d 名)=%d" % (MIN_NAMES_PER_DAY, len(daily)))
    summ = summarize(daily)

    sens = sensitivity_block(kept, btc)
    alias = alias_evidence(deriv_all, cg_sym, PANEL)

    res["out_of_panel"] = {
        "deriv_symbols_since_2023": len(symbols),
        "panel_excluded": sorted(s for s in symbols if s in panel_set),
        "n_universe": len(universe),
        "names_kept": sorted(kept.keys()),
        "names_dropped": sorted(dropped, key=lambda x: x["symbol"]),
        "per_name_rows": {k: v["n_rows"] for k, v in sorted(kept.items())},
        "n_kept": len(kept),
        "n_dropped": len(dropped),
        "rows_total": sum(len(v["rows"]) for v in kept.values()),
        "symbol_multi_coinid": multi,
        "stats": summ,
        "sensitivity_exclude_seen_alias": sens,
        "dimension_sensitivity": dimension_block(kept, btc),
        "alias_evidence": alias,
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["selftest", "gate", "panel", "names", "pregate", "full"], default="gate")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.mode == "selftest":
        return selftest()
    res = run(a.mode)
    if isinstance(res, int):
        return res
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "t204_results.json")
    with open(out, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    log("[out] wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
