"""S-916:Jazz 自己的两种进场单(「低吸边界单」与「突破回踩确认单」)放在 4 小时线上,连同他的管票规则,按状态四格量 —— 并给出今天的匹配板。

Jazz(记忆里的交易框架):「4H 定大方向」「只用低吸边界单 + 突破回踩确认单,绝不市价追涨杀跌」「做空前要先看 EMA 趋势」
「一有盈利立刻把止损移到成本价附近」「第一目标减仓 30%–50%,剩余跟踪 EMA7 让利润奔跑」「单笔最大亏损 4% 账户」
「回测只想测自己的规则(边界低吸单、突破回踩确认单、结构位止损、4% 风险反算仓位)」;11-15「不要高胜率,要高盈亏比」。

4 小时线 = `ohlcv_hourly`(binance_hist)按 UTC 00/04/08/12/16/20 聚合,四根小时线齐了才算一根。指标都只用到该根收盘为止:
EMA7 / 20 / 50、布林 20 × 2σ、H20 / L20 = 此前 20 根(不含本根)的最高 / 最低、结构位 = 含本根在内最近 10 根的最低 / 最高。

规则(第 i 根收盘判,之后的根才成交;一个币一条规则同时只有一张票):
  LB_L   低吸边界单(多):EMA20 > EMA50 且收盘 > EMA50 ⇒ 下一根挂限价 = 布林下轨;最低价 ≤ 限价即成交(开盘已在限价下 ⇒ 按开盘价)。
         止损 = 最近 10 根最低 × (1 − 0.2%)。
  UB_S   反弹边界单(空):镜像 —— EMA20 < EMA50 且收盘 < EMA50 ⇒ 挂布林上轨,止损 = 最近 10 根最高 × (1 + 0.2%)。
  BR_L   突破回踩确认单(多):收盘 > H20 ⇒ 记下 H20 为突破位;之后 12 根内,某根最低 ≤ 突破位 × (1 + 0.3%) 且收盘 ≥ 突破位
         ⇒ 按这根收盘进,止损 = 这根最低 × (1 − 0.2%);等待期间收盘跌破突破位 1% ⇒ 作废。
  BR_S   破位回抽确认单(空):镜像(L20、回抽到破位之下、收盘 ≤ 破位)。
  BRF_L / BRF_S  同 BR,另加 EMA 趋势过滤(多要 EMA20 > EMA50,空要 EMA20 < EMA50)—— 「做空前先看 EMA」。
  止损距离 < 0.4% 按 0.4%;> 8% 不做(4% 风险反算出来的仓位会小到没意义,也离结构太远)。
管票(他写的):+2R 平一半、剩下的止损移到进场价;之后 4 小时收盘反穿 EMA7 全平;最多拿 90 根(15 天)按收盘平。
同一根既碰止损又碰目标 ⇒ 先算止损。跳空越过止损 ⇒ 按开盘价。成本 = 来回 0.12%(按进场价,折成 R 扣)。结果一律按 R(1R = 进场到止损)。
4% 风险反算仓位不改变 R 的分布,只改资金曲线:另报每条规则按进场时间顺序、每张 4% 风险复利的最大回撤与最长水下张数。

状态 = 趋势 × 谁在领(与 S-881 / S-884 同一份装载;用进场那根所在 UTC 日的**前一天**的格子)。
对照 = 同币同格同向,每 30 根(5 天)在收盘无条件进一张,止损同一套结构位,管票同一套。
「站得住」= 发现段(≤ 2022-12-31)与留出段(2023 起)都:票数 ≥ 20、均值 R > 0、盈亏比(平均盈 / 平均亏)≥ 2、均值 R 高于对照。
状态序列平移 100 次(≥ 180 天),数站得住的格子。预期与后果写在台账 S-916(先登记,后计算)。

用法(仓库根目录;环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s916_jazz_4h_rules.py --selftest
    nohup python3 docs/research/s916_jazz_4h_rules.py > docs/research/s916_run.txt 2>&1 &      # 写 s916_results.json(含今天的匹配板)
    nohup python3 docs/research/s916_jazz_4h_rules.py --mgmt hold > docs/research/s916_run_hold.txt 2>&1 &   # S-917:只设止损、拿满 28 天
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


_argv, sys.argv = sys.argv, [sys.argv[0]]
X = _load("s881", os.path.join(HERE, "s881_setup_mining.py"))      # 状态四格的装载与平移
S = _load("s851", os.path.join(HERE, "s851_watch_base_rate.py"))   # 只读取数
sys.argv = _argv

OUT = "docs/research/s916_results.json"
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "LINK", "NEAR", "SUI")
RULES = {"LB_L": 1, "UB_S": -1, "BR_L": 1, "BR_S": -1, "BRF_L": 1, "BRF_S": -1}
CELLS = X.CELLS
SPLIT = dt.date(2022, 12, 31)
BB_N, BB_K, HL_N, SWING_N, RETEST_WIN, RETEST_TOL, CANCEL = 20, 2.0, 20, 10, 12, 0.003, 0.01
BUF, DMIN, DMAX, TP_R, MAX_BARS, COST, EVERY = 0.002, 0.004, 0.08, 2.0, 90, 0.0012, 30
MIN_N, MIN_PAYOFF, N_NULL, SEED, RISK = 20, 2.0, 100, 916, 0.04
#: S-917:`--mgmt hold` = 只有结构止损、不平一半、不保本、不跟 EMA7,拿满 168 根(28 天)按收盘平 —— 把管法和进场分开看
MGMT = "hold" if "--mgmt" in sys.argv and sys.argv[sys.argv.index("--mgmt") + 1] == "hold" else "jazz"
HOLD_BARS = 168
if MGMT == "hold":
    OUT = "docs/research/s916_results_hold.json"


# ── 4 小时线与指标 ─────────────────────────────────────────────────────────────

def to_4h(rows: list) -> dict:
    """小时线 [{ts, open, high, low, close}] → 4 小时线(四根齐了才算)。返回 {t:[...], o, h, l, c}(numpy)。"""
    buckets: dict = {}
    for r in rows:
        ts = dt.datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00"))
        k = ts.replace(hour=ts.hour - ts.hour % 4, minute=0, second=0, microsecond=0)
        buckets.setdefault(k, []).append((ts, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    t, o, h, l, c = [], [], [], [], []
    for k in sorted(buckets):
        b = sorted(buckets[k])
        if len(b) != 4:
            continue
        t.append(k)
        o.append(b[0][1]); h.append(max(x[2] for x in b)); l.append(min(x[3] for x in b)); c.append(b[-1][4])
    return {"t": t, "o": np.array(o), "h": np.array(h), "l": np.array(l), "c": np.array(c)}


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a, out = 2.0 / (n + 1), np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def indicators(b: dict) -> dict:
    c, h, l = b["c"], b["h"], b["l"]
    n = len(c)
    ind = {"e7": ema(c, 7), "e20": ema(c, 20), "e50": ema(c, 50)}
    bl, bu, h20, l20, sl, sh = (np.full(n, np.nan) for _ in range(6))
    for i in range(n):
        if i >= BB_N - 1:
            w = c[i - BB_N + 1:i + 1]
            m, s = w.mean(), w.std()
            bl[i], bu[i] = m - BB_K * s, m + BB_K * s
        if i >= HL_N:
            h20[i], l20[i] = h[i - HL_N:i].max(), l[i - HL_N:i].min()
        if i >= SWING_N - 1:
            sl[i], sh[i] = l[i - SWING_N + 1:i + 1].min(), h[i - SWING_N + 1:i + 1].max()
    ind.update({"bl": bl, "bu": bu, "h20": h20, "l20": l20, "sl": sl, "sh": sh})
    return ind


# ── 管票 ──────────────────────────────────────────────────────────────────────

def manage(b: dict, ind: dict, i0: int, side: int, entry: float, stop: float) -> dict | None:
    """第 i0 根成交(价 entry)之后的管票;返回 {r, exit_i, bars}。i0 这一根本身:限价单在这根里成交,所以这根剩下的部分也算(先看止损)。"""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    if MGMT == "hold":
        return manage_hold(b, i0, side, entry, stop, risk)
    o, h, l, c, e7 = b["o"], b["h"], b["l"], b["c"], ind["e7"]
    half_done, cur_stop, realized, size = False, stop, 0.0, 1.0
    target = entry + side * TP_R * risk
    n = len(c)
    for j in range(i0, min(n, i0 + MAX_BARS + 1)):
        first = j > i0
        # 止损(跳空按开盘)
        if side > 0 and l[j] <= cur_stop:
            px = o[j] if first and o[j] < cur_stop else cur_stop
            realized += size * (px - entry) / risk
            return {"r": realized - COST * entry / risk, "exit_i": j, "bars": j - i0}
        if side < 0 and h[j] >= cur_stop:
            px = o[j] if first and o[j] > cur_stop else cur_stop
            realized += size * (entry - px) / risk
            return {"r": realized - COST * entry / risk, "exit_i": j, "bars": j - i0}
        if not half_done and ((side > 0 and h[j] >= target) or (side < 0 and l[j] <= target)):
            realized += 0.5 * TP_R
            size, half_done, cur_stop = 0.5, True, entry
        if half_done and ((side > 0 and c[j] < e7[j]) or (side < 0 and c[j] > e7[j])) and j > i0:
            realized += size * side * (c[j] - entry) / risk
            return {"r": realized - COST * entry / risk, "exit_i": j, "bars": j - i0}
    j = min(n - 1, i0 + MAX_BARS)
    if j - i0 < MAX_BARS:
        return None                                        # 数据不够拿满 —— 不算(样本末尾)
    realized += size * side * (c[j] - entry) / risk
    return {"r": realized - COST * entry / risk, "exit_i": j, "bars": j - i0}


def manage_hold(b: dict, i0: int, side: int, entry: float, stop: float, risk: float) -> dict | None:
    """S-917 的管法:只有止损(同一根先看止损、跳空按开盘),拿满 HOLD_BARS 根按收盘平;拿不满(样本末尾)不算。"""
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    n = len(c)
    for j in range(i0, min(n, i0 + HOLD_BARS + 1)):
        first = j > i0
        if side > 0 and l[j] <= stop:
            px = o[j] if first and o[j] < stop else stop
            return {"r": (px - entry) / risk - COST * entry / risk, "exit_i": j, "bars": j - i0}
        if side < 0 and h[j] >= stop:
            px = o[j] if first and o[j] > stop else stop
            return {"r": (entry - px) / risk - COST * entry / risk, "exit_i": j, "bars": j - i0}
    j = i0 + HOLD_BARS
    if j >= n:
        return None
    return {"r": side * (c[j] - entry) / risk - COST * entry / risk, "exit_i": j, "bars": j - i0}


def _stop_ok(entry: float, stop: float, side: int) -> float | None:
    d = side * (entry - stop) / entry
    if d <= 0:
        return None
    if d < DMIN:
        return entry * (1 - side * DMIN)
    if d > DMAX:
        return None
    return stop


# ── 进场 ──────────────────────────────────────────────────────────────────────

def tickets(b: dict, ind: dict, rule: str) -> list:
    """一个币一条规则的全部票 [(进场时刻, side, R, 持有根数)]。第 i 根收盘判,之后的根成交;同时只有一张。"""
    side = RULES[rule]
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    e20, e50 = ind["e20"], ind["e50"]
    n, out, i, start = len(c), [], 0, 60
    i = start
    while i < n - 1:
        tk = None
        if rule in ("LB_L", "UB_S"):
            trend = (e20[i] > e50[i] and c[i] > e50[i]) if side > 0 else (e20[i] < e50[i] and c[i] < e50[i])
            lim = ind["bl"][i] if side > 0 else ind["bu"][i]
            if trend and not math.isnan(lim):
                j = i + 1
                hit = l[j] <= lim if side > 0 else h[j] >= lim
                if hit:
                    entry = min(lim, o[j]) if side > 0 else max(lim, o[j])
                    stop = _stop_ok(entry, (ind["sl"][i] * (1 - BUF)) if side > 0 else (ind["sh"][i] * (1 + BUF)), side)
                    if stop is not None:
                        tk = (j, entry, stop)
        else:
            lvl = ind["h20"][i] if side > 0 else ind["l20"][i]
            broke = not math.isnan(lvl) and (c[i] > lvl if side > 0 else c[i] < lvl)
            filt = rule.startswith("BRF")
            if broke and (not filt or (e20[i] > e50[i] if side > 0 else e20[i] < e50[i])):
                for j in range(i + 1, min(n, i + 1 + RETEST_WIN)):
                    if (side > 0 and c[j] < lvl * (1 - CANCEL)) or (side < 0 and c[j] > lvl * (1 + CANCEL)):
                        break
                    touched = l[j] <= lvl * (1 + RETEST_TOL) if side > 0 else h[j] >= lvl * (1 - RETEST_TOL)
                    held = c[j] >= lvl if side > 0 else c[j] <= lvl
                    if touched and held and j + 1 < n:
                        entry = c[j]
                        stop = _stop_ok(entry, (l[j] * (1 - BUF)) if side > 0 else (h[j] * (1 + BUF)), side)
                        if stop is not None:
                            tk = (j + 1, entry, stop)          # 收盘进 ⇒ 从下一根开始管
                        break
        if tk is None:
            i += 1
            continue
        j0, entry, stop = tk
        m = manage(b, ind, j0, side, entry, stop) if rule in ("LB_L", "UB_S") else _manage_from_close(b, ind, j0, side, entry, stop)
        if m is None:
            break
        out.append((b["t"][j0], side, m["r"], m["bars"]))
        i = m["exit_i"] + 1
    return out


def _manage_from_close(b, ind, j0, side, entry, stop):
    """收盘进场的票:进场那根已收完,从下一根(j0)开始管。"""
    return manage(b, ind, j0, side, entry, stop)


def baseline(b: dict, ind: dict, side: int) -> list:
    """对照:每 30 根在收盘进一张(无条件),止损 = 结构位,管票同一套。"""
    c, n, out, i = b["c"], len(b["c"]), [], 60
    while i < n - 1:
        entry = c[i]
        stop = _stop_ok(entry, (ind["sl"][i] * (1 - BUF)) if side > 0 else (ind["sh"][i] * (1 + BUF)), side)
        if stop is None:
            i += EVERY
            continue
        m = manage(b, ind, i + 1, side, entry, stop)
        if m is None:
            break
        out.append((b["t"][i + 1], side, m["r"], m["bars"]))
        i = max(m["exit_i"] + 1, i + EVERY)
    return out


# ── 统计 ──────────────────────────────────────────────────────────────────────

def summ(rs: list) -> dict:
    if not rs:
        return {"n": 0}
    r = np.array(rs)
    w, ls = r[r > 0], r[r <= 0]
    avg_l = float(-ls.mean()) if len(ls) else 0.0
    return {"n": len(r), "mean_r": round(float(r.mean()), 3), "win": round(float((r > 0).mean()), 3),
            "payoff": round(float(w.mean() / avg_l), 2) if len(w) and avg_l > 0 else (99.0 if len(w) else 0.0),
            "pf": round(float(w.sum() / -ls.sum()), 2) if len(ls) and ls.sum() < 0 else 99.0, "worst_r": round(float(r.min()), 2)}


def curve(ts: list) -> dict:
    """按进场时间顺序,每张 4% 风险复利:最大回撤与最长水下张数。"""
    eq, peak, mdd, under, longest = 1.0, 1.0, 0.0, 0, 0
    for _, _, r, _ in sorted(ts, key=lambda x: x[0]):
        eq *= max(0.0, 1 + RISK * r)
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        under = 0 if eq >= peak else under + 1
        longest = max(longest, under)
    return {"final": round(eq, 3), "max_dd": round(mdd, 3), "longest_under_n": longest}


def cell_of(t, cell: dict):
    return cell.get(t.date() - dt.timedelta(days=1))


def scan(tk: dict, bl: dict, cell: dict) -> list:
    rows = []
    for rule, side in RULES.items():
        for cn in CELLS:
            ts = [x for x in tk[rule] if cell_of(x[0], cell) == cn]
            bs = [x for x in bl[side] if cell_of(x[0], cell) == cn]
            halves = lambda xs: (summ([x[2] for x in xs if x[0].date() <= SPLIT]), summ([x[2] for x in xs if x[0].date() > SPLIT]))  # noqa: E731
            (d1, h1), (bd, bh) = halves(ts), halves(bs)
            ok = lambda s, base: bool(s.get("n", 0) >= MIN_N and s["mean_r"] > 0 and s["payoff"] >= MIN_PAYOFF and s["mean_r"] > base.get("mean_r", 0.0))  # noqa: E731
            rows.append({"rule": rule, "cell": cn, "full": summ([x[2] for x in ts]), "disc": d1, "hold": h1, "base_disc": bd, "base_hold": bh,
                         "holds": ok(d1, bd) and ok(h1, bh), "curve": curve(ts) if ts else None})
    return rows


def all_tickets(bars: dict) -> tuple:
    tk = {r: [] for r in RULES}
    bl = {1: [], -1: []}
    per_coin = {}
    for coin, b in bars.items():
        ind = indicators(b)
        per_coin[coin] = {}
        for r in RULES:
            t = tickets(b, ind, r)
            tk[r] += t
            per_coin[coin][r] = len(t)
        for s in (1, -1):
            bl[s] += baseline(b, ind, s)
    return tk, bl, per_coin


def run(bars: dict, cell: dict, n_null: int = N_NULL) -> dict:
    tk, bl, per_coin = all_tickets(bars)
    real = scan(tk, bl, cell)
    rng = np.random.default_rng(SEED)
    null = [sum(x["holds"] for x in scan(tk, bl, X.shifted(cell, int(rng.integers(X.MIN_SHIFT, len(cell) - X.MIN_SHIFT))))) for _ in range(n_null)]
    n_real = sum(x["holds"] for x in real)
    uncond = {r: {"disc": summ([x[2] for x in tk[r] if x[0].date() <= SPLIT]), "hold": summ([x[2] for x in tk[r] if x[0].date() > SPLIT]),
                  "curve": curve(tk[r])} for r in RULES}
    base = {s: {"disc": summ([x[2] for x in bl[s] if x[0].date() <= SPLIT]), "hold": summ([x[2] for x in bl[s] if x[0].date() > SPLIT])} for s in (1, -1)}
    return {"n_tested": len(real), "n_holds": n_real,
            "null": {"n": n_null, "median": float(np.median(null)), "q95": float(np.quantile(null, 0.95)),
                     "p_ge_real": round(float((np.array(null) >= n_real).mean()), 3)},
            "unconditional": uncond, "baseline": {str(k): v for k, v in base.items()}, "per_coin": per_coin, "rows": real}


# ── 今天的匹配板 ──────────────────────────────────────────────────────────────

def board(bars: dict, cell: dict, rows: list) -> dict:
    """最新一根收盘之后:今天的格子、在这一格站得住的规则、每个币上这些规则现在是什么状态(挂单价 / 等回踩的位 / 止损 / 4% 风险的仓位)。"""
    last_day = max(cell)
    today = cell[last_day]
    home = sorted({x["rule"] for x in rows if x["holds"] and x["cell"] == today})
    out = []
    for coin, b in bars.items():
        ind = indicators(b)
        i = len(b["c"]) - 1
        c = b["c"][i]
        info = {"coin": coin, "bar": b["t"][i].isoformat(), "close": round(float(c), 6),
                "trend": "up" if ind["e20"][i] > ind["e50"][i] else "down", "ema50": round(float(ind["e50"][i]), 6)}
        armed = []
        for rule in RULES:
            side = RULES[rule]
            if rule in ("LB_L", "UB_S"):
                trend = (ind["e20"][i] > ind["e50"][i] and c > ind["e50"][i]) if side > 0 else (ind["e20"][i] < ind["e50"][i] and c < ind["e50"][i])
                if trend:
                    lim = float(ind["bl"][i] if side > 0 else ind["bu"][i])
                    stop = float(ind["sl"][i] * (1 - BUF) if side > 0 else ind["sh"][i] * (1 + BUF))
                    st = _stop_ok(lim, stop, side)
                    if st is None:
                        armed.append({"rule": rule, "limit": round(lim, 6), "valid": False,
                                      "why": "边界在结构位之外(挂了就是破位成交)或止损 > 8%:规则不挂", "home_today": rule in home})
                    else:
                        d = side * (lim - st) / lim
                        armed.append({"rule": rule, "limit": round(lim, 6), "stop": round(st, 6), "stop_dist": round(d, 4), "valid": True,
                                      "notional_pct_of_equity_at_4pct_risk": round(RISK / d, 2), "home_today": rule in home})
            else:
                for k in range(max(HL_N, i - RETEST_WIN), i + 1):
                    lvl = ind["h20"][k] if side > 0 else ind["l20"][k]
                    if math.isnan(lvl):
                        continue
                    broke = b["c"][k] > lvl if side > 0 else b["c"][k] < lvl
                    if broke and (not rule.startswith("BRF") or (ind["e20"][k] > ind["e50"][k] if side > 0 else ind["e20"][k] < ind["e50"][k])):
                        cancelled = any((side > 0 and b["c"][j] < lvl * (1 - CANCEL)) or (side < 0 and b["c"][j] > lvl * (1 + CANCEL)) for j in range(k + 1, i + 1))
                        if not cancelled:
                            armed.append({"rule": rule, "level": round(float(lvl), 6), "broke_at": b["t"][k].isoformat(), "valid": True,
                                          "retest_zone": [round(float(lvl), 6), round(float(lvl * (1 + side * RETEST_TOL)), 6)],
                                          "cancel_if_close_beyond": round(float(lvl * (1 - side * CANCEL)), 6),
                                          "wait_bars_left": RETEST_WIN - (i - k), "home_today": rule in home})
                        break
        info["armed"] = armed
        out.append(info)
    return {"as_of_cell_day": last_day.isoformat(), "cell_today": today, "home_rules_today": home, "coins": out}


# ── 装载 ──────────────────────────────────────────────────────────────────────

def load_live() -> tuple:
    _, cell, _ = X.load_live()
    bars = {}
    for coin in COINS:
        rows = S.get("ohlcv_hourly", {"select": "ts,open,high,low,close", "symbol": f"eq.{coin}", "source": "eq.binance_hist", "order": "ts.asc"})
        rows = [r for r in rows if all(r.get(k) is not None for k in ("open", "high", "low", "close"))]
        bars[coin] = to_4h(rows)
        print("loaded", coin, len(rows), "hourly →", len(bars[coin]["c"]), "4h", flush=True)
    return bars, cell


def synthetic() -> tuple:
    rng = np.random.default_rng(SEED)
    bars, start = {}, dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc)
    for n, coin in enumerate(("AAA", "BBB")):
        rows, px = [], 100.0 * (n + 1)
        for k in range(24 * 365 * 6):
            drift = 0.0004 * math.sin(k / (24 * 90)) + 0.00002
            o = px
            px = max(1.0, px * math.exp(drift + 0.006 * rng.standard_normal()))
            hi, lo = max(o, px) * (1 + abs(0.002 * rng.standard_normal())), min(o, px) * (1 - abs(0.002 * rng.standard_normal()))
            rows.append({"ts": (start + dt.timedelta(hours=k)).isoformat(), "open": o, "high": hi, "low": lo, "close": px})
        bars[coin] = to_4h(rows)
    cell, d = {}, dt.date(2019, 1, 1)
    while d <= dt.date(2024, 12, 31):
        k = (d - dt.date(2019, 1, 1)).days
        cell[d] = ("线上" if (k // 120) % 2 == 0 else "线下") + "·" + ("主流领" if (k // 50) % 2 == 0 else "二线领")
        d += dt.timedelta(days=1)
    return bars, cell


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    bars, cell = synthetic() if selftest else load_live()
    out = run(bars, cell, n_null=(6 if selftest else N_NULL))
    out["board"] = board(bars, cell, out["rows"])
    f = lambda s: f"n{s.get('n')} r{s.get('mean_r')} win{s.get('win')} pay{s.get('payoff')} w{s.get('worst_r')}" if s.get("n") else "n0"  # noqa: E731
    print("COUNTS", json.dumps({k: out[k] for k in ("n_tested", "n_holds", "null")}, ensure_ascii=False), flush=True)
    for r, v in out["unconditional"].items():
        print("UNCOND", r, "| disc", f(v["disc"]), "| hold", f(v["hold"]), "| curve", json.dumps(v["curve"]), flush=True)
    for s, v in out["baseline"].items():
        print("BASE", s, "| disc", f(v["disc"]), "| hold", f(v["hold"]), flush=True)
    for x in out["rows"]:
        print("ROW", x["rule"], x["cell"], "| disc", f(x["disc"]), "vs", f(x["base_disc"]), "| hold", f(x["hold"]), "vs", f(x["base_hold"]),
              "| HOLDS" if x["holds"] else "", flush=True)
    bd = out["board"]
    print("BOARD", bd["as_of_cell_day"], bd["cell_today"], "home:", ",".join(bd["home_rules_today"]) or "-", flush=True)
    for cinfo in bd["coins"]:
        print("ARMED", cinfo["coin"], cinfo["bar"], cinfo["trend"], json.dumps([a for a in cinfo["armed"]], ensure_ascii=False)[:400], flush=True)
    if selftest:
        b = bars["AAA"]
        ind = indicators(b)
        cut = len(b["c"]) // 2
        bc = {k: (v[:cut] if k != "t" else v[:cut]) for k, v in b.items()}
        ic = indicators(bc)
        for k in ind:
            assert np.allclose(ind[k][:cut], ic[k], equal_nan=True), f"指标 {k} 用到了之后的数据"
        for r in RULES:
            full = [x for x in tickets(b, ind, r) if x[0] < b["t"][cut - MAX_BARS - 2]]
            part = [x for x in tickets(bc, ic, r) if x[0] < b["t"][cut - MAX_BARS - 2]]
            assert full == part, f"{r}:进场用到了之后的数据"
        # 管票:直接打到止损 = −1R − 成本
        tb = {"t": b["t"][:5], "o": np.array([100, 100, 100, 100, 100.0]), "h": np.array([101, 101, 101, 101, 101.0]),
              "l": np.array([99, 89, 99, 99, 99.0]), "c": np.array([100, 95, 100, 100, 100.0])}
        ti = {"e7": np.full(5, 100.0)}
        m = manage(tb, ti, 1, 1, 100.0, 90.0)
        assert m and abs(m["r"] - (-1 - COST * 100 / 10)) < 1e-9, m          # 两种管法都是 −1R − 成本
        tb2 = {"t": b["t"][:6], "o": np.array([100, 100, 100, 100, 100, 100.0]), "h": np.array([101, 121, 122, 123, 124, 125.0]),
               "l": np.array([99, 99, 105, 105, 105, 105.0]), "c": np.array([100, 115, 118, 104, 110, 110.0])}
        ti2 = {"e7": np.array([100, 110, 112, 112, 112, 112.0])}
        if MGMT == "jazz":
            m2 = manage(tb2, ti2, 1, 1, 100.0, 90.0)
            assert m2 and abs(m2["r"] - (0.5 * 2 + 0.5 * 0.4 - COST * 100 / 10)) < 1e-9, m2   # +2R 平一半,之后收盘 104 < EMA7 112 全平
        if MGMT == "hold":
            mh = manage_hold(tb2, 1, 1, 100.0, 90.0, 10.0)
            assert mh is None, "拿不满 168 根的票不算"
        assert out["n_tested"] == len(RULES) * len(CELLS)
        assert sum(len(v) for v in out["per_coin"].values()) == 2 * len(RULES)
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
