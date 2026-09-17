"""相位距离 —— 把 5b 的检索结果变成 `vdb_distance` 那个槽位要的数 (S-366)。

## 这条接线补的是什么

`beta_core_size.regime_band(vdb_distance)` 早就写好了,而且 I1 处理得很讲究:

    NaN/None → band 3 (mid-tail, default, conservative). Per I1: don't
    silently default to band 1 (in-distribution) where missing data would
    look like a strong daily claim.

**而传真值的调用方只有测试 —— 生产传的是 None。** 于是 ⓠ 的 sizing 层
每天都落在"我不知道"那一档,**并且看起来和正常工作一模一样**,
因为那个默认被设计成安全的,而安全的默认是隐形的。

MEMORY.md 早就写下了这条:**默认值越接近多数类越查不出 —— 危害与可发现性
成反比**(S-122)。这次它兑现在一个**为它设计的槽位上**:
`beta_core_nav_q.vdb_distance` 26 行全是 NULL,`beta_core_nav_size` 0 行。

## 只用 5b,不合成两个角度

SPINE §4:5a 宏观(15 实测维)与 5b 微观(11 维 CIS)**数值不可比、不可平均**。
这里要的是一个标量「今天有多在分布内」,所以取 **5b**:
  · 它挂在每日更新的 `regime_daily` 上(5a 的底表停 42 天)
  · 11 维全部是实测 CIS 量,可解释
5a 的读数**另行记录**,不折进这个数 —— 折进去就又造了一个不可比的平均。

## 距离的定义与值域

`distance = 1 − cosine`。z 化后的余弦 ∈ [−1, 1],所以距离 ∈ [0, 2];
**>1 会被 `regime_band` 夹到 band 5(分布外),那是对的** —— 一个和历史
反相关的日子确实是分布外,不该因为超出 [0,1] 就被当成缺失。

实测 2026-09-16 的近 12 天:0.113 … 0.446,落在 band 1/2/3,**有区分度**。
对照生产现状:每天 band 3。

## 读不到 ≠ 在分布内

任何一步失败都返回 `None`,让下游走它自己的保守默认(band 3)。
**不要在这里编一个距离** —— 编出来的那个数会以一个日度断言的形状进入 sizing。
"""
from __future__ import annotations

import os
from typing import Any, Optional


async def phase_distance(
    d: Optional[str] = None,
    *,
    exclude_days: int = 30,
) -> tuple[Optional[float], dict[str, Any]]:
    """(distance, diag)。`distance is None` ⇒ 读不到,**不是"在分布内"**。

    `diag` 一定带 `reason`(失败时)或 `best_sim`/`best_day`(成功时),
    以及 `regime_match` 自己的 `n_excluded_incomplete` —— **那是覆盖缺口,
    不是"不像"**,必须原样透出。
    """
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not (base and key):
        return None, {"reason": "SUPABASE_URL / SUPABASE_KEY not set on this process"}

    try:
        import httpx

        from src.data.vector.regime_match import most_similar

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{base}/rest/v1/regime_daily",
                params={"select": "d,features,regime_db,n_universe,"
                                  "meditation_regime,meditation",
                        "order": "d.asc", "limit": "2000"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return None, {"reason": f"HTTP {r.status_code}: {r.text[:140]}"}
        rows = r.json()
        if not rows:
            return None, {"reason": "regime_daily 返回 0 行 —— 空 ≠ 在分布内"}

        target = d or max(x["d"] for x in rows)
        hits, diag = most_similar(target, rows, k=5, exclude_days=exclude_days)
        if not hits:
            diag["reason"] = diag.get("error") or "没有可比的历史日"
            return None, diag

        best = hits[0]
        return (1.0 - float(best["sim"])), {
            **diag,
            "target": target,
            "best_day": best["d"],
            "best_sim": round(float(best["sim"]), 4),
            "best_regime": best.get("regime_db"),
            "best_has_meditation": bool(best.get("meditation")),
        }
    except Exception as e:                                        # noqa: BLE001
        return None, {"reason": f"{type(e).__name__}: {str(e)[:140]}"}


#: ⚠️ **`DWELL_DAYS` 和中位数滤波器都不在这里** —— 它们在
#: `beta_core_q_overlay`(`DWELL_DAYS = 5`,`apply_dwell_filter()`,M-WO-7.1 验过、有测试)。
#:
#: 我 2026-09-17 第一版在这个文件里**又定义了一遍 `DWELL_DAYS = 5`、又手写了一遍
#: `statistics.median`** —— 写完才看见 overlay 里早就有。那就是 SPINE 第一条法律
#: 禁止的「一个能力两条活路」:**两份 spec 常量,改一份不改另一份,而它们长得一样。**
#: 现在这里只做**取数**,滤波复用 overlay 那一份。
#: (`apply_dwell_filter` 此前**零生产调用方**,只有测试在调 —— 和 `phase_distance`
#: 本身一样,是「建好了没接」的同一族。这次一起接上。)

#: 5 天里至少要有这么多天算得出距离,否则返回 None。
#: **为什么要这条:** 中位数取在 1 个点上就是那个点本身 —— 它会把一个 raw 值
#: 冒充成 smoothed 值送进 sizing,而类型、字段名、日志全都看不出区别。
#: 这是 S-367「enforcer vs overlay」的同一个形状:**槽位的名字说了一件事,
#: 塞进去的是另一件**。地板不是保守,是让「没平滑」和「平滑了」不同形。
MIN_USABLE_DAYS = 3


async def smoothed_phase_distance(
    d: Optional[str] = None, *, exclude_days: int = 30,
) -> tuple[Optional[float], dict]:
    """§C2-SHIP-SPEC 的 `dwell_filter`:取最近 `DWELL_DAYS` 天的 `phase_distance`,
    交给 `beta_core_q_overlay.apply_dwell_filter()`(5 日滚动中位)。

    返回 `(smoothed, diag)`。**`smoothed is None` ⇒ 算不出,不是"在分布内"**(I1)。
    下游 `is_vdb_failure(None)` 会兜回 baseline 1.0,那是正确的保守行为。

    `diag` 带 `per_day`(逐日原值,含 None)、`n_usable`、`raw_today`,
    **让"平滑了几个点"在调用方可见** —— 不然 5 个点和 1 个点的中位数在库里长得一样。
    """
    import datetime as _dt

    import pandas as _pd

    from src.data.signals.beta_core_q_overlay import DWELL_DAYS, apply_dwell_filter

    base = _dt.date.fromisoformat(d) if d else None
    per_day: list[dict] = []
    idx: list[_dt.date] = []
    vals: list[float] = []
    raw_today: Optional[float] = None

    for i in range(DWELL_DAYS):
        day = (base - _dt.timedelta(days=i)).isoformat() if base else None
        dist, dg = await phase_distance(day, exclude_days=exclude_days)
        tgt = dg.get("target")
        per_day.append({"asked": day, "target": tgt,
                        "distance": dist, "reason": dg.get("reason")})
        if i == 0:
            raw_today = dist
        if dist is not None and tgt:
            idx.append(_dt.date.fromisoformat(tgt))
            vals.append(dist)
        if base is None:
            # 没给日期 ⇒ phase_distance 每次返回同一个最新日,循环 5 次没意义。
            # 用它 target 那天当基准,从下一轮起往回数。
            if not tgt:
                break
            base = _dt.date.fromisoformat(tgt)

    diag = {"dwell_days": DWELL_DAYS, "n_usable": len(vals),
            "min_usable": MIN_USABLE_DAYS, "per_day": per_day,
            "raw_today": raw_today}
    if len(vals) < MIN_USABLE_DAYS:
        diag["reason"] = (f"{DWELL_DAYS} 天里只有 {len(vals)} 天算得出 "
                          f"< {MIN_USABLE_DAYS} —— 不足以平滑,不冒充 smoothed")
        return None, diag

    ser = _pd.Series(vals, index=_pd.DatetimeIndex(idx)).sort_index()
    smoothed = apply_dwell_filter(ser, dwell_days=DWELL_DAYS)
    return float(smoothed.iloc[-1]), diag


__all__ = ["phase_distance", "smoothed_phase_distance"]
