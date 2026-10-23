"""S-677:R-v2 样本外 —— 2018-01 → 2020-02,Binance 全部 USDT 现货对(含已下架)。预注册见台账 S-677(2026-10-23 15:42 UTC)。

不写新规则:票 = `t159_bear_short.run_long`(= r_v2_tickets.sql 逐字);盯市 / 汇总 / 月块自助 / 随机进场零分布
= `s657_s658_breadth_second_leg` 里的 `mtm` / `summary` / `boot_months` / `random_null`;资金曲线 = `t159.nav` + `t159.stats`。
数据(数据根 research/s677/,由 s677_bv_fetch.py 抓):_bv_daily.jsonl、_gate_proxy.json、_survivor_symbols.json。
用法:python3 docs/research/s677_rv2_oos.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
DATA = os.path.join(ROOT, "research", "s677")
_spec = importlib.util.spec_from_file_location("s657", os.path.join(HERE, "s657_s658_breadth_second_leg.py"))
s657 = importlib.util.module_from_spec(_spec)
sys.modules["s657"] = s657
_spec.loader.exec_module(s657)
t159 = s657.t159

SIG_FROM, SIG_TO = "2018-01-01", "2020-02-29"
NAV_TO = "2020-08-31"
s657.SEED = 678                     # random_null 的种子(预注册写的是 678)
BOOT_SEED = 677


def load_bars() -> dict[str, list]:
    bars = {}
    for line in open(os.path.join(DATA, "_bv_daily.jsonl")):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if b[4] > 0})
        if rows and x["symbol"] not in t159.EXCL:
            bars[x["symbol"]] = [list(r) for r in rows]
    return bars


def load_gate() -> dict[str, dict]:
    g = json.load(open(os.path.join(DATA, "_gate_proxy.json")))
    out = {}
    for r in g["runs"]:
        d, end = dt.date.fromisoformat(r["start"]), dt.date.fromisoformat(r["end"])
        while d <= end:
            out[d.isoformat()] = {"gate_open": r["open"]}
            d += dt.timedelta(days=1)
    return out


def fish(bars, d_from, d_to):
    """S-618 口径:rn ≥ 220、adv30 ≥ $5M、之后 120 根内最高收盘 ≥ 3 × 当天收盘 ⇒ 命中;同名命中相隔 ≤ 30 根并成一条鱼。"""
    out = []
    for s, rows in bars.items():
        c = [r[4] for r in rows]
        dv = [r[5] for r in rows]
        hits = []
        for i in range(219, len(rows) - 1):
            d = rows[i][0]
            if not (d_from <= d <= d_to):
                continue
            adv = sum(dv[max(0, i - 29): i + 1]) / len(dv[max(0, i - 29): i + 1])
            fm = max(c[i + 1: i + 121]) if i + 1 < len(c) else None
            if adv >= 5e6 and fm is not None and fm >= 3 * c[i]:
                hits.append(i)
        cur = None
        for i in hits:
            if cur and i - cur["last"] <= 30:
                cur["last"] = i
            else:
                cur = {"symbol": s, "first": i, "last": i}
                out.append(cur)
        for f in out:
            if f["symbol"] == s:
                f["d0"], f["d1"] = rows[f["first"]][0], rows[f["last"]][0]
    return out


def capture(fishes, tickets):
    by = defaultdict(list)
    for t in tickets:
        by[t["symbol"]].append(t["entry_d"])
    got = [f for f in fishes if any(f["d0"] <= e <= f["d1"] for e in by[f["symbol"]])]
    return {"fish": len(fishes), "captured": len(got), "share": (len(got) / len(fishes)) if fishes else None,
            "fish_list": [(f["symbol"], f["d0"], f["d1"]) for f in fishes]}


def judge(tickets, bars):
    rs = [t["r"] for t in tickets]
    out = {"summary": s657.summary(tickets)}
    if len(rs) < 1:
        return out
    bm = s657.boot_months(tickets, seed=BOOT_SEED)
    p_le0 = sum(m <= 0 for m in bm) / len(bm)
    null = sorted(s657.random_null(tickets, bars))
    q95 = null[int(0.95 * len(null))]
    m = sum(rs) / len(rs)
    out["judged"] = {"1_mean": m, "1_p_mean_le_0": p_le0, "2_null_q95": q95, "2_null_median": null[len(null) // 2],
                     "2_pct": sum(x < m for x in null) / len(null), "3_n": len(rs)}
    if len(rs) < 30:
        out["verdict"] = "只报(票数 < 30)"
    else:
        out["verdict"] = "过" if (m > 0 and p_le0 < 0.10 and m > q95) else "不过"
    return out


def money_curve(tickets, bars, f=0.005):
    curve = list(t159.nav(tickets, bars, f, cap=10, d_to=NAV_TO))
    return t159.stats(curve) if curve else None


def main() -> None:
    bars = load_bars()
    gate = load_gate()
    surv = set(json.load(open(os.path.join(DATA, "_survivor_symbols.json")))["symbols"])
    res = {"data": {"pairs": len(bars), "bars": sum(len(v) for v in bars.values()),
                    "first_d": min(v[0][0] for v in bars.values()), "last_d": max(v[-1][0] for v in bars.values()),
                    "survivors_in_data": sorted(s for s in bars if s in surv),
                    "delisted_or_renamed": sorted(s for s in bars if s not in surv)},
           "window": [SIG_FROM, SIG_TO]}
    tk = s657.mtm(t159.run_long(bars, gate, SIG_FROM, SIG_TO), bars)
    res["primary"] = judge(tk, bars)
    res["primary"]["money_f0005"] = money_curve(tk, bars)
    res["primary"]["tickets"] = [{k: t[k] for k in ("symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px",
                                                     "exit_px", "r")} | {"still": bool(t.get("still")),
                                                                          "survivor": t["symbol"] in surv}
                                 for t in tk]
    # 只报
    sb = {s: v for s, v in bars.items() if s in surv}
    ts = s657.mtm(t159.run_long(sb, gate, SIG_FROM, SIG_TO), sb)
    res["survivor_only"] = {"summary": s657.summary(ts)}
    tn = s657.mtm(t159.run_long(bars, {}, SIG_FROM, SIG_TO), bars)
    res["no_gate"] = {"summary": s657.summary(tn), "money_f0005": money_curve(tn, bars)}
    t19 = [t for t in tk if t["signal_d"][:4] == "2019"]
    res["y2019"] = {"n": len(t19), "total": sum(t["r"] for t in t19),
                    "tickets": [(t["symbol"], t["signal_d"], round(t["r"], 2)) for t in t19]}
    fs = fish(bars, SIG_FROM, SIG_TO)
    res["fish_capture"] = capture(fs, tk)
    res["fish_capture_no_gate"] = {k: v for k, v in capture(fs, tn).items() if k != "fish_list"}
    out = os.path.join(HERE, "s677_results.json")
    json.dump(res, open(out, "w"), indent=1, default=str)
    p = res["primary"]
    print(json.dumps({"data": {k: res["data"][k] for k in ("pairs", "bars", "first_d", "last_d")},
                      "n_delisted": len(res["data"]["delisted_or_renamed"]),
                      "primary": {"summary": p["summary"], "judged": p.get("judged"), "verdict": p.get("verdict"),
                                  "money": p.get("money_f0005")},
                      "survivor_only": res["survivor_only"]["summary"], "no_gate": res["no_gate"]["summary"],
                      "no_gate_money": res["no_gate"]["money_f0005"],
                      "y2019": {k: res["y2019"][k] for k in ("n", "total")},
                      "fish": {k: res["fish_capture"][k] for k in ("fish", "captured", "share")},
                      "fish_no_gate": res["fish_capture_no_gate"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
