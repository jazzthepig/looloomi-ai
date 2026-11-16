"""S-642 熊市空头臂的**生产纯函数**(无 IO):规则逐条照 `docs/research/t159_bear_short.py`
(`docs/research/s642_bear_short.sql` 的转写),研究出处见 `docs/research/T-407_s642_forward_plan.md`。

规则(逐字照抄研究的默认做法,三个歧义点按研究默认,写死):

- **宇宙**(`universe_ok`):信号日往前满 220 根;ATR14 > 0;ADV30(30 日美元额均值)≥ 5e6;
  (HH40−LL40)/HH40 ≤ 0.40;当日美元额 ≥ 2 × 前 40 日均额(不含当日)。
- **信号**(`signal_short`):close < LL40 且 close < SMA200 且**闸门关**。
  `mindd120` 没有空头镜像(规则写成那样时还没做那个检验)——这里也不加。
- **闸门**:**复用** `src/data.signals.short_paper.gate_closed_by_day`(majors cap 指数 ≤ 自身 200 日均值),
  本模块**不重写**闸门(重写就会出现两个闸门,以后必然分叉)。
- **进场**:信号日收盘后,下一根 K 线开盘成交(entry = open[i+1]);止损 = entry + 2.5 × ATR14(**信号日**那根)。
- **出场**:持有中自进场日起最多 120 根,先到者为准 —— high ≥ stop ⇒ 止损出场;close > SMA20 ⇒ **次日开盘**出场;
  都没有 ⇒ 时间出场(到第 120 根收盘)。同一根里 stop 与 sma20 都触发 ⇒ **stop 优先**(歧义点 ①)。
- **跳空**:止损那根若 open ≥ stop 按 open 成交,否则按 stop 成交;**进场当日就打到 stop ⇒ 按 stop 价成交**(歧义点 ③)。
- **串链**:同一 symbol 的票按进场序串起来,后一张的进场必须晚于前一张的出场,重叠的票被丢掉。
- **成本**:0.4%(双边,以价格计),R = (entry−exit)/(stop−entry) − 0.004 × entry/(stop−entry)。
- **钱**(`nav`):每票风险 0.5% 净值、最多同时 10 张、逐日盯市、复利;**成本始终是借记**(abs(units))——
  2026-10-25 之前写成 `units × (… − cost)`,空头(units < 0)会变成 0.4% 的**贷记**,复刻必须用当前口径(歧义点 ② 的账本侧)。
- **资金费**:不进这条曲线(S-642 原文把资金费单列在 R 里),与族曲线同口径。

**输入形状**:直接吃生产表。
`ohlcv_daily`(source='binance_hist')的行:`{"symbol","trade_date","open","high","low","close","volume"}`,
按 trade_date 升序;**美元额 = close × volume**(库里的 `volume` 是币量)。
`style_index_pit_daily`(style='majors', weighting='cap')的行:`{"d","ret"}` → `gate_closed_by_day` → 闸门表。
研究排除了 `USDC / BTCDOM / DEFI`,本模块在 `run_short` 里同样排除。

本模块**不建写入端**、不接任何循环:纸面账(`src/data/universe/state_book.py`)在合并后由 Seth 在 `load_inputs` 里调用。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable, Optional

#: 闸门复用生产那一个(short_paper.py);不重写。
from src.data.signals.short_paper import gate_closed_by_day

__all__ = ["EXCL", "COST", "RISK_FRAC", "CAP", "MAX_BARS", "ATR_MULT", "WARMUP",
           "indicators", "universe_ok", "signal_short", "chain", "run_short", "nav",
           "gate_closed_by_day"]

#: 研究里排除的三个标的(照 `t159_bear_short.py` 的 EXCL)
EXCL = {"USDC", "BTCDOM", "DEFI"}
COST = 0.004            # 双边成本(以价格计);与族曲线同口径
RISK_FRAC = 0.005       # 每票风险 0.5% 净值
CAP = 10                # 同时最多 10 张
MAX_BARS = 120          # 最多持有 120 根
ATR_MULT = 2.5          # 止损 = 进场 + 2.5 × ATR14
WARMUP = 220            # 信号日往前满 220 根


# ── 窗口工具(与研究逐行相同,浮点顺序也一样)─────────────────────────────────────────────────────
def _win(v: list[float], i: int, lo: int, hi: int) -> Optional[float]:
    seg = v[max(0, i - hi): i - lo + 1]
    return sum(seg) / len(seg) if seg else None


def _wmax(v: list[float], i: int, hi: int, lo: int) -> Optional[float]:
    seg = v[max(0, i - hi): i - lo + 1]
    return max(seg) if seg else None


def _wmin(v: list[float], i: int, hi: int, lo: int) -> Optional[float]:
    seg = v[max(0, i - hi): i - lo + 1]
    return min(seg) if seg else None


# ── 指标(只用当天及以前)──────────────────────────────────────────────────────────────────────────
def indicators(rows: Iterable[dict]) -> dict:
    """→ 指标包。`rows` = `ohlcv_daily` 的行(dict):trade_date / open / high / low / close / volume,按日期升序。

    美元额 = close × volume(库里的 volume 是币量)。返回的 dict 里 c/o/h/l/dv/d 是序列,其余是同下标的序列。
    """
    rows = list(rows)
    c = [float(r["close"]) for r in rows]
    h = [float(r["high"]) for r in rows]
    l = [float(r["low"]) for r in rows]
    dv = [float(r["close"]) * float(r["volume"]) for r in rows]
    pc = [rows[i - 1]["close"] if i > 0 else rows[i]["close"] for i in range(len(rows))]
    pc = [float(x) for x in pc]
    tr = [max(h[i] - l[i], abs(h[i] - pc[i]), abs(l[i] - pc[i])) for i in range(len(rows))]
    n = len(rows)
    dd = [c[i] / _wmax(c, i, 365, 0) for i in range(n)]
    return {
        "d": [str(r["trade_date"])[:10] for r in rows],
        "c": c, "o": [float(r["open"]) for r in rows], "h": h, "l": l, "dv": dv,
        "sma20": [_win(c, i, 0, 19) or c[i] for i in range(n)],
        "sma200": [_win(c, i, 0, 199) for i in range(n)],
        "atr14": [_win(tr, i, 0, 13) for i in range(n)],
        "adv30": [_win(dv, i, 0, 29) for i in range(n)],
        "adv40p": [_win(dv, i, 1, 40) for i in range(n)],
        "hh40": [_wmax(h, i, 40, 1) for i in range(n)],
        "ll40": [_wmin(l, i, 40, 1) for i in range(n)],
        "mindd120": [_wmin(dd, i, 120, 0) for i in range(n)],
    }


# ── 宇宙与信号 ─────────────────────────────────────────────────────────────────────────────────
def universe_ok(ind: dict, i: int) -> bool:
    """五条宇宙条件(照 `t159_bear_short.py` 的 `_universe`)。"""
    if i < WARMUP or ind["atr14"][i] is None or ind["atr14"][i] <= 0:
        return False
    if ind["adv30"][i] is None or ind["adv30"][i] < 5e6:
        return False
    hh, ll = ind["hh40"][i], ind["ll40"][i]
    if hh is None or ll is None or hh == 0 or (hh - ll) / hh > 0.40:
        return False
    if ind["adv40p"][i] is None or ind["dv"][i] < 2 * ind["adv40p"][i]:
        return False
    return True


def signal_short(ind: dict, i: int, gate: dict[str, bool]) -> bool:
    """S-642 的空头信号:闸门关 + 跌破前 40 日低 + 收在 200 日线之下 + 宇宙五筛。

    `gate` = `{日期: 闸门关(布尔)}`,由 `short_paper.gate_closed_by_day` 产出(关 = True)。
    """
    if not universe_ok(ind, i):
        return False
    if not (ind["c"][i] < ind["ll40"][i]):
        return False
    if ind["sma200"][i] is None or not (ind["c"][i] < ind["sma200"][i]):
        return False
    return bool(gate.get(ind["d"][i], False))


# ── 开票 / 串链 ─────────────────────────────────────────────────────────────────────────────────
def _open_ticket(ind: dict, i: int, sym: str) -> Optional[dict]:
    """信号下标 i → 一张票(进场 / 止损 / 出场 / 成本)。照 `t159_bear_short.py` 的 `run_short` 逐行。"""
    n = len(ind["d"])
    ei = i + 1
    if ei >= n:
        return None
    entry, stop = ind["o"][ei], ind["o"][ei] + ATR_MULT * ind["atr14"][i]
    if not (entry < stop):
        return None
    k = None
    for j in range(ei, min(i + MAX_BARS, n - 1) + 1):
        if ind["h"][j] >= stop or ind["c"][j] > ind["sma20"][j]:
            k = j
            break
    if k is None:
        xi, xp, still = min(i + MAX_BARS, n - 1), ind["c"][min(i + MAX_BARS, n - 1)], (i + MAX_BARS > n - 1)
        why = "time"
    elif ind["h"][k] >= stop:
        # 止损优先(歧义点 ①);进场当日就打到 stop ⇒ 按 stop 价成交(歧义点 ③)
        xi, xp, still = k, (ind["o"][k] if (k > ei and ind["o"][k] >= stop) else stop), False
        why = "stop"
    elif k + 1 <= n - 1:
        xi, xp, still = k + 1, ind["o"][k + 1], False
        why = "sma20"
    else:
        xi, xp, still = k, ind["c"][k], True
        why = "sma20_open"
    mae = min((ind["h"][x] - entry) for x in range(ei, xi + 1)) if xi > ei else 0.0
    mfe = max((entry - ind["l"][x]) for x in range(ei, xi + 1)) if xi > ei else 0.0
    if still:
        why = "open"
    return {
        "symbol": sym, "signal_d": ind["d"][i], "entry_d": ind["d"][ei],
        "exit_d": None if still else ind["d"][xi],
        "entry_px": entry, "stop_px": stop, "exit_px": None if still else xp,
        "ei": ei, "xi": xi, "exit_reason": why, "bars_held": xi - ei + 1, "still": still,
        "mae_r": None if still else mae / (stop - entry),
        "mfe_r": None if still else mfe / (stop - entry),
        "r": None if still else ((entry - xp) / (stop - entry) - COST * entry / (stop - entry)),
    }


def chain(tickets: Iterable[dict]) -> list[dict]:
    """同一 symbol 的票按进场序串起来:后一张的进场必须晚于前一张的出场,重叠的票被丢掉。"""
    tr: dict[str, list[dict]] = defaultdict(list)
    for t in tickets:
        tr[t["symbol"]].append(t)
    res: list[dict] = []
    for sym, ts in tr.items():
        ts.sort(key=lambda t: t["ei"])
        cur = ts[0]
        res.append(cur)
        while True:
            nxt = [t for t in ts if t["ei"] > cur["xi"]]
            if not nxt:
                break
            cur = nxt[0]
            res.append(cur)
    res.sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return res


def run_short(bars: dict[str, list[dict]], gate: dict[str, bool], d_from: str, d_to: str) -> list[dict]:
    """在 `bars`(symbol → `ohlcv_daily` 的行)上跑 S-642 的空头臂,信号日落在 [d_from, d_to]。

    闸门 `gate` = `{日期: 关(布尔)}`(由 `gate_closed_by_day` 产出)。`USDC / BTCDOM / DEFI` 被排除。
    返回串链后的票(照 `t159_bear_short.py` 的 `run_short` + `_chain`)。
    """
    tr: dict[str, list[dict]] = defaultdict(list)
    for sym, rows in bars.items():
        if sym in EXCL:
            continue
        rows = sorted(rows, key=lambda r: str(r["trade_date"])[:10])
        ind = indicators(rows)
        n = len(ind["d"])
        for i in range(WARMUP, n):
            d = ind["d"][i]
            if not (d_from <= d <= d_to) or not signal_short(ind, i, gate):
                continue
            t = _open_ticket(ind, i, sym)
            if t is not None:
                tr[sym].append(t)
    return chain(t for lst in tr.values() for t in lst)


# ── 钱曲线(逐日盯市)────────────────────────────────────────────────────────────────────────────
def _d1(d: str) -> str:
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def nav(tickets: list[dict], closes: dict[str, list[dict]], f: float = RISK_FRAC, cap: Optional[int] = CAP,
        d_to: Optional[str] = None, compound: bool = True, equity0: float = 1.0,
        drop: Optional[Iterable[str]] = None) -> list[dict]:
    """逐日盯市复利。每票风险 f(默认 0.5%)、同时最多 cap(默认 10)张、先到先得;成本**始终借记**(abs(units))。

    `closes` = {symbol: `ohlcv_daily` 的行}(盯市标记 = 不晚于当日最后一条收盘)。
    照 `t159_bear_short.py` 的 `nav`(plpgsql 内核的转写)逐行;返回每天一行 dict。
    """
    drop = set(drop or ())
    tk = [dict(id=f"{t['symbol']}:{t['signal_d']}", symbol=t["symbol"], signal_d=t["signal_d"],
               entry_d=t["entry_d"], exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
               exit_px=t["exit_px"], state=None, units=0.0) for t in tickets
          if t["entry_d"] and t["entry_px"] != t["stop_px"] and t["symbol"] not in drop]
    if not tk:
        return []
    v_from = min(t["entry_d"] for t in tk)
    if d_to is None:
        d_to = max((t["exit_d"] or t["entry_d"]) for t in tk)
    tk = [t for t in tk if v_from <= t["entry_d"] <= d_to]
    for t in tk:
        if t["exit_d"] and t["exit_d"] > d_to:
            t["exit_d"] = t["exit_px"] = None
    days: list[str] = []
    d = date.fromisoformat(v_from)
    while d.isoformat() <= d_to:
        days.append(d.isoformat())
        d += timedelta(days=1)
    # 标记:symbol → (日期序列, 收盘序列);mark(d) = 不晚于 d 的最后一条收盘
    md = {s: ([str(r["trade_date"])[:10] for r in rows], [float(r["close"]) for r in rows])
          for s, rows in closes.items()}
    path_by_day: dict[str, list] = defaultdict(list)
    for t in tk:
        ds, cs = md.get(t["symbol"], ([], []))
        dd = date.fromisoformat(t["entry_d"])
        last = date.fromisoformat((date.fromisoformat(t["exit_d"]) - timedelta(days=1)).isoformat()
                                   if t["exit_d"] else d_to)
        while dd <= last:
            k = _bisect_right(ds, dd.isoformat()) - 1
            if k >= 0:
                path_by_day[dd.isoformat()].append((t, cs[k]))
            dd += timedelta(days=1)
    for t in tk:
        t["_pmap"] = {}
    for d, lst in path_by_day.items():
        for t, m in lst:
            t["_pmap"][d] = m
    for v_e in sorted({t["entry_d"] for t in tk}):
        prev = _d1(v_e)
        eq_prev = equity0
        for k in tk:
            if k["state"] != "taken":
                continue
            # 成本永远是借记:abs(units)。2026-10-25 之前这里写成 units × (… − cost),空头(units < 0)
            # 会把 0.4% 的双边变成 0.4% 的**贷记** —— 每条空头钱曲线都被抬高过。复刻必须用当前口径。
            if k["exit_d"] and k["exit_d"] <= prev:
                eq_prev += k["units"] * (k["exit_px"] - k["entry_px"]) - abs(k["units"]) * COST * k["entry_px"]
            elif prev in k["_pmap"]:
                eq_prev += k["units"] * (k["_pmap"][prev] - k["entry_px"]) - abs(k["units"]) * (COST / 2) * k["entry_px"]
        occ = sum(1 for k in tk if k["state"] == "taken" and k["entry_d"] < v_e
                  and (k["exit_d"] is None or k["exit_d"] >= v_e))
        taken_today = 0
        for k in sorted([k for k in tk if k["entry_d"] == v_e], key=lambda x: (x["signal_d"], x["symbol"])):
            if cap is None or occ + taken_today < cap:
                k["state"] = "taken"
                k["units"] = f * (eq_prev if compound else equity0) / (k["entry_px"] - k["stop_px"])
                taken_today += 1
            else:
                k["state"] = "skipped"
    exits_by_day: dict[str, float] = defaultdict(float)
    closes_by_day: dict[str, int] = defaultdict(int)
    for k in tk:
        if k["state"] == "taken" and k["exit_d"]:
            exits_by_day[k["exit_d"]] += (k["units"] * (k["exit_px"] - k["entry_px"])
                                          - abs(k["units"]) * COST * k["entry_px"])
            closes_by_day[k["exit_d"]] += 1
    ent_by_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for k in tk:
        if k["entry_d"]:
            ent_by_day[k["entry_d"]][0 if k["state"] == "taken" else 1] += 1
    rv_cum, taken_c, skipped_c, closed_c = 0.0, 0, 0, 0
    out: list[dict] = []
    for d in days:
        rv = exits_by_day.get(d, 0.0)
        closed_c += closes_by_day.get(d, 0)
        rv_cum += rv
        un = ec = gr = 0.0
        for k, m in path_by_day.get(d, ()):
            if k["state"] != "taken":
                continue
            un += k["units"] * (m - k["entry_px"])
            ec += abs(k["units"]) * (COST / 2) * k["entry_px"]
            gr += abs(k["units"]) * m
        nt, ns = ent_by_day.get(d, (0, 0))
        taken_c += nt
        skipped_c += ns
        eq = equity0 + rv_cum + un - ec
        # 内核:coalesce(op.n,0) —— _nv_path join _nv_tk on state='taken',只算 taken 的行
        open_n = sum(1 for k, _ in path_by_day.get(d, ()) if k["state"] == "taken")
        out.append(dict(d=d, equity=eq, realized=rv_cum - ec, unrealized=un, open_n=open_n,
                        gross=gr / eq if eq else 0.0, taken=taken_c, skipped=skipped_c, closed=closed_c))
    return out


def _bisect_right(a: list[str], x: str) -> int:
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo
