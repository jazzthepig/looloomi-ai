"""⓪ 战场简报 —— 给 Jazz 下判断用的一张表(只读,不下单,不给建议)。

Jazz ⓪ 开关(regime_call)的输入是人的判断;这张表把 HL 上成交额最大的永续摆成同一把尺子,让判断有据可查:
趋势位置(SMA20 / 50 / 200)、是否刚破 20 日高、离 120 日高点多远、第一段有多大、回撤多深、
**S-658 第二段形态**今天是否成立、资金费年化、未平仓额、按 2.5 ATR 止损算的止损宽度(决定同样风险能开多大)。

**它是筛子,不是信号。** S-658:第二段形态那一天进场,只比同币同月随便哪天进多 +0.09R,不显著 ——
钱在「哪个月、哪个币」,也就是人要判断的那部分。这里只把候选摆出来;选不选、什么时候选,是 ⓪ 开关里那条判断。
数据 = HL 自己的 metaAndAssetCtxs(一次请求)+ 前 N 个币的日线(只取已收盘的,S-644)。
"""
from __future__ import annotations

import asyncio
import datetime as dt
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
    return {"at": now.isoformat(), "source": "hyperliquid metaAndAssetCtxs + candleSnapshot 1d(已收盘)",
            "breadth": summarize(rows), "rows": rows, "errors": errors,
            "note": "筛子,不是信号:S-658 第二段形态那天进场只比同币同月随便哪天进多 +0.09R(不显著)。"
                    "选哪个币、什么时候在场,是 ⓪ 开关里人的判断。"}
