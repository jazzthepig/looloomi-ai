"""S-647 代入模拟的装载与报告。引擎在 src/exec_host/sim_tickets.py(纯函数,实盘执行器的同一个决策函数)。

数据(只读,来自 C 道 T-159 的缓存,与 S-638 同一份票):
  /Volumes/CometCloudAI/cometcloud-local/research/t159/_tickets_2020-03-01_2026-06-20.json   770 张多头票
  /Volumes/CometCloudAI/cometcloud-local/research/t156/_bars_early.jsonl + _bars.jsonl         2018 → 2025-04 日线
  /Volumes/CometCloudAI/cometcloud-local/research/t159/_bars.jsonl                            2025-04 → 2026-10-19
  /Volumes/CometCloudAI/cometcloud-local/research/t159/_funding.json                          binance_perp 资金费(→ 2026-09-30)
HL 永续名单与 Aave v3 USDC 月均存款利率:2026-10-21 从库里读出,写死在下面(可复现)。

用法:python3 docs/research/s647_sim_r_v2.py [--root /Volumes/CometCloudAI/cometcloud-local] [--paths 2000] [--jobs 4]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.exec_host.sim_tickets import EPOCH, SimTicket, simulate, stats  # noqa: E402

HL_PERPS = set("""0G 2Z AAVE ACE ADA AERO AI AI16Z AIXBT ALGO ALT ANIME APE APEX APT AR ARB ARK ASTER ATOM AVAX AVNT AXS
AZTEC BABY BADGER BANANA BCH BERA BIGTIME BIO BLAST BLUR BLZ BNB BNT BOME BRETT BSV BTC CAKE CANTO CASHCAT CATI CC CELO CFX
CHILLGUY CHIP COMP CRV CYBER DASH DOGE DOOD DOT DYDX DYM EIGEN ENA ENS ETC ETH ETHFI FARTCOIN FET FIL FOGO FRIEND FTM FTT
FXS GALA GAS GMT GMX GOAT GRAM GRASS GRIFFAIN HBAR HEMI HMSTR HPOS HYPE HYPER ICP ILV IMX INIT INJ IO IOTA IP JELLY JTO JUP
KAITO KAS KBONK KDOGS KFLOKI KLUNC KNEIRO KPEPE KSHIB LAUNCHCOIN LAYER LDO LINEA LINK LISTA LIT LOOM LTC MANTA MATIC MAV
MAVIA ME MEGA MELANIA MEME MERL MET MEW MINA MKR MNT MON MOODENG MORPHO MOVE MYRO NEAR NEIROETH NEO NFTI NIL NOT NTRN NXPC
OGN OM OMNI ONDO OP ORBS ORDI OX PANDORA PAXG PENDLE PENGU PEOPLE PIXEL PNUT POL POLYX PONS POPCAT PROMPT PROVE PUMP PURR
PYTH RDNT RENDER REQ RESOLV REZ RLB RNDR RSR RUNE S SAGA SAND SCR SEI SHIA SKR SKY SNX SOL SOPH SPX STABLE STBL STG STRAX
STRK STX SUI SUPER SUSHI SYRUP TAO TIA TNSR TON TRB TRUMP TRX TST TURBO UMA UNI UNIBOT USELESS USTC USUAL VINE VIRTUAL VVV
W WCT WIF WLD WLFI XAI XLM XMR XPL XRP YGG YZY ZEC ZEN ZEREBRO ZETA ZK ZORA ZRO""".split())

APY_MONTH = dict(x.split(":") for x in (
    "2023-02:1.79,2023-03:1.53,2023-04:2.15,2023-05:2.48,2023-06:2.37,2023-07:5.01,2023-08:4.99,2023-09:3.62,"
    "2023-10:3.89,2023-11:6.51,2023-12:7.12,2024-01:7.06,2024-02:7.71,2024-03:10.64,2024-04:7.82,2024-05:6.93,"
    "2024-06:7.57,2024-07:5.76,2024-08:4.09,2024-09:3.93,2024-10:4.71,2024-11:7.18,2024-12:12.55,2025-01:8.01,"
    "2025-02:4.45,2025-03:2.98,2025-04:2.70,2025-05:3.58,2025-06:4.01,2025-07:3.81,2025-08:4.30,2025-09:4.48,"
    "2025-10:3.70,2025-11:4.19,2025-12:3.29,2026-01:3.63,2026-02:2.44,2026-03:1.99,2026-04:4.97,2026-05:3.58,"
    "2026-06:3.15,2026-07:3.25,2026-08:3.37,2026-09:3.61,2026-10:3.89").split(","))
APY_FALLBACK = 3.4
HIST_START, HIST_END = dt.date(2020, 4, 1), dt.date(2026, 10, 19)
LEVS = (1.0, 2.0, 3.0, 4.0, 5.0)
SIZES = (704.0, 100_000.0)
POLICIES = ("const", "brake")
#: 钱放在哪(sim_tickets.simulate 的 collateral_mult):A = 预注册原文(偏乐观);B = 全留 HL;C = HL 上 2 × 初始保证金
VARIANTS = {"A": None, "B": float("inf"), "C": 2.0, "C'": "g0.5"}
MC_VARIANTS = ("A", "B", "C", "C'")


def _coll(variant):
    """(collateral_mult, collateral_gross):C' = HL 上留 50% 持仓名义(S-647 补 2,看过 C 之后加的)。"""
    v = VARIANTS[variant]
    return (None, float(v[1:])) if isinstance(v, str) else (v, None)
MC_MONTHS, SEED = 36, 647


def hl_listed(symbol: str) -> bool:
    s = symbol.upper()
    if s.startswith("1000000"):
        s = s[7:]
    elif s.startswith("1000"):
        s = s[4:]
    return s in HL_PERPS or f"K{s}" in HL_PERPS


def apy(d: dt.date) -> float:
    return float(APY_MONTH.get(d.strftime("%Y-%m"), APY_FALLBACK)) / 100.0


def load(root: str):
    bars: dict[str, dict[dt.date, tuple]] = defaultdict(dict)
    for f in ("research/t156/_bars_early.jsonl", "research/t156/_bars.jsonl", "research/t159/_bars.jsonl"):
        for line in open(os.path.join(root, f)):
            for r in json.loads(line):
                bars[r["symbol"]][dt.date.fromisoformat(r["trade_date"][:10])] = (
                    float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
    fund: dict[tuple, float] = defaultdict(float)
    for r in json.load(open(os.path.join(root, "research/t159/_funding.json"))):
        fund[(r["symbol"], r["funding_time"][:10])] += float(r["funding_rate"])
    tix = json.load(open(os.path.join(root, "research/t159/_tickets_2020-03-01_2026-06-20.json")))["long"]
    return bars, fund, tix


def build_tickets(bars, fund, tix) -> tuple[list[SimTicket], dict]:
    out, skipped, reasons = [], 0, defaultdict(int)
    for k, t in enumerate(tix):
        sym, e = t["symbol"], dt.date.fromisoformat(t["entry_d"])
        x = dt.date.fromisoformat(t["exit_d"]) if t.get("exit_d") else None
        if x is None:
            why, exit_off, paper = "open", None, None
        else:
            stop_hit = t["exit_px"] <= t["stop_px"] * (1 + 1e-9)
            why = "stop" if stop_hit else "time" if t.get("bars_held", 0) >= 120 else "sma20"
            paper = (x - e).days
            exit_off = paper if why == "sma20" else paper + 1
        reasons[why] += 1
        last = (x + dt.timedelta(days=2)) if x else HIST_END
        path, prev, d = [], None, e
        sb = bars.get(sym, {})
        if e not in sb:
            skipped += 1
            continue
        while d <= min(last, HIST_END):
            b = sb.get(d)
            if b is None:
                b = (prev[3],) * 4 if prev else None
            if b is None:
                break
            f = fund.get((sym, d.isoformat()))
            path.append((b[0], b[1], b[2], b[3], f))
            prev, d = b, d + dt.timedelta(days=1)
        stop_frac = (t["entry_px"] - t["stop_px"]) / t["entry_px"]
        out.append(SimTicket(tid=f"{sym}:{t['signal_d']}", symbol=sym, entry_day=(e - EPOCH).days, exit_off=exit_off,
                             paper_exit_off=paper, stop_frac=stop_frac, path=tuple(path),
                             signal_day=(dt.date.fromisoformat(t["signal_d"]) - EPOCH).days,
                             major=sym in ("BTC", "ETH")))
    return out, {"skipped_no_bar": skipped, "reasons": dict(reasons), "n": len(out)}


def _apy_hist(day: int) -> float:
    return apy(EPOCH + dt.timedelta(days=day))


def run_hist(tickets_, universe, size, policy, lev, variant="A"):
    ex = (lambda t: hl_listed(t.symbol)) if universe == "HL" else None
    r = simulate(tickets_, size, lev, policy=policy, executable=ex, apy_for_day=_apy_hist,
                 start_day=(HIST_START - EPOCH).days, end_day=(HIST_END - EPOCH).days,
                 collateral_mult=_coll(variant)[0], collateral_gross=_coll(variant)[1])
    s = stats(r.equity, size)
    worst_m, eq = 0.0, [size] + r.equity
    for i in range(30, len(eq), 30):
        worst_m = min(worst_m, eq[i] / eq[i - 30] - 1 if eq[i - 30] > 0 else -1)
    return {"universe": universe, "variant": variant, "size": size, "policy": policy, "lev": lev, **s,
            "worst_30d": worst_m,
            "liquidations": r.liquidations, "fees": r.fees, "funding": r.funding, "lending": r.lending,
            "entered": r.entered, "stops": r.stops, "refused": r.refused, "peak_gross": r.peak_gross_frac,
            "peak_margin": r.peak_margin_frac}


# ── 蒙特卡洛:按月块重抽 ─────────────────────────────────────────────────────
def _months():
    m, out = dt.date(2020, 4, 1), []
    while m <= dt.date(2026, 9, 1):
        nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        out.append((m, nxt))
        m = nxt
    return out


def mc_path(tickets_by_month, months, rng):
    """合成 36 个月:每个月有放回抽一个历史月,把该月进场的票按日偏移搬过来。返回 (票, 每日放贷利率, 起止)。"""
    S0 = 50_000
    base, out, apys = S0, [], []
    for k in range(MC_MONTHS):
        i = rng.randrange(len(months))
        m0, m1 = months[i]
        n = (m1 - m0).days
        for t in tickets_by_month[i]:
            off = (EPOCH + dt.timedelta(days=t.entry_day) - m0).days
            ne = base + off
            out.append(SimTicket(tid=f"{t.tid}#{k}", symbol=t.symbol, entry_day=ne, exit_off=t.exit_off,
                                 paper_exit_off=t.paper_exit_off, stop_frac=t.stop_frac, path=t.path,
                                 signal_day=ne - 1, major=t.major))
        apys += [apy(m0)] * n
        base += n
    return out, apys, S0, base - 1


def _mc_worker(args):
    seed0, n_paths, tickets_by_month, months, configs = args
    res = []
    for p in range(n_paths):
        rng = random.Random(seed0 + p)
        tks, apys, s0, s1 = mc_path(tickets_by_month, months, rng)
        if not tks:
            for c in configs:
                res.append((c, {"cagr": None, "mdd": 0.0, "end": None, "liq": 0}))
            continue
        for (variant, size, policy, lev) in configs:
            r = simulate(tks, size, lev, policy=policy, executable=lambda t: hl_listed(t.symbol),
                         apy_for_day=lambda d: apys[d - s0] if 0 <= d - s0 < len(apys) else APY_FALLBACK / 100,
                         start_day=s0, end_day=s1, collateral_mult=_coll(variant)[0],
                         collateral_gross=_coll(variant)[1])
            s = stats(r.equity, size)
            res.append(((variant, size, policy, lev), {**s, "liq": r.liquidations}))
    return res


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def summarize_mc(raw_rows, configs):
    agg = defaultdict(list)
    for c, x in raw_rows:
        agg[tuple(c)].append(x)
    mc = []
    for c in configs:
        xs = agg.get(tuple(c)) or []
        if not xs:
            continue
        cg = [x["cagr"] for x in xs if x["cagr"] is not None]
        dd = [x["mdd"] for x in xs]
        mc.append({"variant": c[0], "size": c[1], "policy": c[2], "lev": c[3], "n": len(xs),
                   "cagr_p5": pct(cg, .05), "cagr_p25": pct(cg, .25), "cagr_p50": pct(cg, .5),
                   "cagr_p75": pct(cg, .75), "cagr_p95": pct(cg, .95),
                   "mdd_p50": pct(dd, .5), "mdd_p95": pct(dd, .05),
                   "p_mdd_50": sum(d <= -0.5 for d in dd) / len(dd),
                   "p_liq": sum(x["liq"] > 0 for x in xs) / len(xs),
                   "p_loss": sum((x["end"] is not None and x["end"] < c[1]) for x in xs) / len(xs)})
    return mc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/Volumes/CometCloudAI/cometcloud-local")
    ap.add_argument("--paths", type=int, default=2000, help="这一次跑多少条路径(可分段跑,--mc-start 接着编号)")
    ap.add_argument("--mc-start", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--raw", default="s647_mc_raw.jsonl", help="每条路径 × 每个配置一行,追加写")
    ap.add_argument("--out", default="s647_results.json")
    ap.add_argument("--no-hist", action="store_true")
    ap.add_argument("--aggregate", action="store_true", help="只汇总 --raw 里已有的路径")
    ap.add_argument("--mc-variants", default=",".join(MC_VARIANTS))
    a = ap.parse_args()
    configs = [(v, s, p, l) for v in MC_VARIANTS for s in SIZES for p in POLICIES for l in LEVS]
    run_configs = [c for c in configs if c[0] in a.mc_variants.split(",")]
    if a.aggregate:
        rows = [json.loads(x) for x in open(a.raw)]
        res = json.load(open(a.out)) if os.path.exists(a.out) else {}
        res["mc"] = summarize_mc([(r["c"], r["s"]) for r in rows], configs)
        res["mc_paths"] = len({r["p"] for r in rows})
        json.dump(res, open(a.out, "w"), indent=1, default=str)
        print(json.dumps({"mc_paths": res["mc_paths"]}))
        return
    bars, fund, tix = load(a.root)
    tickets_, meta = build_tickets(bars, fund, tix)
    print("tickets", meta, "HL-listed", sum(hl_listed(t.symbol) for t in tickets_), file=sys.stderr)
    if not a.no_hist:
        hist = [run_hist(tickets_, u, s, p, l, v) for v in VARIANTS for u in ("HL", "ALL") for s in SIZES
                for p in POLICIES for l in LEVS]
        res = json.load(open(a.out)) if os.path.exists(a.out) else {}
        res.update({"meta": meta, "hist": hist})
        json.dump(res, open(a.out, "w"), indent=1, default=str)
    if a.paths:
        months = _months()
        by_month = [[t for t in tickets_ if m0 <= EPOCH + dt.timedelta(days=t.entry_day) < m1] for m0, m1 in months]
        per = max(1, a.paths // a.jobs)
        jobs = [(SEED * 100_000 + a.mc_start + j * per, per, by_month, months, run_configs) for j in range(a.jobs)]
        with ProcessPoolExecutor(a.jobs) as pool, open(a.raw, "a") as f:
            for j, chunk in enumerate(pool.map(_mc_worker, jobs)):
                for i, (c, s) in enumerate(chunk):
                    f.write(json.dumps({"p": a.mc_start + j * per + i // len(run_configs), "c": list(c), "s": s}) + "\n")
    print(json.dumps({"meta": meta}, default=str))


if __name__ == "__main__":
    main()
