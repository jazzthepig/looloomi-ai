"""③ 每天一个带概率的决定(Jazz 11-03「先 2 再 3」)—— 规则给敞口,基率给情景,台账给分数。

## 为什么

FoF 的 LP 买的不是 α,是「什么时候减」。我们的 ③ 现在只有一条趋势规则(X1V),它给出 0 / 1,不解释、不打分。
这里不改规则(规则 = 零假设,冻结;改只经预注册),加三样东西:
1. **把今天的决定写成一行**:规则的敞口、输入(趋势 / 宏观状态 / 资金费 / OI / 广度 / 强平地图冲击 / 近 7 天事件)、
   一段合规的人话;
2. **给决定配情景概率** —— 不是模型猜,是**基率**:历史上「同一个趋势符号 × 同一个宏观状态」的日子,之后 30 天 BTC
   落在 < −10% / ±10% / > +10% 的频率(同桶 n < 60 ⇒ 退回无条件频率并标明);
3. **三条情景当天写进 `scenario_ledger`**(作者 seth:exposure,`close:BTC`,结算日 d+30),到期按 Brier 结算。
   **90 天后看:它的 Brier 比无条件基率好不好 —— 不好就是装饰,摘掉。**(S-709)

**分歧标记**:规则满仓而基率 P(< −10%) ≥ 40%,或规则空仓而 P(> +10%) ≥ 40% ⇒ `flag = 规则与基率分歧` —— 这是偏离框架
(overlays)的候选输入,**不自动动钱**,Jazz 看。

表 `exposure_decision_daily`(d 主键):每天 UTC 收盘齐了之后一行;发一条到 feed 群(同一个 chat)。
判活:`select d, rule_exposure, probs, flag from exposure_decision_daily order by d desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
import html
import os
from typing import Any, Optional

TABLE = "exposure_decision_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"exposure_decision_daily": ("d", "sleeve", "rule_exposure", "mult_arm", "mult_m", "inputs", "bucket", "probs",
                                              "n_bucket", "flag", "rationale", "scenario_ids", "posted_at", "code_ref")}
CODE_REF = "exposure_decision v1 (11-03)"
AUTHOR = "seth:exposure"
SLEEVE = "crypto_core"
HORIZON_D = 30
BAND = 0.10
MIN_BUCKET_N = 60
DISAGREE_P = 0.40
REGIMES = ("RISK_ON", "RISK_OFF", "NEUTRAL", "EASING", "TIGHTENING", "STAGFLATION")
FEATURES = ("mom_200", "dist_200", "funding_7d_ann", "oi_chg_30d", "breadth_above_ma50") + tuple(f"regime_share_30d:{r}" for r in REGIMES)
MULT_ARM = "mult_v2_c1"
HIST_KEY = "exposure:base_rates"


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def bucket_of(state: dict) -> str:
    """纯函数。趋势符号 × 30 日里占比最高的宏观状态 → 'up|TIGHTENING' 这类桶名;缺 mom_200 ⇒ 'unknown'。"""
    m = _f(state.get("mom_200"))
    if m is None:
        return "unknown"
    shares = {r: _f(state.get(f"regime_share_30d:{r}")) or 0.0 for r in REGIMES}
    reg = max(shares.items(), key=lambda kv: kv[1])[0] if any(shares.values()) else "NEUTRAL"
    return f"{'up' if m >= 0 else 'down'}|{reg}"


def outcome_bin(ret: float) -> str:
    return "down" if ret < -BAND else ("up" if ret > BAND else "flat")


def forward_returns(closes: dict[str, float], horizon: int = HORIZON_D) -> dict[str, float]:
    """纯函数。{d: close} → {d: close(d+h)/close(d) − 1},按日历日找 d+h(没有那天就不算)。"""
    out = {}
    for d, c in closes.items():
        try:
            d2 = (dt.date.fromisoformat(d) + dt.timedelta(days=horizon)).isoformat()
        except ValueError:
            continue
        c2 = closes.get(d2)
        if c and c2:
            out[d] = c2 / c - 1.0
    return out


SHRINK_K = 5.0            # 伪「独立段」数:同桶样本是 30 日重叠窗口,n=70 天 ≈ 2 段独立观察,不能当 70 个样本用


def base_rates(buckets: dict[str, str], fwd: dict[str, float], today_bucket: str) -> tuple[dict[str, float], int, str]:
    """纯函数。buckets = {d: 桶名}。→ (概率 {down, flat, up}, 同桶样本天数, 用的桶)。
    同桶频率按有效样本 n/30 向无条件频率收缩(k = SHRINK_K);同桶天数 < MIN_BUCKET_N ⇒ 直接无条件('all')。
    实测 11-03:历史 2,833 天里 2,404 天宏观状态是 RISK_ON;down|TIGHTENING 只有 70 天 ≈ 2 段,原始频率 P(跌) = 0 —— 不收缩就是在装。"""
    counts = {"down": 0, "flat": 0, "up": 0}
    allc = {"down": 0, "flat": 0, "up": 0}
    for d, r in fwd.items():
        b = outcome_bin(r)
        allc[b] += 1
        if buckets.get(d) == today_bucket:
            counts[b] += 1
    n = sum(counts.values())
    tot_all = sum(allc.values()) or 1
    p_all = {k: v / tot_all for k, v in allc.items()}
    if n < MIN_BUCKET_N:
        return {k: round(v, 3) for k, v in p_all.items()}, tot_all, "all"
    n_eff = n / HORIZON_D
    p_b = {k: v / n for k, v in counts.items()}
    probs = {k: (n_eff * p_b[k] + SHRINK_K * p_all[k]) / (n_eff + SHRINK_K) for k in counts}
    tot = sum(probs.values()) or 1
    return {k: round(v / tot, 3) for k, v in probs.items()}, n, today_bucket


def rule_exposure(plan: dict) -> Optional[float]:
    """X1V 计划 → 加密腿敞口(0..1):目标权重之和。计划没齐 ⇒ None。"""
    if not plan or not plan.get("ok"):
        return None
    return round(float(sum(_f(w) or 0.0 for w in (plan.get("targets") or {}).values())), 4)


def flag_for(exposure: Optional[float], probs: dict[str, float]) -> Optional[str]:
    if exposure is None:
        return "规则没有给出敞口(收盘没齐)"
    if exposure >= 0.5 and probs.get("down", 0) >= DISAGREE_P:
        return f"规则与基率分歧:规则在场({exposure:g}),基率 P(30 日 < −10%) = {probs['down']:.0%}"
    if exposure < 0.5 and probs.get("up", 0) >= DISAGREE_P:
        return f"规则与基率分歧:规则离场({exposure:g}),基率 P(30 日 > +10%) = {probs['up']:.0%}"
    return None


def rationale(d: str, exposure: Optional[float], bucket: str, probs: dict, n: int, used: str, inputs: dict, flag: Optional[str]) -> str:
    """合规的人话:描述规则与历史频率,不建议任何人做任何事。"""
    trend, _, reg = bucket.partition("|")
    exp_txt = "收盘没齐,规则未给出" if exposure is None else f"{exposure:.0%}"
    ev = inputs.get("events_7d") or {}
    g = lambda k: (_f(inputs.get(k)) or 0.0) * 100   # noqa: E731
    parts = [f"③ 加密腿敞口 {exp_txt}(X1V 趋势规则,{d} 收盘)。",
             f"状态:面板 200 日动量 {g('mom_200'):+.1f}%,30 日宏观状态以 {reg} 为主;"
             f"资金费年化 {g('funding_7d_ann'):.1f}%,30 日 OI {g('oi_chg_30d'):+.0f}%,站上 50 日均线的成员 {g('breadth_above_ma50'):.0f}%。"]
    sell, buy = _f(inputs.get("liq_sell_5pct")), _f(inputs.get("liq_buy_15pct"))
    if sell is not None or buy is not None:
        parts.append("强平地图(头部账户对永续 ±2% 深度):"
                     + (f"跌 5% 被迫卖出 {sell:.1f} 倍" if sell is not None else "")
                     + (";" if sell is not None and buy is not None else "")
                     + (f"涨 15% 被迫买入 {buy:.1f} 倍" if buy is not None else "") + "。")
    if ev:
        parts.append("近 7 天事件:" + "、".join(f"{k} {v}" for k, v in ev.items()) + "。")
    parts.append(f"历史基率({'同状态' if used != 'all' else '无条件'},n = {n}):之后 30 日 BTC 跌超 10% {probs['down']:.0%} / "
                 f"±10% 内 {probs['flat']:.0%} / 涨超 10% {probs['up']:.0%}。这三条已写进情景台账,到期公开结算。")
    if flag:
        parts.append("⚑ " + flag + "(规则不变;偏离只经预注册与编号)。")
    return " ".join(parts)


def scenario_entries(d: str, close: float, probs: dict[str, float]) -> list[dict]:
    h = (dt.date.fromisoformat(d) + dt.timedelta(days=HORIZON_D)).isoformat()
    lo, hi = round(close * (1 - BAND), 2), round(close * (1 + BAND), 2)
    base = {"scenario": f"③ 日决定 {d}", "variable": "close:BTC", "horizon_d": h}
    return [{**base, "id": f"X-{d}-down", "statement": f"BTC {h} 收盘 < {lo}(较 {d} 跌超 10%)", "op": "lt", "hi": lo, "prob": probs["down"]},
            {**base, "id": f"X-{d}-flat", "statement": f"BTC {h} 收盘在 {lo}–{hi}(±10% 内)", "op": "between", "lo": lo, "hi": hi, "prob": probs["flat"]},
            {**base, "id": f"X-{d}-up", "statement": f"BTC {h} 收盘 > {hi}(较 {d} 涨超 10%)", "op": "gt", "lo": hi, "prob": probs["up"]}]


def post_text(row: dict) -> str:
    txt = html.escape(row["rationale"])
    return (f"<b>③ 每日决定 · {row['d']}</b>\n\n{txt}\n\n"
            "<i>这是对我们自己组合规则与历史频率的描述,不是对任何人的建议。</i>")


async def _history() -> tuple[dict[str, str], dict[str, float]]:
    """历史桶(按 d → 'up|RISK_OFF')与 BTC 收盘(按 d);一天内缓存在 Redis(只存桶名,不存 3 万个特征值)。"""
    from src.api.store import redis_get_key_status, redis_set_key
    from src.data.style.header import _read_all
    cached, _st = await redis_get_key_status(HIST_KEY)
    if cached and cached.get("buckets") and cached.get("closes"):
        return cached["buckets"], cached["closes"]
    rows = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                                           "feature": f"in.({','.join(FEATURES)})", "order": "d.asc,feature.asc"})
    states: dict[str, dict] = {}
    for r in rows:
        states.setdefault(str(r["d"])[:10], {})[r["feature"]] = _f(r.get("value"))
    buckets = {d: bucket_of(st) for d, st in states.items()}
    px = await _read_all("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                                         "order": "trade_date.asc"})
    closes = {str(r["trade_date"])[:10]: float(r["close"]) for r in px if _f(r.get("close"))}
    await redis_set_key(HIST_KEY, {"buckets": buckets, "closes": closes}, ttl=20 * 3600)
    return buckets, closes


async def _today_state(d: str) -> dict:
    from src.data.style.header import _read_all
    rows = await _read_all("state_daily", {"select": "feature,value", "entity": "eq.panel", "d": f"eq.{d}",
                                           "feature": f"in.({','.join(FEATURES)})"})
    return {r["feature"]: _f(r.get("value")) for r in rows}


async def _liq_shock() -> dict[str, Optional[float]]:
    """强平地图:跌 5% 时被迫卖出 / 涨 15% 时被迫买入,各对永续 ±2% 深度的最大倍数(BTC / ETH 里取大)。
    11-03 第一张图:头部账户的多头没有强平价(低杠杆),空头的强平价在上方 10–20% —— 风险在挤空那一侧,只报下跌那半边会漏掉它。"""
    try:
        from src.data.market.liq_map import latest_view
        v = await latest_view()
        sh = v.get("shocks") or []
        sell = [s["sell_vs_bid_depth"] for s in sh if s.get("shock") == 0.05 and s.get("sell_vs_bid_depth") is not None]
        buy = [s["buy_vs_ask_depth"] for s in sh if s.get("shock") == 0.15 and s.get("buy_vs_ask_depth") is not None]
        return {"sell_5pct": round(max(sell), 2) if sell else None, "buy_15pct": round(max(buy), 2) if buy else None}
    except Exception:                                                     # noqa: BLE001
        return {"sell_5pct": None, "buy_15pct": None}


async def _events_7d(d: str) -> dict[str, int]:
    from src.data.style.header import _read_all
    since = (dt.date.fromisoformat(d) - dt.timedelta(days=7)).isoformat()
    try:
        rows = await _read_all("events", {"select": "kind", "ts": f"gte.{since}", "kind": "in.(listing,delisting,perp_delisting)"})
    except Exception:                                                     # noqa: BLE001
        return {}
    out: dict[str, int] = {}
    for r in rows:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.notify import notify_telegram, telegram_configured
    from src.api.store import supabase_upsert_table
    from src.data.evaluation.scenario_ledger import submit
    from src.data.execution.host_plan import plan_core
    from src.data.ops.news_feed import resolve_feed_chat
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = (now.date() - dt.timedelta(days=1)).isoformat()
    have = await _read_all(TABLE, {"select": "d,posted_at", "d": f"eq.{d}", "limit": "1"})
    if have:
        return {"ok": True, "status": "skipped", "why": f"{d} 已有决定"}
    buckets, closes = await _history()
    today = await _today_state(d)
    if d not in closes:
        closes = dict(closes)
        px = await _read_all("ohlcv_daily", {"select": "close", "symbol": "eq.BTC", "source": "eq.binance_hist", "trade_date": f"eq.{d}", "limit": "1"})
        if px and _f(px[0].get("close")):
            closes[d] = float(px[0]["close"])
    if not today or d not in closes:
        return {"ok": True, "status": "skipped", "why": f"{d} 的状态 / 收盘还没齐(state {bool(today)}, close {d in closes})"}
    plan = await plan_core(d)
    exposure = rule_exposure(plan)
    bucket = bucket_of(today)
    fwd = forward_returns({k: v for k, v in closes.items() if k < d})
    probs, n, used = base_rates(buckets, fwd, bucket)
    mult = await _read_all("multiplier_daily", {"select": "m", "arm": f"eq.{MULT_ARM}", "d": f"eq.{d}", "limit": "1"})
    inputs = {k: today.get(k) for k in ("mom_200", "dist_200", "funding_7d_ann", "oi_chg_30d", "breadth_above_ma50")}
    inputs.update({f"liq_{k}": v for k, v in (await _liq_shock()).items()})
    inputs["events_7d"] = await _events_7d(d)
    inputs["btc_close"] = closes[d]
    flag = flag_for(exposure, probs)
    text = rationale(d, exposure, bucket, probs, n, used, inputs, flag)
    sub = await submit(scenario_entries(d, closes[d], probs), AUTHOR, now)
    ids = sub.get("ids") or []
    row = {"d": d, "sleeve": SLEEVE, "rule_exposure": exposure, "mult_arm": MULT_ARM, "mult_m": _f(mult[0].get("m")) if mult else None,
           "inputs": inputs, "bucket": used, "probs": probs, "n_bucket": n, "flag": flag, "rationale": text, "scenario_ids": ids,
           "posted_at": None, "code_ref": CODE_REF}
    chat, _why = await resolve_feed_chat()
    if chat and telegram_configured() and await notify_telegram(post_text(row), chat_id=chat, parse_mode="HTML"):
        row["posted_at"] = now.isoformat()
    w = await supabase_upsert_table(TABLE, [row], on_conflict="d")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    return {"ok": True, "d": d, "exposure": exposure, "bucket": used, "probs": probs, "n": n, "flag": flag,
            "scenarios": len(ids), "scenario_why": None if sub.get("ok") else sub.get("why"), "posted": bool(row["posted_at"]),
            "why": f"{d} 敞口 {exposure} · {used} n={n} · {probs}" + (f" · ⚑ {flag}" if flag else "")}
