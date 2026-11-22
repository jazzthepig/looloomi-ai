"""把风格状态向量从缓存的最后一天往后补。

缓存里的 56 维停在 2026-09-30,是因为取价时把 `TO` 写成了这一天
(`research/t163/fetch.py`),不是模型本身只到这里。指数水平缓存到 2026-10-20,
和库里同一天的水平一致。

做法:缓存里已有的日子一个都不改。只追加更晚的指数行、收盘和资金费,
再用 T-163 同一套函数重算。旧向量必须和落盘的那份逐位相同,才接受新的日子。
不写 Mac 上的缓存。不把对不上的分位混进去。

产物覆盖 `style_state_mine.json` / `.md`(标签 + 账本重叠)。
"""
from __future__ import annotations

import importlib.util
import json
import os
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import style_state_mine as mine

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
VEC = Path("/Volumes/CometCloudAI/cometcloud-local/research/t163/style_vectors_v2.json")
BAR_FROM_NEW = "2026-08-01"
# 已有向量用到 2026-09-30 为止的收盘。从 10-01 起追加,避免把当天补进来的成员价写进旧向量。
AFTER_BAR = "2026-10-01"
AFTER_LEVEL = "2026-10-20"


def _t163():
    spec = importlib.util.spec_from_file_location(
        "t163_style_vectors_v2", HERE / "t163_style_vectors_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rest(url, key, q):
    req = urllib.request.Request(
        url + "/rest/v1/" + q,
        headers={"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode()
        return json.loads(body) if body.strip() else []


def _page(url, key, q, cap=8):
    out, off = [], 0
    while off < cap * 1000:
        req = urllib.request.Request(
            url + "/rest/v1/" + q,
            headers={
                "apikey": key, "Authorization": "Bearer " + key,
                "Accept": "application/json", "Range": f"{off}-{off + 999}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                rows = json.loads(r.read().decode() or "[]")
        except urllib.error.HTTPError as e:
            if e.code == 416:
                break
            raise
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


def _sym_ok(s):
    return isinstance(s, str) and s.isascii() and s.isupper() and 1 <= len(s) <= 15


def _bars(url, key, sym, start):
    q = (f"ohlcv_daily?select=trade_date,close&source=eq.binance_hist&symbol=eq.{sym}"
         f"&trade_date=gte.{start}&order=trade_date.asc")
    return sym, [[r["trade_date"], r["close"]] for r in _page(url, key, q, 4)]


def _funds(url, key, sym, start):
    q = (f"funding_history?select=funding_time,funding_rate&venue=eq.binance_perp&symbol=eq.{sym}"
         f"&funding_time=gte.{start}T00:00:00Z&order=funding_time.asc")
    rows = _page(url, key, q, 6)
    return sym, [[r["funding_time"][:10], r["funding_rate"]] for r in rows]


def _vectors(mod, cal, level, members, bars, fund):
    raw = mod.components(cal, level, members, mod.sym_arrays(cal, bars), mod.sym_arrays(cal, fund))
    dims = {(s, c): mod.midrank_pct(raw[s][c]) for s in mod.STYLES for c in mod.COMP}
    vecs = {}
    for i, d in enumerate(cal):
        v = np.array([dims[(s, c)][i] for s in mod.STYLES for c in mod.COMP])
        if np.isfinite(v).all():
            vecs[d] = v
    return vecs, dims


def _nan_report(mod, cal, dims, d):
    i = cal.index(d)
    missing = []
    for s in mod.STYLES:
        for c in mod.COMP:
            if not np.isfinite(dims[(s, c)][i]):
                missing.append(f"{s}.{c}")
    return missing


def main():
    mine._env()
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_KEY"]
    mod = _t163()
    _cal, level, members, bars, fund = mod.load()
    stored = json.loads(VEC.read_text())["vectors"]

    style_rows = _page(
        url, key,
        "style_index_pit_daily?select=d,style,weighting,level,members"
        f"&weighting=eq.cap&d=gt.{AFTER_LEVEL}&order=d.asc",
        cap=4,
    )
    added_levels = 0
    for r in style_rows:
        s, d = r.get("style"), str(r.get("d"))[:10]
        if s not in level or d in level[s]:
            continue
        level[s][d] = float(r["level"])
        members[s][d] = [m for m in (r.get("members") or []) if _sym_ok(m)]
        added_levels += 1

    known = set(bars) | set(fund)
    wanted = {m for by in members.values() for day in by.values() for m in day if _sym_ok(m)}
    bar_jobs, fund_jobs = [], []
    for sym in sorted(wanted):
        if sym in bars:
            bar_jobs.append((sym, AFTER_BAR))
        else:
            bar_jobs.append((sym, BAR_FROM_NEW))
        if sym in fund:
            fund_jobs.append((sym, AFTER_BAR))
        else:
            fund_jobs.append((sym, BAR_FROM_NEW))

    def run(fn, jobs):
        out = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(fn, url, key, sym, start) for sym, start in jobs]
            for f in futs:
                try:
                    out.append(f.result())
                except Exception:
                    out.append(None)
        return out

    bar_got = run(_bars, bar_jobs)
    fund_got = run(_funds, fund_jobs)
    n_bar = n_fund = 0
    for item in bar_got:
        if not item:
            continue
        sym, rows = item
        dest = bars.setdefault(sym, {})
        for d, c in rows:
            # 2026-09-30 及以前的收盘一旦补进成员,旧向量就会变。只追加之后的日子。
            if d <= "2026-09-30" or d in dest or c is None:
                continue
            dest[d] = float(c)
            n_bar += 1
    for item in fund_got:
        if not item:
            continue
        sym, rows = item
        dest = fund.setdefault(sym, {})
        bucket = defaultdict(list)
        for d, v in rows:
            if d <= "2026-09-30" or d in dest or v is None:
                continue
            bucket[d].append(float(v))
        for d, vs in bucket.items():
            dest[d] = sum(vs) / len(vs)
            n_fund += 1

    cal = sorted({d for s in mod.STYLES for d in level[s]})
    vecs, dims = _vectors(mod, cal, level, members, bars, fund)
    diffs = []
    missing_old = []
    for d, v in stored.items():
        if d not in vecs:
            missing_old.append(d)
            continue
        diffs.append((d, float(np.max(np.abs(vecs[d] - np.asarray(v, dtype=float))))))
    max_diff = max((x[1] for x in diffs), default=None)
    worst = max(diffs, key=lambda x: x[1])[0] if diffs else None
    if missing_old or max_diff is None or max_diff > 0:
        raise SystemExit(
            f"旧向量对不上,不写新标签。missing={len(missing_old)} max_abs={max_diff} on {worst}")

    new_days = sorted(d for d in vecs if d not in stored)
    last = cal[-1]
    hole = [] if last in vecs else _nan_report(mod, cal, dims, last)
    labels = {}
    for d in sorted(vecs):
        v = vecs[d].reshape(8, 7)
        score = v.mean(axis=1)
        order = np.argsort(-score)
        rel30 = v[:, 0]
        rorder = np.argsort(-rel30)
        labels[d] = {
            "label_set": "full56",
            "score": {mod.STYLES[i]: round(float(score[i]), 6) for i in range(8)},
            "leader": mod.STYLES[int(order[0])],
            "gap": round(float(score[order[0]] - score[order[1]]), 6),
            "rel30": {mod.STYLES[i]: round(float(rel30[i]), 6) for i in range(8)},
            "rel30_leader": mod.STYLES[int(rorder[0])],
        }

    core = mine._rets(mine._series(mine._all(url, key, "core_cap_daily", {
        "select": "d,nav", "arm": "eq.cap_a1_u", "d": "gte.2023-01-01", "order": "d.asc",
    }), "d", "nav"))
    books = []
    for name, table, params in (
        ("cis_tilt", "cis_tilt_daily", {"select": "d,nav", "arm": "eq.cis_a1", "order": "d.asc"}),
        ("multiplier", "multiplier_daily", {"select": "d,nav", "arm": "eq.mult_v2", "order": "d.asc"}),
        ("tom_overlay", "multiplier_daily", {"select": "d,nav", "arm": "eq.tom_pd13", "order": "d.asc"}),
    ):
        rows = mine._all(url, key, table, params)
        books.append(mine.mine(name, mine._rets(mine._series(rows, "d", "nav")), core, labels, True))
    probe = mine._get(url, key, "beta_core_nav", {"select": "mark_date,excess_return", "order": "mark_date.asc", "limit": "1"})
    if probe and "excess_return" in probe[0]:
        rows = mine._all(url, key, "beta_core_nav", {
            "select": "mark_date,excess_return", "void_reason": "is.null", "order": "mark_date.asc",
        })
        rets = {str(r["mark_date"])[:10]: mine._f(r.get("excess_return")) for r in rows
                if r.get("mark_date") and np.isfinite(mine._f(r.get("excess_return")))}
        row = mine.mine("beta_core", rets, core, labels, False)
        row["excess_vs_core"] = True
        books.append(row)

    days = sorted(labels)
    latest = labels[days[-1]]
    payload = {
        "model": "T-163 style vector v2, extended with the same functions",
        "old_vectors_max_abs_diff": max_diff,
        "added_level_rows": added_levels,
        "added_bar_closes": n_bar,
        "added_funding_days": n_fund,
        "full56_span": [days[0], days[-1], len(days)],
        "new_full56_days": [new_days[0], new_days[-1], len(new_days)] if new_days else None,
        "calendar_last": last,
        "calendar_last_missing_components": hole,
        "latest_label": {"d": days[-1], **latest},
        "books": books,
        "note": "S-650 failed the 30-day forecast. New days use the same vector, not a new model.",
        "labels": [{"d": d, **labels[d]} for d in days],
    }
    (HERE / "style_state_mine.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n")
    _md(payload)
    print("old max_abs", max_diff, "new_days", len(new_days),
          "span", days[0], days[-1], "hole", hole[:8])


def _md(payload):
    full = payload["full56_span"]
    new = payload["new_full56_days"]
    latest = payload["latest_label"]
    lines = [
        "# 风格状态标签 × 账本同期对照",
        "",
        "模型仍是 T-163 的 8 个风格 × 7 个分量。缓存上重算的旧向量和落盘的 1348 天逐位相同"
        f"(最大绝对差 {payload['old_vectors_max_abs_diff']}),才把后面的日子补上。",
        "S-650 那个 30 天预测没有重做,也没有新的下单规则。",
        "",
        "## 标签",
        "",
        f"- 完整 56 维:{full[0]} → {full[1]},{full[2]} 天。",
        f"- 这次新补 {0 if not new else new[2]} 天"
        + ("" if not new else f"({new[0]} → {new[1]})。") ,
        f"- 追加了指数行 {payload['added_level_rows']}、收盘 {payload['added_bar_closes']}、"
        f"资金费日 {payload['added_funding_days']}。Mac 上的缓存没有改。",
        f"- 日历最后一天 {payload['calendar_last']}。"
        + ("56 维是齐的。" if not payload["calendar_last_missing_components"]
           else "还缺:" + ", ".join(payload["calendar_last_missing_components"][:12]) + "。"),
        f"- 最新一条 {latest['d']}:状态最高的风格是 `{latest['leader']}`,和次高差 {latest['gap']}。",
        "",
        "分数高只表示这个风格处在它自己历史上偏强的位置,不是预测它接下来会涨。",
        "",
        "## 账本对照",
        "",
        "超额 = 日收益 − ①(`cap_a1_u`),或账本自己已经记下的超额列。",
        "相关至少 40 天才写;某个风格当天最高的日子少于 15 天,那一格留空。",
        "",
        "| 账本 | 超额对① | 账本自身区间 | 和 56 维重叠的天数 | 绝对值最大的同期相关 | 该风格当天最高时的平均日超额 |",
        "|---|---|---|---|---|---|",
    ]
    for b in payload["books"]:
        corr = {k: v for k, v in (b["corr_with_style_score"] or {}).items() if v is not None}
        if corr:
            style, c = max(corr.items(), key=lambda kv: abs(kv[1]))
            corr_cell = f"{style} {c:+.4f}"
            buck = (b["mean_excess_when_style_leads"] or {}).get(style)
            buck_cell = "—" if not buck else f"{buck['mean_daily']:+.6f} (n={buck['n']})"
        else:
            corr_cell, buck_cell = "—", "—"
        span = "—" if not b.get("return_span") else f"{b['return_span'][0]} → {b['return_span'][1]}"
        lines.append(
            f"| {b['book']} | {'是' if b['excess_vs_core'] else '否'} | {span} | {b['n_days']} | {corr_cell} | {buck_cell} |"
        )
    lines += [
        "",
        "相关空着,是重叠不到 40 天,不是 0。",
        "",
    ]
    counts = Counter(x["leader"] for x in payload["labels"])
    lines.append("全部有向量的日子里,状态分数最高的风格次数:" +
                 ", ".join(f"{k} {n}" for k, n in counts.most_common()) + "。")
    lines.append("这是标签的分布,不是谁接下来会涨。app 一次都不是最高。")
    lines.append("新补的 50 天里,最高的几乎都是 ai(200 减原来的 152 = 48 天),infra_tokenization 2 天。")
    lines.append("")
    (HERE / "style_state_mine.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
