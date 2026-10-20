"""外部叙事 / 社交数据源(Jazz 10-20:Sharpe AI 与 Santiment 的 key 已放 Railway)—— 先探形状,再建入库。

为什么先探:两家的返回结构在文档里都不全(Sharpe 的 mindshare 文档没有响应样例;Santiment 免费档对每个指标的
可取时间窗不同),而 key 只在 Railway 上,沙箱里取不到。「先探再建」(CLAUDE.md:probe before you build)——
这一轮只把**形状**写进 loop_attempt 的 detail(键名、长度、首条样例、时间范围),不落数据、不打印 key。
看到形状以后再写真正的入库表与历史 A/B(台账 S-626 的 K 臂)。
**10-20 起不再排程**:形状已经拿到,入库由 `social_ingest.py` / `_social_ingest_loop` 接手;这里留作换数据源时的手动探针。

注意 Sharpe 的 mindshare 不是社交帖子数:它是「CoinGecko 关注列表人数 + 看涨投票」的份额(Sharpe 文档原话的意思),
所以它测的是**散户关注度**,不是 KOL 喊单。Santiment 的 social_volume_total 才是社交提及数。
"""
from __future__ import annotations

from typing import Any

SOCIAL_METRICS = ("social_volume_total", "social_dominance_total", "sentiment_weighted_total", "unique_social_volume_total")


def shape(obj: Any, depth: int = 3, max_keys: int = 25) -> Any:
    """纯函数。任意 JSON → 它的形状:dict 给键与子形状,list 给长度与首元素形状,字符串截到 40 字,数字原样。"""
    if depth < 0:
        return type(obj).__name__
    if isinstance(obj, dict):
        keys = list(obj.keys())
        out: dict[str, Any] = {"_keys": len(keys)}
        for k in keys[:max_keys]:
            out[str(k)] = shape(obj[k], depth - 1, max_keys)
        return out
    if isinstance(obj, list):
        return {"_len": len(obj), "_first": shape(obj[0], depth - 1, max_keys) if obj else None,
                "_last": shape(obj[-1], 0, max_keys) if len(obj) > 1 else None}
    if isinstance(obj, str):
        return obj[:40]
    return obj


def ts_range(points: Any) -> dict[str, Any]:
    """纯函数。[[ts, v], …] 或 [{datetime|timestamp|date, …}, …] → 起止与条数(找不到时间字段就只给条数)。"""
    if not isinstance(points, list) or not points:
        return {"n": 0}
    def t(p: Any) -> Any:
        if isinstance(p, (list, tuple)) and p:
            return p[0]
        if isinstance(p, dict):
            for k in ("datetime", "timestamp", "date", "ts", "time", "snapshotAt", "d"):
                if k in p:
                    return p[k]
        return None
    return {"n": len(points), "first": t(points[0]), "last": t(points[-1])}


async def _try(name: str, coro: Any, out: dict[str, Any], summarize: Any) -> None:
    try:
        res = await coro
        out[name] = {"ok": True, **summarize(res)}
    except Exception as e:                                        # noqa: BLE001 — 探针:原样记下错因
        out[name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def probe() -> dict[str, Any]:
    from src.data.market.data_layer import get_santiment_gql, get_sharpe_v1
    out: dict[str, Any] = {}

    await _try("sharpe_narratives", get_sharpe_v1("narratives/data"), out,
               lambda r: {"shape": shape(r, 2), "ids": [n.get("id") for n in (r.get("data") or {}).get("narratives", [])][:40]})
    await _try("sharpe_mindshare_tokens", get_sharpe_v1("mindshare/data", {"tokens": "true", "window": "7d"}), out,
               lambda r: {"shape": shape(r, 4)})
    await _try("sharpe_mindshare_hist", get_sharpe_v1("mindshare/data", {"historical": "true", "timeframe": "3Y"}), out,
               lambda r: {"shape": shape(r, 4)})
    await _try("sharpe_mindshare_tokens_hist",
               get_sharpe_v1("mindshare/data", {"tokens": "true", "historical": "true", "timeframe": "3Y"}), out,
               lambda r: {"shape": shape(r, 4)})

    q_restr = "{ getAccessRestrictions(filter: METRIC) { name isAccessible isRestricted restrictedFrom restrictedTo } }"
    await _try("santiment_restrictions", get_santiment_gql(q_restr), out,
               lambda d: {"social": [x for x in (d.get("getAccessRestrictions") or [])
                                     if x.get("name") in SOCIAL_METRICS],
                          "n_metrics": len(d.get("getAccessRestrictions") or [])})
    q_sv = ('{ getMetric(metric: "social_volume_total") { timeseriesData(slug: "bitcoin", from: "utc_now-800d", '
            'to: "utc_now", interval: "1d") { datetime value } } }')
    await _try("santiment_btc_social_volume", get_santiment_gql(q_sv), out,
               lambda d: ts_range(((d.get("getMetric") or {}).get("timeseriesData")) or []))
    q_proj = "{ allProjects(page: 1, pageSize: 500) { slug ticker } }"
    await _try("santiment_projects", get_santiment_gql(q_proj), out,
               lambda d: {"n": len(d.get("allProjects") or []),
                          "sample": (d.get("allProjects") or [])[:5]})
    return out


def verdict(p: dict[str, Any]) -> tuple[str, str]:
    """纯函数。探针结果 → (ok / error, 一句话)。全部失败才算 error;部分失败照样 ok 但写明哪几项。"""
    names = sorted(p)
    bad = [n for n in names if not (p.get(n) or {}).get("ok")]
    if names and len(bad) == len(names):
        return "error", "全部失败:" + "; ".join(f"{n}: {(p[n] or {}).get('error', '')[:80]}" for n in bad)
    return "ok", f"{len(names) - len(bad)}/{len(names)} 项成功" + (f";失败 {bad}" if bad else "")
