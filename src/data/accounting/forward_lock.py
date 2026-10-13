"""前向记录冻结 —— 锚定过的一天,表里就不再变(S-560)。

## 为什么

六个写入端(core_variants / meta_allocator / feature_arms / multiplier / portfolio_layer / 配置层)每一轮都从回放起点
整条重算、整条 upsert。回放行(起点之前)每天重算没问题 —— 那是模拟;但前向行也跟着被重写:配置层的 `why`
每天换一遍,meta_knn 与 core_variants 的前向 nav / ret 随上游修订而变。10-13 核 T-073 时,6 个锚里前向行被改过的有三张表。
「可验证的前向记录就是产品」,一条记了又改的记录不是记录。

## 规则

- 前向行 = d ≥ 该行的 inception(没有 inception 列的表 = 全是前向)。
- **截止日 = 今天(UTC)− 2。** d ≤ 截止日的前向行一旦在表里,就不再改写;缺的可以晚到补写(循环宕过几天),
  晚到在锚里会显示为「锚后补进」,与「改过」分开报。
- 截止日之后的前向行照写(当天收盘可能还在修订);它们的 NAV 从同一 key 前一行(表里的最终状态)接着乘本轮的 ret
  —— 前面的冻结行不变,后面的就不能按重算出来的新水位写。
- 回放行(d < inception)照写,不锚。
- 锚定「今天 − 2」那一天(anchor.py,= 刚冻结的那天)。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

FINAL_LAG_DAYS = 2


def cutoff(today: date) -> str:
    """d ≤ 这一天的前向行已冻结。"""
    return (today - timedelta(days=FINAL_LAG_DAYS)).isoformat()


def is_forward(row: dict) -> bool:
    inc = row.get("inception")
    return not inc or str(row["d"]) >= str(inc)


def lock_rows(rows: list[dict], stored: list[dict], key: Optional[str], today: date, *,
              nav: Optional[str] = "nav", ret: Optional[str] = "ret",
              day_level: bool = False) -> tuple[list[dict], dict[str, int]]:
    """纯函数。rows = 本轮整条算出的行;stored = 表里已有的行(至少 d、key、nav,有就带 inception)。

    返回 (要写的行, 统计)。day_level=True:同一天表里有任何一行就整天冻结(配置层:一天一组决定,不能半天换)。
    """
    cut = cutoff(today)
    key_of = (lambda r: r.get(key)) if key else (lambda r: None)
    have_rows = {(str(r["d"]), key_of(r)) for r in stored}
    have_days = {str(r["d"]) for r in stored}
    stats = {"replay": 0, "frozen_skipped": 0, "late_inserted": 0, "written_forward": 0, "rechained": 0}
    out: list[dict] = []
    fwd: dict[Any, list[dict]] = {}
    for r in rows:
        if not is_forward(r):
            stats["replay"] += 1
            out.append(r)
            continue
        d = str(r["d"])
        exists = (d in have_days) if day_level else ((d, key_of(r)) in have_rows)
        if d <= cut and exists:
            stats["frozen_skipped"] += 1
            continue
        if d <= cut:
            stats["late_inserted"] += 1
        stats["written_forward"] += 1
        fwd.setdefault(key_of(r), []).append(r)
    if nav and ret:
        for k, todo in fwd.items():
            inc = str(todo[0].get("inception") or "")
            written = {str(r["d"]) for r in todo}
            final = {str(s["d"]): float(s[nav]) for s in stored
                     if key_of(s) == k and s.get(nav) is not None and str(s["d"]) >= inc and str(s["d"]) not in written}
            for r in sorted(todo, key=lambda x: str(x["d"])):
                d = str(r["d"])
                prev = max((x for x in final if x < d), default=None)
                if prev is not None and r.get(ret) is not None:
                    new = round(final[prev] * (1 + float(r[ret])), 8)
                    if r.get(nav) is None or abs(float(r[nav]) - new) > 1e-12:
                        stats["rechained"] += 1
                    r = {**r, nav: new}
                if r.get(nav) is not None:
                    final[d] = float(r[nav])
                out.append(r)
    else:
        for todo in fwd.values():
            out.extend(todo)
    return out, stats


async def write_locked(table: str, rows: list[dict], *, key: Optional[str], on_conflict: str,
                       nav: Optional[str] = "nav", ret: Optional[str] = "ret", day_level: bool = False,
                       has_inception: bool = True, today: Optional[date] = None,
                       chunk: int = 2000) -> dict[str, Any]:
    """读表里已有的前向行 → lock_rows → 分块 upsert。返回 {ok, written, why?, lock: 统计}。读不到就不写(读不到 ≠ 没有)。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = today or datetime.now(timezone.utc).date()
    fwd = [r for r in rows if is_forward(r)]
    stored: list[dict] = []
    if fwd:
        start = min(str(r["d"]) for r in fwd)
        cols = ["d"] + ([key] if key else []) + ([nav] if nav else []) + (["inception"] if has_inception else [])
        try:
            stored = await _read_all(table, {"select": ",".join(cols), "d": f"gte.{start}"})
        except Exception as e:  # noqa: BLE001 — 读不到已有行就不知道哪些冻结了:不写,报出来
            return {"ok": False, "written": 0, "why": f"读 {table} 已有前向行失败:{type(e).__name__}: {e}"}
    out, st = lock_rows(rows, stored, key, today, nav=nav, ret=ret, day_level=day_level)
    for i in range(0, len(out), chunk):
        res = await supabase_upsert_table(table, out[i:i + chunk], on_conflict=on_conflict)
        if not res.ok:
            return {"ok": False, "written": i, "why": res.why, "lock": st}
    return {"ok": True, "written": len(out), "lock": st}
