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


__all__ = ["phase_distance"]
