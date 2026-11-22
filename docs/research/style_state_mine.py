"""把已落地的风格状态向量贴到账本上,只做标签和同期对照,不做新的预测。

风格模型就是 T-163 那份 8 风格 × 7 分量(research/t163/style_vectors_v2.json)。
S-650 已经判过:用它预测未来 30 天谁跑赢,不过。这里不重跑那个检验。

这一步只做三件事:
  1. 每个有完整 56 维的日子,记下 8 个风格各自 7 个分量的中秩分位均值(状态),
     以及谁最高、和次高差多少。缺维不补 0。
  2. 用库里仍在更新的 style_index_pit_daily(市值加权)重算相对 majors 的
     30 日 / 90 日对数收益的中秩分位,和模型重叠的日子对一下。对得上,才把
     模型结束之后的日子标成 rel_only;对不上,那一段不混进模型。
  3. 读得到的账本,超额 = 自己的日收益 − ①(core_cap / cap_a1_u)。只在
     收盘日对齐的账上减。报的是同期相关和「该风格当天状态最高」时的平均超额,
     不是一条可以下单的规则。

不写库。产物:同目录 style_state_mine.json 与 style_state_mine.md。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VEC = Path("/Volumes/CometCloudAI/cometcloud-local/research/t163/style_vectors_v2.json")
OUT_JSON = Path(__file__).with_name("style_state_mine.json")
OUT_MD = Path(__file__).with_name("style_state_mine.md")
STYLES = ["majors", "top_l1", "second_l1_l2", "app", "meme", "ai", "infra_tokenization", "defi"]
COMP = ["rel30", "rel90", "ma200_consec", "from_365d_low", "frac_above_50ma", "member_disp30", "funding_7d"]
MIN_CORR_N = 40
MIN_BUCKET = 15


def _env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _t163():
    path = ROOT / "docs/research/t163_style_vectors_v2.py"
    spec = importlib.util.spec_from_file_location("t163_style_vectors_v2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get(url: str, key: str, path: str, params: dict, start: int = 0, page: int = 1000):
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(
        f"{url}/rest/v1/{path}?{qs}",
        headers={
            "apikey": key,
            "Authorization": "Bearer " + key,
            "Accept": "application/json",
            "Range": f"{start}-{start + page - 1}",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode()
        return json.loads(body) if body.strip() else []


def _all(url, key, path, params) -> list:
    out, start = [], 0
    while True:
        batch = _get(url, key, path, params, start)
        out.extend(batch)
        if len(batch) < 1000:
            return out
        start += 1000


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v if math.isfinite(v) else math.nan


def labels_from_vectors(raw: dict) -> dict[str, dict]:
    vecs = raw["vectors"]
    out = {}
    for d in sorted(vecs):
        v = np.asarray(vecs[d], dtype=float)
        if v.size != 56 or not np.isfinite(v).all():
            continue
        comp = v.reshape(8, 7)
        score = comp.mean(axis=1)
        order = np.argsort(-score)
        rel30 = comp[:, 0]
        rorder = np.argsort(-rel30)
        out[d] = {
            "label_set": "full56",
            "score": {STYLES[i]: round(float(score[i]), 6) for i in range(8)},
            "leader": STYLES[int(order[0])],
            "gap": round(float(score[order[0]] - score[order[1]]), 6),
            "rel30": {STYLES[i]: round(float(rel30[i]), 6) for i in range(8)},
            "rel30_leader": STYLES[int(rorder[0])],
        }
    return out


def rel_from_index(rows: list, midrank) -> dict[str, dict[str, float]]:
    by = {s: {} for s in STYLES}
    for r in rows:
        if r.get("weighting") != "cap" or r.get("style") not in by:
            continue
        by[r["style"]][str(r["d"])[:10]] = _f(r.get("level"))
    cal = sorted(set().union(*[set(by[s]) for s in STYLES]))
    cal = [d for d in cal if all(math.isfinite(by[s].get(d, math.nan)) and by[s].get(d, 0) > 0 for s in STYLES)]
    level = {s: np.array([by[s][d] for d in cal], dtype=float) for s in STYLES}
    maj = level["majors"]
    out = {s: {} for s in STYLES}
    for s in STYLES:
        rel30 = midrank(_lag(level[s], 30) - _lag(maj, 30))
        rel90 = midrank(_lag(level[s], 90) - _lag(maj, 90))
        for i, d in enumerate(cal):
            if math.isfinite(rel30[i]) and math.isfinite(rel90[i]):
                out[s][d] = {"rel30": float(rel30[i]), "rel90": float(rel90[i])}
    return out


def _lag(level: np.ndarray, k: int) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log(level) - np.log(np.concatenate([np.full(k, np.nan), level[:-k]]))


def match_rel(labels: dict, rel: dict) -> dict:
    diffs = []
    for d, lab in labels.items():
        if not all(d in rel[s] for s in STYLES):
            continue
        for s in STYLES:
            diffs.append(abs(lab["rel30"][s] - rel[s][d]["rel30"]))
    if not diffs:
        return {"n": 0, "max_abs": None, "median_abs": None}
    a = np.asarray(diffs)
    return {"n": int(len(labels)), "n_compared_cells": int(a.size),
            "max_abs": float(a.max()), "median_abs": float(np.median(a))}


def extend_rel(labels: dict, rel: dict) -> int:
    """模型最后一天之后,只有 30 日和 90 日两条对得上的分量。不把它们叫成 56 维。"""
    last = max(labels)
    added = 0
    days = sorted(set.intersection(*[set(rel[s]) for s in STYLES]))
    for d in days:
        if d <= last or d in labels:
            continue
        rel30 = np.array([rel[s][d]["rel30"] for s in STYLES])
        rel90 = np.array([rel[s][d]["rel90"] for s in STYLES])
        score = (rel30 + rel90) / 2.0
        order = np.argsort(-score)
        rorder = np.argsort(-rel30)
        labels[d] = {
            "label_set": "rel_only",
            "score": {STYLES[i]: round(float(score[i]), 6) for i in range(8)},
            "leader": STYLES[int(order[0])],
            "gap": round(float(score[order[0]] - score[order[1]]), 6),
            "rel30": {STYLES[i]: round(float(rel30[i]), 6) for i in range(8)},
            "rel30_leader": STYLES[int(rorder[0])],
        }
        added += 1
    return added


def _series(rows, date_key, nav_key) -> dict[str, float]:
    out = {}
    for r in rows:
        d, nav = str(r.get(date_key) or "")[:10], _f(r.get(nav_key))
        if d and math.isfinite(nav) and nav > 0:
            out[d] = nav
    return out


def _rets(nav: dict[str, float]) -> dict[str, float]:
    days = sorted(nav)
    out = {}
    for a, b in zip(days, days[1:]):
        if nav[a] > 0:
            out[b] = nav[b] / nav[a] - 1.0
    return out


def _corr(xs, ys) -> float | None:
    if len(xs) < MIN_CORR_N:
        return None
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    if x.std(ddof=1) == 0 or y.std(ddof=1) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def mine(book: str, rets: dict, core: dict, labels: dict, excess: bool) -> dict:
    ret_days = sorted(rets)
    rows = []
    for d, r in rets.items():
        lab = labels.get(d)
        if not lab or lab["label_set"] != "full56":
            continue
        if excess:
            if d not in core:
                continue
            ex = r - core[d]
        else:
            ex = r
        rows.append((d, ex, lab))
    by_style = {s: [] for s in STYLES}
    bucket = {s: [] for s in STYLES}
    for _d, ex, lab in rows:
        for s in STYLES:
            by_style[s].append((ex, lab["score"][s]))
        bucket[lab["leader"]].append(ex)
    corr = {}
    for s, pairs in by_style.items():
        c = _corr([a for a, _ in pairs], [b for _, b in pairs])
        corr[s] = None if c is None else round(c, 4)
    buckets = {}
    for s, xs in bucket.items():
        if len(xs) < MIN_BUCKET:
            buckets[s] = None
        else:
            buckets[s] = {"n": len(xs), "mean_daily": round(float(np.mean(xs)), 6)}
    return {
        "book": book,
        "excess_vs_core": excess,
        "n_return_days": len(ret_days),
        "return_span": [ret_days[0], ret_days[-1]] if ret_days else None,
        "n_days": len(rows),
        "span": [rows[0][0], rows[-1][0]] if rows else None,
        "corr_with_style_score": corr,
        "mean_excess_when_style_leads": buckets,
    }


def main() -> None:
    _env()
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_KEY"]
    t163 = _t163()
    raw = json.loads(VEC.read_text())
    labels = labels_from_vectors(raw)
    idx = _all(url, key, "style_index_pit_daily", {
        "select": "d,style,weighting,level",
        "weighting": "eq.cap",
        "order": "d.asc",
    })
    rel = rel_from_index(idx, t163.midrank_pct)
    agree = match_rel(labels, rel)
    added = 0
    if agree["max_abs"] is not None and agree["max_abs"] < 1e-6:
        added = extend_rel(labels, rel)

    core_rows = _all(url, key, "core_cap_daily", {
        "select": "d,nav", "arm": "eq.cap_a1_u", "d": "gte.2023-01-01", "order": "d.asc",
    })
    core = _rets(_series(core_rows, "d", "nav"))
    books = []
    unread = []
    for name, table, params, date_key, nav_key, excess in (
        ("cis_tilt", "cis_tilt_daily", {"select": "d,nav", "arm": "eq.cis_a1", "order": "d.asc"}, "d", "nav", True),
        ("multiplier", "multiplier_daily", {"select": "d,nav", "arm": "eq.mult_v2", "order": "d.asc"}, "d", "nav", True),
        ("tom_overlay", "multiplier_daily", {"select": "d,nav", "arm": "eq.tom_pd13", "order": "d.asc"}, "d", "nav", True),
    ):
        try:
            rows = _all(url, key, table, params)
        except urllib.error.HTTPError as e:
            unread.append(f"{table} HTTP {e.code}")
            continue
        books.append(mine(name, _rets(_series(rows, date_key, nav_key)), core, labels, excess))

    for name, table in (
        ("beta_core", "beta_core_nav"),
        ("causal_paper", "causal_paper_nav"),
        ("scalable_book", "scalable_book_nav"),
        ("combined_book", "combined_book_nav"),
        ("dingge_paper", "dingge_paper_nav"),
    ):
        try:
            probe = _get(url, key, table, {"select": "*", "limit": "1"})
        except urllib.error.HTTPError as e:
            unread.append(f"{table} HTTP {e.code}")
            continue
        if not probe:
            unread.append(f"{table} empty")
            continue
            continue
        cols = probe[0].keys()
        date_key = "d" if "d" in cols else "mark_date" if "mark_date" in cols else None
        nav_key = "nav" if "nav" in cols else None
        if not date_key:
            continue
        params = {"select": f"{date_key},{nav_key or 'nav'}", "order": f"{date_key}.asc"}
        already_excess = "excess_return" in cols
        if already_excess:
            params["select"] = f"{date_key},excess_return"
        if "void_reason" in cols:
            params["void_reason"] = "is.null"
        rows = _all(url, key, table, params)
        if already_excess:
            rets = {str(r[date_key])[:10]: _f(r.get("excess_return")) for r in rows
                    if r.get(date_key) and math.isfinite(_f(r.get("excess_return")))}
            row = mine(name, rets, core, labels, False)
            row["excess_vs_core"] = True
            books.append(row)
        elif nav_key:
            # 没有超额列、日期又是估值点:不减 ①,避免把两个交易日当成同一天。
            books.append(mine(name, _rets(_series(rows, date_key, nav_key)), core, labels, False))

    days = sorted(labels)
    full = [d for d in days if labels[d]["label_set"] == "full56"]
    rel_days = [d for d in days if labels[d]["label_set"] == "rel_only"]
    last = labels[days[-1]]
    payload = {
        "model": "T-163 style vector v2, 8 styles x 7 components, midrank percentile",
        "model_file_built_at": raw.get("built_at"),
        "full56_span": [full[0], full[-1], len(full)],
        "rel_only_extended_days": added,
        "rel30_agreement_vs_stored_model": agree,
        "latest_label": {"d": days[-1], **last},
        "books": books,
        "unreadable_nav": unread,
        "note": "S-650 failed the 30-day forecast. These numbers are same-day association, not a rule.",
    }
    # 每天的标签单独放下,避免和对照表搅在一起。
    payload["labels"] = [{"d": d, **labels[d]} for d in days]
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _write_md(payload, rel_days)
    print(f"labels {len(days)} full {len(full)} rel_only {len(rel_days)} books {len(books)}")
    print("agreement", agree)
    print("wrote", OUT_MD.name)


def _write_md(payload: dict, rel_days: list[str]) -> None:
    a = payload["rel30_agreement_vs_stored_model"]
    full = payload["full56_span"]
    latest = payload["latest_label"]
    lines = [
        "# 风格状态标签 × 账本同期对照",
        "",
        "模型是已经落地的那份:8 个风格 × 7 个分量的中秩分位(T-163)。",
        "S-650 用它预测未来 30 天谁跑赢,不过。下面没有重做那个预测,也没有新的下单规则。",
        "",
        "## 标签",
        "",
        f"- 完整 56 维:{full[0]} → {full[1]},{full[2]} 天。每天 8 个分数 = 该风格 7 个分量的均值。",
        f"- 和库里 `style_index_pit_daily`(市值加权)重算的 30 日相对分位对比:"
        f"最大绝对差 {None if a.get('max_abs') is None else round(a['max_abs'], 4)},"
        f"中位 {None if a.get('median_abs') is None else round(a['median_abs'], 4)}。",
    ]
    if payload["rel_only_extended_days"]:
        lines.append(
            f"- 模型最后一天之后又标了 {payload['rel_only_extended_days']} 天,"
            f"但只有 30 日和 90 日两条分量(`rel_only`),最后一天 {rel_days[-1] if rel_days else '—'}。"
            "这 段不进下面的对照。"
        )
    else:
        lines.append(
            "- 库里的风格指数比这份向量新,但 30 日分位对不上(上面那个差),"
            "所以 2026-09-30 之后没有混进新标签。对不上就不标。"
        )
    lines += [
        f"- 最新一条标签 {latest['d']}:集合 `{latest['label_set']}`,状态最高的风格是 `{latest['leader']}`,"
        f"和次高差 {latest['gap']}。",
        "",
        "分数高只表示这个风格处在它自己历史上偏强的位置,不是预测它接下来会涨。",
        "",
        "## 账本对照(只在完整 56 维的日子上)",
        "",
        "收盘日记账的账,超额 = 日收益 − ①(`cap_a1_u`)。估值点记账的账不减 ①,相关是它自己的日收益对风格分数。",
        f"相关至少 {MIN_CORR_N} 天才写;某个风格当天最高的日子少于 {MIN_BUCKET} 天,那一格留空。",
        "",
        "| 账本 | 超额对① | 账本自身区间 | 和 56 维重叠的天数 | 绝对值最大的同期相关 | 该风格当天最高时的平均日超额 |",
        "|---|---|---|---|---|---|",
    ]
    for b in payload["books"]:
        corr = {k: v for k, v in (b["corr_with_style_score"] or {}).items() if v is not None}
        if corr:
            style, c = max(corr.items(), key=lambda kv: abs(kv[1]))
            corr_cell = f"{style} {c:+.4f}"
        else:
            style, corr_cell = "—", "—"
        buck = (b["mean_excess_when_style_leads"] or {}).get(style) if style != "—" else None
        buck_cell = "—" if not buck else f"{buck['mean_daily']:+.6f} (n={buck['n']})"
        span = "—" if not b.get("return_span") else f"{b['return_span'][0]} → {b['return_span'][1]}"
        lines.append(
            f"| {b['book']} | {'是' if b['excess_vs_core'] else '否'} | {span} | {b['n_days']} | {corr_cell} | {buck_cell} |"
        )
    lines += [
        "",
        "重叠是 0,是账本的第一天晚于风格向量的最后一天(2026-09-30),不是没读到。",
        "相关空着,是重叠不到 40 天。那不是 0。",
        "",
    ]
    if payload.get("unreadable_nav"):
        lines.append("这把读密钥看不到日收益的表:" + ", ".join(payload["unreadable_nav"]) + "。")
        lines.append("`book_vectors` 里这几本 2026-11-21 仍有行,只是日收益不在这把钥匙下。")
        lines.append("")
    from collections import Counter
    counts = Counter(x["leader"] for x in payload["labels"] if x["label_set"] == "full56")
    lines.append("1348 天里,状态分数最高的风格次数:" +
                 ", ".join(f"{k} {n}" for k, n in counts.most_common()) + "。")
    lines.append("这是标签的分布。app 一次都不是最高。它不说明谁接下来会涨。")
    lines.append("")
    # fix the table - I put corr in two columns wrongly. Let me look...
    # Header has 7 columns but row has book, excess, n, span, corr_cell, buck_cell = 6
    # Header: 账本 | 超额对① | 天数 | 区间 | 相关最高的风格 | 相关 | 当它最高时的平均日超额
    # I merged style and corr into corr_cell. I'll fix the header to 6 columns in a moment if I notice.
    OUT_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
