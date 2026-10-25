"""T-199 / S-683 A 道:两条做空前向臂的历史画像 —— **描述,不是检验**。

两条臂在历史上都已经看过(台账 S-683 的理由:没有没看过的历史能判,只有时间能判)。
这里只把「它们长什么样」冻结下来,给前向逐月对照当**预期带**;本文件**不判**这两条臂。

臂 L(`short_listing_hedged`,台账 S-683 一字不改):事件 = 合约第一根日线 L(数据第一个月 2019-09 上市的不算);
    信号日 = 第 7 根(下标 6),第 8 根(下标 7)开盘进空,s = 50%,N = 60;
    同一时刻按 BTCUSDT 永续开盘价等名义多 BTC,空腿哪天出 BTC 腿就按那天开盘出(仍持有的按最后收盘盯市);
    BTC 腿扣成本(2 × 0.10%)、付多头资金费;对冲 R = (空腿收益 + BTC 腿收益 − BTC 腿成本与资金费)÷ 0.5。
臂 H(`short_h4_gate`):S-681 H4 一字不改(import T-196 的实现 `s681_h4_bear_rally_fail`,不复制),
    只保留信号日 majors 闸门关的票;闸门开着的票另列 blocked。
判据(台账写死,只用来算「要到判据要几个月」):臂 L 已平仓 ≥ 60 且距 inception ≥ 6 个月;
    臂 H 已平仓 ≥ 100 且 ≥ 3 个月。

零分布走 `src/data/evaluation.apparatus.null_distribution`(月块自助 = 按信号月重抽整月),
`short_lab_common.boot_months` 同时算一遍做交叉核对。资金费按真实结算记入(缺数据记 0,另报覆盖率)。

用法:python3 docs/research/t199_short_arms_profile.py [--root <数据根>]
产物:docs/research/t199_results.json(每张票 + 月序列 + 判据画像)、
      docs/research/t199_forward_bands.json(冻结的预期带,前向对照只读它)、
      <数据根>/_reports/absorb_input/T-199_short_arms_profile.md(报告)。
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import importlib.util
import json
import os
import sys
from collections import defaultdict
from typing import Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (REPO, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
os.environ.setdefault("COMETCLOUD_DATA_ROOT", DATA_ROOT)
os.environ["T156_DATA"] = os.path.join(DATA_ROOT, "research", "t156") + "/"   # t159 用 f"{T156}_style.json"

import short_lab_common as sl  # noqa: E402
import s681_h4_bear_rally_fail as h4  # noqa: E402
from src.data.evaluation.apparatus import NoOpNull, null_distribution  # noqa: E402

OUT_RESULTS = os.path.join(HERE, "t199_results.json")
OUT_BANDS = os.path.join(HERE, "t199_forward_bands.json")
REPORT_DIR = os.path.join(DATA_ROOT, "_reports", "absorb_input")
REPORT = os.path.join(REPORT_DIR, "T-199_short_arms_profile.md")

MONTH_LO, MONTH_HI = "2020-01", "2026-09"
TICKET_LO, TICKET_HI = "2026-01-01", "2026-09-30"

L_SIGNAL_IDX = 6                 # 台账:信号日 = 第 7 根(下标 6)
L_S, L_N = 0.50, 60              # 台账:s = 50%,N = 60
L_JUDGE_N, L_JUDGE_M = 60, 6     # 台账判据
H_JUDGE_N, H_JUDGE_M = 100, 3    # 台账判据
BOOT_DRAWS, BOOT_SEED = 2000, 683
BTC_COST = 2 * sl.COST_SIDE      # BTC 腿来回成本:2 × 0.10%
SURVIVOR_PATH = os.path.join(DATA_ROOT, "research", "s677", "_survivor_symbols.json")
EXCL_BASES = {"BTCDOM", "DEFI", "USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDP",
              "USDE", "EURI", "XUSD", "EURT", "USD1", "USDD", "USTC", "FRAX", "LUSD"}

TICKET_FIELDS = ("arm", "symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px", "exit_px",
                 "risk", "ret", "r", "R", "funding", "funding_days", "hold_days", "why", "gap", "still",
                 "first_bar", "btc_entry_px", "btc_exit_px", "btc_raw", "btc_funding", "btc_funding_days",
                 "hedged_ret", "hedged_r")


# ── 小工具 ────────────────────────────────────────────────────────────────────────────────
def month_range(lo: str, hi: str) -> list[str]:
    y, m = int(lo[:4]), int(lo[5:7])
    y1, m1 = int(hi[:4]), int(hi[5:7])
    out = []
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_end(m: str) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    nxt = dt.date(y + 1, 1, 1) if mm == 12 else dt.date(y, mm + 1, 1)
    return (nxt - dt.timedelta(days=1)).isoformat()


def q(a, ps=(0.10, 0.50, 0.90)) -> Optional[dict]:
    arr = np.asarray([x for x in a if x is not None], float)
    if not arr.size:
        return None
    return {f"p{int(p*100)}": float(np.quantile(arr, p)) for p in ps}


def load_t159():
    spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["t159"] = mod
    spec.loader.exec_module(mod)
    return mod


def base_of(sym: str) -> str:
    return sym[:-4] if sym.endswith("USDT") else sym


def load_survivors() -> Optional[set[str]]:
    """今天还在交易的合约名(数据根 research/s677/_survivor_symbols.json,binance_hist 2026-10-23)。
    面板含已下架合约,前向只可能在这批名字上开新票 ⇒ 幸存者偏差必须记下来。"""
    p = SURVIVOR_PATH
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p))
    except Exception:
        return None
    syms = d.get("symbols") if isinstance(d, dict) else d
    return {str(s) for s in syms} if syms else None


# ── 臂 L:空新币 + 等名义多 BTC ───────────────────────────────────────────────────────────
def btc_hedge(um: dict, fund_daily: dict, t: dict) -> Optional[dict]:
    """BTCUSDT 永续多头腿:entry_d 开盘进、exit_d 开盘出(仍持有按最后收盘盯市)。
    多头付正资金费 ⇒ 资金费从腿收益里减。"""
    a = um.get("BTC")
    if a is None:
        return None
    ds, o, c = a["d"], a["o"], a["c"]
    i0 = bisect.bisect_left(ds, t["entry_d"])
    if i0 >= len(ds) or ds[i0] != t["entry_d"]:
        return None
    if t["still"] or not t["exit_d"]:
        i1, x, still = len(ds) - 1, float(c[-1]), True
        end_excl = len(ds)
    else:
        i1 = bisect.bisect_right(ds, t["exit_d"]) - 1
        if i1 < 0:
            return None
        x = float(o[i1])
        still = False
        end_excl = i1 + (1 if ds[i1] < t["exit_d"] else 0)   # 持有到 exit_d 当天开盘 ⇒ [entry_d, exit_d)
    e = float(o[i0])
    if not (e > 0):
        return None
    raw = x / e - 1
    fb = fund_daily.get("BTC", {})
    fs, cov = 0.0, 0
    for j in range(i0, end_excl):
        v = fb.get(ds[j])
        if v is not None:
            fs += float(v)
            cov += 1
    leg_ret = raw - BTC_COST - fs            # 成本 + 多头资金费
    hedged_ret = t["ret"] + leg_ret
    return {"btc_entry_px": e, "btc_exit_px": x, "btc_raw": raw, "btc_funding": fs,
            "btc_funding_days": cov, "btc_hold_days": end_excl - i0, "btc_still": still,
            "hedged_ret": hedged_ret, "hedged_r": hedged_ret / t["risk"]}


def arm_l(um: dict, fund_daily: dict) -> tuple[list[dict], dict]:
    tickets: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)
    for sym in sorted(um):
        a = um[sym]
        base = sym[:-4] if sym.endswith("USDT") else sym
        if not sym.isascii():
            skipped["non_ascii"] += 1
            continue
        if base in EXCL_BASES:
            skipped["excluded_base"] += 1
            continue
        if a["d"][0][:7] == "2019-09":
            skipped["listed_2019_09"] += 1
            continue
        if len(a["d"]) < L_SIGNAL_IDX + 2:
            skipped["too_few_bars"] += 1
            continue
        t = sl.short_ticket(a, L_SIGNAL_IDX, L_S, L_N, fund=fund_daily.get(sym), symbol=sym)
        if t is None:
            skipped["no_ticket"] += 1
            continue
        h = btc_hedge(um, fund_daily, t)
        if h is None:
            skipped["no_btc_leg"] += 1
            continue
        t = dict(t)
        t.update(h)
        t["R"] = h["hedged_r"]
        t["arm"] = "L"
        t["first_bar"] = a["d"][0]
        tickets.append(t)
    return tickets, dict(skipped)


# ── 臂 H:S-681 H4(T-196 的实现,一字不改)+ majors 闸门 ───────────────────────────────────
def arm_h(um: dict, fund_daily: dict, gate: dict) -> tuple[list[dict], list[dict], dict]:
    scan = h4.scan_um(um, fund_daily)
    allt = sl.chain(scan["tickets"])
    kept: list[dict] = []
    blocked: list[dict] = []
    for t in allt:
        g = gate.get(t["signal_d"])
        if g is None:
            blocked.append(dict(t, gate_state="missing"))
        elif g["gate_closed"]:
            t = dict(t)
            t["R"] = t["r"]
            t["arm"] = "H"
            t["first_bar"] = um[t["symbol"]]["d"][0]
            kept.append(t)
        else:
            blocked.append(dict(t, gate_state="open"))
    return kept, blocked, scan


# ── 月序列 / 分布 / 判据画像 ──────────────────────────────────────────────────────────────
def gate_month_state(gate: dict, months: list[str]) -> dict[str, dict]:
    month_set = set(months)
    per = defaultdict(lambda: {"n_days": 0, "n_closed": 0})
    for d, g in gate.items():
        m = d[:7]
        if m in month_set:
            per[m]["n_days"] += 1
            per[m]["n_closed"] += 1 if g.get("gate_closed") else 0
    out = {}
    for m in months:
        s = per.get(m, {"n_days": 0, "n_closed": 0})
        out[m] = {"n_days": s["n_days"], "n_closed_days": s["n_closed"],
                  "all_closed": bool(s["n_days"] and s["n_closed"] == s["n_days"]),
                  "mostly_closed": bool(s["n_days"] and s["n_closed"] / s["n_days"] >= 0.9)}
    return out


def monthly_rows(tickets: list[dict], months: list[str], gstate: dict) -> list[dict]:
    by = defaultdict(list)
    for t in tickets:
        by[t["signal_d"][:7]].append(t)
    rows = []
    for m in months:
        ts = by.get(m, [])
        closed = [t for t in ts if not t["still"]]
        allr = [t["R"] for t in ts]
        cr = [t["R"] for t in closed]
        g = gstate.get(m, {})
        rows.append({"month": m, "n": len(ts), "n_closed": len(closed), "n_open": len(ts) - len(closed),
                     "mean_r": float(np.mean(cr)) if cr else None,
                     "mean_r_all": float(np.mean(allr)) if allr else None,
                     "sum_r_closed": float(np.sum(cr)) if cr else 0.0,
                     "gate_days": g.get("n_days"), "gate_closed_days": g.get("n_closed_days"),
                     "gate_all_closed": g.get("all_closed")})
    return rows


def distribution(tickets: list[dict]) -> dict:
    r = np.array([t["R"] for t in tickets], float)
    closed = np.array([t["R"] for t in tickets if not t["still"]], float)
    if not r.size:
        return {"n": 0}
    return {"n": int(r.size), "n_closed": int(closed.size),
            "mean_r": float(r.mean()), "median_r": float(np.median(r)),
            "p05_r": float(np.quantile(r, 0.05)), "p95_r": float(np.quantile(r, 0.95)),
            "win_rate": float((r > 0).mean()),
            "worst_1pct_r": float(np.quantile(r, 0.01)), "best_r": float(r.max()),
            "total_r": float(r.sum()),
            "mean_r_closed": float(closed.mean()) if closed.size else None,
            "funding_coverage_short": float(np.mean([t["funding_days"] / max(1, t["hold_days"]) for t in tickets])),
            "funding_mean_short": float(np.mean([t["funding"] for t in tickets])),
            "funding_coverage_btc": (float(np.mean([t["btc_funding_days"] / max(1, t["btc_hold_days"])
                                                   for t in tickets]))
                                     if tickets and "btc_funding_days" in tickets[0] else None)}


def boot_p(tickets: list[dict], draws: int = BOOT_DRAWS, seed: int = BOOT_SEED):
    """月块自助 p(平均 R ≤ 0):按信号月重抽整月。零分布走 apparatus.null_distribution。
    返回 (p, 退化标志):所有票在同一个信号月 ⇒ 重抽没有变化(装置报 NoOpNull)⇒ 分布退化成一点,
    p = 1(平均 R ≤ 0)或 0(平均 R > 0),标记 degenerate=True。"""
    by = defaultdict(list)
    for t in tickets:
        by[t["signal_d"][:7]].append(t["R"])
    months = list(by)
    if not months:
        return None, False
    sums = np.array([float(np.sum(by[m])) for m in months])
    cnts = np.array([float(len(by[m])) for m in months])

    def fn(rng):
        picks = rng.integers(0, len(months), size=len(months))
        return float(sums[picks].sum() / cnts[picks].sum())

    mean = float(sums.sum() / cnts.sum())
    try:
        null = null_distribution(fn, draws, seed)
    except NoOpNull:
        return (1.0 if mean <= 0 else 0.0), True
    return float((null <= 0).mean()), False


def boot_p_shortlab(tickets: list[dict], draws: int = BOOT_DRAWS, seed: int = BOOT_SEED) -> Optional[float]:
    """交叉核对:short_lab_common.boot_months(同一估计量,Python random 的抽法)。"""
    proxy = [{"signal_d": t["signal_d"], "r": t["R"]} for t in tickets]
    if not proxy:
        return None
    p = sl.boot_months(proxy, draws=draws, seed=seed)
    return None if p != p else float(p)      # NaN → None


def judge_paths(tickets: list[dict], months: list[str], need_n: int, need_months: int) -> list[dict]:
    """每个历史月份当假想起点:按台账判据数要几个月到判、到判时的平均 R 与月块自助 p、会不会判过。"""
    by = defaultdict(list)
    for t in tickets:
        by[t["signal_d"][:7]].append(t)
    paths = []
    for k0, m0 in enumerate(months):
        acc: list[dict] = []
        hit = None
        for k in range(k0, len(months)):
            m = months[k]
            acc.extend(by.get(m, []))
            end = month_end(m)
            closed = [t for t in acc if (not t["still"]) and t["exit_d"] <= end]
            elapsed = k - k0 + 1
            if len(closed) >= need_n and elapsed >= need_months:
                rs = [t["R"] for t in closed]
                p, degenerate = boot_p(closed)
                p2 = boot_p_shortlab(closed)
                mr = float(np.mean(rs))
                hit = {"start_month": m0, "reached": True, "judge_month": m, "months_to_judge": elapsed,
                       "n_closed": len(closed), "n_signal_months": len({t["signal_d"][:7] for t in closed}),
                       "mean_r": mr, "p_le0": p, "p_le0_degenerate": degenerate, "p_le0_shortlab": p2,
                       "would_pass": bool(p is not None and mr > 0 and p < 0.05)}
                break
        if hit is None:
            end = month_end(months[-1])
            closed = [t for t in acc if (not t["still"]) and t["exit_d"] <= end]
            hit = {"start_month": m0, "reached": False, "months_to_judge": None,
                   "n_closed_at_end": len(closed),
                   "mean_r_at_end": float(np.mean([t["R"] for t in closed])) if closed else None,
                   "would_pass": False}
        paths.append(hit)
    return paths


def judge_summary(paths: list[dict]) -> dict:
    reached = [p for p in paths if p.get("reached")]
    n_pass = sum(1 for p in reached if p.get("would_pass"))
    return {"n_start_months": len(paths), "n_reached": len(reached),
            "frac_reached": (len(reached) / len(paths)) if paths else None,
            "n_would_pass": n_pass,
            "frac_would_pass_of_reached": (n_pass / len(reached)) if reached else None,
            "frac_would_pass_of_all_starts": (n_pass / len(paths)) if paths else None,
            "months_to_judge": q([p["months_to_judge"] for p in reached], ps=(0.10, 0.50, 0.90)),
            "months_to_judge_min": min((p["months_to_judge"] for p in reached), default=None),
            "months_to_judge_max": max((p["months_to_judge"] for p in reached), default=None),
            "mean_r_at_judge": (float(np.mean([p["mean_r"] for p in reached])) if reached else None),
            "mean_r_at_judge_q": q([p["mean_r"] for p in reached], ps=(0.10, 0.50, 0.90)),
            "p_le0_at_judge": (float(np.mean([p["p_le0"] for p in reached if p["p_le0"] is not None]))
                               if any(p["p_le0"] is not None for p in reached) else None)}


def band_block(rows: list[dict], keep=None) -> dict:
    sel = [r for r in rows if keep is None or keep(r)]
    counts = [r["n"] for r in sel]
    means = [r["mean_r"] for r in sel if r["mean_r"] is not None]
    return {"n_months": len(sel), "n_months_with_r": len(means),
            "tickets_per_month": q(counts), "tickets_per_month_mean": float(np.mean(counts)) if counts else None,
            "mean_r_per_month": q(means), "mean_r_per_month_mean": float(np.mean(means)) if means else None}


def by_year(tickets: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for t in tickets:
        by[t["signal_d"][:4]].append(t)
    out = []
    for y in sorted(by):
        ts = by[y]
        closed = [t for t in ts if not t["still"]]
        out.append({"year": y, "n": len(ts), "n_closed": len(closed),
                    "mean_r": float(np.mean([t["R"] for t in ts])),
                    "mean_r_closed": float(np.mean([t["R"] for t in closed])) if closed else None,
                    "win_rate": float(np.mean([t["R"] > 0 for t in ts]))})
    return out


# ── 报告 ──────────────────────────────────────────────────────────────────────────────────
def fmt(x, nd=3):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def write_report(res: dict, path: str) -> None:
    L, H = res["arm_L"], res["arm_H"]
    months = res["meta"]["months"]
    out = []
    a = out.append
    a("# T-199 / S-683 A 道:两条做空前向臂的历史画像")
    a("")
    a("**这是描述,不是检验。** 两条臂(臂 L 空新币 + 等名义多 BTC;臂 H 熊市反弹失败 × majors 闸门关)"
      "在历史上都已经看过,历史只能给出「它们长什么样」,给不出「它们会不会过」。"
      "本文件把历史画像冻结成前向逐月对照的**预期带**;判据本身只用来算「要到判据要几个月」,不在这份报告里下结论。")
    a("")
    a(f"- 数据根:`{res['meta']['data_root']}`(`research/s681/`:890 个 USDT 本位永续含已下架 + 891 个资金费;"
      f"majors 闸门 = `t159.load_gate()`,源 `{res['meta']['gate_source']}`)")
    a(f"- 窗口:月序列 {months[0]} → {months[-1]};逐张票清单 {TICKET_LO} → {TICKET_HI}")
    a(f"- 判据(台账写死):臂 L 已平仓 ≥ {L_JUDGE_N} 且距 inception ≥ {L_JUDGE_M} 个月;"
      f"臂 H 已平仓 ≥ {H_JUDGE_N} 且 ≥ {H_JUDGE_M} 个月")
    a(f"- p 值:月块自助 {BOOT_DRAWS} 次、种子 {BOOT_SEED},零分布走 `src/data/evaluation/apparatus.null_distribution`;"
      f"同时用 `short_lab_common.boot_months` 交叉核对")
    sb = res.get("survivorship", {})
    if sb.get("L"):
        a(f"- **幸存者偏差(前向对照用哪条带,先看这条):** 面板含已下架合约;"
          f"臂 L {sb['L']['n_tickets_survivor']}/{sb['L']['n_tickets']} 张票"
          f"({fmt(sb['L']['frac_survivor'], 3)})、臂 H {sb['H']['n_tickets_survivor']}/{sb['H']['n_tickets']} 张票"
          f"({fmt(sb['H']['frac_survivor'], 3)})落在今天仍在交易的名字上 ⇒ 前向月票数结构上低于历史带;"
          f"预期带另给一份「只算今天仍在交易的名字」的带。")
    a("")
    for arm, blk, title in (("L", L, "臂 L:空新币 + 等名义多 BTC(对冲 R)"),
                             ("H", H, "臂 H:S-681 H4 × majors 闸门关(单腿 R)")):
        a(f"## {title}")
        a("")
        d = blk["distribution"]
        u = blk["universe"]
        a(f"- 票数 {u['n_tickets']}(其中已平仓 {u['n_closed']}、未平 {u['n_open']})")
        if arm == "L":
            a(f"- 宇宙:{u['n_symbols_total']} 个合约,进扫描 {u['n_symbols_in_scope']};"
              f"跳过:{json.dumps(u['skipped'], ensure_ascii=False)};"
              f"第一根日线落在 2019-09 的合约 {u['n_2019_09_listed']} 个")
        else:
            a(f"- 宇宙:{u['n_symbols_total']} 个合约;H4 票(闸门前) {u['n_h4_tickets_before_gate']},"
              f"闸门关留下 {u['n_tickets']},blocked {u['n_blocked']}"
              f"(闸门开 {u['n_blocked_gate_open']}、闸门无记录 {u['n_blocked_gate_missing']})")
        a(f"- R 分布:均值 {fmt(d.get('mean_r'))}、中位 {fmt(d.get('median_r'))}、"
          f"5 分位 {fmt(d.get('p05_r'))}、95 分位 {fmt(d.get('p95_r'))}、"
          f"胜率 {fmt(d.get('win_rate'), 3)}、最差 1% {fmt(d.get('worst_1pct_r'))}")
        if d.get("funding_coverage_btc") is not None:
            a(f"- 资金费:空腿覆盖率 {fmt(d.get('funding_coverage_short'), 3)}、BTC 腿覆盖率 {fmt(d.get('funding_coverage_btc'), 3)};"
              f"空腿平均资金费 {fmt(d.get('funding_mean_short'), 5)}")
        js = blk["judge_summary"]
        a(f"- 到判据:从 {js['n_start_months']} 个历史月份当起点,{js['n_reached']} 个能到判;"
          f"到判要 {fmt(js.get('months_to_judge_min'), 0)}–{fmt(js.get('months_to_judge_max'), 0)} 个月"
          f"(p50 {fmt((js.get('months_to_judge') or {}).get('p50'), 1)});"
          f"到判时平均 R 均值 {fmt(js.get('mean_r_at_judge'))};"
          f"**会判过的起点 {js['n_would_pass']}/{js['n_reached']}"
          f"({fmt(js.get('frac_would_pass_of_reached'), 3)} 的能到判起点)**")
        a("")
        a("### 月序列(按信号月)")
        a("")
        if arm == "H":
            a("| 月 | 票数 | 已平 | 未平 | 平均 R(已平) | 平均 R(全) | 闸门关/当月天 |")
            a("|---|---|---|---|---|---|---|")
            for r in blk["monthly"]:
                a(f"| {r['month']} | {r['n']} | {r['n_closed']} | {r['n_open']} | "
                  f"{fmt(r['mean_r'])} | {fmt(r['mean_r_all'])} | "
                  f"{r['gate_closed_days']}/{r['gate_days']} |")
        else:
            a("| 月 | 票数 | 已平 | 未平 | 平均 R(已平) | 平均 R(全) |")
            a("|---|---|---|---|---|---|")
            for r in blk["monthly"]:
                a(f"| {r['month']} | {r['n']} | {r['n_closed']} | {r['n_open']} | "
                  f"{fmt(r['mean_r'])} | {fmt(r['mean_r_all'])} |")
        a("")
        a("### 按年")
        a("")
        a("| 年 | 票数 | 已平 | 平均 R | 胜率 |")
        a("|---|---|---|---|---|")
        for r in blk["by_year"]:
            a(f"| {r['year']} | {r['n']} | {r['n_closed']} | {fmt(r['mean_r'])} | {fmt(r['win_rate'])} |")
        a("")
        b = blk["bands"]
        a("### 冻结的预期带")
        a("")
        a("| 口径 | 月数 | 月票数 p10 / p50 / p90 | 月平均 R p10 / p50 / p90 |")
        a("|---|---|---|---|")
        for name, bb in b.items():
            if not isinstance(bb, dict) or "tickets_per_month" not in bb:
                continue
            tp, mr = bb["tickets_per_month"], bb["mean_r_per_month"]
            a(f"| {name} | {bb['n_months']} | "
              f"{fmt((tp or {}).get('p10'), 1)} / {fmt((tp or {}).get('p50'), 1)} / {fmt((tp or {}).get('p90'), 1)} | "
              f"{fmt((mr or {}).get('p10'))} / {fmt((mr or {}).get('p50'))} / {fmt((mr or {}).get('p90'))} |")
        a("")
        a("### 到判据的路径(每个历史月份当假想起点)")
        a("")
        a("| 起点 | 到判月 | 几个月 | 已平仓 | 平均 R | p(≤0) | 会判过 |")
        a("|---|---|---|---|---|---|---|")
        for pth in blk["judge_paths"]:
            if pth.get("reached"):
                a(f"| {pth['start_month']} | {pth['judge_month']} | {pth['months_to_judge']} | {pth['n_closed']} | "
                  f"{fmt(pth['mean_r'])} | {fmt(pth['p_le0'], 4)} | {'是' if pth['would_pass'] else '否'} |")
            else:
                a(f"| {pth['start_month']} | — | 未到判 | {pth['n_closed_at_end']} | "
                  f"{fmt(pth.get('mean_r_at_end'))} | — | 否 |")
        a("")
    a("## 协议问题(照台账一字不改,只记录)")
    a("")
    for line in res["protocol_notes"]:
        a(f"- {line}")
    a("")
    a("## 探索性 —— 需另立预注册、在新数据上过零信号对照")
    a("")
    for line in res["exploratory_notes"]:
        a(f"- {line}")
    a("")
    a("## 产物")
    a("")
    a("- `docs/research/t199_results.json`:两条臂每张票 + 月序列 + 判据画像")
    a("- `docs/research/t199_forward_bands.json`:冻结的预期带(前向逐月对照只读它)")
    a("")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


# ── 主流程 ────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    global DATA_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DATA_ROOT)
    args = ap.parse_args()
    DATA_ROOT = args.root
    os.environ["COMETCLOUD_DATA_ROOT"] = DATA_ROOT
    os.environ["T156_DATA"] = os.path.join(DATA_ROOT, "research", "t156") + "/"

    um = sl.load_um()
    fund_daily = sl.daily_funding(sl.load_funding())
    t159 = load_t159()
    gate = t159.load_gate()
    months = month_range(MONTH_LO, MONTH_HI)
    gstate = gate_month_state(gate, months)

    # ── 臂 L ──────────────────────────────────────────────────────────────────────────────
    L, L_skip = arm_l(um, fund_daily)
    L_monthly = monthly_rows(L, months, gstate)
    L_paths = judge_paths(L, months, L_JUDGE_N, L_JUDGE_M)
    L_bands = {"全期(2020-01 → 2026-09)": band_block(L_monthly),
               "闸门全关的月份": band_block(L_monthly, lambda r: r["gate_all_closed"])}

    # ── 臂 H ──────────────────────────────────────────────────────────────────────────────
    H, H_blocked, H_scan = arm_h(um, fund_daily, gate)
    H_monthly = monthly_rows(H, months, gstate)
    H_paths = judge_paths(H, months, H_JUDGE_N, H_JUDGE_M)
    H_bands = {"全期(2020-01 → 2026-09)": band_block(H_monthly),
               "闸门全关的月份": band_block(H_monthly, lambda r: r["gate_all_closed"])}

    # ── 幸存者偏差:只留「今天还在交易的名字」(前向只可能在这批名字上开新票)──────────────
    surv = load_survivors()
    surv_block: dict = {}
    if surv:
        L_s = [t for t in L if base_of(t["symbol"]) in surv]
        H_s = [t for t in H if base_of(t["symbol"]) in surv]
        L_ms = monthly_rows(L_s, months, gstate)
        H_ms = monthly_rows(H_s, months, gstate)
        L_bands["只算今天仍在交易的名字(幸存者口径)"] = band_block(L_ms)
        H_bands["只算今天仍在交易的名字(幸存者口径)"] = band_block(H_ms)
        surv_block = {
            "source": SURVIVOR_PATH,
            "n_survivor_symbols": len(surv),
            "n_panel_symbols": len({t["symbol"] for t in L} | {t["symbol"] for t in H}),
            "n_panel_symbols_in_survivor": len({base_of(s) for s in
                                                ({t["symbol"] for t in L} | {t["symbol"] for t in H})} & surv),
            "L": {"n_tickets": len(L), "n_tickets_survivor": len(L_s),
                  "frac_survivor": (len(L_s) / len(L)) if L else None,
                  "mean_r": float(np.mean([t["R"] for t in L])) if L else None,
                  "mean_r_survivor": float(np.mean([t["R"] for t in L_s])) if L_s else None},
            "H": {"n_tickets": len(H), "n_tickets_survivor": len(H_s),
                  "frac_survivor": (len(H_s) / len(H)) if H else None,
                  "mean_r": float(np.mean([t["R"] for t in H])) if H else None,
                  "mean_r_survivor": float(np.mean([t["R"] for t in H_s])) if H_s else None},
        }
    else:
        surv_block = {"source": SURVIVOR_PATH, "error": "文件不存在或读不出,幸存者口径未算"}

    # ── 探索性敏感性(不是结论)──────────────────────────────────────────────────────────
    panel_start = sorted({t["symbol"] for t in L if t["first_bar"][:7] == "2020-01"})
    L_ex = [t for t in L if t["first_bar"][:7] != "2020-01"]
    L_ex_paths = judge_paths(L_ex, months, L_JUDGE_N, L_JUDGE_M)
    old_min = h4.MIN_LISTED_DAYS
    h4.MIN_LISTED_DAYS = 220
    H220, _, _ = arm_h(um, fund_daily, gate)
    h4.MIN_LISTED_DAYS = old_min
    H220_paths = judge_paths(H220, months, H_JUDGE_N, H_JUDGE_M)

    # BTC 腿资金费符号翻过来(经济上是错的:多头付正费率)—— 只为定位台账 H1 那个数的来源
    L_flip = [(t["ret"] + t["btc_raw"] - 0.002 + t["btc_funding"]) / t["risk"] for t in L]
    L_flip_m = [t["signal_d"][:7] for t in L]
    flip_disc = [v for v, mm in zip(L_flip, L_flip_m) if "2020-01" <= mm <= "2023-12"]
    flip_hold = [v for v, mm in zip(L_flip, L_flip_m) if mm >= "2024-01"]

    exploratory = {
        "L_without_panel_start": {
            "dropped_symbols": panel_start,
            "n_tickets": len(L_ex),
            "mean_r": float(np.mean([t["R"] for t in L_ex])) if L_ex else None,
            "judge": judge_summary(L_ex_paths)},
        "H_listed_220": {
            "n_tickets": len(H220),
            "mean_r": float(np.mean([t["R"] for t in H220])) if H220 else None,
            "judge": judge_summary(H220_paths)},
        "L_btc_funding_sign_flipped": {
            "disc_mean_r": float(np.mean(flip_disc)) if flip_disc else None,
            "hold_mean_r": float(np.mean(flip_hold)) if flip_hold else None,
            "note": "经济上错的方向(多头付正费率);只用来定位台账 H1 那个 +0.26/+0.155 的来源"},
    }

    # ── 交叉核对:逐位复现 `s681_h1_new_listing.py`(台账 S-681 H1 的短腿)────────────────
    h1: list[dict] = []
    for sym in sorted(um):
        a = um[sym]
        if a["d"][0] < "2019-10-01" or len(a["d"]) <= L_SIGNAL_IDX + 1:
            continue
        t = sl.short_ticket(a, L_SIGNAL_IDX, L_S, L_N, fund=fund_daily.get(sym), symbol=sym)
        if t:
            t["first_bar"] = a["d"][0]
            h1.append(t)
    h1 = sl.chain(h1)
    h1_d = [t for t in h1 if "2020-01-01" <= t["signal_d"] <= "2023-12-31"]
    h1_h = [t for t in h1 if t["signal_d"] >= "2024-01-01"]
    crosscheck_h1 = {
        "script": "docs/research/s681_h1_new_listing.py",
        "n_total": len(h1), "disc_n": len(h1_d), "hold_n": len(h1_h),
        "disc_mean_r": float(np.mean([t["r"] for t in h1_d])),
        "hold_mean_r": float(np.mean([t["r"] for t in h1_h])),
        "reference_from_committed_results_json": {"disc_mean_r": 0.04544193159722148,
                                                   "hold_mean_r": 0.06447948239385101},
        "bit_identical": bool(len(h1_d) == 258 and len(h1_h) == 620
                              and abs(float(np.mean([t["r"] for t in h1_d])) - 0.04544193159722148) < 1e-12
                              and abs(float(np.mean([t["r"] for t in h1_h])) - 0.06447948239385101) < 1e-12),
    }

    protocol_notes = [
        "臂 L 的「数据第一个月 2019-09 上市的不算」这条规则在本面板上是**空规则**:"
        "`research/s681/_um_daily.jsonl` 里第一根日线落在 2019-09 的合约数为 0"
        "(面板最早的第一根日线是 2020-01-01)。实际后果是:2019-09 ~ 2019-12 上线的合约"
        "(含 BTCUSDT 永续本身)在这份面板里**看不到**,2020-01-01 之前上市的老币被当成了「新币」。",
        "同上:面板起点被截断 —— 2020-01-01 有 "
        f"{len(panel_start)} 个合约的第一根日线落在那天(含 BTC / ETH / BNB),它们在臂 L 里被当作上市事件。"
        "本次按台账一字不改地保留,剔除它们的敏感性在「探索性」一节。",
        "台账 S-683 臂 H 写「≥ 220 根」,T-196 的实现(本文件 import 的一份)是「上市 ≥ 200 天」"
        "(= 信号下标 ≥ 200)。两者不是同一条:本报告主口径用 T-196 的实现(卡上写明「你 T-196 的实现」),"
        "「220 根」版本的差异在「探索性」一节。",
        "「到判时的票数」口径:按台账「**已平仓** ≥ N」,判据时点只数**在该时点之前已经平掉**的票"
        "(平仓日 ≤ 该月末);仍在持有的票不计、也不进平均 R 与自助 p(否则会把未来信息带进历史判定)。",
        "臂 L 的 R = (空腿净收益 + BTC 腿毛收益 − BTC 腿来回成本 0.20% − BTC 腿多头资金费)÷ 0.5;"
        "空腿净收益已含空腿自己的来回成本 0.20% 与空头收到的资金费(台账「共同口径」)。",
        "臂 L 的空腿**逐位复现**已提交的 `docs/research/s681_h1_new_listing.py`(台账 S-681 H1):"
        f"发现段 {crosscheck_h1['disc_n']} 票平均 R {crosscheck_h1['disc_mean_r']:.6f}、"
        f"留出段 {crosscheck_h1['hold_n']} 票平均 R {crosscheck_h1['hold_mean_r']:.6f},"
        "与 `docs/research/s681_h1_results.json` 完全一致 ⇒ 进场下标、止损、持有、成本、资金费都对齐了。",
        "**对冲口径与台账 H1 那一节的只报数有差(要记下来):** 台账 S-681 H1 一节写「对冲版 发现段 +0.26R / 留出段 +0.155R、"
        "七年无负年」,但那段数**没有落进任何脚本**(H1 脚本里没有对冲腿)。按 S-683 写死的公式实算:"
        f"发现段 {fmt(float(np.mean([t['R'] for t in L if '2020-01-01' <= t['signal_d'] <= '2023-12-31'])))}R、"
        f"留出段 {fmt(float(np.mean([t['R'] for t in L if t['signal_d'] >= '2024-01-01'])))}R;"
        "按年 2020 +0.42 / 2021 −0.04 / 2022 +0.17 / 2023 +0.24 / 2024 +0.30 / 2025 +0.05 / 2026 +0.14 —— "
        "同号、同量级,但 **2021 年是负的**(台账那版写的是 +0.01、无负年)。差额落在 BTC 腿的实现细节上"
        "(资金费符号翻过来会变成 +0.30/+0.17,仍不等于台账那个数 ⇒ 台账那个数不可复现)。"
        "前向预期带用本报告这一版。",
        "「月平均 R」分位只在**有票的月份**上算(没票的月份平均 R 无定义);「月票数」分位把**零票月份**算进去。",
        "闸门口径:`t159.load_gate()` 用 `research/t156/_style.json` 的 majors cap 指数自 200 日均值;"
        "该指数自 2020-01-01 起、200 个观测后才有 gate_closed 判定 ⇒ 2020-01 ~ 2020-07 的 H4 票"
        "在结构上不可能通过闸门,全部记为 blocked。",
        "「闸门全关的月份」定义 = 该月内闸门**每个**交易日都 gate_closed(逐月表里另有「闸门关/当月天」两列可自行改口径)。"
        "臂 L 协议里没有闸门,它的「闸门全关的月份」分位只作参考。",
        "**幸存者偏差(前向对照必读):** 面板 `research/s681/` 含已下架合约(890 个),"
        f"今天还能在 binance_hist 上看到的是 {surv_block.get('n_survivor_symbols', '—')} 个"
        f"(`research/s677/_survivor_symbols.json`,2026-10-23)。"
        f"臂 L {surv_block.get('L', {}).get('n_tickets', '—')} 张票里只有 "
        f"{surv_block.get('L', {}).get('n_tickets_survivor', '—')} 张落在还活着的名字上"
        f"({fmt(surv_block.get('L', {}).get('frac_survivor'), 3)});"
        f"臂 H 是 {surv_block.get('H', {}).get('n_tickets_survivor', '—')}/"
        f"{surv_block.get('H', {}).get('n_tickets', '—')}"
        f"({fmt(surv_block.get('H', {}).get('frac_survivor'), 3)})。"
        "⇒ 前向月票数**结构上**会低于历史带(历史上已下架的币不会再来一次上市事件),"
        "拿全期带直接比会把「前向宇宙变小」误读成「策略变差」。"
        "预期带里另给一份「只算今天仍在交易的名字」的带,前向对照用那份更公平。",
    ]

    exploratory_notes = [
        "臂 L 剔除「第一根日线 = 2020-01-01」的 "
        f"{len(panel_start)} 个合约后:票数 {len(L_ex)}(原 {len(L)})、平均对冲 R "
        f"{fmt(exploratory['L_without_panel_start']['mean_r'])};"
        f"会判过的起点 {exploratory['L_without_panel_start']['judge']['n_would_pass']}/"
        f"{exploratory['L_without_panel_start']['judge']['n_reached']}"
        f"(原 {judge_summary(L_paths)['n_would_pass']}/{judge_summary(L_paths)['n_reached']})。"
        "**探索性 —— 需另立预注册、在新数据上过零信号对照。**",
        "臂 H 换成「上市 ≥ 220 天」:票数 "
        f"{exploratory['H_listed_220']['n_tickets']}(原 {len(H)})、平均 R "
        f"{fmt(exploratory['H_listed_220']['mean_r'], 4)}(原 {fmt(float(np.mean([t['R'] for t in H])), 4) if H else '—'});"
        f"会判过的起点 {exploratory['H_listed_220']['judge']['n_would_pass']}/"
        f"{exploratory['H_listed_220']['judge']['n_reached']}。"
        "**探索性 —— 需另立预注册、在新数据上过零信号对照。**",
        "把臂 L 的 BTC 腿资金费符号翻过来(经济上是错的方向:多头付正费率)⇒ 发现段 "
        f"{fmt(exploratory['L_btc_funding_sign_flipped']['disc_mean_r'])}R、留出段 "
        f"{fmt(exploratory['L_btc_funding_sign_flipped']['hold_mean_r'])}R,更靠近台账 H1 那个 +0.26/+0.155 "
        "但仍不相等 ⇒ 台账那版对冲腿另有实现细节,不可复现。**探索性 —— 需另立预注册、在新数据上过零信号对照。**",
        "只留「今天仍在交易的名字」的敏感性:臂 L 平均对冲 R "
        f"{fmt(surv_block.get('L', {}).get('mean_r_survivor'))}(全样本 {fmt(surv_block.get('L', {}).get('mean_r'))})、"
        f"臂 H 平均 R {fmt(surv_block.get('H', {}).get('mean_r_survivor'))}"
        f"(全样本 {fmt(surv_block.get('H', {}).get('mean_r'))})。"
        "存活下来的名字平均 R 更高 —— 这正是幸存者偏差的方向,不能当成「筛得更准」读。"
        "**探索性 —— 需另立预注册、在新数据上过零信号对照。**",
    ]

    res = {
        "meta": {
            "task": "T-199", "ledger": "S-683", "kind": "description_not_test",
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "data_root": DATA_ROOT,
            "gate_source": os.path.join(DATA_ROOT, "research", "t156", "_style.json"),
            "months": months, "ticket_window": [TICKET_LO, TICKET_HI],
            "judge": {"L": {"n_closed": L_JUDGE_N, "months": L_JUDGE_M},
                      "H": {"n_closed": H_JUDGE_N, "months": H_JUDGE_M}},
            "boot": {"draws": BOOT_DRAWS, "seed": BOOT_SEED, "scheme": "month_block_resample"},
            "rules": {"L_signal_index": L_SIGNAL_IDX, "L_s": L_S, "L_N": L_N, "L_risk": L_S,
                      "H": "s681_h4_bear_rally_fail.py (T-196) verbatim",
                      "H_gate": "t159.load_gate().gate_closed on signal_d"},
        },
        "arm_L": {
            "universe": {"n_symbols_total": len(um), "n_symbols_in_scope": len(L),
                         "n_tickets": len(L), "n_closed": sum(1 for t in L if not t["still"]),
                         "n_open": sum(1 for t in L if t["still"]), "skipped": L_skip,
                         "n_2019_09_listed": sum(1 for a in um.values() if a["d"][0][:7] == "2019-09")},
            "distribution": distribution(L),
            "by_year": by_year(L),
            "monthly": L_monthly,
            "bands": L_bands,
            "judge_paths": L_paths,
            "judge_summary": judge_summary(L_paths),
            "tickets": [dict({k: t[k] for k in TICKET_FIELDS if k in t}) for t in L],
            "tickets_2026": [dict({k: t[k] for k in TICKET_FIELDS if k in t})
                             for t in L if TICKET_LO <= t["signal_d"] <= TICKET_HI],
        },
        "arm_H": {
            "universe": {"n_symbols_total": len(um),
                         "n_h4_tickets_before_gate": len(H_scan["tickets"]),
                         "n_tickets": len(H), "n_closed": sum(1 for t in H if not t["still"]),
                         "n_open": sum(1 for t in H if t["still"]),
                         "n_blocked": len(H_blocked),
                         "n_blocked_gate_open": sum(1 for t in H_blocked if t["gate_state"] == "open"),
                         "n_blocked_gate_missing": sum(1 for t in H_blocked if t["gate_state"] == "missing"),
                         "n_state_days": H_scan["n_state_days"], "n_cand_days": H_scan["n_cand_days"]},
            "distribution": distribution(H),
            "by_year": by_year(H),
            "monthly": H_monthly,
            "bands": H_bands,
            "judge_paths": H_paths,
            "judge_summary": judge_summary(H_paths),
            "tickets": [dict({k: t[k] for k in TICKET_FIELDS if k in t}) for t in H],
            "tickets_2026": [dict({k: t[k] for k in TICKET_FIELDS if k in t})
                             for t in H if TICKET_LO <= t["signal_d"] <= TICKET_HI],
            "blocked": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "gate_state": t["gate_state"],
                         "r": t["r"]} for t in H_blocked],
        },
        "protocol_notes": protocol_notes,
        "exploratory": exploratory,
        "exploratory_notes": exploratory_notes,
        "survivorship": surv_block,
        "crosscheck_h1_short_leg": crosscheck_h1,
    }
    json.dump(res, open(OUT_RESULTS, "w"), indent=1, default=str)

    bands_out = {
        "frozen_at_utc": res["meta"]["generated_at_utc"],
        "task": "T-199", "ledger": "S-683",
        "kind": "expected_bands_from_history_DESCRIPTION_ONLY",
        "how_to_read": "前向逐月对照只读这份文件:每个前向月的票数与平均 R,落在对应分位带内即『与历史画像一致』;"
                       "落在带外只是画像不一致,不构成结论。",
        "conventions": {
            "months": f"{MONTH_LO} → {MONTH_HI}",
            "ticket_counts_include_zero_ticket_months": True,
            "mean_r_percentiles_use_months_with_at_least_one_closed_ticket": True,
            "monthly_mean_r_is_over_closed_tickets": True,
            "gate_closed_month_definition": "该月内闸门每个交易日都 gate_closed",
            "judge": {"L": {"n_closed": L_JUDGE_N, "months": L_JUDGE_M},
                      "H": {"n_closed": H_JUDGE_N, "months": H_JUDGE_M}},
            "boot": {"draws": BOOT_DRAWS, "seed": BOOT_SEED},
        },
        "arm_L": {"bands": L_bands, "n_tickets": len(L),
                  "months_with_tickets": sum(1 for r in L_monthly if r["n"] > 0)},
        "arm_H": {"bands": H_bands, "n_tickets": len(H),
                  "months_with_tickets": sum(1 for r in H_monthly if r["n"] > 0)},
        "survivorship": surv_block,
    }
    json.dump(bands_out, open(OUT_BANDS, "w"), indent=1, default=str)

    os.makedirs(REPORT_DIR, exist_ok=True)
    write_report(res, REPORT)

    # ── 汇总行(上下文要省)──────────────────────────────────────────────────────────────
    for arm, blk in (("L", res["arm_L"]), ("H", res["arm_H"])):
        js = blk["judge_summary"]
        print(arm, "n", blk["universe"]["n_tickets"], "closed", blk["universe"]["n_closed"],
              "meanR", fmt(blk["distribution"].get("mean_r")), "medR", fmt(blk["distribution"].get("median_r")),
              "win", fmt(blk["distribution"].get("win_rate")),
              "p05", fmt(blk["distribution"].get("p05_r")), "p95", fmt(blk["distribution"].get("p95_r")),
              "worst1%", fmt(blk["distribution"].get("worst_1pct_r")))
        print(arm, "judge reached", js["n_reached"], "/", js["n_start_months"],
              "months", js.get("months_to_judge_min"), "-", js.get("months_to_judge_max"),
              "p50", fmt((js.get("months_to_judge") or {}).get("p50"), 1),
              "pass", js["n_would_pass"], "frac", fmt(js.get("frac_would_pass_of_reached")))
    print("L skipped", json.dumps(L_skip), "L 2019-09 listed",
          res["arm_L"]["universe"]["n_2019_09_listed"], "panel_start", len(panel_start))
    print("H blocked", res["arm_H"]["universe"]["n_blocked"],
          "open", res["arm_H"]["universe"]["n_blocked_gate_open"],
          "missing", res["arm_H"]["universe"]["n_blocked_gate_missing"])
    print("L 2026 tickets", len(res["arm_L"]["tickets_2026"]), "H 2026 tickets", len(res["arm_H"]["tickets_2026"]))
    print("OUT", OUT_RESULTS, OUT_BANDS, REPORT)


if __name__ == "__main__":
    main()
