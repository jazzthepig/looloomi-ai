"""偏离(overlay)—— 「规则是零假设,打破是实验」(Jazz 11-02,DECISIONS 10-08/11-02)。

## 是什么

基线 = 冻结的规则(v1 = T25 + X1V + R-v2;`portfolio_targets.plan_fields` 算出的目标)。**偏离**是一次带编号的、
有期限的、在预算内的调整,可以直接动真钱:
- `crypto_mult`:X1V 加密腿额度乘一个数(0 = 清掉,1.5 = 加一半);结果不超过净值 × 0.9(加密总敞口硬顶,R-v2 由主机另守);
- `gold_pp` / `equity_pp`:黄金 / 股票腿目标权重挪几个百分点(各自合计不超过 ±10pp;挪出的钱在现金腿)。
来源:`scenario`(情景引擎,可带 `scenario_id` 指向情景台账)· `jazz`(⓪ / 临时判断)· `opportunity` · `seth`。

## 纪律(写进库,不靠自觉)

- **只追加**:写下之后不能改、不能删(触发器);撤回 = 另写一条 `overlay_events`(cancel)。
- 写入时间由库定;`starts_d` 不早于写下那天;期限最长 90 天;**必须写理由与退出条件**。
- 只有主 token(Jazz / Seth)能写 —— lane 的 token 写不了动真钱的东西。
- 开始那天与结束后第一天都当作再平衡事件(`t25.event`):偏离要立刻生效、到期要立刻回到基线,不等 5% 偏离带,
  周末也动(Jazz 11-01:周末只为重大事件动;一次有编号的偏离就是这种事件)。

## 成绩单

每天记一行 `overlay_daily`:基线额度、偏离后的额度、生效的偏离编号。偏离的价值 = 偏离造成的额度差 × 之后的收益
(归因另算,见 `docs/research/` 的归因卡);基线本身照常和纸面 `flex_x1v:T25` 并排。

判活:`select d, ids, x1v_base_usd, x1v_usd from overlay_daily order by d desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

TABLE = "overlays"
EVENTS = "overlay_events"
DAILY = "overlay_daily"
WRITES_TABLES = (TABLE, EVENTS, DAILY)
WRITES_COLUMNS = {TABLE: ("id", "d", "author", "source", "thesis", "scenario_id", "crypto_mult", "gold_pp", "equity_pp",
                          "starts_d", "ends_d", "exit_rule", "code_ref"),
                  EVENTS: ("overlay_id", "kind", "reason", "author"),
                  DAILY: ("d", "ids", "capital_usd", "x1v_base_usd", "x1v_usd", "gold_base_usd", "gold_usd",
                          "equity_base_usd", "equity_usd", "clipped", "code_ref")}
CODE_REF = "overlays v1 (11-02)"
SOURCES = ("scenario", "jazz", "opportunity", "seth")
WRITERS = ("seth", "seth-lane")              # 能写偏离的 token(lane-a/b/c 不行)
CRYPTO_MULT_MAX = 3.0
from src.data.execution.portfolio_targets import CRYPTO_GROSS_CAP_FRAC  # noqa: E402  —— 加密总敞口硬顶只有一个出处
LEG_PP_LIMIT = 10.0
MAX_DAYS = 90
_ID = re.compile(r"^OV-[0-9A-Za-z_-]{1,40}$")


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def validate(e: dict, today: dt.date) -> list[str]:
    """纯函数。一条偏离的问题清单(空 = 能写)。"""
    why = []
    if not _ID.match(str(e.get("id") or "")):
        why.append("id 形如 OV-0001")
    if e.get("source") not in SOURCES:
        why.append(f"source 要是 {SOURCES}")
    for k in ("thesis", "exit_rule"):
        if len(str(e.get(k) or "").strip()) < 8:
            why.append(f"{k} 要写清楚(至少一句话)")
    m, g, q = _f(e.get("crypto_mult")), _f(e.get("gold_pp")), _f(e.get("equity_pp"))
    if m is None and g is None and q is None:
        why.append("crypto_mult / gold_pp / equity_pp 至少给一个")
    if m is not None and not 0 <= m <= CRYPTO_MULT_MAX:
        why.append(f"crypto_mult 要在 [0, {CRYPTO_MULT_MAX}]")
    for k, v in (("gold_pp", g), ("equity_pp", q)):
        if v is not None and abs(v) > LEG_PP_LIMIT:
            why.append(f"{k} 要在 ±{LEG_PP_LIMIT:g}pp 内")
    try:
        s, t = dt.date.fromisoformat(str(e.get("starts_d"))[:10]), dt.date.fromisoformat(str(e.get("ends_d"))[:10])
        if s < today:
            why.append(f"starts_d {s} 不能早于今天 {today}(不补写过去)")
        if t < s:
            why.append("ends_d 要不早于 starts_d")
        elif (t - s).days > MAX_DAYS:
            why.append(f"期限最长 {MAX_DAYS} 天(到期再写一条)")
    except ValueError:
        why.append("starts_d / ends_d 要是日期")
    return why


def active(overlays: list[dict], cancelled: set[str], d: str) -> list[dict]:
    """纯函数。d 这天生效的偏离(没撤、starts_d ≤ d ≤ ends_d),按 id 排。"""
    return sorted([o for o in overlays if o["id"] not in cancelled
                   and str(o["starts_d"])[:10] <= d <= str(o["ends_d"])[:10]], key=lambda o: o["id"])


def boundary_today(overlays: list[dict], cancelled_on: dict[str, str], d: str) -> list[str]:
    """纯函数。今天开始的、昨天到期的、昨天或今天被撤的 —— 这些让今天成为再平衡事件。"""
    y = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
    out = []
    for o in overlays:
        if str(o["starts_d"])[:10] == d or str(o["ends_d"])[:10] == y or cancelled_on.get(o["id"]) in (y, d):
            out.append(o["id"])
    return sorted(out)


def apply(fields: dict, act: list[dict], event_ids: list[str]) -> dict:
    """纯函数。基线计划段 + 生效的偏离 → 偏离后的计划段(预算内截断,截了什么写明)。基线原样留在 `overlays.baseline`。"""
    cap = float(fields["t25_capital_usd"])
    legs = (fields.get("t25") or {}).get("legs") or {}
    base = {"x1v_nav_budget_usd": fields["x1v_nav_budget_usd"],
            "legs": {k: v.get("target_usd") for k, v in legs.items()}}
    mult = 1.0
    gold = eq = 0.0
    for o in act:
        if _f(o.get("crypto_mult")) is not None:
            mult *= float(o["crypto_mult"])
        gold += _f(o.get("gold_pp")) or 0.0
        eq += _f(o.get("equity_pp")) or 0.0
    clipped = []
    if mult > CRYPTO_MULT_MAX:
        clipped.append(f"crypto_mult {mult:g} → {CRYPTO_MULT_MAX:g}")
        mult = CRYPTO_MULT_MAX
    x1v = round(float(base["x1v_nav_budget_usd"]) * mult, 2)
    if x1v > CRYPTO_GROSS_CAP_FRAC * cap:
        clipped.append(f"X1V 额度 {x1v:.2f} → 净值 × {CRYPTO_GROSS_CAP_FRAC}")
        x1v = round(CRYPTO_GROSS_CAP_FRAC * cap, 2)
    for name, v in (("gold_pp", gold), ("equity_pp", eq)):
        if abs(v) > LEG_PP_LIMIT:
            clipped.append(f"{name} {v:+g} → ±{LEG_PP_LIMIT:g}")
    gold, eq = max(-LEG_PP_LIMIT, min(LEG_PP_LIMIT, gold)), max(-LEG_PP_LIMIT, min(LEG_PP_LIMIT, eq))
    out = {**fields, "x1v_nav_budget_usd": x1v}
    t25 = {**(fields.get("t25") or {})}
    new_legs = {}
    for sym, leg in legs.items():
        pp = gold if leg.get("sleeve") == "gold" else eq if leg.get("sleeve") == "equity" else 0.0
        new_legs[sym] = {**leg, "target_usd": round(max(0.0, float(leg["target_usd"]) + pp / 100 * cap), 2)}
    t25["legs"] = new_legs
    if event_ids:
        t25["rebalance_today"] = True
        t25["event"] = "overlay:" + ",".join(event_ids)
    out["t25"] = t25
    out["overlays"] = {"ids": [o["id"] for o in act], "crypto_mult": round(mult, 6), "gold_pp": gold, "equity_pp": eq,
                       "baseline": base, "clipped": clipped, "event": t25.get("event")}
    return out


def daily_row(d: str, applied: dict) -> dict:
    """纯函数。偏离后的计划段 → overlay_daily 的一行(基线 vs 偏离后)。"""
    ov = applied.get("overlays") or {}
    base = ov.get("baseline") or {}
    legs = (applied.get("t25") or {}).get("legs") or {}
    by = {v.get("sleeve"): (k, v) for k, v in legs.items()}

    def leg(sl: str) -> tuple[Optional[float], Optional[float]]:
        k, v = by.get(sl, (None, {}))
        return (base.get("legs") or {}).get(k), v.get("target_usd")
    gb, g = leg("gold")
    eb, e = leg("equity")
    return {"d": d, "ids": ov.get("ids") or [], "capital_usd": applied.get("t25_capital_usd"),
            "x1v_base_usd": base.get("x1v_nav_budget_usd"), "x1v_usd": applied.get("x1v_nav_budget_usd"),
            "gold_base_usd": gb, "gold_usd": g, "equity_base_usd": eb, "equity_usd": e,
            "clipped": ov.get("clipped") or [], "code_ref": CODE_REF}


async def load(d: str) -> tuple[list[dict], list[str]]:
    """d 这天生效的偏离 + 今天的边界事件。读不到抛 —— 读不到 ≠ 没有偏离(调用方决定怎么办)。"""
    from src.data.style.header import _read_all
    near = (dt.date.fromisoformat(d) - dt.timedelta(days=MAX_DAYS + 2)).isoformat()
    rows = await _read_all(TABLE, {"select": "*", "ends_d": f"gte.{near}", "order": "id.asc"})
    ev = await _read_all(EVENTS, {"select": "overlay_id,kind,at", "kind": "eq.cancel"})
    cancelled_on = {e["overlay_id"]: str(e["at"])[:10] for e in ev}
    cancelled = {k for k, on in cancelled_on.items() if on <= d}
    return active(rows, cancelled, d), boundary_today(rows, cancelled_on, d)


async def submit(e: dict, author_lane: str, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_insert_table
    if author_lane not in WRITERS:
        return {"ok": False, "why": f"token 的 lane {author_lane!r} 不能写动真钱的偏离(只有 {WRITERS})"}
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).date()
    why = validate(e, today)
    if why:
        return {"ok": False, "why": "有问题 —— 不写", "problems": why}
    row = {"id": e["id"], "d": today.isoformat(), "author": author_lane, "source": e["source"],
           "thesis": str(e["thesis"])[:1000], "scenario_id": e.get("scenario_id"),
           "crypto_mult": _f(e.get("crypto_mult")), "gold_pp": _f(e.get("gold_pp")), "equity_pp": _f(e.get("equity_pp")),
           "starts_d": str(e["starts_d"])[:10], "ends_d": str(e["ends_d"])[:10], "exit_rule": str(e["exit_rule"])[:500],
           "code_ref": CODE_REF}
    res = await supabase_insert_table(TABLE, [row])
    if not res.ok:
        return {"ok": False, "why": f"写入失败(id 已存在 / 起始日早于今天 都会被库拒):{(res.why or '')[:300]}"}
    return {"ok": True, "id": e["id"]}


async def cancel(overlay_id: str, reason: str, author_lane: str) -> dict[str, Any]:
    from src.api.store import supabase_insert_table
    if author_lane not in WRITERS:
        return {"ok": False, "why": f"token 的 lane {author_lane!r} 不能撤偏离"}
    if len(str(reason or "").strip()) < 4:
        return {"ok": False, "why": "撤回要写原因"}
    res = await supabase_insert_table(EVENTS, [{"overlay_id": overlay_id, "kind": "cancel", "reason": str(reason)[:500],
                                                "author": author_lane}])
    return {"ok": bool(res.ok), "why": None if res.ok else (res.why or "")[:300]}
