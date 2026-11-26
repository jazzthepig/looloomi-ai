"""T-437:S-916 盲复算 —— 只按 tasks/T-437.json 上的规格从零写,数 24 格里哪些「站得住」。

写法:不读 docs/research/s916_jazz_4h_rules.py,也不读它的产物;本脚本落盘 s916_blind_results.json
之后才允许做对账。

用法(仓库根目录):
    python3 docs/research/s916_blind.py
产物:
    docs/research/s916_blind_results.json   —— 24 格(规则 × 状态格)两段的张数 / 均值 R / 盈亏比 / 对照均值 / 站不站得住
输入:
    /Volumes/CometCloudAI/cometcloud-local/research/t437/bars4h.json   (docs/research/_t437_fetch.py 抓的 4 小时线)
    s881_setup_mining.load_live() 返回的 cell(4 个状态格)
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t437/bars4h.json"
OUT = os.path.join(HERE, "s916_blind_results.json")

SYMS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "LINK", "NEAR", "SUI")
CELLS = ("线上·主流领", "线上·二线领", "线下·主流领", "线下·二线领")
SPLIT = dt.date(2022, 12, 31)     # 发现段 ≤ 2022-12-31,留出段 2023 起
START_BAR = 60                    # 从第 60 根(0 起)起判
MAX_HOLD = 90                     # 最多拿 90 根,按收盘平
COST = 0.0012                     # 成本 0.12%
MIN_STOP = 0.004                  # 止损距离下限 0.4%
MAX_STOP = 0.08                   # 止损距离上限 8%,超了不做
MIN_N = 20                        # 每段至少 20 张
MIN_PAYOFF = 2.0                  # 盈亏比下限
CTRL_EVERY = 30                   # 对照:每 30 根一张,平仓后至少隔 30 根
BR_WAIT = 12                      # 突破后等 12 根

RULES = (
    {"id": "LB_L", "kind": "LB", "side": 1},
    {"id": "UB_S", "kind": "LB", "side": -1},
    {"id": "BR_L", "kind": "BR", "side": 1},
    {"id": "BR_S", "kind": "BR", "side": -1},
    {"id": "BRF_L", "kind": "BRF", "side": 1},
    {"id": "BRF_S", "kind": "BRF", "side": -1},
)


# ---------------------------------------------------------------- 指标(全部只用收盘)

def ema(c: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(c)
    out[0] = c[0]
    for i in range(1, len(c)):
        out[i] = a * c[i] + (1 - a) * out[i - 1]
    return out


def indicators(bars: list) -> dict:
    o = np.array([b[1] for b in bars], float)
    h = np.array([b[2] for b in bars], float)
    l = np.array([b[3] for b in bars], float)
    c = np.array([b[4] for b in bars], float)
    s = pd.Series(c)
    mid = s.rolling(20).mean()
    sd = s.rolling(20).std(ddof=0)          # 总体标准差
    return {
        "ts": np.array([b[0] for b in bars], dtype="int64"),
        "o": o, "h": h, "l": l, "c": c,
        "ema7": ema(c, 7), "ema20": ema(c, 20), "ema50": ema(c, 50),
        "boll_lo": (mid - 2 * sd).to_numpy(), "boll_hi": (mid + 2 * sd).to_numpy(),
        "h20": s.rolling(20).max().shift(1).to_numpy(),      # 此前 20 根(不含本根)最高
        "l20": s.rolling(20).min().shift(1).to_numpy(),      # 此前 20 根(不含本根)最低
        "slo": s.rolling(10).min().to_numpy(),                # 结构位:含本根最近 10 根最低
        "shi": s.rolling(10).max().to_numpy(),                # 结构位:含本根最近 10 根最高
    }


# ---------------------------------------------------------------- 管票

def norm_stop(side: int, entry_px: float, stop_px: float):
    """止损距离 <0.4% 按 0.4%;>8% 或方向不对 ⇒ None(不做)。"""
    if side > 0:
        if not np.isfinite(stop_px) or stop_px >= entry_px:
            return None
        dist = (entry_px - stop_px) / entry_px
    else:
        if not np.isfinite(stop_px) or stop_px <= entry_px:
            return None
        dist = (stop_px - entry_px) / entry_px
    if dist > MAX_STOP:
        return None
    if dist < MIN_STOP:
        stop_px = entry_px * (1 - MIN_STOP) if side > 0 else entry_px * (1 + MIN_STOP)
    return stop_px


def manage(bars: dict, side: int, entry_i: int, entry_px: float, stop_px: float, mstart: int):
    """同一根先看止损;+2R 平一半、剩下止损移到进场价;平了一半之后收盘反穿 EMA7 全平;
    最多拿 90 根按收盘平。返回 (exit_i, exit_px, r_gross);样本末尾还没了结 ⇒ None(该票不算)。"""
    o, h, l, c = bars["o"], bars["h"], bars["l"], bars["c"]
    risk = (entry_px - stop_px) if side > 0 else (stop_px - entry_px)
    half, r_part, just_part = False, None, False

    def gross(exit_px: float) -> float:
        r_final = (exit_px - entry_px) * side / risk
        return 0.5 * (r_part + r_final) if half else r_final

    for i in range(mstart, len(c)):
        # 1) 止损(跳空越过按开盘)
        if side > 0:
            if l[i] <= stop_px:
                px = o[i] if o[i] < stop_px else stop_px
                return i, px, gross(px)
        else:
            if h[i] >= stop_px:
                px = o[i] if o[i] > stop_px else stop_px
                return i, px, gross(px)
        # 2) +2R 平一半,止损移到进场价
        just_part = False
        if not half:
            tgt = entry_px + side * 2 * risk
            hit = (h[i] >= tgt) if side > 0 else (l[i] <= tgt)
            if hit:
                px = o[i] if ((o[i] >= tgt) if side > 0 else (o[i] <= tgt)) else tgt
                half, r_part, just_part = True, (px - entry_px) * side / risk, True
                stop_px = entry_px
        # 3) 平了一半之后,收盘反穿 EMA7 全平(不在 +2R 成交那一根)
        if half and not just_part:
            e7 = bars["ema7"][i]
            if (side > 0 and c[i] < e7) or (side < 0 and c[i] > e7):
                return i, c[i], gross(c[i])
        # 4) 最多拿 90 根,按收盘平
        if i - entry_i >= MAX_HOLD:
            return i, c[i], gross(c[i])
    return None


def utc_date(ts: int) -> dt.date:
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date()


def make_ticket(bars: dict, side: int, entry_i: int, entry_px: float, exit_i: int, exit_px: float,
                r_gross: float, risk: float) -> dict:
    return {"d": utc_date(bars["ts"][entry_i]), "side": side, "r": r_gross - COST * entry_px / risk,
            "r_gross": r_gross, "entry_i": entry_i, "exit_i": exit_i}


# ---------------------------------------------------------------- 规则

def run_lb(bars: dict, side: int) -> list:
    """LB_L / UB_S:第 i 根判,第 i+1 根挂限价(限价单当根有效:最低 ≤ 限价成交,开盘已低于限价按开盘)。"""
    out, n = [], len(bars["c"])
    i = START_BAR
    while i + 1 < n:
        if side > 0:
            ok = bars["ema20"][i] > bars["ema50"][i] and bars["c"][i] > bars["ema50"][i]
            limit = bars["boll_lo"][i]
        else:
            ok = bars["ema20"][i] < bars["ema50"][i] and bars["c"][i] < bars["ema50"][i]
            limit = bars["boll_hi"][i]
        if not ok:
            i += 1
            continue
        j = i + 1
        px = None
        if side > 0:
            if bars["o"][j] < limit:
                px = bars["o"][j]
            elif bars["l"][j] <= limit:
                px = limit
        else:
            if bars["o"][j] > limit:
                px = bars["o"][j]
            elif bars["h"][j] >= limit:
                px = limit
        if px is None:
            i += 1
            continue
        base = bars["slo"][i] * 0.998 if side > 0 else bars["shi"][i] * 1.002
        stop = norm_stop(side, px, base)
        if stop is None:
            i += 1
            continue
        risk = (px - stop) if side > 0 else (stop - px)
        res = manage(bars, side, j, px, stop, j)          # 成交那根也管
        if res is None:
            i = j + 1
            continue
        ei, ex, rg = res
        out.append(make_ticket(bars, side, j, px, ei, ex, rg, risk))
        i = ei + 1                                        # 下一张从平仓后一根开始找
    return out


def run_br(bars: dict, side: int, filt: bool) -> list:
    """BR_L / BR_S(以及 BRF 加一条 EMA20>EMA50 / <):第 i 根判,之后 12 根内某根进,按该根收盘进。"""
    out, n = [], len(bars["c"])
    i = START_BAR
    while i < n:
        lvl = bars["h20"][i] if side > 0 else bars["l20"][i]
        if not np.isfinite(lvl):
            i += 1
            continue
        trig = (bars["c"][i] > lvl) if side > 0 else (bars["c"][i] < lvl)
        if not trig:
            i += 1
            continue
        if filt:
            f = (bars["ema20"][i] > bars["ema50"][i]) if side > 0 else (bars["ema20"][i] < bars["ema50"][i])
            if not f:
                i += 1
                continue
        entry_i = None
        for j in range(i + 1, min(n, i + 1 + BR_WAIT)):
            # 等待中收盘跌破(涨破)突破位 × 0.99(× 1.01) ⇒ 作废
            if (side > 0 and bars["c"][j] < lvl * 0.99) or (side < 0 and bars["c"][j] > lvl * 1.01):
                break
            hit = (bars["l"][j] <= lvl * 1.003 and bars["c"][j] >= lvl) if side > 0 \
                else (bars["h"][j] >= lvl * 0.997 and bars["c"][j] <= lvl)
            if hit:
                entry_i = j
                break
        if entry_i is None:
            i += 1
            continue
        px = bars["c"][entry_i]
        base = bars["l"][entry_i] * 0.998 if side > 0 else bars["h"][entry_i] * 1.002
        stop = norm_stop(side, px, base)
        if stop is None:
            i = entry_i + 1
            continue
        risk = (px - stop) if side > 0 else (stop - px)
        res = manage(bars, side, entry_i, px, stop, entry_i + 1)   # 从下一根开始管
        if res is None:
            i = entry_i + 1
            continue
        ei, ex, rg = res
        out.append(make_ticket(bars, side, entry_i, px, ei, ex, rg, risk))
        i = ei + 1
    return out


def run_ctrl(bars: dict, side: int) -> list:
    """对照:同币每 30 根在收盘进一张(止损 = 该根结构位,同一套管票),平仓后至少隔 30 根。"""
    out, n = [], len(bars["c"])
    last_exit = None
    for i in range(START_BAR, n, CTRL_EVERY):
        if last_exit is not None and i - last_exit < CTRL_EVERY:
            continue
        px = bars["c"][i]
        base = bars["slo"][i] if side > 0 else bars["shi"][i]
        stop = norm_stop(side, px, base)
        if stop is None:
            continue
        risk = (px - stop) if side > 0 else (stop - px)
        res = manage(bars, side, i, px, stop, i + 1)      # 收盘进 ⇒ 从下一根开始管
        if res is None:
            continue
        ei, ex, rg = res
        out.append(make_ticket(bars, side, i, px, ei, ex, rg, risk))
        last_exit = ei
    return out


# ---------------------------------------------------------------- 统计

def stats(rs: list) -> dict:
    if not rs:
        return {"n": 0, "mean_R": None, "payoff": None}
    wins = [r for r in rs if r > 0]
    loss = [r for r in rs if r < 0]
    pf = (sum(wins) / len(wins)) / abs(sum(loss) / len(loss)) if wins and loss else (None if not wins else float("inf"))
    return {"n": len(rs), "mean_R": round(float(np.mean(rs)), 4),
            "payoff": (None if pf is None else (pf if not np.isfinite(pf) else round(pf, 4)))}


def pf_json(v):
    return "inf" if v is not None and not isinstance(v, str) and not np.isfinite(v) else v


def main() -> None:
    raw = json.load(open(CACHE))
    syms = raw["symbols"]

    # 状态格:只用 s881_setup_mining.load_live() 返回的 cell
    spec = importlib.util.spec_from_file_location("s881", os.path.join(HERE, "s881_setup_mining.py"))
    s881 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s881)
    _, cell, _ = s881.load_live()

    bars = {s: indicators(syms[s]) for s in SYMS if s in syms}

    tickets: dict[str, list] = {r["id"]: [] for r in RULES}
    ctrl: dict[int, list] = {1: [], -1: []}
    for s, b in bars.items():
        for rule in RULES:
            if rule["kind"] == "LB":
                t = run_lb(b, rule["side"])
            elif rule["kind"] == "BR":
                t = run_br(b, rule["side"], False)
            else:
                t = run_br(b, rule["side"], True)
            for x in t:
                x["sym"] = s
                x["cell"] = cell.get(x["d"] - dt.timedelta(days=1))
            tickets[rule["id"]] += t
        for side in (1, -1):
            for x in run_ctrl(b, side):
                x["sym"] = s
                x["cell"] = cell.get(x["d"] - dt.timedelta(days=1))
                ctrl[side].append(x)

    rows = []
    for rule in RULES:
        tk = [t for t in tickets[rule["id"]] if t["cell"]]
        side = rule["side"]
        for cn in CELLS:
            d = [t["r"] for t in tk if t["cell"] == cn and t["d"] <= SPLIT]
            h = [t["r"] for t in tk if t["cell"] == cn and t["d"] > SPLIT]
            cd = [t["r"] for t in ctrl[side] if t["cell"] == cn and t["d"] <= SPLIT]
            ch = [t["r"] for t in ctrl[side] if t["cell"] == cn and t["d"] > SPLIT]
            sd, sh = stats(d), stats(h)
            cdm = round(float(np.mean(cd)), 4) if cd else None
            chm = round(float(np.mean(ch)), 4) if ch else None
            ok_d = (sd["n"] >= MIN_N and sd["mean_R"] is not None and sd["mean_R"] > 0
                    and sd["payoff"] is not None and sd["payoff"] >= MIN_PAYOFF
                    and cdm is not None and sd["mean_R"] > cdm)
            ok_h = (sh["n"] >= MIN_N and sh["mean_R"] is not None and sh["mean_R"] > 0
                    and sh["payoff"] is not None and sh["payoff"] >= MIN_PAYOFF
                    and chm is not None and sh["mean_R"] > chm)
            rows.append({"rule": rule["id"], "cell": cn,
                         "disc": {**sd, "payoff": pf_json(sd["payoff"]), "ctrl_mean_R": cdm, "pass": bool(ok_d)},
                         "hold": {**sh, "payoff": pf_json(sh["payoff"]), "ctrl_mean_R": chm, "pass": bool(ok_h)},
                         "holds": bool(ok_d and ok_h)})

    for r in rows:
        d, h = r["disc"], r["hold"]
        print(f"{r['rule']:6s} {r['cell']} | disc n{d['n']:>3d} m{d['mean_R']} pf{d['payoff']} c{d['ctrl_mean_R']}"
              f" | hold n{h['n']:>3d} m{h['mean_R']} pf{h['payoff']} c{h['ctrl_mean_R']}"
              f" | {'HOLDS' if r['holds'] else '-'}", flush=True)

    n_hold = sum(1 for r in rows if r["holds"])
    out = {
        "card": "T-437", "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "spec_from": "tasks/T-437.json(S-916 规格全文,盲复算)",
        "data": {"bars": CACHE, "hourly_source": "ohlcv_hourly(source=binance_hist)",
                 "bucket": "UTC 00/04/08/12/16/20,四根齐", "symbols": list(bars.keys()),
                 "cell_source": "s881_setup_mining.load_live() 的 cell(进场那根 UTC 日的前一天)"},
        "params": {"start_bar": START_BAR, "max_hold": MAX_HOLD, "cost": COST,
                   "min_stop": MIN_STOP, "max_stop": MAX_STOP, "min_n": MIN_N,
                   "min_payoff": MIN_PAYOFF, "ctrl_every": CTRL_EVERY, "br_wait": BR_WAIT,
                   "split": str(SPLIT)},
        "assumptions": [
            "H20/L20 与结构位都按「收盘」算(卡上『指标只用到该根收盘』统辖这四项)。",
            "LB 的限价单只在第 i+1 根当根有效(卡上没给撤单窗口,BR 才有『12 根』)。",
            "限价成交那根也管票:先看止损,再看 +2R;BR 的进场根不管(从下一根开始管)。",
            "+2R 平一半后止损移到进场价;EMA7 反穿全平不在 +2R 成交那一根生效。",
            "止损距离 <0.4% 按 0.4% 放宽;>8% 或方向不对 ⇒ 不做(对照票同一套)。",
            "样本末尾还没了结的票(拿不满 90 根)不算。",
            "对照的 30 根网格从第 60 根起;平仓后至少隔 30 根。",
            "状态格取「进场那根所在 UTC 日的前一天」;没有格子的票不进任何格。",
        ],
        "counts": {r["id"]: {"total": len(tickets[r["id"]]),
                             "no_cell": sum(1 for t in tickets[r["id"]] if not t["cell"]),
                             "disc": sum(1 for t in tickets[r["id"]] if t["cell"] and t["d"] <= SPLIT),
                             "hold": sum(1 for t in tickets[r["id"]] if t["cell"] and t["d"] > SPLIT)}
                   for r in RULES},
        "ctrl_counts": {("long" if s > 0 else "short"): {"total": len(ctrl[s]),
                                                         "no_cell": sum(1 for t in ctrl[s] if not t["cell"]),
                                                         "disc": sum(1 for t in ctrl[s] if t["cell"] and t["d"] <= SPLIT),
                                                         "hold": sum(1 for t in ctrl[s] if t["cell"] and t["d"] > SPLIT)}
                        for s in (1, -1)},
        "n_holds": n_hold, "rows": rows,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("WROTE", OUT, "| 站得住", n_hold, "/ 24")


if __name__ == "__main__":
    main()
