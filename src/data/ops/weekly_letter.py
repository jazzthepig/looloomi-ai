"""周信(Jazz 11-03「先 2 再 3」的 3):一张被公开打过分的表,带着去见人 —— 不带预测,带记分。

## 内容(每一段都只读装置已记的表;读不到的段写「读不到」,不编)

1. 一句话:本周我们的加密腿在场几天、金 / 股腿照常,净值相对「持有面板」怎么样。
2. 真钱账:`live_account_daily` 周起止净值与周收益;对照 `core_variants_daily` 的 `cap_pit24`(按时点前 24 大持有)同期收益。
3. ③ 每日决定:`exposure_decision_daily` 本周每天的敞口、基率、近邻基率、分歧标记。
4. 记分表:`scenario_ledger` × `scenario_scores` 本周结算的命题,按作者:条数、命中率、平均 Brier(0 = 全对、0.25 = 乱猜);
   还没结算的列「等待」。**这是信的主角**:我们事前写、事后公开结算。
5. 事件:`events` 本周上币 / 下币 / 永续上下 的条数与点到 CIS 名字的几条。
6. 坟场:本周否定了什么(`graveyard` 由 Seth 在生成时给;台账是私有的,这里只放结论一句)。
7. 书本与层(11-04 加):⓪ 周期向量本周的相位(`cycle_vector_daily`)、② 待遇倾斜前向账两臂自起点的净值(`treatment_tilt_daily`)、
   发行方决策 → 结果(`decision_outcomes`:每类决策每期限的超额分布,n < 5 只报 thin;本周新结的行点名)。
8. 合规尾注:描述,不是建议;信号枚举只用五档。

`POST /internal/weekly-letter {week_end, graveyard[], note}` 生成并存 `weekly_letters`;`GET /internal/weekly-letter` 取最近一封。
发给谁、怎么发是 Jazz 的手;这里只产 markdown。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

TABLE = "weekly_letters"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"weekly_letters": ("week_end", "markdown", "data", "note")}
CORE_ARM = "cap_pit24"
COMPLIANCE = ("本信描述我们自己组合的规则、历史频率与公开结算的记录,不构成对任何人的投资建议;"
              "CometCloud 信号只用 STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT 五档描述资产在宇宙里的位置,"
              "不是对未来表现的预测。")


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def week_range(week_end: str) -> tuple[str, str]:
    e = dt.date.fromisoformat(week_end)
    return (e - dt.timedelta(days=6)).isoformat(), week_end


def live_week(rows: list[dict]) -> dict[str, Any]:
    """纯函数。live_account_daily 本周行 → 起止净值、周收益、流入标记。"""
    rows = sorted([r for r in rows if r.get("d")], key=lambda r: str(r["d"]))
    if not rows:
        return {"ok": False, "why": "本周没有真钱快照"}
    e0, e1 = _f(rows[0].get("equity_usd")), _f(rows[-1].get("equity_usd"))
    navs = [_f(r.get("nav")) for r in rows if _f(r.get("nav"))]
    ret = (navs[-1] / navs[0] - 1.0) if len(navs) >= 2 and navs[0] else None
    return {"ok": True, "d0": str(rows[0]["d"])[:10], "d1": str(rows[-1]["d"])[:10], "equity0": e0, "equity1": e1, "ret": ret,
            "days": len(rows), "flows": any(r.get("note") and "流" in str(r.get("note")) for r in rows)}


def panel_week(rows: list[dict]) -> Optional[float]:
    """纯函数。core_variants_daily(arm cap_pit24)本周日收益 → 复合周收益。"""
    rets = [_f(r.get("ret")) for r in rows if _f(r.get("ret")) is not None]
    if not rets:
        return None
    acc = 1.0
    for r in rets:
        acc *= 1.0 + r
    return acc - 1.0


def scorecard(entries: list[dict], scores: list[dict], d0: str, d1: str) -> dict[str, Any]:
    """纯函数。本周结算的(scored_at 在 [d0, d1+1))按作者汇总;未结算的按作者计数。"""
    by_id = {e["id"]: e for e in entries}
    settled: dict[str, dict] = {}
    for s in scores:
        at = str(s.get("scored_at") or "")[:10]
        if not (d0 <= at <= d1) or s.get("outcome") is None:
            continue
        e = by_id.get(s["id"])
        if not e:
            continue
        a = settled.setdefault(e.get("author") or "?", {"n": 0, "hits": 0, "brier_sum": 0.0, "items": []})
        a["n"] += 1
        a["hits"] += 1 if s["outcome"] else 0
        a["brier_sum"] += float(s.get("brier") or 0.0)
        a["items"].append({"id": s["id"], "statement": str(e.get("statement") or "")[:120], "prob": e.get("prob"),
                           "outcome": bool(s["outcome"]), "observed": s.get("observed")})
    for a in settled.values():
        a["hit_rate"] = round(a["hits"] / a["n"], 3)
        a["mean_brier"] = round(a["brier_sum"] / a["n"], 4)
        del a["brier_sum"]
    scored_ids = {s["id"] for s in scores if s.get("outcome") is not None}
    pending: dict[str, int] = {}
    for e in entries:
        if e["id"] not in scored_ids:
            pending[e.get("author") or "?"] = pending.get(e.get("author") or "?", 0) + 1
    return {"settled": settled, "pending": pending}


def layers_section(cycle: list[dict], tilt: list[dict], outcomes: list[dict], d0: str, d1: str) -> list[str]:
    """纯函数。第 6 段:⓪ 相位 · ② 待遇倾斜两臂 · 发行方决策 → 结果。空表写「还没有行」,不编。"""
    L = ["## 6 · 书本与层", ""]
    wk = [r for r in cycle if d0 <= str(r.get("d"))[:10] <= d1]
    if wk:
        last = max(wk, key=lambda r: str(r.get("d")))
        n_turn = sum(1 for r in wk if r.get("phase") == "turning")
        L.append(f"- ⓪ 周期向量:本周 {n_turn}/{len(wk)} 天处于 turning;{str(last.get('d'))[:10]} 恶化分 {_f(last.get('deterioration')) if last.get('deterioration') is not None else '—'}"
                 f" · 搬家分位 {_f(last.get('shift_pct')) if last.get('shift_pct') is not None else '—'} · {last.get('phase') or '未打分'}(只记,不动钱)")
    else:
        L.append("- ⓪ 周期向量:本周还没有行。")
    by_arm: dict[str, dict] = {}
    for r in tilt:
        if str(r.get("d"))[:10] <= d1:
            cur = by_arm.get(r["arm"])
            if cur is None or str(r.get("d")) > str(cur.get("d")):
                by_arm[r["arm"]] = r
    if by_arm.get("treatment_tilt") and by_arm.get("panel_hold"):
        t, h = _f(by_arm["treatment_tilt"].get("nav")), _f(by_arm["panel_hold"].get("nav"))
        L.append(f"- ② 待遇倾斜前向账(起点 {by_arm['treatment_tilt'].get('inception')}):倾斜臂 {t:.4f} · 等权臂 {h:.4f} · 差 {_pct(t / h - 1.0 if t and h else None)}"
                 f"(到 {str(by_arm['treatment_tilt'].get('d'))[:10]};90 天前不谈结论)")
    else:
        L.append("- ② 待遇倾斜前向账:还没有行。")
    if outcomes:
        from src.data.entity.decision_outcomes import aggregate
        agg = [a for a in aggregate(outcomes) if a["horizon_d"] == 30]
        if agg:
            L += ["", "| 决策类 | n(30 天) | 超额中位 | 命中 | |", "|---|---|---|---|---|"]
            for a in agg:
                L.append(f"| {a['kind']} | {a['n']} | {_pct(a['median_excess'])} | {a['hit_rate']:.0%} | {'thin' if a['thin'] else ''} |")
        fresh = [r for r in outcomes if d0 <= str(r.get("settled_at") or "")[:10] <= d1]
        for r in sorted(fresh, key=lambda r: (str(r.get("kind")), str(r.get("d"))))[:8]:
            L.append(f"- 本周新结:{r.get('kind')} {r.get('symbol')} {str(r.get('d'))[:10]} → {r.get('horizon_d')} 天 超额 {_pct(_f(r.get('excess')))}(对 {r.get('bench')})")
    else:
        L.append("- 发行方决策 → 结果:还没有到期结算的行。")
    return L


def compose(week_end: str, live: dict, panel_ret: Optional[float], decisions: list[dict], card: dict, events: dict,
            graveyard: list[str], note: str = "", layers: Optional[list[str]] = None) -> str:
    d0, d1 = week_range(week_end)
    L = [f"# CometCloud 周信 · {d0} → {d1}", ""]
    days_in = sum(1 for r in decisions if (_f(r.get("rule_exposure")) or 0) >= 0.5)
    L.append(f"**一句话。** 本周加密腿按规则在场 {days_in}/{len(decisions)} 天;"
             + (f"真钱净值周收益 {_pct(live.get('ret'))},同期持有面板(按时点前 24 大){_pct(panel_ret)}。" if live.get("ok")
                else f"真钱账:{live.get('why')}。"))
    if note:
        L += ["", note.strip()]
    L += ["", "## 1 · 真钱账"]
    if live.get("ok"):
        L.append(f"- 净值 {live['equity0']:,.0f} → {live['equity1']:,.0f} USDC({live['d0']} → {live['d1']},{live['days']} 个快照)"
                 + ("(本周有出入金,周收益按 NAV 算)" if live.get("flows") else ""))
        L.append(f"- 周收益 {_pct(live.get('ret'))} · 持有面板 {_pct(panel_ret)} · 差 {_pct((live.get('ret') or 0) - (panel_ret or 0)) if live.get('ret') is not None and panel_ret is not None else '—'}")
    L += ["", "## 2 · ③ 每日决定(规则给敞口,基率给情景)", "", "| 日 | 敞口 | 基率 跌/平/涨 | 近邻基率 | 标记 |", "|---|---|---|---|---|"]
    for r in sorted(decisions, key=lambda r: str(r.get("d"))):
        p = r.get("probs") or {}
        pk = (r.get("inputs") or {}).get("probs_knn") or {}
        e = _f(r.get("rule_exposure"))
        L.append(f"| {str(r.get('d'))[:10]} | {'—' if e is None else f'{e:.0%}'} | {p.get('down', 0):.0%}/{p.get('flat', 0):.0%}/{p.get('up', 0):.0%} "
                 f"({r.get('bucket')}, n={r.get('n_bucket')}) | " + (f"{pk.get('down', 0):.0%}/{pk.get('flat', 0):.0%}/{pk.get('up', 0):.0%}" if pk else "—")
                 + f" | {r.get('flag') or ''} |")
    if not decisions:
        L.append("| — | 本周没有决定行 | | | |")
    L += ["", "## 3 · 记分表(事前写下、事后公开结算)", ""]
    st = card.get("settled") or {}
    if st:
        L += ["| 作者 | 本周结算 | 命中 | 平均 Brier(0 全对 / 0.25 乱猜) |", "|---|---|---|---|"]
        for a, v in sorted(st.items()):
            L.append(f"| {a} | {v['n']} | {v['hit_rate']:.0%} | {v['mean_brier']:.3f} |")
        L.append("")
        for a, v in sorted(st.items()):
            for it in v["items"][:6]:
                L.append(f"- {'✅' if it['outcome'] else '❌'} `{it['id']}`(p = {it['prob']}):{it['statement']}"
                         + (f" —— 实际 {it['observed']}" if it.get("observed") is not None else ""))
    else:
        L.append("本周没有到期结算的命题。")
    pend = card.get("pending") or {}
    if pend:
        L.append("")
        L.append("等待结算:" + " · ".join(f"{a} {n} 条" for a, n in sorted(pend.items())))
    L += ["", "## 4 · 事件", ""]
    if events:
        L.append("- " + " · ".join(f"{k} {v}" for k, v in sorted(events.get("counts", {}).items())) if events.get("counts") else "- 本周事件库无条目")
        for t in (events.get("named") or [])[:8]:
            L.append(f"- {t}")
    L += ["", "## 5 · 坟场(本周否定了什么)", ""]
    L += [f"- {g}" for g in graveyard] if graveyard else ["- 本周没有新的否定。"]
    if layers:
        L += [""] + layers
    L += ["", "---", "", f"*{COMPLIANCE}*"]
    return "\n".join(L)


#: 11-05(Jazz:周信发到他的社群)—— 社群版只换叫法、去掉内部编号与表名,数字一个不改。
_PUBLIC_AUTHORS = (
    (re.compile(r"seth:exposure-knn"), "近邻臂(机械)"),
    (re.compile(r"seth:exposure"), "基率臂(机械)"),
    (re.compile(r"\bai:[A-Za-z0-9_.:\-]+"), "AI 判断臂"),
    (re.compile(r"\bseth[:\-][a-z\-]+"), "研究团队"),
    (re.compile(r"\blane-([abc])\b"), lambda m: f"研究组 {m.group(1).upper()}"),
    (re.compile(r"\bjazz\b"), "Jazz"),
)
_PUBLIC_TERMS = (
    ("## 1 · 真钱账", "## 1 · 实盘账户"), ("真钱净值", "实盘净值"), ("③ 每日决定", "每日决定"),
    ("⓪ 周期向量", "周期向量"), ("② 待遇倾斜前向账", "小股东待遇倾斜(前向记录)"), ("搬家分位", "状态变化分位"),
    ("处于 turning", "处于转向相"), ("· turning", "· 转向相"), ("· normal", "· 常态相"), ("X1V", "趋势规则"), ("T25", "实盘组合"), ("R-v2", "交易层"),
    ("## 6 · 书本与层", "## 6 · 其他前向记录"), ("| thin |", "| 样本少 |"), ("perp_delisting", "永续下线"), ("perp_listing", "永续上线"), ("delisting", "现货下币"), ("listing", "现货上币"),
)


def public_edition(md: str) -> str:
    """纯函数。周信 → 社群版:作者换成人话、命题去掉内部编号、层级记号与内部代号换掉、「读不到的段」只说有缺。数字不动。"""
    out = []
    for line in md.split("\n"):
        if line.startswith("*读不到的段:"):
            out.append("*本周有部分数据没有取到,相关段落按「没有行」写出,没有估算。*")
            continue
        line = re.sub(r"`[^`]+`\(p = ([0-9.]+)\)", lambda m: f"(事前概率 {float(m.group(1)):.0%})", line)
        for pat, rep in _PUBLIC_AUTHORS:
            line = pat.sub(rep, line)
        for a, b in _PUBLIC_TERMS:
            line = line.replace(a, b)
        line = re.sub(r"[⓪①②③④]\s?", "", line) if not line.startswith("*") else line
        out.append(line)
    return "\n".join(out)


async def build(week_end: str, graveyard: Optional[list[str]] = None, note: str = "") -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    d0, d1 = week_range(week_end)
    unreadable: list[str] = []

    async def _try(name, coro):
        try:
            return await coro
        except Exception as e:                                            # noqa: BLE001
            unreadable.append(f"{name}: {type(e).__name__}")
            return []
    live_rows = await _try("live_account_daily", _read_all("live_account_daily", {"select": "d,equity_usd,nav,note", "d": f"gte.{d0}", "order": "d.asc"}))
    live_rows = [r for r in live_rows if str(r.get("d"))[:10] <= d1]
    panel_rows = await _try("core_variants_daily", _read_all("core_variants_daily", {"select": "d,ret", "arm": f"eq.{CORE_ARM}", "d": f"gte.{d0}", "order": "d.asc"}))
    panel_rows = [r for r in panel_rows if str(r.get("d"))[:10] <= d1]
    decisions = await _try("exposure_decision_daily", _read_all("exposure_decision_daily", {
        "select": "d,rule_exposure,probs,bucket,n_bucket,flag,inputs", "d": f"gte.{d0}", "order": "d.asc"}))
    decisions = [r for r in decisions if str(r.get("d"))[:10] <= d1]
    entries = await _try("scenario_ledger", _read_all("scenario_ledger", {"select": "id,author,statement,prob,horizon_d"}))
    scores = await _try("scenario_scores", _read_all("scenario_scores", {"select": "id,scored_at,outcome,brier,observed"}))
    ev_rows = await _try("events", _read_all("events", {"select": "kind,symbols,title", "ts": f"gte.{d0}", "kind": "in.(listing,delisting,perp_listing,perp_delisting)"}))
    counts: dict[str, int] = {}
    named: list[str] = []
    for r in ev_rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        if r.get("symbols") and len(named) < 12:
            named.append(f"{r['kind']}:{','.join(r['symbols'][:4])} — {str(r.get('title') or '')[:80]}")
    cycle = await _try("cycle_vector_daily", _read_all("cycle_vector_daily", {"select": "d,deterioration,shift_pct,phase", "d": f"gte.{d0}", "order": "d.asc"}))
    tilt = await _try("treatment_tilt_daily", _read_all("treatment_tilt_daily", {"select": "d,arm,nav,inception", "order": "d.desc", "limit": "14"}))
    outcomes = await _try("decision_outcomes", _read_all("decision_outcomes", {"select": "kind,horizon_d,excess,symbol,d,bench,settled_at", "order": "d.desc", "limit": "5000"}))
    live = live_week(live_rows)
    panel_ret = panel_week(panel_rows)
    card = scorecard(entries, scores, d0, d1)
    layers = layers_section(cycle, tilt, outcomes, d0, d1)
    md = compose(week_end, live, panel_ret, decisions, card, {"counts": counts, "named": named}, graveyard or [], note, layers)
    if unreadable:
        md += "\n\n*读不到的段:" + "、".join(unreadable) + "*"
    data = {"live": live, "panel_ret": panel_ret, "decisions": len(decisions), "scorecard": card, "events": counts, "unreadable": unreadable,
            "markdown_public": public_edition(md)}
    w = await supabase_upsert_table(TABLE, [{"week_end": week_end, "markdown": md, "data": data, "note": note}], on_conflict="week_end")
    return {"ok": bool(w), "week_end": week_end, "markdown": md, "markdown_public": data["markdown_public"], "data": data,
            "why": None if w else f"写 {TABLE} 失败"}
