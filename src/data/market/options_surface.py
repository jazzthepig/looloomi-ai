"""期权面(Jazz 11-06「美股有很多短期对冲工具 —— 反向 / 倍数 ETF、期权组合;决定不了可能是矢量不足,要加维度」)。

Deribit 公开 `get_book_summary_by_currency`(一次返回一个币的全部期权)→ 每天一行特征,进 `options_surface_daily`:
期限结构(ATM 隐含波动 7 / 30 / 90 天)、30 天偏斜(90% 看跌 − 110% 看涨的隐含波动)、看跌 / 看涨持仓与成交比、
做市商伽马敞口(GEX,约定下的估计)、以及**对冲本身的价格**:30 天 90% 看跌期权、90 / 80 看跌价差各占现货的百分比 —— 「要不要对冲」的另一半是「对冲多贵」。

## 纪律

- 只用一次批量请求 / 币(`source_policy.assert_bulk_source` 按请求数判)。只记,不进敞口。
- 历史期权面在 Deribit 免费接口上取不到(要付费的逐笔档案),**这张表从 2026-11-06 起前向积累**;DVOL(`deriv_vol_daily`)有 2021 起的历史。
- 每个特征在缺档时留空,不插值成假数。

判活:`select currency, max(d), count(*) from options_surface_daily group by 1`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Optional

TABLE = "options_surface_daily"
WRITES_TABLES = (TABLE,)
COLS = ("d", "currency", "spot", "atm_iv_7d", "atm_iv_30d", "atm_iv_90d", "term_slope", "skew_30d", "pc_oi_ratio",
        "pc_vol_ratio", "put90_30d_cost_pct", "put_spread_90_80_30d_cost_pct", "total_oi_usd", "n_options",
        "gex_net_usd_1pct", "gex_call_usd_1pct", "gex_put_usd_1pct", "gamma_pin_strike", "fetched_at")
WRITES_COLUMNS = {TABLE: COLS}
LOOP_NAME = "_options_surface_loop"
API = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
CURRENCIES = ("BTC", "ETH")
_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def parse_name(name: str) -> Optional[tuple[dt.date, float, str]]:
    """纯函数。'BTC-27NOV26-68000-P' → (到期日, 行权价, 'P' / 'C');认不出 ⇒ None。"""
    try:
        _, exp, k, t = name.split("-")
        day, mon, yy = int(exp[:-5]), _MON[exp[-5:-2]], 2000 + int(exp[-2:])
        return dt.date(yy, mon, day), float(k), t
    except (ValueError, KeyError):
        return None


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def features(rows: list[dict], today: dt.date) -> dict[str, Any]:
    """纯函数。一个币的全部期权行 → 当日特征。"""
    opts = []
    for r in rows:
        p = parse_name(str(r.get("instrument_name") or ""))
        F, iv = _f(r.get("underlying_price")), _f(r.get("mark_iv"))
        if not p or not F or F <= 0:
            continue
        exp, k, t = p
        days = (exp - today).days
        if days < 1:
            continue
        opts.append({"days": days, "k": k, "t": t, "F": F, "iv": iv, "oi": _f(r.get("open_interest")) or 0.0,
                     "vol": _f(r.get("volume_usd")) or 0.0, "px": _f(r.get("mark_price"))})
    out: dict[str, Any] = {"n_options": len(opts)}
    if not opts:
        return out
    spot = sorted(o["F"] for o in opts if o["days"] <= 10)[0] if any(o["days"] <= 10 for o in opts) else opts[0]["F"]
    out["spot"] = round(spot, 2)
    expiries = sorted({o["days"] for o in opts})

    def near_exp(target: int) -> Optional[int]:
        cands = [e for e in expiries if 0.5 * target <= e <= 1.6 * target] or expiries
        return min(cands, key=lambda e: abs(e - target)) if cands else None

    def iv_at(days: int, t: str, m: float) -> Optional[float]:
        leg = [o for o in opts if o["days"] == days and o["t"] == t and o["iv"]]
        if not leg:
            return None
        o = min(leg, key=lambda o: abs(o["k"] / o["F"] - m))
        return o["iv"] if abs(o["k"] / o["F"] - m) <= 0.05 else None

    def px_at(days: int, m: float) -> Optional[float]:
        leg = [o for o in opts if o["days"] == days and o["t"] == "P" and o["px"] is not None]
        if not leg:
            return None
        o = min(leg, key=lambda o: abs(o["k"] / o["F"] - m))
        return o["px"] if abs(o["k"] / o["F"] - m) <= 0.05 else None    # Deribit 期权按标的币计价 ⇒ 价格本身就是占现货的比例

    for tgt, key in ((7, "atm_iv_7d"), (30, "atm_iv_30d"), (90, "atm_iv_90d")):
        e = near_exp(tgt)
        c, p = (iv_at(e, "C", 1.0), iv_at(e, "P", 1.0)) if e else (None, None)
        vals = [v for v in (c, p) if v is not None]
        out[key] = round(sum(vals) / len(vals), 2) if vals else None
    if out.get("atm_iv_7d") is not None and out.get("atm_iv_90d") is not None:
        out["term_slope"] = round(out["atm_iv_7d"] - out["atm_iv_90d"], 2)
    e30 = near_exp(30)
    if e30:
        p90, c110 = iv_at(e30, "P", 0.90), iv_at(e30, "C", 1.10)
        out["skew_30d"] = round(p90 - c110, 2) if p90 is not None and c110 is not None else None
        a, b = px_at(e30, 0.90), px_at(e30, 0.80)
        out["put90_30d_cost_pct"] = round(a * 100, 3) if a is not None else None
        out["put_spread_90_80_30d_cost_pct"] = round((a - b) * 100, 3) if a is not None and b is not None else None
    # 做市商伽马敞口(GEX,11-06 原因层「被迫交易的人」):常用约定 —— 做市商对客户的看涨净多、看跌净空,
    # 看涨伽马记正、看跌记负;单位 = 现货动 1% 时做市商要对冲的美元。正 ⇒ 做市商逆势对冲(压波动);负 ⇒ 顺势(放大)。
    # 只是约定下的估计(不知道真实的做市商持仓方向),记下来当维度,不当结论。
    import math
    gc = gp = 0.0
    by_k: dict[float, float] = {}
    for o in opts:
        if not o["iv"] or o["iv"] <= 0 or not o["oi"]:
            continue
        T, sig, S, K = o["days"] / 365.0, o["iv"] / 100.0, o["F"], o["k"]
        d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
        g = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (S * sig * math.sqrt(T))
        usd = g * o["oi"] * S * S * 0.01
        if o["t"] == "C":
            gc += usd
        else:
            gp += usd
        by_k[K] = by_k.get(K, 0.0) + usd
    if gc or gp:
        out["gex_call_usd_1pct"], out["gex_put_usd_1pct"] = round(gc, 0), round(-gp, 0)
        out["gex_net_usd_1pct"] = round(gc - gp, 0)
        out["gamma_pin_strike"] = max(by_k, key=by_k.get) if by_k else None
    poi = sum(o["oi"] for o in opts if o["t"] == "P")
    coi = sum(o["oi"] for o in opts if o["t"] == "C")
    pv = sum(o["vol"] for o in opts if o["t"] == "P")
    cv = sum(o["vol"] for o in opts if o["t"] == "C")
    out["pc_oi_ratio"] = round(poi / coi, 3) if coi else None
    out["pc_vol_ratio"] = round(pv / cv, 3) if cv else None
    out["total_oi_usd"] = round((poi + coi) * spot, 0)
    return out


def _get(url: str) -> Any:
    import json
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


async def run_once(now: Optional[dt.datetime] = None, get: Optional[Callable[[str], Any]] = None) -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import assert_bulk_source
    assert_bulk_source(len(CURRENCIES), "deribit", job="options surface (one book-summary request per currency)")
    get = get or _get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    rows, failed = [], {}
    for c in CURRENCIES:
        try:
            payload = await asyncio.to_thread(get, f"{API}?currency={c}&kind=option")
        except Exception as e:                                             # noqa: BLE001
            failed[c] = f"{type(e).__name__}: {str(e)[:120]}"
            continue
        f = features((payload or {}).get("result") or [], now.date())
        if not f.get("n_options"):
            failed[c] = "空的期权表"
            continue
        rows.append({k: f.get(k) for k in COLS if k not in ("d", "currency", "fetched_at")} |
                    {"d": now.date().isoformat(), "currency": c, "fetched_at": now.isoformat()})
    if not rows:
        return {"ok": False, "refused": True, "why": f"一个币都没取到:{failed}"}
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d,currency")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    b = next((r for r in rows if r["currency"] == "BTC"), rows[0])
    return {"ok": not failed, "written": len(rows), "failed": failed or None,
            "why": f"{b['currency']} ATM30 {b.get('atm_iv_30d')} · 偏斜 {b.get('skew_30d')} · 30 天 90% 看跌 {b.get('put90_30d_cost_pct')}% 现货"}
