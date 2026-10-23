"""S-678:R-v2 样本外第二次 —— S-677 的宇宙加上 BTC 计价对(按 BTCUSDT 折美元、成交合并)。预注册见台账 S-678(2026-10-23 15:55 UTC)。

票 / 判据 / 只报项全部复用 s677_rv2_oos(它又复用 t159.run_long 与 s657 的统计);本文件只做一件新事:把两种计价的日线并成一条美元日线。
  同一基础币同一天:有 USDT 对 ⇒ 用 USDT 对的 OHLC;没有 ⇒ BTC 对折算:开 × BTCUSDT 开、收 × BTCUSDT 收(精确)、
  高 × BTCUSDT 高、低 × BTCUSDT 低(上下界,偏保守)。dv = 美元收盘 × (USDT 对成交量 + BTC 对成交量)。BTCUSDT 当天没有 ⇒ 没有 bar。
数据(数据根 research/s677/):_bv_daily.jsonl(USDT 对,第 6 列是 dv)、_bv_daily_btc.jsonl(BTC 对,第 6 列是基础币成交量)。
用法:python3 docs/research/s678_rv2_oos_btcpairs.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import importlib.util
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("s677", os.path.join(HERE, "s677_rv2_oos.py"))
s677 = importlib.util.module_from_spec(_spec)
sys.modules["s677"] = s677
_spec.loader.exec_module(s677)
t159, s657 = s677.t159, s677.s657
DATA = s677.DATA


def _load(fn: str) -> dict[str, dict[str, list]]:
    out = {}
    for line in open(os.path.join(DATA, fn)):
        x = json.loads(line)
        out[x["symbol"]] = {b[0]: b for b in x["bars"] if b[4] > 0}
    return out


def merged_bars() -> tuple[dict[str, list], dict[str, set], dict]:
    usdt, btcq = _load("_bv_daily.jsonl"), _load("_bv_daily_btc.jsonl")
    btc = usdt["BTC"]
    bars, converted = {}, {}
    diffs = []
    for s in sorted(set(usdt) | set(btcq)):
        if s in t159.EXCL:
            continue
        u, b = usdt.get(s, {}), (btcq.get(s, {}) if s != "BTC" else {})
        rows, conv = [], set()
        for d in sorted(set(u) | set(b)):
            vb = b[d][5] if d in b else 0.0
            if d in u:
                o, h, l, c, dv = u[d][1:6]
                vu = dv / c
                if d in b and d in btc:
                    diffs.append(abs(b[d][4] * btc[d][4] / c - 1))
            elif d in b and d in btc:
                o, h, l, c = (b[d][k] * btc[d][k] for k in (1, 2, 3, 4))
                vu = 0.0
                conv.add(d)
            else:
                continue
            rows.append([d, o, h, l, c, c * (vu + vb)])
        if rows:
            bars[s], converted[s] = rows, conv
    check = {"n_overlap_days": len(diffs), "median_abs_close_gap": statistics.median(diffs) if diffs else None,
             "p99_abs_close_gap": sorted(diffs)[int(0.99 * len(diffs))] if diffs else None}
    return bars, converted, check


def main() -> None:
    bars, conv, check = merged_bars()
    gate = s677.load_gate()
    surv = set(json.load(open(os.path.join(DATA, "_survivor_symbols.json")))["symbols"])
    prev = json.load(open(os.path.join(HERE, "s677_results.json")))
    seen = {(t["symbol"], t["signal_d"]) for t in prev["primary"]["tickets"]}
    res = {"data": {"bases": len(bars), "bars": sum(len(v) for v in bars.values()),
                    "converted_bars": sum(len(v) for v in conv.values()), "usdt_vs_btc_close_check": check,
                    "not_in_today_panel": len([s for s in bars if s not in surv])},
           "window": [s677.SIG_FROM, s677.SIG_TO]}
    tk = s657.mtm(t159.run_long(bars, gate, s677.SIG_FROM, s677.SIG_TO), bars)
    res["primary"] = s677.judge(tk, bars)
    res["primary"]["money_f0005"] = s677.money_curve(tk, bars)
    res["primary"]["tickets"] = [{k: t[k] for k in ("symbol", "signal_d", "entry_d", "exit_d", "entry_px", "stop_px",
                                                     "exit_px", "r")} | {"still": bool(t.get("still")),
                                                                          "survivor": t["symbol"] in surv,
                                                                          "converted_signal_bar": t["signal_d"] in conv[t["symbol"]],
                                                                          "seen_in_s677": (t["symbol"], t["signal_d"]) in seen}
                                 for t in tk]
    rs = lambda ts: {"n": len(ts), "mean": (sum(t["r"] for t in ts) / len(ts)) if ts else None,  # noqa: E731
                     "total": sum(t["r"] for t in ts)}
    res["only_report"] = {
        "crash_2018q1": rs([t for t in tk if "2018-01-01" <= t["signal_d"] <= "2018-03-13"]),
        "on_converted_bars": rs([t for t in tk if t["signal_d"] in conv[t["symbol"]]]),
        "on_usdt_bars": rs([t for t in tk if t["signal_d"] not in conv[t["symbol"]]]),
        "new_vs_s677": rs([t for t in tk if (t["symbol"], t["signal_d"]) not in seen]),
        "overlap_with_s677": len([t for t in tk if (t["symbol"], t["signal_d"]) in seen]),
        "survivor_only": s657.summary(s657.mtm(t159.run_long({s: v for s, v in bars.items() if s in surv}, gate,
                                                             s677.SIG_FROM, s677.SIG_TO), bars)),
    }
    tn = s657.mtm(t159.run_long(bars, {}, s677.SIG_FROM, s677.SIG_TO), bars)
    res["only_report"]["no_gate"] = {"summary": s657.summary(tn), "money_f0005": s677.money_curve(tn, bars)}
    fs = s677.fish(bars, s677.SIG_FROM, s677.SIG_TO)
    res["only_report"]["fish"] = s677.capture(fs, tk)
    res["only_report"]["fish_no_gate"] = {k: v for k, v in s677.capture(fs, tn).items() if k != "fish_list"}
    json.dump(res, open(os.path.join(HERE, "s678_results.json"), "w"), indent=1, default=str)
    p = res["primary"]
    print(json.dumps({"data": res["data"], "summary": {k: v for k, v in p["summary"].items() if k != "top10"},
                      "top10": p["summary"]["top10"], "judged": p.get("judged"), "verdict": p.get("verdict"),
                      "money": p.get("money_f0005"),
                      "only_report": {k: (v if k not in ("survivor_only", "no_gate", "fish") else
                                          ({kk: vv for kk, vv in v.items() if kk not in ("top10", "fish_list")}
                                           if isinstance(v, dict) else v))
                                      for k, v in res["only_report"].items()}}, indent=1, default=str))


if __name__ == "__main__":
    main()
