"""证据面的「其他产品线」(T-112):World50、山寨龙头腿、灵活组合三本前向账本。

它们**不在登记表 BOOKS 里** —— 登记表的每一本都是配置层(L3)的候选,超额一律对 ①;
这三本是另一条产品线,各有各的基准(World50 的 EW×Mom 对 EW,龙头腿的挑法对门内等权),
放进 L3 会让 World50 和加密账本在同一个凯利里抢权重,那不是 Jazz 定的结构(灵活组合 35 / 50 / 15 是恒定配比)。

口径与 `proof.proof_rows` 一致:前向窗口从开账日起(开账日是第一天收益的起点)、超额 = 日收益之差、
任意时刻有效下界用配置层同一个 `evidence`。开账之前每一行写 `not_started` 与开账日,不写空。
**不下结论句**(S-491)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import pandas as pd

from src.data.allocation.allocator import MIN_DAYS, evidence

FORWARD_START = "2026-12-31"


@dataclass(frozen=True)
class Line:
    id: str
    line: str
    name: str
    thesis: str
    series: str                 # navs 里的键
    benchmark: Optional[str]    # navs 里的键;None = 只报自身
    also: tuple[str, ...] = ()  # 另报的同窗口对照(只给收益,不算下界)


LINES: tuple[Line, ...] = (
    Line("world50_ewxmom", "world50", "World50 equal weight, momentum-tilted (quarterly 6 + 12 month)",
         "The 50 largest listed assets (companies, gold, crypto) held equally, tilted toward the stronger half (S-581 / S-584).",
         "world50:EWxMom", "world50:EW"),
    Line("world50_ew", "world50", "World50 equal weight",
         "The 50 largest listed assets held equally; the reference for the momentum tilt.", "world50:EW", None),
    Line("alt_top6", "alt_leaders", "Alt leaders, six by fundamentals + flows + size - volatility",
         "Inside the leader gate (top 15 non-BTC, calm, not diluting), pick six by the pre-registered score (S-589).",
         "alt_leaders:TOP6", "alt_leaders:GATE_EW", ("alt_leaders:ETH", "core")),
    Line("alt_fo6", "alt_leaders", "Alt leaders, six by fundamentals + flows",
         "Same gate; pick six by fundamentals and flows only (S-591).",
         "alt_leaders:FO6", "alt_leaders:GATE_EW", ("alt_leaders:ETH", "core")),
    Line("alt_gate_ew", "alt_leaders", "Alt leader gate, equal weight",
         "Every name that passes the leader gate, held equally; the reference for both pickers.",
         "alt_leaders:GATE_EW", "core", ("alt_leaders:ETH",)),
    Line("flex_35_50_15", "flex", "Flexible mix at its constant weights: 35% core crypto / 50% World50 / 15% cash",
         "A constant mix of the two forward books; the allocation engine did not separate from it (S-585).",
         "flex:CONST_35_50_15", None, ("core", "world50:EWxMom")),
)


def _window(s: Optional[pd.Series], asof: pd.Timestamp, start: str = FORWARD_START) -> Optional[pd.Series]:
    if s is None:
        return None
    s = s.dropna().sort_index()
    return s[(s.index >= pd.Timestamp(start)) & (s.index <= asof)]


def _ret(s: Optional[pd.Series]) -> Optional[float]:
    if s is None or len(s) < 2:
        return None
    return float(s.iloc[-1] / s.iloc[0] - 1)


def _same_window(ref: Optional[pd.Series], w: pd.Series) -> Optional[pd.Series]:
    if ref is None or len(w) < 2:
        return None
    r = ref.dropna().sort_index()
    seg = r[(r.index >= w.index[0]) & (r.index <= w.index[-1])]
    if len(seg) < 2 or (seg.index[0] - w.index[0]).days > 3 or (w.index[-1] - seg.index[-1]).days > 3:
        return None
    return seg


def other_line_rows(navs: Mapping[str, Optional[pd.Series]], asof: pd.Timestamp,
                    lines: tuple[Line, ...] = LINES, start: str = FORWARD_START) -> list[dict[str, Any]]:
    """纯函数。`navs`:{'world50:EW': Series, 'alt_leaders:TOP6': Series, ..., 'core': Series}。"""
    out = []
    for ln in lines:
        row: dict[str, Any] = {"id": ln.id, "line": ln.line, "name": ln.name, "thesis": ln.thesis,
                               "opens": start, "benchmark": ln.benchmark}
        if asof < pd.Timestamp(start):
            row.update({"evidence_class": "not_started", "note": f"Forward record opens on {start}; nothing is recorded before it."})
            out.append(row)
            continue
        w = _window(navs.get(ln.series), asof, start)
        if w is None or w.empty:
            row.update({"evidence_class": "no_record", "note": "NAV could not be read - this is not a zero"})
            out.append(row)
            continue
        n = max(0, len(w) - 1)
        row.update({"evidence_class": "forward" if n >= MIN_DAYS else "forward_young", "forward_days": n,
                    "window": [w.index[1].date().isoformat(), w.index[-1].date().isoformat()] if len(w) >= 2 else None,
                    "total_return": _ret(w)})
        if ln.benchmark:
            b = _same_window(navs.get(ln.benchmark), w)
            br = _ret(b)
            ev = evidence(w, b) if b is not None else {"n_days": 0}
            row.update({"benchmark_return_same_window": br,
                        "excess_vs_benchmark": (row["total_return"] - br) if row["total_return"] is not None and br is not None else None,
                        "excess_ann": ev.get("mu"), "excess_vol_ann": ev.get("sigma"),
                        "anytime_lower_bound_ann": ev.get("mu_lo_cs")})
        row["also_same_window"] = {k: _ret(_same_window(navs.get(k), w)) for k in ln.also}
        out.append(row)
    return out


HOW_TO_READ_OTHER = {
    "line": "Product lines kept apart from the crypto allocation layer: each has its own benchmark and none competes for "
            "the core's weight.",
    "opens": "The forward record starts on this date. Earlier numbers anywhere else are replay, not evidence.",
    "excess_vs_benchmark": "Total return minus the named benchmark's over the same window (world50: momentum tilt vs equal "
                           "weight; alt leaders: each picker vs every name in the gate; the gate vs the crypto core).",
    "also_same_window": "Other references over the same window, returns only (ETH, the crypto core, the World50 book).",
}


async def load_other_navs() -> dict[str, pd.Series]:
    """world50_book_nav 与 forward_book_nav → {'world50:EW': ..., 'alt_leaders:TOP6': ..., 'flex:CONST_35_50_15': ...}。"""
    from src.data.style.header import _read_all
    out: dict[str, pd.Series] = {}
    for table, book_col in (("world50_book_nav", None), ("forward_book_nav", "book")):
        sel = "d,arm,nav" + (",book" if book_col else "")
        rows = await _read_all(table, {"select": sel, "order": "d.asc"})
        groups: dict[str, list] = {}
        for r in rows or []:
            if r.get("nav") is None:
                continue
            key = f"{r['book'] if book_col else 'world50'}:{r['arm']}"
            groups.setdefault(key, []).append((r["d"], float(r["nav"])))
        for k, pts in groups.items():
            s = pd.Series([v for _, v in pts], index=pd.to_datetime([d for d, _ in pts]))
            out[k] = s[~s.index.duplicated(keep="last")].sort_index()
    return out
