"""⓪ 战场简报 —— 给 Jazz 下判断用的一张表(只读,不下单,不给建议)。

Jazz ⓪ 开关(regime_call)的输入是人的判断;这张表把 HL 上成交额最大的永续摆成同一把尺子,让判断有据可查:
趋势位置(SMA20 / 50 / 200)、是否刚破 20 日高、离 120 日高点多远、第一段有多大、回撤多深、
**S-658 第二段形态**今天是否成立、资金费年化、未平仓额、按 2.5 ATR 止损算的止损宽度(决定同样风险能开多大)。

**价值捕获比**(持币人收入 ÷ 协议收入,60 天;S-661 留出段 IC +0.086、t 3.45 —— 但 S-664:控制规模 / 波动 / 稀释后
留出段只剩 +0.018,**是描述不是信号**,它说明的是「这个币为什么不稀释」)来自 `protocol_revenue_daily`,
HL 币名经 `asset_mcap_daily` 的 symbol → CoinGecko id 接上;接不上或没有收入的币是空(不是 0)。
**90 日稀释**(流通量增长 = 市值 ÷ 价格,CoinGecko)是留出段最强的单变量(S-664 IC +0.119、t 4.05),
R-v2 的票开在一季度稀释 > 2.2% 的币上平均只有 +0.28R、其余 +0.57 / +0.76R(S-665);> 2.2% 标 `diluting`。

**它是筛子,不是信号。** S-658:第二段形态那一天进场,只比同币同月随便哪天进多 +0.09R,不显著 ——
钱在「哪个月、哪个币」,也就是人要判断的那部分。这里只把候选摆出来;选不选、什么时候选,是 ⓪ 开关里那条判断。
数据 = HL 自己的 metaAndAssetCtxs(一次请求)+ 前 N 个币的日线(只取已收盘的,S-644)。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
from typing import Any, Optional

from src.data.execution.regime_call import HL_INFO, STOP_ATR

TOP_N = 40
_CONC = 4


def _mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def coin_state(bars: list[tuple], ctx: Optional[dict] = None) -> dict[str, Any]:
    """纯函数。[(d, o, h, l, c[, v])](已收盘,升序;v = 币数)+ HL 的 assetCtx → 这个币今天的状态。
    不足 21 根 ⇒ 只给能算的。"""
    bars = sorted(bars)
    n = len(bars)
    out: dict[str, Any] = {"bars": n}
    if n < 2:
        return out
    c = [b[4] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    dv = [b[4] * b[5] if len(b) > 5 else None for b in bars]
    last = c[-1]
    out["d"], out["close"] = bars[-1][0], last
    for k, lab in ((7, "ret_7d"), (30, "ret_30d"), (90, "ret_90d")):
        out[lab] = (last / c[-1 - k] - 1.0) if n > k else None
    for w in (20, 50, 200):
        out[f"above_sma{w}"] = (last > _mean(c[-w:])) if n >= w else None
    if n >= 60:
        out["sma50_rising"] = _mean(c[-50:]) > _mean(c[-60:-10])
    if n >= 21:
        out["breakout_20d"] = last > max(h[-21:-1])
        trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(n - 14, n)]
        out["stop_width"] = STOP_ATR * (sum(trs) / 14.0) / last
    w120 = c[-121:]
    out["dd_from_120d_high"] = last / max(w120) - 1.0
    # S-658 第二段形态(与预注册同一组数):峰值在 [t−120, t−15],P / L ≥ 2,回撤 20–50%,今天收盘破 20 日高、站上 SMA50
    if n >= 150:
        i = n - 1
        seg = c[i - 120:i - 14]
        P = max(seg)
        tp = i - 120 + max(k for k, v in enumerate(seg) if v == P)
        L = min(c[max(0, tp - 120):tp + 1])
        m = min(c[tp + 1:i])
        out["first_leg_x"] = P / L if L > 0 else None
        out["pullback"] = m / P - 1.0
        out["peak_d"] = bars[tp][0]
        vol_ok = True
        if dv[-1] is not None and all(x is not None for x in dv[-21:-1]):
            vol_ok = dv[-1] >= 1.5 * (sum(dv[-21:-1]) / 20.0)
        out["second_leg_setup"] = bool(L > 0 and P / L >= 2.0 and 0.5 * P <= m <= 0.8 * P and out.get("breakout_20d")
                                       and out.get("above_sma50") and vol_ok)
    if ctx:
        f = float(ctx.get("funding") or 0.0)
        out["funding_apr"] = f * 24 * 365
        out["oi_usd"] = float(ctx.get("openInterest") or 0.0) * float(ctx.get("markPx") or 0.0)
        out["vol_24h_usd"] = float(ctx.get("dayNtlVlm") or 0.0)
    return out


def tag(s: dict) -> str:
    """一个词的位置描述(表里一眼看)。"""
    if s.get("second_leg_setup"):
        return "第二段形态"
    if s.get("breakout_20d") and s.get("above_sma50"):
        return "破 20 日高"
    if s.get("above_sma50") and s.get("sma50_rising"):
        return "趋势中"
    if s.get("above_sma20") and not s.get("above_sma50"):
        return "反弹"
    if s.get("above_sma50") is False and s.get("above_sma200") is False:
        return "弱势"
    return "震荡"


def summarize(rows: list[dict]) -> dict[str, Any]:
    """纯函数。全表 → 广度(有多少在 SMA50 之上、多少在破 20 日高)与中位收益。"""
    def share(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(1 for x in v if x) / len(v), 3) if v else None

    def med(k):
        v = sorted(r[k] for r in rows if r.get(k) is not None)
        return v[len(v) // 2] if v else None

    return {"n": len(rows), "above_sma50": share("above_sma50"), "above_sma200": share("above_sma200"),
            "breakout_20d": share("breakout_20d"), "second_leg_setups": sum(1 for r in rows if r.get("second_leg_setup")),
            "median_ret_30d": med("ret_30d"), "funding_apr_median": med("funding_apr")}


DILUTING = 0.022            # S-665:R-v2 历史最高三分位的下界(一个季度流通量涨 2.2%)


def attach_value(rows: list[dict], sym_to_gecko: dict[str, str], vc: dict[str, dict],
                 dil: Optional[dict[str, float]] = None) -> int:
    """纯函数。给每行补价值捕获比与 90 日稀释(HL 名 kPEPE → PEPE);返回接上价值捕获比的个数。"""
    n = 0
    dil = dil or {}
    for r in rows:
        c = r["coin"]
        sym = c[1:] if c.startswith("k") and c[1:2].isupper() else c
        g = sym_to_gecko.get(sym.upper())
        v = vc.get(g) if g else None
        r["gecko_id"] = g
        r["value_capture"] = v["value_capture"] if v else None
        r["holders_rev_30d"] = v["holders_rev_30d"] if v else None
        r["dil90"] = dil.get(g) if g else None
        r["diluting"] = (r["dil90"] > DILUTING) if r["dil90"] is not None else None
        n += 1 if (v and v["value_capture"] is not None) else 0
    return n


def dilution(now_rows: list[dict], old_rows: list[dict]) -> dict[str, float]:
    """纯函数。两个时点的 asset_mcap_daily 行 → {coin_id: ln(供给 / 90 天前供给)};每个 coin_id 取各自时点最近的一天。"""
    def supply(rows):
        best: dict[str, tuple[str, float]] = {}
        for x in rows:
            cid, p, m = x.get("coin_id"), float(x.get("price") or 0.0), float(x.get("mcap") or 0.0)
            if cid and p > 0 and m > 0 and (cid not in best or str(x["d"]) > best[cid][0]):
                best[cid] = (str(x["d"]), m / p)
        return {k: v[1] for k, v in best.items()}
    a, b = supply(now_rows), supply(old_rows)
    return {k: math.log(a[k] / b[k]) for k in a if k in b and a[k] > 0 and b[k] > 0}


async def _value_inputs() -> tuple[dict[str, str], dict[str, dict], dict[str, float], Optional[str]]:
    """(symbol → gecko_id, gecko_id → 价值捕获, gecko_id → 90 日稀释, 读不到的原因)。读不到不挡简报,写明。"""
    try:
        from src.data.style.header import _read_all
        from src.data.market.protocol_revenue import latest_value_capture
        from src.data.vector.market_state_writer import _sb_get
        vc = await latest_value_capture()
        last = await _sb_get("asset_mcap_daily", {"select": "d", "order": "d.desc", "limit": "1"})
        if not last.ok or not last.rows:
            return {}, vc, {}, f"asset_mcap_daily 读不到:{last.reason}"
        d1 = dt.date.fromisoformat(str(last.rows[0]["d"])[:10])
        m = await _sb_get("asset_mcap_daily", {"select": "symbol,coin_id,mcap,price,d", "d": f"eq.{d1.isoformat()}",
                                                "limit": "2000"})
        if not m.ok:
            return {}, vc, {}, f"asset_mcap_daily 读不到:{m.reason}"
        old = await _read_all("asset_mcap_daily", {
            "select": "coin_id,d,price,mcap", "d": f"gte.{(d1 - dt.timedelta(days=97)).isoformat()}",
            "and": f"(d.lte.{(d1 - dt.timedelta(days=90)).isoformat()})", "order": "coin_id.asc,d.asc"})
        dil = dilution(m.rows or [], old)
        best: dict[str, tuple[float, str]] = {}
        for x in m.rows or []:
            sym, cid, mc = str(x.get("symbol") or "").upper(), x.get("coin_id"), float(x.get("mcap") or 0.0)
            if sym and cid and (sym not in best or mc > best[sym][0]):
                best[sym] = (mc, cid)                            # 同名取市值最大的那个
        return {k: v[1] for k, v in best.items()}, vc, dil, None if vc else "protocol_revenue_daily 还没有数据"
    except Exception as e:                                       # noqa: BLE001
        return {}, {}, {}, f"{type(e).__name__}: {str(e)[:160]}"


async def build_brief(top_n: int = TOP_N, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import httpx
    now = now or dt.datetime.now(dt.timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    start_ms = now_ms - 260 * 86_400_000
    async with httpx.AsyncClient(timeout=20.0) as cl:
        r = await cl.post(HL_INFO, json={"type": "metaAndAssetCtxs"})
        r.raise_for_status()
        meta, ctxs = r.json()
        live = [(a["name"], c) for a, c in zip(meta["universe"], ctxs) if not a.get("isDelisted")]
        live.sort(key=lambda x: -float(x[1].get("dayNtlVlm") or 0.0))
        pick = live[:top_n]
        sem = asyncio.Semaphore(_CONC)
        errors: list[str] = []

        async def one(name: str, ctx: dict) -> Optional[dict]:
            async with sem:
                try:
                    cr = await cl.post(HL_INFO, json={"type": "candleSnapshot", "req": {
                        "coin": name, "interval": "1d", "startTime": start_ms, "endTime": now_ms}})
                    cr.raise_for_status()
                    bars = [(dt.datetime.fromtimestamp(int(k["t"]) / 1000, dt.timezone.utc).date().isoformat(),
                             float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k.get("v") or 0.0))
                            for k in cr.json() or [] if int(k["T"]) < now_ms]
                except Exception as e:                           # noqa: BLE001
                    errors.append(f"{name}: {type(e).__name__}")
                    return None
                s = coin_state(bars, ctx)
                return {"coin": name, "tag": tag(s), **s}

        rows = [x for x in await asyncio.gather(*(one(n, c) for n, c in pick)) if x]
    rows.sort(key=lambda r: -(r.get("ret_30d") if r.get("ret_30d") is not None else -9))
    s2g, vc, dil, why = await _value_inputs()
    n_vc = attach_value(rows, s2g, vc, dil)
    return {"at": now.isoformat(), "source": "hyperliquid metaAndAssetCtxs + candleSnapshot 1d(已收盘)",
            "breadth": summarize(rows), "rows": rows, "errors": errors,
            "value_capture": {"matched": n_vc, "why_missing": why, "source": "protocol_revenue_daily(DeFiLlama,S-661)"},
            "note": "筛子,不是信号:S-658 第二段形态那天进场只比同币同月随便哪天进多 +0.09R(不显著)。"
                    "选哪个币、什么时候在场,是 ⓪ 开关里人的判断。"}
