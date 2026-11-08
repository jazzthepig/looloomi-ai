"""按币的资金面空间(11-07,Jazz「回到高维,继续开发」)—— HIGH_DIM_ONTOLOGY §5 里 Asset 空间缺的「原因维」。

## 为什么

Asset 空间到今天只有 CIS 的 27 维(支柱水平 + 变化 + 风险矩)—— 全是**反射**。S-81 的定理:扩散反射没用,要扩散**因**
(资金流、决策、注意力)。市场层的因早就并进了 `feature_matrix_daily`,按币的从来没有:谁在加杠杆、散户站哪边、大户和
散户分歧多大、被迫成交在哪。对手盘族(S-726 / S-768)要问的「这个币现在被谁拿着」,在几何上就是这里的一个点。

## 空间(`asset_flow_daily`,物化视图;迁移 `2026-11-07_asset_flow_daily.sql`)

每个 (币, 日) 一行,全部是 d 日收盘已知的量(`DIMS` 的次序 = 向量的次序):

| 维 | 量 | 读法 |
|---|---|---|
| fund7 | 7 日均资金费年化(Binance,结算次数加权) | 多头付多少钱拿着 |
| doi7 | ln(OI_d / OI_{d−7})(张数) | 新开的杠杆 |
| crowd | ln(全体账户多空比) | 散户站哪边 |
| smart | ln(大户持仓多空比) − crowd | 大户与散户的分歧 |
| taker7 | 7 日均 ln(主动买 / 主动卖)(5 分钟档) | 谁在吃单 |
| mom7 / mom30 | 相对 BTC 的 7 / 30 日对数收益 | 价格已经走了多少 |
| vol30 / vratio | 30 日波动、7 日 ÷ 30 日波动 | 相位 |
| turn | ln(7 日均成交额 ÷ 60 日均) | 注意力 / 成交暴增 |
| dd90 | ln(收盘 ÷ 90 日最高) | 离高点多远 |

每一维在**当天截面里**取百分位,居中到 [−1, 1] 成 11 维向量 `vec`(百分位 ⇒ 无量纲、抗极值、不需要历史均值方差 ⇒ 天然时点)。
结果列 `x7` / `x30` = d+1 开盘 → d+7 / d+30 收盘(期间停更取最后一个收盘)减当天截面等权,到期才有。

## 已知的偏(写在用它的每一处)

- **幸存者:** 宇宙来自 `deriv_metrics_daily`,它的名单 = 今天还在 Binance 现货在册的名字(binance_vision.py)⇒ 死掉的币不在。
  水平(「这种状态之后平均跑输多少」)偏乐观;不同状态之间的**相对**比较受影响较小。
- **2022-06 起**(metrics 档 2022 年前几乎是空壳),约 1,450 天 × 平均 169 个币。
- 近邻会扎堆(大币彼此像):一次查询的 100 个近邻常常只来自十几个币 ⇒ 报「币 × 月」的独立簇数,别把 100 当成 100 个样本。

## 用法(只描述,不进敞口)

`analogs(symbol, d)` → 历史上资金面最像的 k 个 (币, 日)(只在结果已到期的行里找 —— 时点安全由 SQL 函数保证)+ 它们之后 30 天
超额的分布 + 这个点在截面里最极端的三维。进探索仓 / AI 判断臂的档案;任何一条要动钱,另立预注册(S-774 先判它有没有排序力)。

判活:`select max(d), count(*), count(vec) from asset_flow_daily` —— max(d) 跟 `deriv_metrics_daily` 的最新一天一致。
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Any, Optional

VIEW = "asset_flow_daily"
RPC_REFRESH = "refresh_asset_flow"
RPC_KNN = "asset_flow_knn"
DIMS = ("fund7", "doi7", "crowd", "smart", "taker7", "mom7", "mom30", "vol30", "vratio", "turn", "dd90")
REFRESH_TIMEOUT_S = 600.0   # 与库里函数的 statement_timeout 一致(宇宙 v2 之后行数会翻倍)
K_DEFAULT = 100
HORIZON_DEFAULT = 30
DIM_LABELS = {
    "fund7": "资金费", "doi7": "OI 7 日变化", "crowd": "散户多空比", "smart": "大户 − 散户", "taker7": "主动买卖",
    "mom7": "7 日相对 BTC", "mom30": "30 日相对 BTC", "vol30": "30 日波动", "vratio": "波动比 7/30",
    "turn": "成交暴增", "dd90": "离 90 日高点",
}


def needs_refresh(view_max: Optional[str], source_max: Optional[str]) -> bool:
    """纯函数。物化视图落后于上游(metrics 最新一天)⇒ 要刷;读不到视图 ⇒ 也刷。"""
    if not source_max:
        return False
    return not view_max or str(view_max)[:10] < str(source_max)[:10]


def extremes(row: dict, n: int = 3) -> list[dict]:
    """纯函数。这个点在当天截面里最极端的 n 维(百分位离 0.5 最远的)。"""
    out = []
    for k in DIMS:
        q = row.get(f"q_{k}")
        if q is None:
            continue
        out.append({"dim": k, "label": DIM_LABELS[k], "pct": round(float(q), 3), "raw": row.get(k)})
    out.sort(key=lambda x: -abs(x["pct"] - 0.5))
    return out[:n]


def summarize(nbrs: list[dict], horizon: int = HORIZON_DEFAULT) -> dict[str, Any]:
    """纯函数。近邻 → 之后超额的分布 + 独立簇数(币 × 月)。超额是对当天截面等权的,所以无条件基准 = 0。"""
    key = "x7" if horizon <= 7 else "x30"
    xs = sorted(float(r[key]) for r in nbrs if r.get(key) is not None)
    if not xs:
        return {"n": 0}
    clusters = {(r.get("symbol"), str(r.get("d"))[:7]) for r in nbrs}

    def q(p: float) -> float:
        i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
        return round(xs[i], 4)
    return {"n": len(xs), "symbols": len({r.get("symbol") for r in nbrs}), "clusters": len(clusters),
            "median": round(statistics.median(xs), 4), "mean": round(sum(xs) / len(xs), 4),
            "share_negative": round(sum(1 for x in xs if x < 0) / len(xs), 3), "p10": q(0.10), "p90": q(0.90),
            "dist_median": round(statistics.median(float(r["dist"]) for r in nbrs if r.get("dist") is not None), 3)
            if any(r.get("dist") is not None for r in nbrs) else None}


async def refresh(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """上游有新的一天才刷(物化刷新 ~40 秒,不每小时白刷)。"""
    from src.api.store import supabase_rpc_write
    from src.data.vector.market_state_writer import _sb_get
    v = await _sb_get(VIEW, {"select": "d", "order": "d.desc", "limit": "1"})
    s = await _sb_get("deriv_metrics_daily", {"select": "d", "n_points": "gte.200", "order": "d.desc", "limit": "1"})
    vmax = (v.rows or [{}])[0].get("d") if v.ok and v.rows else None
    smax = (s.rows or [{}])[0].get("d") if s.ok and s.rows else None
    if not needs_refresh(vmax, smax):
        return {"ok": True, "skipped": True, "latest": vmax, "why": f"已是最新({vmax})"}
    r = await supabase_rpc_write(RPC_REFRESH, {}, timeout=REFRESH_TIMEOUT_S)
    if not r.ok:
        return {"ok": False, "why": f"{RPC_REFRESH} 失败(客户端 {REFRESH_TIMEOUT_S:.0f} s):{(r.why or '')[:160]}"}
    n = r.value[0] if isinstance(r.value, list) and r.value else r.value
    if isinstance(n, dict):
        n = next(iter(n.values()), None)
    out = {"ok": bool(n), "rows": n, "latest_before": vmax, "source_latest": smax,
           "why": f"按币资金面空间刷新:{n} 行(上游最新 {smax})"}
    try:                                   # 11-07:S-774 R ✅ 的前向记录(周一预测 + 到期结算);出错不挡刷新
        from src.data.state.asset_flow_forecast import run_once as _fc_run
        fc = await _fc_run(now)
        out["forecast"] = {k: fc.get(k) for k in ("ok", "forecast_d", "n", "settled")}
        out["why"] = f"{out['why']} | 前向预测:{fc.get('why')}"
    except Exception as e:                 # noqa: BLE001
        out["why"] = f"{out['why']} | 前向预测出错:{type(e).__name__}: {str(e)[:120]}"
    return out


async def analogs(symbol: str, d: Optional[str] = None, k: int = K_DEFAULT, horizon: int = HORIZON_DEFAULT) -> dict[str, Any]:
    """某币某日(默认最新)资金面最像的历史 (币, 日) 与它们之后的超额。只描述。"""
    from src.api.store import supabase_rpc
    from src.data.vector.market_state_writer import _sb_get
    sym = str(symbol or "").upper()
    params = {"select": "*", "symbol": f"eq.{sym}", "order": "d.desc", "limit": "1"}
    if d:
        params["d"] = f"eq.{d[:10]}"
    rq = await _sb_get(VIEW, params)
    if not rq.ok or not rq.rows:
        return {"ok": False, "why": f"{VIEW} 里没有 {sym}{' @ ' + d if d else ''}(不在宇宙:7 日均成交额 < 200 万美元或没有 metrics)"}
    row = rq.rows[0]
    if row.get("vec") is None:
        return {"ok": False, "why": f"{sym} @ {row['d']} 有缺维,没有向量", "row": {k2: row.get(k2) for k2 in ("d",) + DIMS}}
    nb = await supabase_rpc(RPC_KNN, {"p_symbol": sym, "p_d": row["d"], "p_k": int(k), "p_h": int(horizon)}) or []
    crowd = None
    try:                                   # 11-08:同一个币身上正在走的对手盘事件(下架 / 标签 / 上币 / squeeze / 尖峰)+ 台账基率
        from src.data.signals.crowd_map import active as _crowd
        cm = await _crowd(symbol=sym, days=30)
        crowd = {"kinds": sorted({e["kind"] for e in cm.get("events") or []}),
                 "events": [{k2: e.get(k2) for k2 in ("kind", "d", "age_days")} | {"base_median_30d": e["base"]["median_30d"],
                            "vs": e["base"]["vs"], "ledger": e["base"]["ledger"]} for e in (cm.get("events") or [])[:10]],
                 "missing": cm.get("missing")}
    except Exception as e:                 # noqa: BLE001 —— 读不到不挡近邻
        crowd = {"error": type(e).__name__}
    return {"ok": bool(nb), "symbol": sym, "d": row["d"], "n_cs": row.get("n_cs"), "extremes": extremes(row),
            "analogs": summarize(nb, horizon), "nearest": nb[:10], "horizon": horizon, "crowd": crowd,
            "caveat": "只描述;宇宙是幸存者(死币不在);近邻扎堆,看 clusters 不看 n;crowd 的基率是台账的历史中位,不是信号"}
