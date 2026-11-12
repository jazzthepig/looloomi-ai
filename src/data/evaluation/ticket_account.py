"""单票账本的账户内核 —— 一批已经定好进出场的票,放进一个有名额、有名义上限的账户,逐日记账(11-13,S-828 之后)。

## 为什么放进 src

一周之内,研究里手写的逐日账本出了三次同一类错:T-256 的 sleeve_nav(同日进出的票永不平仓,18 张只成交 2 张)、
T-342(日历日的永续盈亏喂进只含工作日的表,周末全丢)、`t251_gross_cap.simulate`(进场当天被止损的票永不出场,塞满 14 个名额 ——
据此得出的「R-v2 的钱等于一张票」「40% 上限不咬合」「名额 14 好于 10」全是假的,S-828)。三份「一致」的复算 import 的是同一个函数。
修好之后有两台研究引擎(B 道 `docs/research/t352_engine.py`、A 道 `docs/research/t353_engine.py`),都在 docs/ 里、都没有单元测试。
这里是第三台:**有不变量、有测试、谁都能 import 的那一台**。研究与前向记账(S-831 的新旧尺寸并排)从此用它。

## 语义(与主机的 `exec_host.tickets` 同一套尺寸规则)

每一天按这个顺序:
1. **开盘出场**:出场原因是 stop / sma20、且出场日晚于进场日的票,按 `exit_px` 平;
2. **进场**:按(信号日, 币)排序;名额满 ⇒ 挡;同币已在场 ⇒ 挡;`名义 = 开盘净值 × risk_frac ÷ stop_frac`,单票不超过净值一半;
   低于 `min_notional` ⇒ 挡;加上它名义合计超过 `开盘净值 × gross_cap` ⇒ 挡(整张不进,不截断);
3. **同日出场**:进场当天就出场的票(当根被止损)—— **必须排在进场之后**,这就是 S-828;
4. **收盘出场**:其余原因(到期、停更)按 `exit_px` 平;
5. 收盘盯市记净值。
成本:来回 `cost`(默认 0.4%),一半在持仓期间挂在净值上、出场时一次结清。

## 不变量(`strict=True` 时违反即抛)

- 没有一张票在自己的出场日之后还在场;
- 窗口末还在场的票,出场日都晚于最后一天或为空;
- 成交的票 = 已了结的 + 窗口末还在场的(一张不多、一张不少)。

纯函数;取价由调用方给(`mark(symbol, day, use_open)`),`marks_from_bars` 是常用的那一种(当天没有就用之前最近一根的收盘)。
"""
from __future__ import annotations

import bisect
import datetime as dt
from collections import defaultdict
from typing import Any, Callable, Iterable, Optional

OPEN_EXIT_REASONS = ("stop", "sma20")
STOP_ATR = 2.5
Mark = Callable[[str, str, bool], Optional[float]]


def marks_from_bars(bars: dict[str, list]) -> Mark:
    """bars = {symbol: [[d, o, h, l, c, ...], ...]} → mark(symbol, day, use_open)。当天没有 bar ⇒ 之前最近一根的收盘;再没有 ⇒ None。"""
    om = {s: {r[0]: float(r[1]) for r in rows} for s, rows in bars.items()}
    cm = {s: {r[0]: float(r[4]) for r in rows} for s, rows in bars.items()}
    ds = {s: sorted(cm[s]) for s in bars}

    def mark(sym: str, day: str, use_open: bool) -> Optional[float]:
        px = (om if use_open else cm).get(sym, {}).get(day)
        if px is not None:
            return px
        d = ds.get(sym) or []
        i = bisect.bisect_right(d, day) - 1
        return cm[sym][d[i]] if i >= 0 else None
    return mark


def stop_frac_of(t: dict, stop_atr: float = STOP_ATR) -> Optional[float]:
    """主机计划里的止损距离占比:有信号日的 ATR 与收盘就用 stop_atr × ATR ÷ 收盘,否则用(进场价 − 止损价)÷ 进场价。"""
    try:
        if t.get("ref_close"):
            return stop_atr * float(t["atr14"]) / float(t["ref_close"])
        return (float(t["entry_px"]) - float(t["stop_px"])) / float(t["entry_px"])
    except (TypeError, ValueError, ZeroDivisionError, KeyError):
        return None


def simulate(tickets: Iterable[dict], mark: Mark, *, risk_frac: float, gross_cap: Optional[float], cap_n: int,
             equity0: float = 1.0, cost: float = 0.004, min_notional: float = 0.0, stop_atr: float = STOP_ATR,
             max_single_frac: float = 0.5, qty_round: Optional[Callable[[float, float], float]] = None,
             last_day: Optional[str] = None, strict: bool = True) -> dict[str, Any]:
    """纯函数。tickets:每张要有 tid / symbol / signal_d / entry_d / entry_px / stop_px(或 atr14 + ref_close)/ exit_d / exit_px / exit_reason。
    返回 curve [(day, 收盘净值, 在场张数, 名义合计)]、taken、blocked(按原因)、gross_ratio(每天进场后的名义 ÷ 开盘净值)、realized。"""
    tks = [t for t in tickets if t.get("entry_d") and t.get("entry_px")]
    entries: dict[str, list] = defaultdict(list)
    ex_open: dict[str, list] = defaultdict(list)
    ex_same: dict[str, list] = defaultdict(list)
    ex_close: dict[str, list] = defaultdict(list)
    for t in tks:
        entries[t["entry_d"]].append(t)
        if t.get("exit_d") and t.get("exit_px") is not None:
            if t["exit_d"] == t["entry_d"]:
                ex_same[t["exit_d"]].append(t)
            elif t.get("exit_reason") in OPEN_EXIT_REASONS:
                ex_open[t["exit_d"]].append(t)
            else:
                ex_close[t["exit_d"]].append(t)
    for d in entries:
        entries[d].sort(key=lambda t: (str(t.get("signal_d") or ""), t["symbol"]))
    if not tks:
        return {"curve": [], "taken": set(), "blocked": {}, "gross_ratio": [], "realized": 0.0, "open_at_end": []}
    d0 = dt.date.fromisoformat(min(entries))
    d1 = dt.date.fromisoformat(last_day or max([t["exit_d"] for t in tks if t.get("exit_d")] + [max(entries)]))
    book: dict[Any, dict] = {}
    held: set[str] = set()
    realized = 0.0
    taken: set = set()
    blocked: dict[str, list] = {"cap": [], "coin": [], "min": [], "gross": []}
    curve, gross_ratio = [], []
    n_closed = 0

    def equity(day: str, use_open: bool) -> float:
        e = equity0 + realized
        for p in book.values():
            px = mark(p["symbol"], day, use_open)
            if px is not None:
                e += p["qty"] * (px - p["entry_px"]) - p["qty"] * (cost / 2) * p["entry_px"]
        return e

    def close(t: dict) -> None:
        nonlocal realized, n_closed
        p = book.pop(t["tid"], None)
        if p is None:
            return
        pnl = p["qty"] * (float(t["exit_px"]) - p["entry_px"] - cost * p["entry_px"])
        realized += pnl
        n_closed += 1
        held.discard(p["symbol"])

    day = d0
    while day <= d1:
        ds = day.isoformat()
        for t in ex_open.get(ds, []):
            close(t)
        eq_open = equity(ds, True)
        gross = 0.0
        for p in book.values():
            px = mark(p["symbol"], ds, True)
            gross += p["qty"] * (px if px is not None else p["entry_px"])
        limit = eq_open * gross_cap if gross_cap is not None else float("inf")
        for t in entries.get(ds, []):
            if len(book) >= cap_n:
                blocked["cap"].append(t["tid"])
                continue
            if t["symbol"] in held:
                blocked["coin"].append(t["tid"])
                continue
            sf, mid = stop_frac_of(t, stop_atr), mark(t["symbol"], ds, True)
            if not mid or mid <= 0 or sf is None or not (0 < sf < 0.9):
                blocked["min"].append(t["tid"])
                continue
            target = min(eq_open * risk_frac / sf, eq_open * max_single_frac)
            qty = qty_round(target / mid, mid) if qty_round else target / mid
            n = qty * mid
            if n < min_notional or qty <= 0:
                blocked["min"].append(t["tid"])
                continue
            if gross + n > limit:
                blocked["gross"].append(t["tid"])
                continue
            gross += n
            book[t["tid"]] = {"symbol": t["symbol"], "entry_px": float(t["entry_px"]), "qty": qty, "exit_d": t.get("exit_d")}
            held.add(t["symbol"])
            taken.add(t["tid"])
        gross_ratio.append((ds, gross / eq_open if eq_open > 0 else 0.0))
        for t in ex_same.get(ds, []):
            close(t)
        for t in ex_close.get(ds, []):
            close(t)
        if strict:
            late = [k for k, p in book.items() if p["exit_d"] and p["exit_d"] <= ds]
            assert not late, f"不变量:{ds} 收盘后仍有已到出场日的票在场 {late[:5]}"
        curve.append((ds, equity(ds, False), len(book), gross))
        day += dt.timedelta(days=1)
    if strict:
        assert n_closed + len(book) == len(taken), f"不变量:成交 {len(taken)} 张 ≠ 已了结 {n_closed} + 在场 {len(book)}"
        last = d1.isoformat()
        assert all((not p["exit_d"]) or p["exit_d"] > last for p in book.values()), "不变量:窗口末在场的票里有出场日不晚于最后一天的"
    return {"curve": curve, "taken": taken, "blocked": blocked, "gross_ratio": gross_ratio, "realized": realized,
            "open_at_end": sorted(book)}
