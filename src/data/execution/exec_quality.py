"""执行质量日表 `execution_quality_daily` —— `fill_log.execution_quality` 第一次有了消费者(10-30,真钱第一笔成交之后)。

## 为什么现在才有

`fill_log.py`(每笔意图的实施成本)与 `reconcile.py`(逐日偏离)都是纯函数,写于 T-122 / T-124,
直到 10-30 都**没有任何调用点** —— 规则 5b 的形状(写完了,没有调度者,一行都没有)。东京执行器 10-30 15:44 UTC
在 HL 现货下了第一批真单(T25 的 XAUT0 / SPYX),从这一刻起「真钱是不是回测的忠实表达」有了可以算的数。

## 口径(与 fill_log 同一份)

- 一本账 = 一个 sleeve(`x1v_spot_host_dry` / `x1v_spot` / `r_v2_host_dry` / `r_v2_live` / `t25_legs_host_dry` / `t25_legs_live` …)。
- 每天一行(按 `ts_decision` 的 UTC 日)+ 一行自开账起累计(`span = since_inception`,d = 算的那天)。
- 滑点 = 成交均价对决策时中间价(买正卖负 = 我们付的);手续费 bps 按成交名义额;未成交机会成本按 `mid_at_resolve`;
  实施差额 = 三者之和。**空跑 sleeve 没有结果行**:只报意图数与报价时的价差,滑点列为空(不是 0)。
- live sleeve 里**没有结果的意图**单列 `n_unresolved`:成交记录没落下来是真实状态,不能当成「没下」。
- 每天重算最近 `RECENT_DAYS` 天 + 累计行(幂等 upsert);进 `forward_anchor_daily`(键 sleeve + span)。

## 延迟(11-02)

三段,各取中位数(秒 / 分),不进锚(`anchor.DROP`):这是诊断,不是业绩 —— 而且锚过的日子重算时多出几列,
不能让锚把它报成「记录被改过」。
- `median_close_to_decision_min`:日收盘(UTC 00:00)→ 决策(意图的 `ts_decision`)。**按收盘定的规则才有意义**;
  灾难止损(`signal_ref` 带 catastrophe)不算 —— 它本来就是盘中触发。空跑也记(决策时间与有没有成交无关)。
- `median_decision_to_fill_s`:决策 → 结果(`ts_resolved − ts_decision`),含取盘口、落发件箱、签名、往返。
- `median_venue_s`:交易所那一段(`seconds_to_resolve`,下单 → 回报)。两者之差 = 主机自己花的时间。

## 判活判据(规则 5b ②)

    select d, sleeve, span, n_intents, fill_rate, mean_slippage_bps, implementation_shortfall_bps
      from execution_quality_daily order by d desc, sleeve limit 10;      -- UTC 01:00 后应有昨天 + since_inception
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from src.data.execution.fill_log import Intent, Outcome, execution_quality

TABLE = "execution_quality_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "sleeve", "span", "n_intents", "n_resolved", "n_unresolved", "n_filled", "fill_rate",
                          "notional_usd", "mean_slippage_bps", "mean_fee_bps", "mean_opportunity_bps",
                          "implementation_shortfall_bps", "median_quoted_spread_bps", "maker_share", "first_d",
                          "median_close_to_decision_min", "median_decision_to_fill_s", "median_venue_s",
                          "note", "code_ref", "computed_at")}
#: 11-02 延迟三列:诊断、不进锚(见 docstring「延迟」);CODE_REF 不升 —— 升了会改掉已锚日子的 payload
LATENCY_FIELDS = ("median_close_to_decision_min", "median_decision_to_fill_s", "median_venue_s")
CODE_REF = "exec_quality v1 (10-30)"
RECENT_DAYS = 7
DRY_SUFFIX = "_dry"

_INTENT_FIELDS = {f for f in Intent.__dataclass_fields__}
_OUTCOME_FIELDS = {f for f in Outcome.__dataclass_fields__}


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _intent(r: dict) -> Intent:
    return Intent(**{k: r.get(k) for k in _INTENT_FIELDS if k in r})


def _outcome(r: dict) -> Outcome:
    d = {k: r.get(k) for k in _OUTCOME_FIELDS if k in r}
    d["filled_notional_usd"] = _f(d.get("filled_notional_usd")) or 0.0
    d["fee_usd"] = _f(d.get("fee_usd")) or 0.0
    return Outcome(**d)


def _day(ts: str) -> str:
    return str(ts)[:10]


def _ts(x: Any) -> Optional[dt.datetime]:
    try:
        t = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _median(xs: list[float], nd: int) -> Optional[float]:
    xs = sorted(xs)
    return round(xs[len(xs) // 2], nd) if xs else None


def latency(intents: list[dict], outcomes: dict[str, dict]) -> dict[str, Optional[float]]:
    """纯函数。三段延迟的中位数(偶数个取上中位,与价差同一个口径)。"""
    close_min, d2f, venue = [], [], []
    for r in intents:
        td = _ts(r.get("ts_decision"))
        if td is None:
            continue
        if "catastrophe" not in str(r.get("signal_ref") or ""):
            midnight = td.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            close_min.append((td - midnight).total_seconds() / 60)
        o = outcomes.get(r["intent_id"])
        if o is None:
            continue
        tr = _ts(o.get("ts_resolved"))
        if tr is not None and tr >= td:
            d2f.append((tr - td).total_seconds())
        v = _f(o.get("seconds_to_resolve"))
        if v is not None and v >= 0:
            venue.append(v)
    return {"median_close_to_decision_min": _median(close_min, 1), "median_decision_to_fill_s": _median(d2f, 2),
            "median_venue_s": _median(venue, 3)}


def summarise(sleeve: str, window: str, d: str, intents: list[dict], outcomes: dict[str, dict]) -> dict[str, Any]:
    """纯函数。一本账在一个窗口里的一行。`outcomes` 按 intent_id。"""
    pairs, unresolved = [], 0
    for r in intents:
        o = outcomes.get(r["intent_id"])
        if o is None:
            unresolved += 1
            continue
        pairs.append((_intent(r), _outcome(o)))
    dry = sleeve.endswith(DRY_SUFFIX)
    q = execution_quality(pairs)
    spreads = sorted(v for v in (_intent(r).decision_spread_bps for r in intents) if v is not None)
    row: dict[str, Any] = {
        "d": d, "sleeve": sleeve, "span": window, "n_intents": len(intents), "n_resolved": len(pairs),
        "n_unresolved": 0 if dry else unresolved, "n_filled": q.n_filled,
        "fill_rate": None if dry or not pairs else round(q.fill_rate, 4),
        "notional_usd": round(q.notional_usd, 2),
        "mean_slippage_bps": None if q.mean_slippage_bps is None else round(q.mean_slippage_bps, 3),
        "mean_fee_bps": None if q.mean_fee_bps is None else round(q.mean_fee_bps, 3),
        "mean_opportunity_bps": None if q.mean_opportunity_bps is None else round(q.mean_opportunity_bps, 3),
        "implementation_shortfall_bps": (None if q.implementation_shortfall_bps is None
                                         else round(q.implementation_shortfall_bps, 3)),
        "median_quoted_spread_bps": round(spreads[len(spreads) // 2], 3) if spreads else None,
        "maker_share": None if q.maker_share is None else round(q.maker_share, 4),
        "first_d": min(_day(r["ts_decision"]) for r in intents) if intents else None,
        "code_ref": CODE_REF,
        **latency(intents, outcomes),
    }
    notes = []
    if dry:
        notes.append("空跑:只记意图,没有成交,滑点不适用")
    elif unresolved:
        notes.append(f"{unresolved} 个意图没有结果行(成交记录没落下来 ≠ 没下单)")
    if q.note and not dry:
        notes.append(q.note)
    row["note"] = ";".join(notes) or None
    return row


def rows_for(intents: list[dict], outcomes: list[dict], today: str, recent_days: int = RECENT_DAYS) -> list[dict]:
    """纯函数。所有 sleeve:最近 `recent_days` 天里有意图的每一天一行 + 一行累计。"""
    by_id = {o["intent_id"]: o for o in outcomes}
    sleeves: dict[str, list[dict]] = {}
    for r in intents:
        sleeves.setdefault(r["sleeve"], []).append(r)
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=recent_days)).isoformat()
    out = []
    for sleeve, rows in sorted(sleeves.items()):
        days = sorted({_day(r["ts_decision"]) for r in rows if _day(r["ts_decision"]) >= cutoff})
        for d in days:
            out.append(summarise(sleeve, "day", d, [r for r in rows if _day(r["ts_decision"]) == d], by_id))
        out.append(summarise(sleeve, "since_inception", today, rows, by_id))
    return out


#: 对外(证据面 `execution` 段):只出聚合,不出方向词与币名;每本账最新的一行累计。
PUBLIC_FIELDS = ("sleeve", "d", "first_d", "n_intents", "n_resolved", "n_unresolved", "n_filled", "fill_rate", "notional_usd",
                 "mean_slippage_bps", "mean_fee_bps", "mean_opportunity_bps", "implementation_shortfall_bps",
                 "median_quoted_spread_bps", *LATENCY_FIELDS, "note")
HOW_TO_READ_EXEC = (
    "One row per execution sleeve, cumulative since its first intent. Sleeves ending in _dry record intents only (no "
    "orders), so slippage is blank there, not zero. For live sleeves: mean_slippage_bps is the fill price against the "
    "mid at decision time (positive = paid), mean_fee_bps the venue fee on filled notional, mean_opportunity_bps what "
    "unfilled orders cost, implementation_shortfall_bps their sum. median_quoted_spread_bps is the spread at decision "
    "time, i.e. what a backtest assumes and never observes. Latency (medians): median_close_to_decision_min is minutes "
    "from the 00:00 UTC daily close to the decision, median_decision_to_fill_s decision to venue response, median_venue_s "
    "the venue round trip alone. n_unresolved counts intents with no recorded outcome; "
    "that is a data gap, not a trade that did not happen. Small n means a thin estimate, not a good one."
)


def public_rows(rows: list[dict]) -> list[dict]:
    """纯函数。每本账只留最新一行(按 d),字段按 PUBLIC_FIELDS。"""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("sleeve") not in latest or str(r.get("d")) > str(latest[r["sleeve"]].get("d")):
            latest[r["sleeve"]] = r
    return [{k: r.get(k) for k in PUBLIC_FIELDS} | {"live": not str(r.get("sleeve", "")).endswith(DRY_SUFFIX)}
            for _, r in sorted(latest.items())]


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).date().isoformat()
    intents = await _read_all("execution_intents", {"select": "*", "order": "ts_decision.asc"})
    if not intents:
        return {"ok": True, "refused": True, "why": "还没有任何意图"}
    outcomes = await _read_all("execution_outcomes", {"select": "*", "order": "ts_resolved.asc"})
    rows = rows_for(intents, outcomes, today)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    for r in rows:
        r["computed_at"] = stamp
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d,sleeve,span")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    live = {r["sleeve"]: r for r in rows if r["span"] == "since_inception" and not r["sleeve"].endswith(DRY_SUFFIX)}
    return {"ok": True, "d": today, "written": len(rows), "sleeves": sorted(set(r["sleeve"] for r in rows)),
            "live": {k: {"n": v["n_intents"], "fill_rate": v["fill_rate"], "slip_bps": v["mean_slippage_bps"],
                         "shortfall_bps": v["implementation_shortfall_bps"]} for k, v in live.items()}}
