"""S-891:形态的前向记分自动化(setup-watch v1)—— 每天判一次形态登记表里的形态,触发就把三条命题写进情景台账。

Jazz 11-15:「很多周期性的机会都没有落实。」形态登记表(`docs/SETUP_REGISTRY.md`)第六样是「前向」,之前只有 11-14 手写的一次;
手写会挑时候,机器每天判、触发就记,才是没挑过的前向样本。**只记分,不下单**(执行层不 import 本模块,测试钉住)。

形态 #1(空的一侧,BTC / ETH):D 日收盘 —— 线下(panel `dist_200` < 0)且稳定币抽(`stable_supply_30d` < 0);
收盘 < 此前 20 根日线的最低价(不含 D);D 日为止 7 天的币安永续资金费(逐日均值再取 7 天均值)> 0。
进场价 = D 收盘;认错线 = 那个 20 日低 × 1.01,且不高于进场价 × 1.08。结算日 = D + 28。三条命题:
认错线被碰到(`high:` gt)、第 28 天收盘低于进场价(`close:` lt)、期间最低跌破进场价 × 0.90(`low:` lt)。
同一形态同一个币,上一组的结算日还没到(≥ D)就不再写。概率 = S-891 的历史基率(两段中点),写死在 `PROBS`。
形态 #2(多的一侧)按 S-891 的规则不进 v1(早段只有 5 组)。

调度:`_scenario_ledger_loop` 每小时一轮,结算之后调 `run_once`;要的数(D 的日线、状态、资金费)没到就等,写过的那天不再写。
判活:`select id, written_at, prob from scenario_ledger where author = 'seth:setup-watch' order by written_at desc limit 6`
(没有触发的日子本来就不写 —— 判活看 `_scenario_ledger_loop` 的 detail 里 `setup_watch` 那一段)。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

AUTHOR = "seth:setup-watch"
SYMBOLS = ("BTC", "ETH")
HORIZON_D = 28
LOOKBACK = 20
STOP_ABOVE, STOP_CAP, MOVE = 1.01, 1.08, 0.90
#: S-891 结果:2020-01 → 2026-10-17,BTC + ETH,一个窗口一组;≤ 2022 有 8 组、2023 起 11 组;取两段中点。
PROBS = {1: {"STOP": 0.597, "CLOSE": 0.801, "MOVE": 0.682}}
BASE_NOTE = {1: "历史同定义 19 组(≤ 2022 8 组 / 2023 起 11 组):碰到认错线 37.5% / 81.8%,第 28 天收盘低于进场价 87.5% / 72.7%,"
                "期间跌破 −10% 100% / 36.4%;概率取两段中点"}
WRITES_TABLES = ("scenario_ledger",)


def D(s: Any) -> dt.date:
    return s if isinstance(s, dt.date) and not isinstance(s, dt.datetime) else dt.date.fromisoformat(str(s)[:10])


# ── 纯函数 ──────────────────────────────────────────────────────────────────────

def trigger_1(bars: list[dict], d: dt.date, t: Optional[float], l: Optional[float], f7: Optional[float]) -> Optional[dict]:
    """bars:该币的日线 [{d, high, low, close}],按日升序。D 日触发 ⇒ {entry, lo20, stop};否则 None。要的数缺了也是 None。"""
    if t is None or l is None or f7 is None or not (t < 0 and l < 0 and f7 > 0):
        return None
    i = next((k for k, b in enumerate(bars) if D(b["d"]) == d), None)
    if i is None or i < LOOKBACK:
        return None
    prior = bars[i - LOOKBACK:i]
    lo20 = min(float(b["low"]) for b in prior)
    entry = float(bars[i]["close"])
    if not entry < lo20:
        return None
    return {"entry": entry, "lo20": lo20, "stop": min(lo20 * STOP_ABOVE, entry * STOP_CAP)}


def funding_7d(rows: list[dict], d: dt.date) -> Optional[float]:
    """rows:[{funding_time, funding_rate}]。先按 UTC 日求均值,再对 [D − 6, D] 里有数的日子求均值;一天都没有 ⇒ None。"""
    by: dict[dt.date, list[float]] = {}
    for r in rows:
        if r.get("funding_rate") is None:
            continue
        day = D(str(r["funding_time"])[:10])
        if d - dt.timedelta(days=6) <= day <= d:
            by.setdefault(day, []).append(float(r["funding_rate"]))
    if not by or d not in by:
        return None
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def blocked(existing: list[dict], setup: int, sym: str, d: dt.date) -> bool:
    """同一形态同一个币,已有一组的结算日 ≥ D ⇒ 不再写。"""
    pre = f"SW{setup}-{sym}-"
    return any(str(e.get("id", "")).startswith(pre) and D(e["horizon_d"]) >= d for e in existing)


def propositions_1(sym: str, d: dt.date, hit: dict) -> list[dict]:
    h = (d + dt.timedelta(days=HORIZON_D)).isoformat()
    tag = d.strftime("%Y%m%d")
    entry, stop, low_line = round(hit["entry"], 6), round(hit["stop"], 6), round(hit["entry"] * MOVE, 6)
    why = (f"形态 #1(docs/SETUP_REGISTRY.md):{d} 收盘线下 · 稳定币抽,收盘 {entry:g} 跌破此前 20 天低点 {hit['lo20']:g},"
           f"7 日资金费为正。{BASE_NOTE[1]}。这是形态的前向记分(S-891),不是收益承诺,也不是下单。")
    base = {"scenario": f"形态 #1 · {sym} · {d} 触发", "horizon_d": h}
    return [
        {**base, "id": f"SW1-{sym}-{tag}-STOP", "variable": f"high:{sym}", "op": "gt", "lo": stop, "prob": PROBS[1]["STOP"],
         "statement": f"{sym} 在 {h} 24:00 UTC 之前碰到认错线 {stop:g}。" + why},
        {**base, "id": f"SW1-{sym}-{tag}-CLOSE", "variable": f"close:{sym}", "op": "lt", "hi": entry, "prob": PROBS[1]["CLOSE"],
         "statement": f"{sym} {h} 收盘低于 {d} 收盘 {entry:g}(不考虑认错线)。" + why},
        {**base, "id": f"SW1-{sym}-{tag}-MOVE", "variable": f"low:{sym}", "op": "lt", "hi": low_line, "prob": PROBS[1]["MOVE"],
         "statement": f"{sym} 在 {h} 之前最低价跌到 {low_line:g}({d} 收盘的 −10%)以下。" + why},
    ]


def plan(d: dt.date, bars: dict[str, list[dict]], state: dict[str, Optional[float]], funding: dict[str, list[dict]],
         existing: list[dict]) -> dict[str, Any]:
    """纯函数:D 日要写哪些命题;要的数没到 ⇒ waiting 写明缺什么。"""
    missing = [k for k in ("dist_200", "stable_supply_30d") if state.get(k) is None]
    missing += [f"{s} 日线" for s in SYMBOLS if not any(D(b["d"]) == d for b in bars.get(s, []))]
    missing += [f"{s} 资金费" for s in SYMBOLS if funding_7d(funding.get(s, []), d) is None]
    if missing:
        return {"waiting": missing, "entries": [], "fired": {}}
    entries, fired = [], {}
    for s in SYMBOLS:
        hit = trigger_1(bars[s], d, state["dist_200"], state["stable_supply_30d"], funding_7d(funding[s], d))
        if hit is None:
            fired[s] = "未触发"
        elif blocked(existing, 1, s, d):
            fired[s] = "触发,但上一组还没到结算日"
        else:
            entries += propositions_1(s, d, hit)
            fired[s] = f"触发:进场 {hit['entry']:g},认错线 {hit['stop']:g}"
    return {"waiting": [], "entries": entries, "fired": fired}


# ── 读库 / 写入 ────────────────────────────────────────────────────────────────

_DONE: dict[str, str] = {}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """D = 昨天(UTC)。一天判一次:判过的 D(写了或确认没触发)不再读库。"""
    from src.data.evaluation.scenario_ledger import submit
    from src.data.style.header import _read_all
    now = now or dt.datetime.now(dt.timezone.utc)
    d = now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=1)
    if _DONE.get("d") == d.isoformat():
        return {"ok": True, "d": d.isoformat(), "already": _DONE.get("result")}
    lo = (d - dt.timedelta(days=LOOKBACK + 15)).isoformat()
    bars: dict[str, list[dict]] = {}
    for s in SYMBOLS:
        rows = await _read_all("ohlcv_daily", {"select": "trade_date,high,low,close", "source": "eq.binance_hist", "symbol": f"eq.{s}",
                                               "trade_date": f"gte.{lo}", "order": "trade_date.asc"})
        bars[s] = [{"d": r["trade_date"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in rows
                   if D(r["trade_date"]) <= d and None not in (r.get("high"), r.get("low"), r.get("close"))]
    st = await _read_all("state_daily", {"select": "feature,value", "entity": "eq.panel", "d": f"eq.{d.isoformat()}",
                                         "feature": "in.(dist_200,stable_supply_30d)"})
    state = {r["feature"]: (float(r["value"]) if r.get("value") is not None else None) for r in st}
    funding = {}
    for s in SYMBOLS:
        funding[s] = await _read_all("funding_history", {"select": "funding_time,funding_rate", "venue": "eq.binance_perp",
                                                         "symbol": f"eq.{s}", "funding_time": f"gte.{(d - dt.timedelta(days=6)).isoformat()}",
                                                         "order": "funding_time.asc"})
        funding[s] = [r for r in funding[s] if D(str(r["funding_time"])[:10]) <= d]
    existing = await _read_all("scenario_ledger", {"select": "id,horizon_d", "author": f"eq.{AUTHOR}", "order": "id.asc"})
    p = plan(d, bars, state, funding, existing)
    if p["waiting"]:
        return {"ok": True, "d": d.isoformat(), "waiting": p["waiting"]}
    out: dict[str, Any] = {"ok": True, "d": d.isoformat(), "fired": p["fired"]}
    if p["entries"]:
        w = await submit(p["entries"], AUTHOR, now=now)
        if not w.get("ok"):
            return {"ok": False, "d": d.isoformat(), "fired": p["fired"], "why": w.get("why"), "problems": w.get("problems")}
        out["written"] = w.get("ids")
    _DONE.update({"d": d.isoformat(), "result": {k: v for k, v in out.items() if k != "ok"}})
    return out
