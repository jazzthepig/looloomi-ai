"""证据面(T-053):把 ① 与每本账的前向证据按证据等级摆到门外 —— 外部 agent 一次调用就能回答
「哪本账有前向证据、相对 ① 怎样、配置层为什么给它这个权重」。

口径与配置层(L3)完全相同:窗口 = `allocator.INCEPTION` 起(或账本自己的首日,取晚者),
超额 = 账本日收益 − ① 日收益,下界 = l3-v2 的任意时刻有效下界(不是固定 2 标准误)。
**这里不下任何结论句** —— 每个数字旁边写清楚它是哪一类证据,读者自己判断(S-491 的教训)。

证据等级:
    forward          前向记录,且已满 MIN_DAYS 天(能进配置层的门槛检查)
    forward_young    前向记录,不满 MIN_DAYS 天(只描述,不评估)
    caveat           账本有已知问题,数字不可信(写明原因)
    retired          按设计退役
    no_record        读不到 NAV(不是 0)
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd

from src.data.allocation.allocator import CORE, INCEPTION, MIN_DAYS, evidence, forward_window


def evidence_class(status: str, caveat: str, n_days: int) -> str:
    if status == "retired_by_design":
        return "retired"
    if caveat:
        return "caveat"
    return "forward" if n_days >= MIN_DAYS else "forward_young"


def proof_rows(books: list, navs: Mapping[str, Optional[pd.Series]], core: Optional[pd.Series],
               alloc: Mapping[str, Mapping[str, Any]], asof: pd.Timestamp) -> list[dict]:
    """纯函数。`books`:登记表的 Book;`alloc`:配置层最新一天 {book: {weight, d}}。"""
    core_w = forward_window(core, asof)
    out = []
    for b in books:
        nav = navs.get(b.id) if b.id != CORE else core
        row: dict[str, Any] = {"id": b.id, "layer": b.layer, "name": b.name, "thesis": b.cause}
        if nav is None or nav.dropna().empty:
            row.update({"evidence_class": "no_record", "note": "NAV could not be read - this is not a zero"})
            out.append(row)
            continue
        w = forward_window(nav, asof)
        ev = evidence(w, core_w) if b.id != CORE else {"n_days": max(0, len(w.dropna()) - 1) if w is not None else 0}
        n = int(ev.get("n_days") or 0)
        s = w.dropna() if w is not None else pd.Series(dtype=float)
        total = float(s.iloc[-1] / s.iloc[0] - 1) if len(s) >= 2 else None
        cs = core_w.dropna() if core_w is not None else pd.Series(dtype=float)
        seg = cs[(cs.index >= s.index[0]) & (cs.index <= s.index[-1])] if len(s) >= 2 and len(cs) else cs.iloc[0:0]
        core_ret = float(seg.iloc[-1] / seg.iloc[0] - 1) if len(seg) >= 2 else None
        a = alloc.get(b.id) or {}
        row.update({
            "evidence_class": evidence_class(b.status, b.caveat, n),
            "caveat": b.caveat or None,
            "window": [s.index[1].date().isoformat(), s.index[-1].date().isoformat()] if len(s) >= 2 else None,   # 首日是收益的起点,不算一天
            "forward_days": n,
            "total_return": total,
            "core_return_same_window": core_ret,
            "excess_vs_core": (total - core_ret) if total is not None and core_ret is not None else None,
            "excess_ann": ev.get("mu"), "excess_vol_ann": ev.get("sigma"),
            "anytime_lower_bound_ann": ev.get("mu_lo_cs"),
            "l3_weight": a.get("weight", 0.0 if b.id != CORE else None),
            "l3_as_of": a.get("d"),
        })
        out.append(row)
    return out


HOW_TO_READ = {
    "window": f"The allocation layer's forward window: from {INCEPTION} (or the book's first day, whichever is later). "
              "Earlier history is not shown here - some of it is after-the-fact replay, not evidence.",
    "excess_vs_core": "Book total return minus the core's (24 names, market-cap weighted, single coin <= 40%, spot only) "
                      "over the same window. The benchmark is always holding the core, never zero.",
    "anytime_lower_bound_ann": "Anytime-valid lower bound on the mean daily excess, annualised: re-checking it daily does not "
                               f"inflate it. The allocation layer gives a book weight only when this is > 0 and the book has "
                               f">= {MIN_DAYS} forward days; the weight is also shrunk toward 0 first.",
    "evidence_class": "forward | forward_young (< 60 forward days, descriptive only) | caveat (known issue, numbers not "
                      "reliable) | retired | no_record (could not be read - not a zero).",
    "l3_weight": "Weight the allocation layer gave this book on its latest day; the core takes the rest.",
}
