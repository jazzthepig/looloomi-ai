"""T-348 续做(lane-c,2026-11-12):S-681 H2 / H3 / H4 三族按**账户口径**重判。
票与规则一字不动:票本用它们自己已发布的 results JSON 里的 tickets;资金曲线用
`short_lab_common.money` 背后的同一把尺(`t159_bear_short.nav`:每票风险 0.5%、同时最多 10 张、
逐日盯市、成本 0.2%/0.4%);行情 bar 从它们自己的 Binance klines 缓存(`_cache_um_klines`)重建。

用法: python3 t348_s681.py
产物: t348_s681_results.json + _t348_s681_section.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import t348_graveyard as G  # noqa: E402
import t159_bear_short as T159  # noqa: E402

DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
S681_DIR = os.path.join(DATA_ROOT, "research", "s681")
KL_CACHE = os.path.join(S681_DIR, "_cache_um_klines")
OUT_JSON = os.path.join(HERE, "t348_s681_results.json")
OUT_MD = os.path.join(HERE, "_t348_s681_section.md")

F_FAM = 0.005
CAP_FAM = 10


def log(msg: str) -> None:
    print(str(msg), flush=True)


def load_bars(symbols: set[str]) -> dict[str, list]:
    """symbol → [[d, o, h, l, c, qv], ...](从 Binance klines 月缓存聚合;与
    `short_lab_common.load_um` 的结构一致,只在内存里,不落盘)。"""
    by_sym: dict[str, list[str]] = defaultdict(list)
    for fn in os.listdir(KL_CACHE):
        if not fn.endswith(".json"):
            continue
        pair = fn.rsplit("_", 1)[0]
        if not pair.endswith("USDT"):
            continue
        base = pair[:-4]
        if base in symbols:
            by_sym[base].append(fn)
    out: dict[str, list] = {}
    for sym, fns in by_sym.items():
        rows: list = []
        for fn in fns:
            try:
                with open(os.path.join(KL_CACHE, fn)) as f:
                    rows.extend(json.load(f))
            except Exception:
                continue
        rows = sorted({tuple(r) for r in rows if r and len(r) >= 5 and float(r[4]) > 0})
        out[sym] = [list(r) for r in rows]
    return out


def money_curve(tickets: list[dict], closes: dict[str, list]) -> tuple[pd.Series, int]:
    """照 `short_lab_common.money` 的口径(t159.nav:f=0.5%/票、cap=10、逐日盯市)。"""
    tk = [{"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"],
           "exit_d": None if t.get("still") else t["exit_d"], "entry_px": t["entry_px"],
           "stop_px": t["stop_px"], "exit_px": None if t.get("still") else t["exit_px"]}
          for t in tickets]
    tk = [t for t in tk if t["entry_d"] and t["entry_px"] and t["stop_px"]
          and t["entry_px"] != t["stop_px"]]
    if not tk:
        return pd.Series(dtype=float), 0
    d_to = max([t["exit_d"] for t in tk if t["exit_d"]] + [max(t["entry_d"] for t in tk)])
    curve = list(T159.nav(tk, closes, F_FAM, cap=CAP_FAM, d_to=d_to))
    nav = pd.Series({pd.Timestamp(r["d"]): float(r["equity"]) for r in curve}).sort_index()
    return nav, len(tk)


def family(label: str, tickets: list[dict], closes: dict[str, list], note: str) -> dict:
    nav, n = money_curve(tickets, closes)
    if n == 0:
        raise RuntimeError(f"{label}: 没有可算的票")
    taken = sum(1 for t in tickets if t.get("entry_d"))
    best = max(tickets, key=lambda t: float(t.get("r") if t.get("r") is not None else -9e9))
    first = min(t["entry_d"] for t in tickets if t.get("entry_d"))
    last = max([(t.get("exit_d") or t["entry_d"]) for t in tickets if t.get("entry_d")])
    log(f"  {label}: 票 {taken} · 曲线 {len(nav)} 天 {nav.index[0].date()} → {nav.index[-1].date()}"
        f" · 终值 {float(nav.iloc[-1]):.4f}")
    return {"nav": nav, "first_entry": first, "last_exit": last, "n_tickets": taken,
            "risk_frac": F_FAM, "cap": CAP_FAM,
            "best_ticket": {"symbol": best.get("symbol"), "signal_d": best.get("signal_d"),
                            "entry_d": best.get("entry_d"), "r": best.get("r"),
                            "why": "族内 r 最大的一张(只报不判)"},
            "note": note}


def main() -> None:
    kernel = G.load_kernel()
    log("=== 基准 ===")
    base = G.build_base(kernel)
    res = {"card": "T-348", "part": "续做:S-681 H2 / H3 / H4",
           "base": {"C0_total_return": base["C0_total_return"],
                    "cal_start": str(base["cal_idx"][0].date()),
                    "cal_end": str(base["cal_idx"][-1].date())}}

    h2 = json.load(open(os.path.join(HERE, "s681_h2_pump_fade_results.json")))
    h3 = json.load(open(os.path.join(HERE, "s681_h3_funding_crowd_results.json")))
    h4 = json.load(open(os.path.join(HERE, "s681_h4_bear_rally_fail_results.json")))
    tk_h2 = h2["tickets"]
    tk_h3 = list(h3["tickets"]["discovery"]) + list(h3["tickets"]["holdout"])
    tk_h4 = h4["tickets"]
    syms = {t["symbol"] for t in tk_h2 + tk_h3 + tk_h4}
    log(f"=== bar 重建({len(syms)} 个标的)→")
    closes = load_bars(syms)
    hit = sum(1 for t in tk_h2 + tk_h3 + tk_h4 if t["symbol"] in closes and closes[t["symbol"]])
    log(f"  命中 bar 的票 {hit}/{len(tk_h2) + len(tk_h3) + len(tk_h4)}")

    fams = {
        "S681_H2": family("S-681 H2(pump fade)", tk_h2, closes,
                          "照 short_lab_common.money 的尺(t159.nav:f 0.5%/票、cap 10、逐日盯市);"
                          "资金费未计(照他们自己的口径:资金费单列在 R 里)"),
        "S681_H3": family("S-681 H3(资金费拥挤)", tk_h3, closes,
                          "同上;票 = 发现段 + 留出段合并"),
        "S681_H4": family("S-681 H4(熊市反弹失败)", tk_h4, closes, "同上"),
    }
    for key, f in fams.items():
        # 窗口开始之前(= 族票源最早 → 2021-10-11)这一段族自身的表现:
        # 基准账本延到 2020 之前,这一段就是窗口 A 的开头,必须先量出来。
        nav = f["nav"]
        pre = nav[nav.index <= pd.Timestamp(G.WIN_START)]
        f["pre_window_slice"] = {
            "d0": str(nav.index[0].date()), "d1": str(pre.index[-1].date()) if len(pre) else None,
            "n_days": int(len(pre)),
            "total_return": (float(pre.iloc[-1] / pre.iloc[0]) - 1.0) if len(pre) > 1 else None,
            "max_dd": (float((pre / pre.cummax() - 1.0).min()) if len(pre) > 1 else None),
        }
        log(f"  {key}: 窗口前一段(→ {G.WIN_START})族自身 "
            f"{f['pre_window_slice']['total_return']:+.4%}")
        res[key] = G.evaluate(base, kernel, f, key)
        json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=2, default=str)
        log(f"  → {key} 写完")
    write_md(res)
    log(f"  → 已写 {OUT_JSON} / {OUT_MD}")


def write_md(res: dict) -> None:
    L: list[str] = []
    A = L.append
    A("\n---\n")
    A("## 第三部分(lane-c 续做,2026-11-12):S-681 H2 / H3 / H4 三族\n")
    A(f"C0 的 **NAV 起点 2021-10-11**(收益日历起点 {res['base']['cal_start']} → {res['base']['cal_end']})。")
    A("**窗口 A 被基准账本起点卡住**:三族的票源最早到 2020-04(H3)/2020-09(H4)/2020-11(H2),"
      "但 C0(RBv2 + R-v2 腿)最早只到 2021-10-11 ⇒ 窗口 A = 窗口 B = 2021-10-11 起。"
      "基准账本往前延到 2020 需要重算 RBv2 / R-v2 腿(本轮未做)。\n")
    for key, label in (("S681_H2", "S-681 H2(pump fade)"),
                       ("S681_H3", "S-681 H3(资金费拥挤)"),
                       ("S681_H4", "S-681 H4(熊市反弹失败)")):
        r = res[key]
        fs = r["family_standalone"]
        A(f"**{label}** —— 票 {r['meta']['n_tickets']} 张;族自身(全段 "
          f"{fs.get('d0')} → {fs.get('d1')})总回报 {fs.get('total_return', float('nan')):+.4%}、"
          f"年化 {fs.get('cagr', float('nan')):+.4%}、最大回撤 {fs.get('max_dd', float('nan')):+.4%}。\n")
        A("| 窗口 | C0 CAGR | +族 CAGR | Δ(pp) | C0 最长水下 | +族 最长水下 | C0 最大回撤 | +族 最大回撤 | 自检② 差 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for wn, w in r["windows"].items():
            A(f"| {wn}({w['start']} →) | {w['C0']['metrics']['cagr']:+.4%} | "
              f"{w['C0_plus_family']['metrics']['cagr']:+.4%} | {w['diff']['cagr_pp']:+.3f} | "
              f"{w['C0']['underwater'].get('length_d')} 日 | {w['C0_plus_family']['underwater'].get('length_d')} 日 | "
              f"{w['C0']['metrics']['max_dd']:+.4%} | {w['C0_plus_family']['metrics']['max_dd']:+.4%} | "
              f"{w['selfcheck_family']['abs_diff']:.1e} |")
        A("")
        A(f"结论:{r['conclusion']['class']}"
          + ("(**窗口依赖**)" if r["conclusion"]["window_dependent"] else "")
          + f" · 「去掉最好一张」:{r['meta'].get('best_ticket', {}).get('symbol')} "
            f"({r['meta'].get('best_ticket', {}).get('entry_d')}, r={r['meta'].get('best_ticket', {}).get('r')})"
            "(只报不判)\n")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
